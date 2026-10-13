"""Explicit local assets and an isolated, fingerprinted PTv3 worker."""
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import threading
import time
import numpy as np

from ..annotation_io import content_digest, file_digest, read_json, sha256
from ..quality_benchmark import write_report
from .contracts import ProviderUnavailable, validate_labels
from .preprocessing import PREPROCESSING
from .provider import RecognitionProvider, TilePrediction

CLOUD2BIM_COMMIT = "cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e"
POINTCEPT_REFERENCE = "1342eda30e96cbb5fadf5374ff8eb18f6de15c71"
# Keep native classes absent from our supported geometry taxonomy visible.
# Never map furniture, beams or services into walls/slabs.
NATIVE_TO_TAXONOMY = [0, 5, 2, 11, 7, 12, 8, 1, 13, 14, 15, 16]


@dataclass(frozen=True)
class Cloud2BIMAssets:
    python: str
    checkpoint: str
    checkpoint_sha256: str
    model_config: str
    model_config_sha256: str
    runtime_manifest: str
    runtime_manifest_sha256: str
    device: str = "cuda:0"
    timeout_seconds: float = 600.

    def validate(self):
        for name in ("checkpoint_sha256", "model_config_sha256", "runtime_manifest_sha256"):
            sha256(getattr(self, name), name)
        if self.device != "cpu" and self.device != "cuda:0":
            raise ProviderUnavailable("This experiment only supports explicit CPU or CUDA:0; no AMD/OpenCL claim")
        if isinstance(self.timeout_seconds, bool) or not np.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Isolated inference timeout must be finite and positive")
        for name in ("python", "checkpoint", "model_config", "runtime_manifest"):
            if not isinstance(getattr(self, name), str) or not Path(getattr(self, name)).is_absolute():
                raise ValueError("Isolated model assets/interpreter require explicit absolute local paths")
        return self


class Cloud2BIMProvider(RecognitionProvider):
    def __init__(self, assets):
        self.assets = assets
        self.warnings = ["Experimental PTv3 proposals only; real-scan domain gap remains unqualified",
                         "Published Cloud2BIM DL directory has no runnable inference/configuration; exact training parity is not claimed",
                         "Canonical normal signs differ from upstream unoriented normals; evaluate at the applicable specialist-provider checkpoint"]
        self.instances = []
        self.process = None

    def descriptor(self):
        from dataclasses import asdict
        # Paths stay local, not in public reports. Their supplied digests and
        # actual worker source bind the reusable generation to explicit assets.
        assets = asdict(self.assets)
        value = {"id": "cloud2bim_experimental", "version": CLOUD2BIM_COMMIT,
                 "backend": assets["device"], "score_kind": "maximum_raw_logit_not_probability",
                 "checkpoint_sha256": assets["checkpoint_sha256"], "model_config_sha256": assets["model_config_sha256"],
                 "runtime_manifest_sha256": assets["runtime_manifest_sha256"],
                 "interpreter_sha256": file_digest(assets["python"]) if Path(assets["python"]).is_file() else None,
                 "worker_sha256": file_digest(Path(__file__).with_name("cloud2bim_worker.py")),
                 "preprocessing_sha256": file_digest(Path(__file__).with_name("preprocessing.py")),
                 "preprocessing": PREPROCESSING, "native_to_taxonomy": NATIVE_TO_TAXONOMY,
                 "pointcept_reference": POINTCEPT_REFERENCE, "timeout_seconds": self.assets.timeout_seconds}
        return {**value, "fingerprint": content_digest(value)}

    def prepare(self, cloud, identity, directory, control):
        assets = self.assets.validate()
        if not Path(assets.python).is_file():
            raise ProviderUnavailable("Explicit isolated Python interpreter is missing")
        for name in ("checkpoint", "model_config", "runtime_manifest"):
            path = Path(getattr(assets, name))
            if not path.is_file():
                raise ProviderUnavailable("Explicit local " + name + " is missing; automatic downloads are disabled")
            if file_digest(path, cancelled=control.cancelled) != getattr(assets, name + "_sha256"):
                raise ValueError("Model asset digest mismatch: " + name)
        if Path(assets.checkpoint).stat().st_size < 1024:
            raise ProviderUnavailable("Checkpoint is missing/truncated or only a Git LFS pointer")
        # Runtime attestation is read-only JSON, never executable configuration.
        runtime = read_json(assets.runtime_manifest)
        if runtime.get("schema_version") != 1 or runtime.get("pointcept_commit") != POINTCEPT_REFERENCE:
            raise ValueError("Explicit runtime manifest must pin the reviewed Pointcept source commit")
        sha256(runtime.get("pointcept_python_tree_sha256"), "installed Pointcept Python source digest")
        if not isinstance(runtime.get("python_version"), str) or not runtime["python_version"]:
            raise ValueError("Runtime manifest must pin the isolated Python version")
        expected = runtime.get("packages")
        if not isinstance(expected, dict) or not {"numpy", "scipy", "torch", "spconv", "torch-scatter", "torch-cluster"} <= set(expected):
            raise ValueError("Runtime manifest lacks exact model package versions")
        if any(not isinstance(v, str) or not v.strip() for v in expected.values()):
            raise ValueError("Runtime package versions must be nonempty strings")
        config = read_json(assets.model_config)
        if config.get("schema_version") != 1 or config.get("preprocessing") != PREPROCESSING or not isinstance(config.get("model"), dict):
            raise ValueError("Model JSON must explicitly declare the reviewed preprocessing and exact model configuration")
        if config["model"].get("num_classes") != 12 or config["model"].get("backbone", {}).get("in_channels") != 3:
            raise ValueError("Cloud2BIM model requires 12 native classes and normal-only three-channel input")
        if Path(assets.checkpoint).stat().st_size * 4 > control.working_budget:
            raise ProviderUnavailable("Checkpoint admission estimate exceeds the explicit RAM budget")

    def _request(self, tile, directory):
        relative = tile.id.replace(":", "_")
        job = directory / ("worker-" + relative)
        job.mkdir()
        for name, values in (("points", tile.points), ("vote_mask", tile.vote_mask)):
            np.save(job / (name + ".npy"), values, allow_pickle=False)
        request = {"schema_version": 1, "points": str(job / "points.npy"), "vote_mask": str(job / "vote_mask.npy"),
                   "output_directory": str(job), "assets": vars(self.assets), "native_to_taxonomy": NATIVE_TO_TAXONOMY}
        write_report(job / "request.json", request)
        return job.resolve()

    def infer_chunk(self, tile, directory, control):
        job = self._request(tile, directory.resolve())
        # No user shell, credential forwarding, automatic package installation
        # or inherited PYTHONPATH. -I selects only the explicitly chosen env.
        environment = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LD_LIBRARY_PATH"}}
        environment.update({"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                            "CUBLAS_WORKSPACE_CONFIG": ":4096:8"})
        try:
            self.process = subprocess.Popen([self.assets.python, "-I", str(Path(__file__).with_name("cloud2bim_worker.py")),
                                             str(job / "request.json")], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, env=environment)
            control.child_pid = self.process.pid
            # Drain continuously, retaining only a bounded tail even for a
            # noisy runtime. The worker never writes point data to stdout.
            tail = bytearray()
            pipe = self.process.stdout
            def drain():
                try:
                    for chunk in iter(lambda: pipe.read(4096), b""):
                        tail.extend(chunk)
                        if len(tail) > 16384:
                            del tail[:-16384]
                except (OSError, ValueError):
                    pass  # Owned pipe closed during cancellation.
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            start = time.monotonic()
            while self.process.poll() is None:
                control.check()
                if time.monotonic() - start > self.assets.timeout_seconds:
                    raise ProviderUnavailable("Explicit isolated inference timeout exceeded")
                threading.Event().wait(.05)
            reader.join(timeout=1.)
            if self.process.returncode == 20:
                raise ProviderUnavailable(tail.decode("utf-8", errors="replace").strip())
            if self.process.returncode != 0:
                raise ValueError("Isolated model worker failed its contract: " + tail.decode("utf-8", errors="replace").strip())
            labels = np.load(job / "labels.npy", allow_pickle=False)
            scores = np.load(job / "scores.npy", allow_pickle=False)
            validate_labels(labels, scores, len(tile.points))
            return TilePrediction(labels, scores)
        finally:
            self.close()
            control.child_pid = None

    def close(self):
        process = self.process
        if process is None:
            return
        try:
            if process.poll() is None:
                # Only terminate this owned worker and its descendants.
                import psutil
                try:
                    descendants = psutil.Process(process.pid).children(recursive=True)
                except psutil.NoSuchProcess:
                    descendants = []
                for child in descendants:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                process.terminate()
                try:
                    process.wait(timeout=2.)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.)
                for child in descendants:
                    try:
                        if child.is_running():
                            child.kill()
                    except psutil.NoSuchProcess:
                        pass
        finally:
            if process.stdout:
                process.stdout.close()
            self.process = None
