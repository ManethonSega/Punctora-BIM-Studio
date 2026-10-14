"""Punctora-owned specialist runtime, proposals and truthful orchestration."""
from copy import deepcopy
from dataclasses import dataclass, asdict
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time

import cv2
import numpy as np

from ..annotation_io import content_digest, file_digest, read_json
from ..quality_benchmark import write_report
from ..storage import mapped_array
from .contracts import ProviderUnavailable, array_descriptor
from .provider import RecognitionProvider, TilePrediction, combine_tiles
from .specialist_decoders import decode_masks, decode_obb, decode_section
from .specialist_frames import (plan_frame, plan_pixels, rasterize_plan, rasterize_section,
                                section_frame, slab_section_windows)
from .specialist_indices import prepare_point_model_view
from .specialist_pack import (MODEL_PACK_MANIFEST, SPECIALIST_PROVIDER_ID,
                              SPECIALIST_PROVIDER_VERSION, resolve_model_pack)
from .specialist_worker import image_tensor


NATIVE_TO_TAXONOMY = np.asarray([0, 5, 2, 11, 7, 12, 8, 1, 13, 14, 15, 16], dtype="<i2")


@dataclass(frozen=True)
class PunctoraSpecialistAssets:
    python: str
    model_root: str
    timeout_seconds: float = 900.

    def validate(self):
        if not isinstance(self.python, str) or not Path(self.python).is_absolute():
            raise ValueError("Specialist Python requires an explicit absolute path")
        if not isinstance(self.model_root, str) or not Path(self.model_root).is_absolute():
            raise ValueError("Specialist model root requires an explicit absolute path")
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not np.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise ValueError("Specialist timeout must be finite and positive")
        return self


@dataclass(frozen=True)
class SpecialistSettings:
    level_bounds: tuple = ()
    plan_tile_m: float = 10.24
    plan_native_pixels: int = 1024
    stair_tile_m: float = 20.48
    stair_native_pixels: int = 2048
    plan_model_pixels: int = 512
    upper_slice_offset_m: float = 1.5
    slice_thickness_m: float = .20
    maximum_plan_tiles: int = 64
    maximum_view_points: int = 1_500_000
    maximum_section_views: int = 64
    section_score_threshold: float = .4
    obb_score_threshold: float = .25
    tta_minimum_votes: int = 4

    def validate(self):
        numeric = (self.plan_tile_m, self.stair_tile_m, self.upper_slice_offset_m,
                   self.slice_thickness_m, self.section_score_threshold, self.obb_score_threshold)
        try:
            finite = np.isfinite(numeric).all()
            positive = self.plan_tile_m > 0 and self.stair_tile_m > 0 and self.slice_thickness_m > 0
        except TypeError as exc:
            raise ValueError("Specialist physical view settings must be finite numbers") from exc
        if not finite or not positive:
            raise ValueError("Specialist physical view settings must be finite and positive")
        for name in ("plan_native_pixels", "stair_native_pixels", "plan_model_pixels",
                     "maximum_plan_tiles", "maximum_view_points", "maximum_section_views", "tta_minimum_votes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("Specialist count settings must be positive integers")
        if self.tta_minimum_votes > 6 or not 0 <= self.section_score_threshold <= 1 or not 0 <= self.obb_score_threshold <= 1:
            raise ValueError("Invalid specialist score or TTA setting")
        levels = []
        for index, value in enumerate(self.level_bounds, 1):
            if (not isinstance(value, dict) or set(value) - {"name", "bottom_m", "top_m", "evidence_state"}
                    or not {"name", "bottom_m", "top_m"} <= set(value)
                    or not isinstance(value["name"], str) or not value["name"].strip()
                    or not np.isfinite([value["bottom_m"], value["top_m"]]).all()
                    or value["top_m"] <= value["bottom_m"]):
                raise ValueError(f"Invalid specialist level bound {index}")
            levels.append({"name": value["name"], "bottom_m": float(value["bottom_m"]),
                           "top_m": float(value["top_m"]),
                           "evidence_state": value.get("evidence_state", "user_supplied_bound_not_measured_floor")})
        levels.sort(key=lambda item: (item["bottom_m"], item["top_m"], item["name"]))
        if any(a["top_m"] > b["bottom_m"] + 1e-8 for a, b in zip(levels, levels[1:])):
            raise ValueError("Specialist level bounds overlap")
        return SpecialistSettings(**{**asdict(self), "level_bounds": tuple(levels)})


def _branches_for_role(active, names):
    return [name for name in names if name in active]


def foreground_consensus(votes, minimum_votes):
    """Keep foreground/background evidence separate from subtype consensus."""
    votes = np.asarray(votes)
    if votes.ndim != 2 or votes.shape[1] < 2:
        raise ValueError("Foreground consensus requires background plus at least one foreground class")
    foreground_votes = votes[:, 1:].sum(axis=1)
    native_subclass = votes[:, 1:].argmax(axis=1) + 1
    return foreground_votes >= minimum_votes, native_subclass, foreground_votes


class PunctoraSpecialistProvider(RecognitionProvider):
    """All output remains ProposalSet/overlay evidence until later run owners refit it."""
    def __init__(self, assets, settings=None):
        self.assets = assets.validate()
        self.settings = (settings or SpecialistSettings()).validate()
        self.instances, self.warnings = [], []
        self.process = None
        self.manifest = deepcopy(MODEL_PACK_MANIFEST)
        self.asset_status = {name: {"status": "unchecked"} for name in "ABCDEFGHIJ"}
        self.active_branches, self.missing_branches = [], list("ABCDEFGHIJ")
        self.preflight = None
        self.work = self.artifact_root = None
        self.views, self.proposals, self.point_shards = [], [], []
        self.proposal_support = {}
        self.point_diagnostics = []
        self.tta_diagnostics = []
        self.original_population = self.model_view_population = 0
        self.branch_failures = {}

    @property
    def worker_path(self):
        return Path(__file__).with_name("specialist_worker.py")

    @staticmethod
    def _worker_summary(response):
        """Publish runtime/tensor facts, never transient absolute paths."""
        return {key: deepcopy(value) for key, value in response.items() if key != "output"}

    def bind_source(self, cloud, control):
        assets = self.assets.validate()
        if not Path(assets.python).is_file():
            self.preflight = {"status": "unavailable", "reason": "Explicit specialist Python interpreter is missing"}
            return
        if not Path(assets.model_root).is_dir():
            self.preflight = {"status": "unavailable", "reason": "Explicit specialist model directory is missing"}
            return
        self.manifest, self.asset_status, self.missing_branches = resolve_model_pack(
            assets.model_root, cancelled=control.cancelled)
        self.active_branches = [name for name in "ABCDEFGHIJ" if name not in self.missing_branches]
        if not self.active_branches:
            self.preflight = {"status": "unavailable", "reason": "No reviewed A through J specialist assets are present"}
            return
        largest = max(value.get("graph_bytes", 0) + value.get("companion_bytes", 0)
                      for value in self.asset_status.values())
        if largest * 4 > control.working_budget:
            self.preflight = {"status": "unavailable", "reason": "Largest specialist graph admission estimate exceeds RAM budget"}
            return
        try:
            with tempfile.TemporaryDirectory(prefix="punctora-specialist-preflight-") as temporary:
                directory = Path(temporary)
                request = self._base_request(directory, "preflight")
                request["active_branches"] = self.active_branches
                self.preflight = self._execute(request, directory, control)
        except ProviderUnavailable as exc:
            # The common provider lifecycle enters fallback from prepare(),
            # where its staging cleanup and requested/actual reporting apply.
            self.preflight = {"status": "unavailable", "reason": str(exc)}
            return
        if self.preflight.get("active_branches") != self.active_branches:
            raise ValueError("Specialist preflight did not load the admitted branch set")
        self.original_population = int(len(cloud.points))

    def descriptor(self):
        runtime = self.preflight.get("runtime") if isinstance(self.preflight, dict) else None
        value = {"id": SPECIALIST_PROVIDER_ID, "version": SPECIALIST_PROVIDER_VERSION,
                 "backend": (runtime or {}).get("actual_provider", "CPUExecutionProvider pending"),
                 "score_kind": "branch_native_logits_scores_votes_not_calibrated_probability",
                 "model_pack_id": self.manifest["pack_id"],
                 "model_pack_version": self.manifest["pack_version"],
                 "model_pack_manifest_sha256": self.manifest["manifest_sha256"],
                 "asset_status": self.asset_status,
                 "active_branches": self.active_branches,
                 "missing_branches": self.missing_branches,
                 "runtime": runtime, "settings": asdict(self.settings),
                 "worker_sha256": file_digest(self.worker_path),
                 "interpreter_sha256": file_digest(self.assets.python) if Path(self.assets.python).is_file() else None,
                 "automatic_download": False,
                 "geometry_authority": "review_only"}
        return {**value, "fingerprint": content_digest(value)}

    def _base_request(self, directory, mode):
        response = directory / "response.json"
        return {"schema_version": 1, "mode": mode, "automatic_download": False,
                "model_root": self.assets.model_root, "manifest": self.manifest,
                "response": str(response)}

    def _execute(self, request, directory, control):
        directory.mkdir(parents=True, exist_ok=True)
        request_path = directory / "request.json"
        write_report(request_path, request)
        environment = {key: value for key, value in os.environ.items()
                       if key in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LD_LIBRARY_PATH"}}
        environment.update({"OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"})
        tail = bytearray()
        try:
            self.process = subprocess.Popen([self.assets.python, "-I", str(self.worker_path), str(request_path)],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, env=environment)
            control.child_pid = self.process.pid
            pipe = self.process.stdout
            def drain():
                try:
                    for block in iter(lambda: pipe.read(4096), b""):
                        tail.extend(block)
                        if len(tail) > 16384:
                            del tail[:-16384]
                except (OSError, ValueError):
                    pass
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            started = time.monotonic()
            while self.process.poll() is None:
                control.check()
                if time.monotonic() - started > self.assets.timeout_seconds:
                    raise ProviderUnavailable("Specialist worker timeout exceeded")
                threading.Event().wait(.05)
            reader.join(timeout=1.)
            output = tail.decode("utf-8", errors="replace").strip()
            if self.process.returncode == 20:
                raise ProviderUnavailable(output or "Specialist runtime unavailable")
            if self.process.returncode != 0:
                raise ValueError("Specialist worker failed its contract: " + output)
            response = read_json(request["response"])
            if response.get("schema_version") != 1 or response.get("status") != "complete":
                raise ValueError("Specialist worker returned an incomplete response")
            return response
        finally:
            self.close()
            control.child_pid = None

    def prepare(self, cloud, identity, directory, control):
        if not isinstance(self.preflight, dict) or self.preflight.get("status") != "complete":
            reason = (self.preflight or {}).get("reason", "Specialist preflight was not completed")
            raise ProviderUnavailable(reason)
        self.work = Path(directory)
        self.artifact_root = self.work / "specialist"
        self.artifact_root.mkdir()
        write_report(self.artifact_root / "model-pack-v1.json", self.manifest)
        write_report(self.artifact_root / "runtime-v1.json", self.preflight)
        self.cloud = cloud

    def _point_request(self, view, tile, control):
        directory = self.work / ("point-" + tile.id.replace(":", "_"))
        directory.mkdir()
        feed_manifest = {}
        for name, value in view.feed.items():
            path = directory / (name + ".npy")
            np.save(path, value, allow_pickle=False)
            feed_manifest[name] = str(path.resolve())
        write_report(directory / "feed.json", feed_manifest)
        output = directory / "logits.npy"
        request = self._base_request(directory, "point")
        request.update(branch="I", feed_manifest=str((directory / "feed.json").resolve()),
                       output=str(output.resolve()))
        response = self._execute(request, directory, control)
        return output, response

    def infer_chunk(self, tile, directory, control):
        labels = np.full(len(tile.points), -1, dtype="<i2")
        scores = np.zeros(len(tile.points), dtype="<f4")
        if "I" not in self.active_branches:
            return TilePrediction(labels, scores)
        view = prepare_point_model_view(tile, control)
        if view is None:
            self.point_diagnostics.append({"tile": tile.id, "status": "no_supported_normals",
                                           "original_context_points": len(tile.points)})
            return TilePrediction(labels, scores)
        output, response = self._point_request(view, tile, control)
        logits = np.load(output, mmap_mode="r", allow_pickle=False)
        try:
            if logits.shape != (len(view.feed["feat"]), 12) or logits.dtype != np.float32 or not np.isfinite(logits).all():
                raise ValueError("Branch I logits changed after worker validation")
            native = logits.argmax(axis=1)
            winner = logits[np.arange(len(logits)), native]
            ordered = np.partition(logits, -2, axis=1)
            margin = ordered[:, -1] - ordered[:, -2]
            restored_native = native[view.voxel_inverse]
            restored_score = winner[view.voxel_inverse]
            restored_margin = margin[view.voxel_inverse]
            labels[view.tile_rows] = NATIVE_TO_TAXONOMY[restored_native]
            scores[view.tile_rows] = restored_score.astype("<f4")
            keep = tile.vote_mask[view.tile_rows]
            values = np.empty(int(keep.sum()), dtype=[("row", "<u8"), ("label", "<i2"), ("margin", "<f4")])
            values["row"] = tile.context_rows[view.tile_rows][keep]
            values["label"] = labels[view.tile_rows][keep]
            values["margin"] = restored_margin[keep].astype("<f4")
            values.sort(order="row", kind="stable")
            margin_path = self.work / ("i-margin-" + tile.id.replace(":", "_") + ".npy")
            np.save(margin_path, values, allow_pickle=False)
            self.point_shards.append(margin_path)
            diagnostic = {"tile": tile.id, "status": "complete", **view.diagnostics,
                          "voting_rows": int(keep.sum()), "worker": self._worker_summary(response)}
            self.point_diagnostics.append(diagnostic)
            self.model_view_population += int(view.diagnostics["model_view_points"])
        finally:
            logits._mmap.close()
        return TilePrediction(labels, scores)

    def combine_tiles(self, shards, count, directory, control):
        result = combine_tiles(shards, count, directory, control)
        specialist = Path(directory) / "specialist"
        specialist.mkdir(exist_ok=True)
        vote_count = mapped_array(specialist / "i-vote-count.npy", "<u4", (count,))
        agreement = mapped_array(specialist / "i-agreement.npy", "|u1", (count,))
        margins = mapped_array(specialist / "i-margin.npy", "<f4", (count,))
        label_map = np.load(Path(directory) / result["labels"], mmap_mode="r", allow_pickle=False)
        vote_maps = [np.load(path, mmap_mode="r", allow_pickle=False) for path in shards]
        margin_maps = [np.load(path, mmap_mode="r", allow_pickle=False) for path in self.point_shards]
        try:
            for begin in range(0, count, control.chunk_points):
                control.check()
                end = min(count, begin + control.chunk_points)
                total = np.zeros(end - begin, dtype=np.uint32)
                winning = np.zeros(end - begin, dtype=np.uint32)
                best_margin = np.full(end - begin, -np.inf, dtype=np.float32)
                target = label_map[begin:end]
                for values in vote_maps:
                    left, right = np.searchsorted(values["row"], [begin, end])
                    part = values[left:right]
                    local = part["row"].astype(np.int64) - begin
                    np.add.at(total, local, 1)
                    np.add.at(winning, local, part["label"] == target[local])
                for values in margin_maps:
                    left, right = np.searchsorted(values["row"], [begin, end])
                    part = values[left:right]
                    local = part["row"].astype(np.int64) - begin
                    selected = part["label"] == target[local]
                    np.maximum.at(best_margin, local[selected], part["margin"][selected])
                vote_count[begin:end] = total
                agreement[begin:end] = np.where(total, np.floor(255 * winning / np.maximum(total, 1)), 0).astype(np.uint8)
                margins[begin:end] = np.where(np.isfinite(best_margin), best_margin, 0.)
            for value in (vote_count, agreement, margins):
                value.flush()
        finally:
            label_map._mmap.close()
            for value in [*vote_maps, *margin_maps, vote_count, agreement, margins]:
                value._mmap.close()
        self._semantic_rescue(Path(directory) / result["labels"], control)
        return result

    def _cloud_bounds(self, control):
        low, high = np.full(3, np.inf), np.full(3, -np.inf)
        for begin in range(0, len(self.cloud.points), control.chunk_points):
            control.check()
            points = self.cloud.points[begin:begin + control.chunk_points]
            low, high = np.minimum(low, points.min(axis=0)), np.maximum(high, points.max(axis=0))
        return low, high

    def _levels(self, low, high):
        if self.settings.level_bounds:
            return [dict(value) for value in self.settings.level_bounds]
        return [{"name": "Observed vertical extent", "bottom_m": float(low[2]), "top_m": float(high[2]),
                 "evidence_state": "observed_extent_not_measured_floor"}]

    @staticmethod
    def _iter_box_rows(index, minimum, maximum):
        cell = index.cell_size_m
        lower, upper = np.floor(np.asarray(minimum) / cell).astype(np.int64), np.floor(np.asarray(maximum) / cell).astype(np.int64)
        for cells, starts, rows in index.runs:
            left = np.searchsorted(cells["x"], lower[0], side="left")
            right = np.searchsorted(cells["x"], upper[0], side="right")
            block = cells[left:right]
            positions = np.flatnonzero((block["y"] >= lower[1]) & (block["y"] <= upper[1])
                                       & (block["z"] >= lower[2]) & (block["z"] <= upper[2])) + left
            for position in positions:
                end = starts[position + 1] if position + 1 < len(starts) else len(rows)
                yield rows[starts[position]:end]

    def _rows_in_box(self, index, minimum, maximum, control):
        parts, count = [], 0
        for part in self._iter_box_rows(index, minimum, maximum):
            control.check()
            count += len(part)
            if count > self.settings.maximum_view_points:
                raise ProviderUnavailable("Specialist raster view exceeds its explicit original-point cap; crop or subdivide")
            parts.append(np.asarray(part, dtype=np.int64))
        if not parts:
            return np.empty(0, dtype=np.int64)
        rows = np.unique(np.concatenate(parts))
        points = self.cloud.points[rows]
        keep = np.all((points >= minimum) & (points <= maximum), axis=1)
        return rows[keep]

    def _infer_image(self, branch, image, identifier, control):
        directory = self.work / ("image-" + identifier)
        directory.mkdir()
        tensor_path, output = directory / "tensor.npy", directory / "outputs.npz"
        tensor = image_tensor(branch, image)
        np.save(tensor_path, tensor, allow_pickle=False)
        request = self._base_request(directory, "image")
        request.update(branch=branch, tensor=str(tensor_path.resolve()), output=str(output.resolve()))
        response = self._execute(request, directory, control)
        archive = np.load(output, allow_pickle=False)
        try:
            outputs = {name: archive[name].copy() for name in archive.files}
        finally:
            archive.close()
        return outputs, response

    @staticmethod
    def _component_proposals(branch, points, level, tile_id, minimum_points=6, source_rows=None):
        if len(points) < minimum_points:
            return []
        origin = points[:, :2].min(axis=0)
        pixel = .05
        # Local subtraction near survey-scale coordinates can leave an exact
        # cell boundary a few float64 ULPs below its integer.  The tolerance is
        # below 5 nm at this grid and only stabilizes mathematical boundaries.
        grid = np.floor((points[:, :2] - origin) / pixel + 1e-7).astype(np.int64)
        width, height = grid.max(axis=0) + 1
        if width * height > 4_000_000:
            return []
        image = np.zeros((height, width), dtype=np.uint8)
        image[grid[:, 1], grid[:, 0]] = 1
        count, labels = cv2.connectedComponents(image, connectivity=8)
        point_components = labels[grid[:, 1], grid[:, 0]]
        result = []
        for component in range(1, count):
            rows, columns = np.nonzero(labels == component)
            if len(rows) < minimum_points:
                continue
            local_xy = np.column_stack((columns + .5, rows + .5)) * pixel
            # OpenCV geometry is float32: fit only the local metre-scale view,
            # then restore the f64 survey/local origin after the model call.
            centre, size, angle = cv2.minAreaRect(local_xy.astype(np.float32))
            size = (max(float(size[0]), pixel), max(float(size[1]), pixel))
            local_rectangle = cv2.boxPoints((centre, size, angle)).astype(np.float64)
            rectangle = local_rectangle + origin
            if branch == "I" and abs(float(cv2.contourArea(local_rectangle.astype(np.float32)))) < .15:
                continue
            support = (np.asarray(source_rows, dtype=np.uint64)[point_components == component]
                       if source_rows is not None else np.empty(0, dtype=np.uint64))
            result.append({"id": f"{branch}:{tile_id}:{component}", "branch": branch,
                           "class": {"D": "wall", "E": "opening", "F": "beam", "G": "column",
                                     "H": "stair", "I": "wall"}[branch],
                           "status": "proposed", "polygon_xy_m": rectangle.tolist(),
                           "z_min_m": level["bottom_m"], "z_max_m": level["top_m"],
                           "support_points": int(len(support) if source_rows is not None else len(rows)),
                           "support_state": "point_gated_model_view_candidate",
                           "display_scope": "minimum one-cell envelope; not accepted physical width",
                           "geometry_authority": "review_only", "_source_rows": support})
        return result

    def _add_proposals(self, items):
        for item in items:
            rows = np.unique(np.asarray(item.pop("_source_rows", []), dtype=np.uint64))
            item["source_support"] = {"kind": "specialist_support_index", "key": item["id"]}
            self.proposal_support[item["id"]] = rows
            self.proposals.append(item)

    def _semantic_rescue(self, labels_path, control):
        """Keep uncovered I-wall residuals as separate, point-gated proposals."""
        if "I" not in self.active_branches:
            return
        labels = np.load(labels_path, mmap_mode="r", allow_pickle=False)
        try:
            low, high = self._cloud_bounds(control)
            levels = self._levels(low, high)
            masks = []
            from shapely.geometry import Polygon
            from shapely.ops import unary_union
            for proposal in self.proposals:
                if proposal.get("branch") == "D" and proposal.get("polygon_xy_m"):
                    shape = Polygon(proposal["polygon_xy_m"])
                    if shape.is_valid and not shape.is_empty:
                        masks.append(shape.buffer(.30))
            covered = unary_union(masks) if masks else None
            for level_index, level in enumerate(levels):
                parts, row_parts, count = [], [], 0
                for begin in range(0, len(labels), control.chunk_points):
                    control.check()
                    end = min(len(labels), begin + control.chunk_points)
                    points = np.asarray(self.cloud.points[begin:end], dtype=np.float64)
                    keep = ((labels[begin:end] == 0) & (points[:, 2] >= level["bottom_m"])
                            & (points[:, 2] <= level["top_m"]))
                    selected = points[keep]
                    count += len(selected)
                    if count > self.settings.maximum_view_points:
                        self.warnings.append(
                            f"Branch I semantic rescue for {level['name']} exceeds the explicit point cap; "
                            "point labels remain available without a component overlay")
                        parts = []
                        break
                    if len(selected):
                        parts.append(selected)
                        row_parts.append(np.flatnonzero(keep).astype(np.uint64) + begin)
                if not parts:
                    continue
                points = np.concatenate(parts)
                source_rows = np.concatenate(row_parts)
                if covered is not None:
                    from shapely import contains_xy
                    residual = ~contains_xy(covered, points[:, 0], points[:, 1])
                    points, source_rows = points[residual], source_rows[residual]
                items = self._component_proposals("I", points, level, f"residual-{level_index}",
                                                  source_rows=source_rows)
                for item in items:
                    item["rescue_rule"] = {"existing_wall_distance_m": .30,
                                           "minimum_residual_area_m2": .15,
                                           "classification": "I wall label; original-point extent"}
                self._add_proposals(items)
        finally:
            labels._mmap.close()

    def _plan_tile(self, centre, level, tile_number, index, control):
        settings = self.settings
        half = settings.stair_tile_m * np.sqrt(2) / 2
        minimum = [centre[0] - half, centre[1] - half, level["bottom_m"]]
        maximum = [centre[0] + half, centre[1] + half, level["top_m"]]
        rows = self._rows_in_box(index, minimum, maximum, control)
        if not len(rows):
            return
        points = np.asarray(self.cloud.points[rows], dtype=np.float64)
        upper_low = min(level["top_m"], level["bottom_m"] + settings.upper_slice_offset_m)
        upper_high = min(level["top_m"], upper_low + settings.slice_thickness_m)
        if upper_high <= upper_low:
            upper_low, upper_high = level["bottom_m"], level["top_m"]
        middle = (level["bottom_m"] + level["top_m"]) / 2
        middle_low, middle_high = middle - settings.slice_thickness_m / 2, middle + settings.slice_thickness_m / 2
        upper_rows = (points[:, 2] >= upper_low) & (points[:, 2] <= upper_high)
        middle_rows = (points[:, 2] >= middle_low) & (points[:, 2] <= middle_high)
        votes = {branch: np.zeros((len(points), 3 if branch in {"D", "E"} else 2), dtype=np.uint8)
                 for branch in _branches_for_role(self.active_branches, "DEFGH")}
        j_candidates = []
        for angle in (0., 30., 60.):
            for mirrored in (False, True):
                for branch in _branches_for_role(self.active_branches, "DEFG"):
                    if branch in self.branch_failures:
                        continue
                    frame_id = f"plan:{tile_number}:{branch}:{int(angle)}:{int(mirrored)}"
                    frame = plan_frame(frame_id, centre, settings.plan_tile_m, settings.plan_native_pixels,
                                       angle, mirrored, upper_low, upper_high, settings.plan_model_pixels)
                    image, raster = rasterize_plan(frame, points[upper_rows])
                    try:
                        outputs, worker = self._infer_image(branch, image, frame_id.replace(":", "_"), control)
                    except ProviderUnavailable as exc:
                        self.branch_failures.setdefault(branch, str(exc))
                        self.warnings.append(f"Specialist branch {branch} unavailable: {exc}")
                        if branch == "D" and "J" in self.active_branches:
                            self.branch_failures.setdefault("J", "Branch J requires the branch D plan overlay")
                        continue
                    labels, winning, margin = decode_masks(branch, outputs)
                    pixel_rows, pixel_columns, inside = plan_pixels(frame, points, pixels=settings.plan_model_pixels)
                    inside &= upper_rows
                    sampled = labels[pixel_rows[inside], pixel_columns[inside]]
                    np.add.at(votes[branch], (np.flatnonzero(inside), sampled), 1)
                    self.views.append({"branch": branch, "frame": frame.to_dict(), "raster": raster,
                                       "worker": self._worker_summary(worker), "native_label_counts": np.bincount(labels.ravel(), minlength=votes[branch].shape[1]).tolist(),
                                       "winning_logit_range": [float(winning.min()), float(winning.max())],
                                       "margin_range": [float(margin.min()), float(margin.max())]})
                    if branch == "D" and "J" in self.active_branches and "J" not in self.branch_failures:
                        base = cv2.resize(image, (settings.plan_model_pixels, settings.plan_model_pixels), interpolation=cv2.INTER_LINEAR)
                        overlay = np.repeat(base[:, :, None], 3, axis=2)
                        palette = np.asarray([[0, 0, 0], [0, 0, 255], [0, 255, 0]], dtype=np.uint8)
                        overlay = (.5 * overlay + .5 * palette[labels]).astype(np.uint8)
                        try:
                            j_outputs, j_worker = self._infer_image("J", overlay, frame_id.replace(":", "_") + "_J", control)
                        except ProviderUnavailable as exc:
                            self.branch_failures.setdefault("J", str(exc))
                            self.warnings.append(f"Specialist branch J unavailable: {exc}")
                            continue
                        decoded = decode_obb(j_outputs, frame, settings.obb_score_threshold)
                        j_candidates.extend(decoded)
                        self.views.append({"branch": "J", "frame": frame.to_dict(), "worker": self._worker_summary(j_worker),
                                           "candidates": len(decoded), "overlay_recipe": "BGR alpha 0.5, no JPEG"})
                if "H" in self.active_branches and "H" not in self.branch_failures:
                    frame_id = f"plan:{tile_number}:H:{int(angle)}:{int(mirrored)}"
                    frame = plan_frame(frame_id, centre, settings.stair_tile_m, settings.stair_native_pixels,
                                       angle, mirrored, middle_low, middle_high, settings.plan_model_pixels)
                    image, raster = rasterize_plan(frame, points[middle_rows])
                    try:
                        outputs, worker = self._infer_image("H", image, frame_id.replace(":", "_"), control)
                    except ProviderUnavailable as exc:
                        self.branch_failures.setdefault("H", str(exc))
                        self.warnings.append(f"Specialist branch H unavailable: {exc}")
                        continue
                    labels, winning, margin = decode_masks("H", outputs)
                    pixel_rows, pixel_columns, inside = plan_pixels(frame, points, pixels=settings.plan_model_pixels)
                    inside &= middle_rows
                    sampled = labels[pixel_rows[inside], pixel_columns[inside]]
                    np.add.at(votes["H"], (np.flatnonzero(inside), sampled), 1)
                    self.views.append({"branch": "H", "frame": frame.to_dict(), "raster": raster,
                                       "worker": self._worker_summary(worker), "native_label_counts": np.bincount(labels.ravel(), minlength=2).tolist(),
                                       "winning_logit_range": [float(winning.min()), float(winning.max())],
                                       "margin_range": [float(margin.min()), float(margin.max())]})
        for branch, branch_votes in votes.items():
            selected, native_subclass, foreground_votes = foreground_consensus(
                branch_votes, settings.tta_minimum_votes)
            self.tta_diagnostics.append({
                "branch": branch,
                "tile": str(tile_number),
                "candidate_points": int(len(points)),
                "selected_foreground_points": int(selected.sum()),
                "foreground_vote_histogram": np.bincount(
                    foreground_votes, minlength=7).astype(np.uint64).tolist(),
                "selected_native_subclass_counts": np.bincount(
                    native_subclass[selected], minlength=branch_votes.shape[1]).astype(np.uint64).tolist(),
            })
            self._add_proposals(self._component_proposals(
                branch, points[selected], level, str(tile_number), source_rows=rows[selected]))
        self._wall_instances(j_candidates, level, tile_number, points, rows)
        self._section_views(points, rows, level, tile_number, j_candidates, control)

    def _wall_instances(self, candidates, level, tile_number, points, source_rows):
        for candidate in candidates:
            corners = np.asarray(candidate["corners_xy_m"], dtype=np.float64)
            edges = np.roll(corners, -1, axis=0) - corners
            lengths = np.linalg.norm(edges, axis=1)
            long_index = int(lengths.argmax())
            if lengths[long_index] <= .05:
                continue
            start = (corners[long_index] + corners[(long_index + 3) % 4]) / 2
            end = (corners[(long_index + 1) % 4] + corners[(long_index + 2) % 4]) / 2
            thickness = max(.01, float(np.min(lengths)))
            geometry = {"type": "wall", "start": start.tolist(), "end": end.tolist(),
                        "base": level["bottom_m"], "height": level["top_m"] - level["bottom_m"],
                        "thickness": thickness}
            identifier = "specialist:wall:" + content_digest({"tile": tile_number, "query": candidate,
                                                                 "level": level["name"]})[:24]
            item = {"id": identifier, "class": "wall", "status": "proposed", "geometry": geometry,
                    "bounds_m": [[float(corners[:, 0].min()), float(corners[:, 1].min()), level["bottom_m"]],
                                 [float(corners[:, 0].max()), float(corners[:, 1].max()), level["top_m"]]],
                    "support_reference": "ProposalSet source arrays, independently revalidate before acceptance",
                    "support_state": "inferred", "native_score": candidate["native_score"],
                    "native_score_kind": candidate["native_score_kind"],
                    "provenance": {"axis": "specialist_J_proposal_only", "height": level["evidence_state"],
                                   "thickness": "specialist_J_proposal_only"}}
            from shapely import contains_xy
            from shapely.geometry import Polygon
            shape = Polygon(corners).buffer(1e-9)
            support = np.asarray(source_rows, dtype=np.uint64)[contains_xy(shape, points[:, 0], points[:, 1])]
            item["source_support"] = {"kind": "specialist_support_index", "key": identifier}
            # Deterministic, query-aware cross-view suppression.  Later wall
            # fitting still owns physical deduplication against original points.
            centre = corners.mean(axis=0)
            duplicate = None
            for previous in self.instances:
                previous_centre = (np.asarray(previous["geometry"]["start"]) + np.asarray(previous["geometry"]["end"])) / 2
                if np.linalg.norm(previous_centre - centre) <= max(.10, thickness):
                    duplicate = previous
                    break
            if duplicate is None:
                self.instances.append(item); self.proposal_support[identifier] = np.unique(support)
            elif item["native_score"] > duplicate["native_score"]:
                self.proposal_support.pop(duplicate["id"], None)
                self.instances[self.instances.index(duplicate)] = item
                self.proposal_support[identifier] = np.unique(support)

    def _section_views(self, points, source_rows, level, tile_number, walls, control):
        jobs = []
        if "A" in self.active_branches:
            jobs.append(("A", np.array([1., 0.]), "overview"))
        for index, wall in enumerate(walls[:max(0, self.settings.maximum_section_views - len(jobs))]):
            corners = np.asarray(wall["corners_xy_m"])
            edge = corners[1] - corners[0]
            if np.linalg.norm(edge) <= 1e-12:
                continue
            for branch in _branches_for_role(self.active_branches, "BC"):
                jobs.append((branch, edge, f"wall-{index}"))
                if len(jobs) >= self.settings.maximum_section_views:
                    break
        for sequence, (branch, axis, scope) in enumerate(jobs):
            if branch in self.branch_failures:
                continue
            frame_id = f"section:{tile_number}:{branch}:{sequence}"
            try:
                frame = section_frame(frame_id, points, axis, base_m=level["bottom_m"],
                                      extension_m=.15 if branch == "B" else 0.)
            except ValueError:
                continue
            image = rasterize_section(frame, points)
            rendered = slab_section_windows(frame, image) if branch == "A" else [
                (image, frame, {"lossless_inference_buffer": True, "generic_section": True})]
            decoded = []
            for window_index, (window, mapped_frame, transform) in enumerate(rendered):
                try:
                    outputs, worker = self._infer_image(
                        branch, window, frame_id.replace(":", "_") + f"_{window_index}", control)
                except ProviderUnavailable as exc:
                    self.branch_failures.setdefault(branch, str(exc))
                    self.warnings.append(f"Specialist branch {branch} unavailable: {exc}")
                    decoded = []
                    break
                values = decode_section(branch, outputs, mapped_frame, self.settings.section_score_threshold)
                decoded.extend(values)
                self.views.append({"branch": branch, "frame": mapped_frame.to_dict(), "source_frame": frame.to_dict(),
                                   "input_transform": transform, "worker": self._worker_summary(worker),
                                   "candidates_before_cross_window_nms": len(values), "section_scope": scope})
            if branch == "A" and len(rendered) > 1:
                decoded = self._section_nms(decoded, .3)
            for item in decoded:
                world = item["world"]
                start, end = np.asarray(world["start"], dtype=np.float64), np.asarray(world["end"], dtype=np.float64)
                direction = end - start
                length = np.linalg.norm(direction)
                if length <= 1e-12 or world["z_max_m"] - world["z_min_m"] <= 1e-6:
                    continue
                side = np.array([-direction[1], direction[0]]) / length * max(.015, frame.pixel_m * 1.5)
                item.update({"id": f"{branch}:{tile_number}:{sequence}:" + content_digest(
                                 {"frame": item["frame_id"], "query": item["query_id"], "world": world})[:16],
                             "class": {"A": "slab", "B": "opening", "C": "beam"}[branch],
                             "section_scope": scope, "geometry_authority": "review_only",
                             "polygon_xy_m": [(start - side).tolist(), (end - side).tolist(),
                                                (end + side).tolist(), (start + side).tolist()],
                             "z_min_m": world["z_min_m"], "z_max_m": world["z_max_m"],
                             "display_scope": "thin section ribbon; width is visual only, not physical geometry"})
                axis = direction / length
                along = points[:, :2] @ axis
                low, high = sorted((float(start @ axis), float(end @ axis)))
                supported = ((along >= low) & (along <= high) & (points[:, 2] >= world["z_min_m"])
                             & (points[:, 2] <= world["z_max_m"]))
                item["_source_rows"] = np.asarray(source_rows, dtype=np.uint64)[supported]
                self._add_proposals([item])

    @staticmethod
    def _section_nms(items, threshold):
        def rectangle(item):
            world = item["world"]
            start, end = np.asarray(world["start"]), np.asarray(world["end"])
            axis = end - start
            length = np.linalg.norm(axis)
            if length <= 1e-12:
                return None
            direction = axis / length
            u1, u2 = sorted((float(start @ direction), float(end @ direction)))
            return np.array([u1, world["z_min_m"], u2, world["z_max_m"]], dtype=np.float64)
        ordered = sorted(items, key=lambda item: (-item["native_score"], item["frame_id"], item["query_id"]))
        kept, boxes = [], []
        for item in ordered:
            box = rectangle(item)
            if box is None:
                continue
            duplicate = False
            for previous in boxes:
                low = np.maximum(box[:2], previous[:2]); high = np.minimum(box[2:], previous[2:])
                intersection = float(np.maximum(high - low, 0).prod())
                area_a = float(np.maximum(box[2:] - box[:2], 0).prod())
                area_b = float(np.maximum(previous[2:] - previous[:2], 0).prod())
                union = area_a + area_b - intersection
                if union > 0 and intersection / union > threshold:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(item); boxes.append(box)
        return kept

    def prepare_instances(self, cloud, identity, directory, control, spatial_index):
        image_branches = _branches_for_role(self.active_branches, "ABCDEFGHJ")
        if not image_branches:
            return
        low, high = self._cloud_bounds(control)
        levels = self._levels(low, high)
        side = self.settings.plan_tile_m
        x0, y0 = np.floor(low[:2] / side).astype(np.int64)
        x1, y1 = np.floor(high[:2] / side).astype(np.int64)
        tiles = [(x, y) for x in range(int(x0), int(x1) + 1) for y in range(int(y0), int(y1) + 1)]
        if len(tiles) * len(levels) > self.settings.maximum_plan_tiles:
            reason = (f"Image specialists need {len(tiles) * len(levels)} plan tiles, above the explicit "
                      f"limit {self.settings.maximum_plan_tiles}; point branch I remains active")
            for branch in image_branches:
                self.branch_failures[branch] = reason
            self.warnings.append(reason)
            return
        for level_index, level in enumerate(levels):
            for tile_index, (x, y) in enumerate(tiles):
                control.check()
                centre = [(x + .5) * side, (y + .5) * side]
                identifier = f"{level_index}-{tile_index}-{x}-{y}"
                try:
                    self._plan_tile(centre, level, identifier, spatial_index, control)
                except ProviderUnavailable as exc:
                    reason = str(exc)
                    for branch in image_branches:
                        self.branch_failures.setdefault(branch, reason)
                    self.warnings.append(f"Specialist image tile {identifier} unavailable: {reason}")

    def write_artifacts(self, directory, control):
        destination = Path(directory) / "specialist"
        destination.mkdir(exist_ok=True)
        for source in self.artifact_root.iterdir():
            shutil.copy2(source, destination / source.name)
        support_ids = sorted({item["id"] for item in [*self.proposals, *self.instances]})
        support_entries, support_parts, offset = [], [], 0
        for identifier in support_ids:
            rows = np.unique(np.asarray(self.proposal_support.get(identifier, []), dtype="<u8"))
            support_entries.append({"id": identifier, "offset": offset, "count": int(len(rows))})
            support_parts.append(rows); offset += len(rows)
        support_rows = np.concatenate(support_parts) if support_parts else np.empty(0, dtype="<u8")
        np.save(destination / "proposal-source-rows.npy", support_rows, allow_pickle=False)
        write_report(destination / "support-index-v1.json",
                     {"schema_version": 1, "coordinate_authority": "ProposalSet source-array row indices",
                      "entries": support_entries})
        write_report(destination / "views-v1.json", {"schema_version": 1, "views": self.views,
                                                       "coordinate_authority": "original f64 source mapping"})
        write_report(destination / "specialist-proposals-v1.json",
                     {"schema_version": 1, "geometry_authority": "review_only",
                      "proposals": self.proposals})
        artifacts = []
        for path in sorted(destination.iterdir()):
            if path.is_file():
                artifacts.append({"path": "specialist/" + path.name, "sha256": file_digest(path, cancelled=control.cancelled)})
        point_arrays = {}
        for name, filename in (("agreement", "i-agreement.npy"), ("vote_count", "i-vote-count.npy"),
                               ("margin", "i-margin.npy")):
            path = destination / filename
            if path.is_file():
                value = np.load(path, mmap_mode="r", allow_pickle=False)
                try:
                    point_arrays[name] = array_descriptor(path, "specialist/" + filename, value, control.cancelled)
                finally:
                    value._mmap.close()
        support_descriptor = array_descriptor(destination / "proposal-source-rows.npy",
                                              "specialist/proposal-source-rows.npy", support_rows,
                                              control.cancelled)
        branches = {}
        for name in "ABCDEFGHIJ":
            status = "missing" if name in self.missing_branches else "failed" if name in self.branch_failures else "active"
            branches[name] = {"status": status, "task": self.manifest["branches"][name]["task"],
                              "graph_sha256": self.asset_status[name].get("graph_sha256"),
                              "companion_sha256": self.asset_status[name].get("companion_sha256"),
                              "failure": self.branch_failures.get(name)}
        return {"specialist_v1": {"schema_version": 1, "provider_id": SPECIALIST_PROVIDER_ID,
                 "provider_version": SPECIALIST_PROVIDER_VERSION, "geometry_authority": "review_only",
                 "model_pack_manifest_sha256": self.manifest["manifest_sha256"],
                 "runtime": self.preflight["runtime"], "branches": branches,
                 "original_source_population": self.original_population,
                 "point_model_view_population": self.model_view_population,
                 "point_tiles": self.point_diagnostics,
                 "tta_diagnostics": self.tta_diagnostics,
                 "tta_rule": "six views: 0/30/60 degrees and mirrored; foreground and native-class votes separate; minimum four",
                 "views_path": "specialist/views-v1.json",
                 "proposals_path": "specialist/specialist-proposals-v1.json",
                 "support_index_path": "specialist/support-index-v1.json",
                 "support_rows": support_descriptor,
                 "point_arrays": point_arrays, "artifacts": artifacts,
                 "accepted_geometry_changes": 0, "accepted_cuts": 0, "ifc_objects_written": 0}}

    def close(self):
        process = self.process
        if process is None:
            return
        try:
            if process.poll() is None:
                try:
                    import psutil
                    owner = psutil.Process(process.pid)
                    children = owner.children(recursive=True)
                except Exception:
                    children = []
                for child in children:
                    try:
                        child.terminate()
                    except Exception:
                        pass
                process.terminate()
                try:
                    process.wait(timeout=2.)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.)
                for child in children:
                    try:
                        if child.is_running():
                            child.kill()
                    except Exception:
                        pass
        finally:
            if process.stdout:
                process.stdout.close()
            self.process = None
