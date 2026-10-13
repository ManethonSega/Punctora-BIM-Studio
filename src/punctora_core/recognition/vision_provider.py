"""Replaceable 2D proposals, with an independent classical projection path."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import threading
import time
import numpy as np

from ..annotation_io import content_digest, file_digest, identifier, number, read_json, sha256
from ..opening_raster import projected_void_regions
from ..quality_benchmark import write_report
from .contracts import ProviderUnavailable


def validate_detections(values, projection, maximum_regions=512):
    if not isinstance(values, list) or len(values) > maximum_regions:
        raise ValueError("2D detector must return a bounded list of regions")
    result = []
    nz, nx = projection.frame.shape
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("2D regions must be dictionaries")
        identifier(value.get("class"), "2D class")
        identifier(value.get("score_kind"), "2D native score kind")
        if value.get("native_score") is not None:
            number(value["native_score"], "2D native score")
        box = value.get("box")
        if not isinstance(box, (list, tuple)) or len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in box):
            raise ValueError("2D box requires four exact integer pixel boundaries")
        x0, z0, x1, z1 = box
        if not 0 <= x0 < x1 <= nx or not 0 <= z0 < z1 <= nz:
            raise ValueError("2D box escapes the wall image or has zero area")
        mask = value.get("mask")
        if mask is None:
            mask = np.zeros((nz, nx), dtype=bool)
            mask[z0:z1, x0:x1] = True
        if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.shape != (nz, nx) or not mask.any():
            raise ValueError("2D mask must be nonempty bool with exact image dimensions")
        rows, cols = np.nonzero(mask)
        if rows.min() < z0 or rows.max() >= z1 or cols.min() < x0 or cols.max() >= x1:
            raise ValueError("2D mask escapes its declared box")
        evidence = value.get("evidence", {})
        if not isinstance(evidence, dict):
            raise ValueError("2D evidence must be a dictionary")
        result.append({**value, "box": list(box), "mask": mask})
    return result


class VisionProvider(ABC):
    @abstractmethod
    def descriptor(self): pass

    def prepare(self, directory, control): pass

    @abstractmethod
    def infer(self, projection, directory, control): pass

    def close(self): pass


class ProjectedEvidenceProvider(VisionProvider):
    """Geometry-only baseline. Repeated frames never certify a material."""
    def __init__(self, minimum_width_m=.5, minimum_height_m=.55, minimum_edge_support=.65, maximum_regions=512):
        self.options = dict(minimum_width_m=minimum_width_m, minimum_height_m=minimum_height_m,
                            minimum_edge_support=minimum_edge_support, maximum_regions=maximum_regions)

    def descriptor(self):
        value = {"id": "projected_classical_evidence", "version": "1", "backend": "CPU",
                 "score_kind": "separate_native_values_not_probability", "options": self.options}
        return {**value, "fingerprint": content_digest(value)}

    def infer(self, projection, directory, control):
        regions = projected_void_regions(projection, **self.options, check=control.check)
        # Depth strips are column hypotheses only, not certified columns.
        import cv2
        depth = projection.signed_depth_m
        protruding = (np.isfinite(depth) & (depth > .08) & (projection.return_counts > 0)).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(protruding, 8)
        cell = projection.frame.cell_m
        for i in range(1, count):
            control.check()
            x, z, w, h, area = map(int, stats[i])
            if .08 <= w * cell <= 1.2 and h * cell >= .6 and h >= 2 * w and area / (w * h) >= .4:
                regions.append({"class": "column", "box": [x, z, x + w, z + h], "mask": labels == i,
                                "native_score": float(area / (w * h)), "score_kind": "projected_depth_strip_occupancy",
                                "evidence": {"method": "protruding_vertical_strip", "classification": "hypothesis",
                                             "structural_role": "unknown"}})
        return validate_detections(regions, projection, self.options["maximum_regions"])


@dataclass(frozen=True)
class VisionAssets:
    python: str
    worker: str
    worker_sha256: str
    configuration: str
    configuration_sha256: str
    runtime_fingerprint: str
    timeout_seconds: float = 300.


class IsolatedVisionProvider(VisionProvider):
    """Explicit local adapter protocol, not an assumed pretrained detector.

    The user-supplied fingerprinted worker is trusted local code and owns its
    model/environment. No remote service, runtime install or download is
    orchestrated here. Missing assets can use the classical path. Bad regions
    fail rather than being ignored or converted into accepted cuts.
    """
    def __init__(self, assets):
        self.assets, self.process = assets, None

    def descriptor(self):
        value = {"id": "isolated_2d", "version": "wall-image-protocol-v1", "backend": "explicit_local_worker",
                 "score_kind": "worker_native_values_not_probability", "worker_sha256": self.assets.worker_sha256,
                 "configuration_sha256": self.assets.configuration_sha256,
                 "runtime_fingerprint": self.assets.runtime_fingerprint, "timeout_seconds": self.assets.timeout_seconds,
                 "interpreter_sha256": file_digest(self.assets.python) if Path(self.assets.python).is_file() else None}
        return {**value, "fingerprint": content_digest(value)}

    def prepare(self, directory, control):
        for name in ("worker_sha256", "configuration_sha256", "runtime_fingerprint"):
            sha256(getattr(self.assets, name), name)
        number(self.assets.timeout_seconds, "2D timeout", True)
        for name in ("python", "worker", "configuration"):
            path = Path(getattr(self.assets, name))
            if not path.is_absolute():
                raise ValueError("Vision assets require explicit absolute local paths")
            if not path.is_file():
                raise ProviderUnavailable("Explicit 2D " + name + " missing; no automatic asset download")
            if name != "python" and file_digest(path, cancelled=control.cancelled) != getattr(self.assets, name + "_sha256"):
                raise ValueError("2D asset fingerprint mismatch: " + name)
        configuration = read_json(self.assets.configuration)
        if configuration.get("schema_version") != 1 or configuration.get("trusted_local_worker") is not True:
            raise ValueError("2D configuration must explicitly attest trusted local worker code")
        if configuration.get("runtime_fingerprint") != self.assets.runtime_fingerprint:
            raise ValueError("2D runtime fingerprint disagrees with configuration")
        # This is declared runtime provenance, not audited binary parity.
        for item in configuration.get("model_assets", []):
            path = Path(item["path"])
            if not path.is_absolute():
                raise ValueError("2D model assets require absolute local paths")
            if not path.is_file():
                raise ProviderUnavailable("Explicit 2D model asset missing")
            sha256(item["sha256"], "2D model asset digest")
            if file_digest(path, cancelled=control.cancelled) != item["sha256"]:
                raise ValueError("2D model asset digest mismatch")

    def infer(self, projection, directory, control):
        job = Path(directory) / ("vision-" + projection.frame.id.split(":")[1])
        job.mkdir()
        image = job / "image.npz"
        np.savez(image, face_counts=projection.face_counts, return_counts=projection.return_counts,
                 signed_depth_m=projection.signed_depth_m, rgb=projection.rgb, rgb_valid=projection.rgb_valid)
        output = job / "response.json"
        write_report(job / "request.json", {"schema_version": 1, "frame": projection.frame.to_dict(),
                     "image": str(image.resolve()), "image_sha256": file_digest(image),
                     "configuration": self.assets.configuration, "configuration_sha256": self.assets.configuration_sha256,
                     "runtime_fingerprint": self.assets.runtime_fingerprint, "output": str(output.resolve()),
                     "pixel_origin": "lower_left", "score_policy": "native_separate_not_probability"})
        environment = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LD_LIBRARY_PATH"}}
        environment.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
        try:
            # Recheck executable code/config immediately before each launch.
            for name in ("worker", "configuration"):
                if file_digest(getattr(self.assets, name)) != getattr(self.assets, name + "_sha256"):
                    raise ValueError("2D asset changed after admission")
            self.process = subprocess.Popen([self.assets.python, "-I", self.assets.worker, str((job / "request.json").resolve())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment)
            control.child_pid = self.process.pid
            started = time.monotonic()
            while self.process.poll() is None:
                control.check()
                if time.monotonic() - started > self.assets.timeout_seconds:
                    raise ProviderUnavailable("Isolated 2D timeout exceeded")
                threading.Event().wait(.05)
            if self.process.returncode == 20:
                raise ProviderUnavailable("2D worker reports unavailable device/operator/assets")
            if self.process.returncode != 0:
                raise ValueError("2D worker failed its contract")
            if output.stat().st_size > 4 * 1024**2:
                raise ValueError("2D worker response exceeds the bounded JSON protocol")
            response = read_json(output)
            if (response.get("schema_version") != 1 or response.get("frame_id") != projection.frame.id
                    or response.get("image_sha256") != file_digest(image)
                    or response.get("runtime_fingerprint") != self.assets.runtime_fingerprint):
                raise ValueError("2D response identity/fingerprint mismatch")
            # Dense masks are optional row-major flat true-pixel indices, not
            # arbitrary file paths or executable serialized objects.
            values = response.get("detections")
            if not isinstance(values, list) or len(values) > 512:
                raise ValueError("2D worker detections exceed the protocol limit")
            for value in values:
                if "mask_pixels" in value:
                    indices = value.pop("mask_pixels")
                    if not isinstance(indices, list) or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < projection.face_counts.size for i in indices):
                        raise ValueError("2D mask pixel IDs are malformed")
                    mask = np.zeros(projection.frame.shape, dtype=bool)
                    mask.ravel()[indices] = True
                    value["mask"] = mask
            return validate_detections(values, projection)
        finally:
            self.close()
            control.child_pid = None

    def close(self):
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                import psutil
                try:
                    children = psutil.Process(self.process.pid).children(recursive=True)
                except psutil.NoSuchProcess:
                    children = []
                for child in children:
                    try: child.terminate()
                    except psutil.NoSuchProcess: pass
                self.process.terminate()
                try: self.process.wait(timeout=2.)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2.)
                for child in children:
                    try:
                        if child.is_running(): child.kill()
                    except psutil.NoSuchProcess: pass
        finally:
            self.process = None
