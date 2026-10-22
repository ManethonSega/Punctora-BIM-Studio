"""Punctora-owned specialist runtime, proposals and truthful orchestration."""
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass, asdict
import json
import math
import os
from pathlib import Path
import queue
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
from .specialist_frames import plan_frame, plan_pixels, slab_section_windows
from .specialist_indices import prepare_point_model_view
from .specialist_pack import (MODEL_PACK_MANIFEST, SPECIALIST_PROVIDER_ID,
                              SPECIALIST_PROVIDER_VERSION, resolve_model_pack)
from .specialist_worker import image_tensor
from .specialist_runtime import runtime_plan


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
        self.control = None
        self.exchange = None
        self.exchange_root = None
        self.response_queue = None
        self.stdout_reader = self.stderr_reader = None
        self.stderr_tail = bytearray()
        self.request_sequence = 0
        self.worker_start_count = 0
        self.session_cache_limit = 1
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
        self.runtime_profile = {}
        self.runtime_plan = runtime_plan(2, 1, 1, 1)

    @contextmanager
    def _profile_phase(self, name, control):
        """Bounded, durable timing facts, including unfinished/failed requests."""
        previous = getattr(control, 'stage', None)
        previous_started = getattr(control, 'provider_phase_started', None)
        started = time.monotonic()
        control.stage = 'specialist_' + name
        control.provider_timings = deepcopy(self.runtime_profile)
        control.provider_phase_started = started
        failed = False
        if hasattr(control, 'emit'): control.emit()
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            entry = self.runtime_profile.setdefault(name, {'calls': 0, 'seconds': 0., 'failures': 0})
            entry['calls'] += 1
            entry['seconds'] += time.monotonic() - started
            entry['failures'] += int(failed)
            control.provider_timings = deepcopy(self.runtime_profile)
            control.provider_phase_started = previous_started
            if previous is not None: control.stage = previous
            if hasattr(control, 'emit'): control.emit()

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
        session_estimate = largest * 4
        if session_estimate > control.working_budget:
            self.preflight = {"status": "unavailable", "reason": "Largest specialist graph admission estimate exceeds RAM budget"}
            return
        self.session_cache_limit = max(1, min(10, len(self.active_branches),
                                             int(control.working_budget * .60) // max(1, session_estimate)))
        self.runtime_plan = runtime_plan(getattr(control, 'cpu_workers', 1), control.working_budget,
                                         largest, self.session_cache_limit)
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
                 "adapter_version": "a38-owned-worker-exchange-v4",
                 "point_preprocessing": "source-key centring; one original-neighbour normal per fixed-0.06m voxel representative",
                 "view_point_limit_scope": "maximum_materialized_original_points_per_block; complete_physical_raster",
                 "backend": (runtime or {}).get("actual_provider", "CPUExecutionProvider pending"),
                 "score_kind": "branch_native_logits_scores_votes_not_calibrated_probability",
                 "model_pack_id": self.manifest["pack_id"],
                 "model_pack_version": self.manifest["pack_version"],
                 "model_pack_manifest_sha256": self.manifest["manifest_sha256"],
                 "asset_status": self.asset_status,
                 "active_branches": self.active_branches,
                 "missing_branches": self.missing_branches,
                 "runtime": runtime, "runtime_plan": self.runtime_plan, "settings": asdict(self.settings),
                 "worker_sha256": file_digest(self.worker_path),
                 "interpreter_sha256": file_digest(self.assets.python) if Path(self.assets.python).is_file() else None,
                 "automatic_download": False,
                 "geometry_authority": "review_only"}
        return {**value, "fingerprint": content_digest(value)}

    def _base_request(self, directory, mode):
        response = directory / "response.json"
        return {"schema_version": 1, "mode": mode, "automatic_download": False,
                "model_root": self.assets.model_root, "manifest": self.manifest,
                "response": str(response), "maximum_cached_sessions": self.session_cache_limit,
                "runtime_plan": self.runtime_plan}

    def _start_worker(self, control):
        if self.process is not None and self.process.poll() is None:
            return
        environment = {key: value for key, value in os.environ.items()
                       if key in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LD_LIBRARY_PATH"}}
        # ORT owns the explicit intra-op pools. Nested BLAS/OpenMP pools must
        # not multiply the wave's declared CPU budget.
        environment.update({"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
        self.response_queue = queue.Queue()
        self.stderr_tail = bytearray()
        self.process = subprocess.Popen(
            [self.assets.python, "-I", str(self.worker_path), "--serve"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        self.control = control
        self.worker_start_count += 1
        control.child_pid = self.process.pid
        stdout, stderr = self.process.stdout, self.process.stderr
        responses, stderr_tail = self.response_queue, self.stderr_tail

        def read_stdout():
            try:
                for line in iter(stdout.readline, b""):
                    try:
                        responses.put(json.loads(line.decode("utf-8")))
                    except Exception as exc:
                        responses.put(ValueError("Specialist worker emitted malformed protocol JSON: " + str(exc)))
            except (OSError, ValueError):
                pass

        def read_stderr():
            try:
                for block in iter(lambda: stderr.read(4096), b""):
                    stderr_tail.extend(block)
                    if len(stderr_tail) > 16384:
                        del stderr_tail[:-16384]
            except (OSError, ValueError):
                pass

        self.stdout_reader = threading.Thread(target=read_stdout, daemon=True)
        self.stderr_reader = threading.Thread(target=read_stderr, daemon=True)
        self.stdout_reader.start()
        self.stderr_reader.start()
        started = time.monotonic()
        while True:
            control.check()
            if self.process.poll() is not None:
                detail = self.stderr_tail.decode("utf-8", errors="replace").strip()
                raise ProviderUnavailable(detail or "Specialist worker stopped before protocol readiness")
            try:
                ready = self.response_queue.get(timeout=.05)
            except queue.Empty:
                if time.monotonic() - started > self.assets.timeout_seconds:
                    raise ProviderUnavailable("Specialist worker startup timeout exceeded")
                continue
            if isinstance(ready, BaseException):
                raise ready
            if ready != {"schema_version": 1, "status": "ready"}:
                raise ValueError("Specialist worker failed its readiness contract")
            return

    def _execute(self, request, directory, control):
        with self._profile_phase(request.get('branch', request['mode']) + '_worker', control):
            response = self._execute_request(request, directory, control)
            self._record_worker_timing(response)
            return response

    def _record_worker_timing(self, response):
        for value in response.get('results', [response]):
            if value.get('timings'):
                entry = self.runtime_profile.setdefault(value['branch']+'_onnx', {'calls': 0, 'seconds': 0., 'failures': 0})
                entry['calls'] += 1
                for name, seconds in value['timings'].items():
                    entry[name] = entry.get(name, 0.) + seconds
                entry['seconds'] += sum(value['timings'].values())
                if 'session_cache_hit' in value:
                    name = 'session_cache_hits' if value['session_cache_hit'] else 'session_cache_misses'
                    entry[name] = entry.get(name, 0) + 1
        if response.get('process_timing'):
            entry = self.runtime_profile.setdefault('worker_process', {'calls': 0, 'seconds': 0., 'failures': 0, 'cpu_seconds': 0.})
            entry['calls'] += 1
            entry['seconds'] += response['process_timing']['wall_seconds']
            entry['cpu_seconds'] += response['process_timing']['cpu_seconds']

    def _execute_request(self, request, directory, control):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            self._start_worker(control)
            self.request_sequence += 1
            request_id = self.request_sequence
            # The control envelope is small. Send it inline so the persistent
            # worker never has to reopen a just-published JSON file through a
            # long or Unicode project staging path. Large tensors and outputs
            # remain file-backed in the short provider-owned exchange.
            message = json.dumps({"request_id": request_id, "request": request},
                                 ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
            self.process.stdin.write(message.encode("utf-8"))
            self.process.stdin.flush()
            started = time.monotonic()
            while True:
                control.check()
                if self.process.poll() is not None:
                    detail = self.stderr_tail.decode("utf-8", errors="replace").strip()
                    raise ValueError("Specialist worker stopped during inference: " + detail)
                try:
                    reply = self.response_queue.get(timeout=.05)
                except queue.Empty:
                    if time.monotonic() - started > self.assets.timeout_seconds:
                        raise ProviderUnavailable("Specialist worker request timeout exceeded")
                    continue
                if isinstance(reply, BaseException):
                    raise reply
                if (not isinstance(reply, dict) or reply.get("schema_version") != 1
                        or reply.get("request_id") != request_id):
                    raise ValueError("Specialist worker failed its response identity contract")
                if reply.get("status") == "unavailable":
                    raise ProviderUnavailable(reply.get("error") or "Specialist runtime unavailable")
                if reply.get("status") != "complete":
                    raise ValueError("Specialist worker failed its contract: " + reply.get("error", "unknown failure"))
                break
            response = read_json(request["response"])
            if response.get("schema_version") != 1 or response.get("status") != "complete":
                raise ValueError("Specialist worker returned an incomplete response")
            return response
        except BaseException:
            # Keep the exchange alive while caller contexts unwind; the outer
            # recognition lifecycle removes it after stopping the worker.
            self._stop_worker()
            raise

    def prepare(self, cloud, identity, directory, control):
        if not isinstance(self.preflight, dict) or self.preflight.get("status") != "complete":
            reason = (self.preflight or {}).get("reason", "Specialist preflight was not completed")
            raise ProviderUnavailable(reason)
        self.work = Path(directory)
        # Worker-only tensors never cross the saved project's deep staging
        # path.  Keep one short, provider-owned exchange alive until the
        # persistent worker has stopped, then remove it in close().
        if self.exchange is not None:
            self.exchange.cleanup()
        self.exchange = tempfile.TemporaryDirectory(prefix="punctora-specialist-exchange-")
        self.exchange_root = Path(self.exchange.name).resolve()
        self.artifact_root = self.work / "specialist"
        self.artifact_root.mkdir()
        write_report(self.artifact_root / "model-pack-v1.json", self.manifest)
        write_report(self.artifact_root / "runtime-v1.json", self.preflight)
        self.cloud = cloud

    def _point_request(self, view, tile, control):
        if self.exchange_root is None:
            raise RuntimeError("Specialist worker exchange is not prepared")
        directory = Path(tempfile.mkdtemp(prefix="point-", dir=self.exchange_root))
        feed_manifest = {}
        for name, value in view.feed.items():
            path = directory / (name + ".npy")
            self._publish_exchange_array(path, value)
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
        with self._profile_phase('I_preprocessing', control):
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
            shutil.rmtree(output.parent)
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
        with self._profile_phase('semantic_components', control):
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


    def _infer_image(self, branch, image, identifier, control):
        if self.exchange_root is None:
            raise RuntimeError("Specialist worker exchange is not prepared")
        directory = Path(tempfile.mkdtemp(prefix="image-", dir=self.exchange_root))
        tensor_path, output = directory / "tensor.npy", directory / "outputs.npz"
        tensor = image_tensor(branch, image)
        self._publish_exchange_array(tensor_path, tensor)
        request = self._base_request(directory, "image")
        request.update(branch=branch, tensor=str(tensor_path.resolve()), output=str(output.resolve()))
        try:
            response = self._execute(request, directory, control)
            with np.load(output, allow_pickle=False) as archive:
                outputs = {name: archive[name].copy() for name in archive.files}
            return outputs, response
        finally:
            # Inputs and dense logits are transient, not evidence artifacts.
            shutil.rmtree(directory)

    def _try_image(self, branch, image, identifier, control):
        if branch in self.branch_failures:return None
        try:return self._infer_image(branch,image,identifier,control)
        except ProviderUnavailable as exc:
            self.branch_failures[branch]=str(exc)
            self.warnings.append(f'Specialist branch {branch} unavailable: {exc}')
            return None

    def _try_images(self, jobs, control):
        """Bounded independent image waves, returned in submitted view order."""
        if self.runtime_plan['image_workers'] == 1:
            return [self._try_image(branch, image, identifier, control) for branch, image, identifier in jobs]
        results = []
        width = self.runtime_plan['image_workers']
        for begin in range(0, len(jobs), width):
            wave = jobs[begin:begin+width]
            active = [(i, job) for i, job in enumerate(wave) if job[0] not in self.branch_failures]
            values = [None] * len(wave)
            if active:
                if self.exchange_root is None:
                    raise RuntimeError("Specialist worker exchange is not prepared")
                with tempfile.TemporaryDirectory(prefix='image-wave-', dir=self.exchange_root) as temporary:
                    directory = Path(temporary)
                    items = []
                    for index, (branch, image, identifier) in active:
                        tensor, output = directory/f'{index}-tensor.npy', directory/f'{index}-outputs.npz'
                        self._publish_exchange_array(tensor, image_tensor(branch, image))
                        items.append({'branch': branch, 'tensor': str(tensor.resolve()), 'output': str(output.resolve())})
                    request = self._base_request(directory, 'image_batch')
                    request['jobs'] = items
                    try:
                        response = self._execute(request, directory, control)
                    except ProviderUnavailable as exc:
                        response = {'results': [{'branch': item['branch'], 'status': 'unavailable', 'error': str(exc)} for item in items]}
                    replies = response.get('results')
                    if not isinstance(replies, list) or len(replies) != len(items):
                        raise ValueError('Specialist image wave returned the wrong population')
                    for (index, (branch, _, _)), item, reply in zip(active, items, replies):
                        if reply.get('branch') != branch:
                            raise ValueError('Specialist image wave changed branch identity')
                        if reply.get('status') == 'unavailable':
                            if branch not in self.branch_failures:
                                self.branch_failures[branch] = reply.get('error') or 'Specialist branch unavailable'
                                self.warnings.append(f'Specialist branch {branch} unavailable: {self.branch_failures[branch]}')
                            continue
                        if reply.get('status') != 'complete' or reply.get('output') != item['output']:
                            raise ValueError('Specialist image wave changed output identity/status')
                        with np.load(item['output'], allow_pickle=False) as archive:
                            outputs = {name: archive[name].copy() for name in archive.files}
                        values[index] = outputs, reply
            results.extend(values)
        return results

    @staticmethod
    def _publish_exchange_array(path, value):
        """Publish a complete NPY name before exposing it to another process."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".tensor-", suffix=".npy", dir=path.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with temporary.open("wb") as stream:
                np.save(stream, value, allow_pickle=False)
                stream.flush()
            os.replace(temporary, path)
            if not path.is_file() or path.stat().st_size <= 0:
                raise OSError("Specialist exchange array publication failed")
        finally:
            temporary.unlink(missing_ok=True)


    def _add_proposals(self, items):
        for item in items:
            rows = np.unique(np.asarray(item.pop("_source_rows", []), dtype=np.uint64))
            item["source_support"] = {"kind": "specialist_support_index", "key": item["id"]}
            self.proposal_support[item["id"]] = rows
            self.proposals.append(item)

    def _semantic_rescue(self, labels_path, control):
        """Build bounded per-core components for every supported physical class."""
        if "I" not in self.active_branches:
            return
        from .streaming_views import SourceBox, components
        from .contracts import TAXONOMY
        labels = np.load(labels_path, mmap_mode="r", allow_pickle=False)
        try:
            low, high = self._cloud_bounds(control)
            side = self.settings.plan_tile_m
            for li, level in enumerate(self._levels(low, high)):
                for x in range(math.floor(low[0]/side), math.floor(high[0]/side)+1):
                    for y in range(math.floor(low[1]/side), math.floor(high[1]/side)+1):
                        minimum, maximum = np.array([x, y])*side, (np.array([x, y])+1)*side
                        source = SourceBox(self.cloud, self.spatial_index,
                            [*minimum, level['bottom_m']], [*maximum, level['top_m']],
                            control, self.settings.maximum_view_points)
                        present = set()
                        for rows, _ in source.blocks():
                            present.update(labels[rows].tolist())
                        for name in ('wall', 'window', 'door', 'slab', 'ceiling', 'roof', 'stair', 'column', 'beam'):
                            label = TAXONOMY.index(name)
                            if label not in present:
                                continue
                            items = components(source, lambda rows, p, value=label: labels[rows] == value,
                                minimum, maximum, level, 'I', f'{li}-{x}-{y}-{name}', name)
                            self._add_proposals(items)
        finally:
            labels._mmap.close()

    def _stream_plan_tile(self, centre, level, tile_number, spatial_index, control):
        from .streaming_views import SourceBox, components, owned, plan_images, section_image
        settings = self.settings
        half = settings.stair_tile_m * np.sqrt(2) / 2
        source = SourceBox(self.cloud, spatial_index, [centre[0]-half, centre[1]-half, level['bottom_m']],
            [centre[0]+half, centre[1]+half, level['top_m']], control, settings.maximum_view_points)
        core_min = np.asarray(centre)-settings.plan_tile_m/2
        core_max = np.asarray(centre)+settings.plan_tile_m/2
        upper = min(level['top_m'], level['bottom_m']+settings.upper_slice_offset_m)
        if upper >= level['top_m']:
            upper = level['bottom_m']
        middle = (level['bottom_m']+level['top_m'])/2
        predictions, walls, rasters = {}, [], {}
        image_jobs, image_context, fields = [], [], []
        for branch in _branches_for_role(self.active_branches, 'DEFGH'):
            predictions[branch] = []
            zlow, zhigh = ((middle-settings.slice_thickness_m/2, middle+settings.slice_thickness_m/2)
                          if branch == 'H' else (upper, min(level['top_m'], upper+settings.slice_thickness_m)))
            for angle in (0., 30., 60.):
                for mirror in (False, True):
                    identifier = f'plan:{tile_number}:{branch}:{int(angle)}:{int(mirror)}'
                    frame = plan_frame(identifier, centre,
                        settings.stair_tile_m if branch == 'H' else settings.plan_tile_m,
                        settings.stair_native_pixels if branch == 'H' else settings.plan_native_pixels,
                        angle, mirror, zlow, zhigh, settings.plan_model_pixels)
                    raster_key=(angle,mirror,frame.side_m,frame.native_pixels,zlow,zhigh)
                    if raster_key not in rasters:
                        rasters[raster_key]=frame
                    fields.append((branch, frame, raster_key, identifier))
        rasters = dict(zip(rasters, plan_images(source, list(rasters.values()))))
        for branch, frame, raster_key, identifier in fields:
            image, raster = rasters[raster_key]
            if not raster['rasterized_points']: continue
            image_jobs.append((branch, image, identifier.replace(':','_')))
            image_context.append((branch, frame, raster))
        # Interleave branches for each TTA view. Consume in canonical branch/view
        # order so completion order cannot change votes, proposal IDs or support.
        order = sorted(range(len(image_jobs)), key=lambda i: (image_context[i][1].rotation_degrees,
            image_context[i][1].mirrored, image_context[i][0]))
        inferred_views = self._try_images([image_jobs[i] for i in order], control)
        inferred_views = dict(zip(order, inferred_views))
        refinement_jobs, refinement_frames = [], []
        for view_index, ((branch, image, identifier), (_, frame, raster)) in enumerate(zip(image_jobs, image_context)):
            inferred = inferred_views[view_index]
            if inferred is None: continue
            outputs, worker = inferred
            labels, _, _ = decode_masks(branch, outputs)
            predictions[branch].append((frame, labels))
            self.views.append({'branch': branch, 'frame': frame.to_dict(), 'raster': raster,
                'worker': self._worker_summary(worker), 'core_min_xy_m': core_min.tolist(),
                'native_label_counts':np.bincount(labels.ravel(),minlength=3 if branch in 'DE' else 2).tolist(),
                'core_max_xy_m': core_max.tolist(), 'ownership': 'half_open_core; full_physical_halo_context'})
            if branch == 'D' and 'J' in self.active_branches:
                base = cv2.resize(image, (settings.plan_model_pixels, settings.plan_model_pixels))
                palette = np.asarray([[0, 0, 0], [0, 0, 255], [0, 255, 0]], dtype=np.uint8)
                overlay = (.5*np.repeat(base[:, :, None], 3, axis=2)+.5*palette[labels]).astype(np.uint8)
                refinement_jobs.append(('J', overlay, identifier+'_J'))
                refinement_frames.append(frame)
        for frame, inferred in zip(refinement_frames, self._try_images(refinement_jobs, control)):
            if inferred is None: continue
            outputs, worker = inferred
            values = decode_obb(outputs, frame, settings.obb_score_threshold)
            walls.extend(values)
            self.views.append({'branch': 'J', 'frame': frame.to_dict(), 'candidates': len(values),
                'worker': self._worker_summary(worker), 'overlay_recipe': 'BGR alpha 0.5, no JPEG'})
        for branch, views in predictions.items():
            if not views:
                continue
            def selector(rows, points):
                votes = np.zeros(len(points), dtype=np.uint8)
                for frame, labels in views:
                    r, c, inside = plan_pixels(frame, points, pixels=settings.plan_model_pixels)
                    votes[inside] += labels[r[inside], c[inside]] > 0
                return votes >= settings.tta_minimum_votes
            self._add_proposals(components(source, selector, core_min, core_max, level, branch,
                str(tile_number), {'D':'wall', 'E':'opening', 'F':'beam', 'G':'column', 'H':'stair'}[branch]))
            histogram=np.zeros(7,dtype=np.int64);subclasses=np.zeros(3 if branch in 'DE' else 2,dtype=np.int64)
            population=selected_population=0
            for _,points in source.blocks():
                points=points[owned(points,core_min,core_max)]
                votes=np.zeros((len(points),len(subclasses)),dtype=np.uint8)
                for frame,labels in views:
                    r,c,inside=plan_pixels(frame,points,pixels=settings.plan_model_pixels)
                    np.add.at(votes,(np.flatnonzero(inside),labels[r[inside],c[inside]]),1)
                foreground=votes[:,1:].sum(axis=1)
                keep=foreground>=settings.tta_minimum_votes
                population+=len(points);selected_population+=int(keep.sum())
                histogram+=np.bincount(foreground,minlength=7)
                subclasses+=np.bincount(votes[keep,1:].argmax(axis=1)+1,minlength=len(subclasses))
            self.tta_diagnostics.append({'branch':branch,'tile':str(tile_number),'candidate_points':population,
                'selected_foreground_points':selected_population,'foreground_vote_histogram':histogram.tolist(),
                'selected_native_subclass_counts':subclasses.tolist()})
        # Query geometry is retained only when it owns original core support.
        from shapely.geometry import Polygon
        kept=[]
        for wall in sorted(walls,key=lambda w:(-w['native_score'],w['frame_id'],w['query_id'])):
            shape=Polygon(wall['corners_xy_m'])
            if not shape.is_valid or shape.area<=1e-6:continue
            if any(shape.intersection(other).area/max(1e-9,shape.union(other).area)>.65 for _,other in kept):continue
            kept.append((wall,shape))
        walls=[w for w,_ in kept]
        for wi, wall in enumerate(walls):
            from shapely.geometry import Polygon
            from shapely import contains_xy
            shape = Polygon(wall['corners_xy_m']).buffer(1e-9)
            bounds=shape.bounds
            wall_source=SourceBox(self.cloud,spatial_index,[bounds[0],bounds[1],level['bottom_m']],
                [bounds[2],bounds[3],level['top_m']],control,settings.maximum_view_points,shape)
            support, points_sample = [], []
            for rows, points in wall_source.blocks():
                keep = owned(points, core_min, core_max) & contains_xy(shape, points[:, 0], points[:, 1])
                if keep.any():
                    support.extend(rows[keep][:max(0,4096-len(support))].tolist())
                    points_sample.extend(points[keep][:max(0,4096-len(points_sample))].tolist())
            if support:
                self._wall_instances([wall], level, f'{tile_number}-{wi}', np.asarray(points_sample), np.asarray(support))
        jobs = [('A', np.array([1., 0.]), 'overview',source,centre)] if 'A' in self.active_branches else []
        # B/C still execute on orthogonal sections when J emits no wall query.
        for wall in walls[:max(1,(settings.maximum_section_views-len(jobs))//2)]:
            corners=np.asarray(wall['corners_xy_m']);edges=np.roll(corners,-1,axis=0)-corners
            axis=edges[np.linalg.norm(edges,axis=1).argmax()]
            shape=Polygon(corners).buffer(.20);bounds=shape.bounds
            section_source=SourceBox(self.cloud,spatial_index,[bounds[0],bounds[1],level['bottom_m']],
                [bounds[2],bounds[3],level['top_m']],control,settings.maximum_view_points,shape)
            # The section must lie on the detected wall, not on a parallel
            # plane through the tile centre. This origin also restores boxes.
            jobs.extend((b,axis,'wall',section_source,corners.mean(axis=0)) for b in _branches_for_role(self.active_branches,'BC'))
        if not walls:
            for axis in (np.array([1.,0.]),np.array([0.,1.])):
                jobs.extend((b,axis,'orthogonal_fallback',source,centre) for b in _branches_for_role(self.active_branches,'BC'))
        for sequence, (branch, axis, scope, section_source, section_origin) in enumerate(jobs[:settings.maximum_section_views]):
            identifier = f'section:{tile_number}:{branch}:{sequence}'
            frame, image = section_image(section_source, identifier, axis, section_origin, level['bottom_m'], .15 if branch=='B' else 0.)
            if frame is None:
                continue
            windows = slab_section_windows(frame, image) if branch=='A' else [(image, frame, {})]
            decoded = []
            for wi, (image, mapped, transform) in enumerate(windows):
                inferred=self._try_image(branch,image,identifier.replace(':','_')+f'_{wi}',control)
                if inferred is None:decoded=[];break
                outputs,worker=inferred
                decoded.extend(decode_section(branch, outputs, mapped, settings.section_score_threshold))
                self.views.append({'branch':branch, 'frame':mapped.to_dict(), 'source_frame':frame.to_dict(),
                    'input_transform':transform,'section_scope':scope,'worker':self._worker_summary(worker)})
            for item in self._section_nms(decoded,.3):
                world = item['world']; a,b = np.asarray(world['start']),np.asarray(world['end'])
                vector=b-a; length=np.linalg.norm(vector)
                if length<=1e-8 or world['z_max_m']-world['z_min_m']<=1e-6:
                    continue
                side=np.array([-vector[1],vector[0]])/length*max(.015,frame.pixel_m*1.5)
                support=[]
                for rows,points in section_source.blocks():
                    u=(points[:,:2]-a)@(vector/length)
                    keep=owned(points,core_min,core_max)&(u>=0)&(u<=length)&(points[:,2]>=world['z_min_m'])&(points[:,2]<=world['z_max_m'])
                    support.extend(rows[keep][:max(0,4096-len(support))].tolist())
                if not support:
                    continue
                item.update({'id':identifier+':'+content_digest(world)[:16], 'branch':branch,
                    'class':{'A':'slab','B':'opening','C':'beam'}[branch], 'status':'proposed',
                    'geometry_authority':'review_only','polygon_xy_m':[(a-side).tolist(),(b-side).tolist(),(b+side).tolist(),(a+side).tolist()],
                    'z_min_m':world['z_min_m'],'z_max_m':world['z_max_m'],
                    'display_scope':'thin section ribbon; width is visual only, not physical geometry',
                    '_source_rows':support})
                self._add_proposals([item])


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
                if (abs(previous['geometry']['base']-geometry['base'])>.08
                        or abs(previous['geometry']['height']-geometry['height'])>.08):continue
                previous_direction=np.asarray(previous['geometry']['end'])-previous['geometry']['start']
                if abs(previous_direction@(end-start))/(np.linalg.norm(previous_direction)*np.linalg.norm(end-start))<np.cos(np.deg2rad(3)):continue
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
        self.spatial_index = spatial_index
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
                    with self._profile_phase('image_views', control):
                        self._stream_plan_tile(centre, level, identifier, spatial_index, control)
                except ProviderUnavailable as exc:
                    reason = str(exc)
                    for branch in image_branches:
                        self.branch_failures.setdefault(branch, reason)
                    self.warnings.append(f"Specialist image tile {identifier} unavailable: {reason}")

    def write_artifacts(self, directory, control):
        from .streaming_views import stitch_proposals
        self.proposals, stitched_support = stitch_proposals(self.proposals, self.proposal_support, control.check)
        self.proposal_support.update(stitched_support)
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
        executed = {name:sum(v.get('branch')==name for v in self.views) for name in 'ABCDEFGHJ'}
        executed['I']=sum(v.get('status')=='complete' for v in self.point_diagnostics)
        for name in "ABCDEFGHIJ":
            if name not in self.missing_branches and not executed[name]:
                self.branch_failures.setdefault(name,'No eligible populated view executed; branch is not qualified by asset loading')
            status = "missing" if name in self.missing_branches else "failed" if name in self.branch_failures else "active"
            branches[name] = {"status": status, "task": self.manifest["branches"][name]["task"],
                              "graph_sha256": self.asset_status[name].get("graph_sha256"),
                              "companion_sha256": self.asset_status[name].get("companion_sha256"),
                              "failure": self.branch_failures.get(name), "executed_views":executed[name]}
        return {"specialist_v1": {"schema_version": 1, "provider_id": SPECIALIST_PROVIDER_ID,
                 "provider_version": SPECIALIST_PROVIDER_VERSION, "geometry_authority": "review_only",
                 "model_pack_manifest_sha256": self.manifest["manifest_sha256"],
                 "runtime": self.preflight["runtime"], "branches": branches,
                 "runtime_profile": deepcopy(self.runtime_profile),
                 "runtime_plan": deepcopy(self.runtime_plan),
                 "source_read_stats": deepcopy(getattr(control, 'source_read_stats', {})),
                 "runtime_profile_scope": "nested host wall phases; branch ONNX component wall sums may overlap in parallel waves; worker_process records non-overlapping process wall and all-thread CPU seconds",
                 "original_source_population": self.original_population,
                 "point_model_view_population": self.model_view_population,
                 "model_context_overlap_factor": sum(v.get('original_context_points',0) for v in self.point_diagnostics)/max(1,self.original_population),
                 "normal_neighbourhood_points":sum(v.get('normal_context_points',0) for v in self.point_diagnostics),
                 "normal_queries":sum(v.get('normal_queries',0) for v in self.point_diagnostics),
                 "point_tiles": self.point_diagnostics,
                 "tta_diagnostics": self.tta_diagnostics,
                 "tta_rule": "six views: 0/30/60 degrees and mirrored; foreground and native-class votes separate; minimum four",
                 "views_path": "specialist/views-v1.json",
                 "proposals_path": "specialist/specialist-proposals-v1.json",
                 "support_index_path": "specialist/support-index-v1.json",
                 "support_rows": support_descriptor,
                 "point_arrays": point_arrays, "artifacts": artifacts,
                 "accepted_geometry_changes": 0, "accepted_cuts": 0, "ifc_objects_written": 0}}

    def _stop_worker(self):
        process = self.process
        if process is None:
            return
        try:
            if process.poll() is None:
                if process.stdin:
                    try:
                        process.stdin.close()
                    except (OSError, ValueError):
                        pass
                try:
                    process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
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
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except (OSError, ValueError):
                        pass
            for reader in (self.stdout_reader, self.stderr_reader):
                if reader:
                    reader.join(timeout=1.)
            if self.control is not None:
                self.control.child_pid = None
            self.process = None
            self.control = None
            self.response_queue = None
            self.stdout_reader = self.stderr_reader = None

    def close(self):
        self._stop_worker()
        exchange, self.exchange = self.exchange, None
        self.exchange_root = None
        if exchange is not None:
            exchange.cleanup()
