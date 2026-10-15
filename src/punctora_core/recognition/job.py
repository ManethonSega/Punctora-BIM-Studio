"""Internal recognition runner. Never updates a saved model or IFC."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
from pathlib import Path
import os
import threading
import time
import numpy as np

from ..annotation_io import validate_identity
from ..cropping import crop_mask
from ..performance import _process
from ..sampling import available_memory_bytes, total_memory_bytes, release_mapped_source_pages, resolved_cpu_workers
from ..storage import mapped_array
from .cache import ProposalCache, cache_key
from .contracts import ARRAY_TYPES, TAXONOMY, ProviderUnavailable, array_descriptor
from .provider import implementation_fingerprint, write_vote_shard
from .tiling import TileIndex, TileOverflow, TileSettings


class RecognitionControl:
    """Sample combined process RAM and retain diagnostics outside staging.

    This is admission control plus a sampled working-set limit, not an OS
    hard allocation guarantee. A child exceeding the cap is terminated by its
    provider. There is no automatic spatial decimation to satisfy the budget.
    """
    def __init__(self, memory_limit_bytes=0, chunk_points=65536, cancelled=lambda: False, diagnostics=None,
                 cpu_workers=0, memory_fraction=.80):
        if isinstance(chunk_points, bool) or not isinstance(chunk_points, int) or chunk_points < 1:
            raise ValueError("Recognition chunk size must be a positive integer")
        if isinstance(memory_limit_bytes, bool) or not isinstance(memory_limit_bytes, int) or memory_limit_bytes < 0:
            raise ValueError("Recognition RAM cap must be a nonnegative integer")
        if isinstance(cpu_workers, bool) or not isinstance(cpu_workers, int) or cpu_workers < -1:
            raise ValueError("Recognition CPU workers must be -1, zero or a positive integer")
        if (isinstance(memory_fraction, bool) or not isinstance(memory_fraction, (int, float))
                or not .70 <= memory_fraction <= .80):
            raise ValueError("Recognition RAM fraction must be between 0.70 and 0.80")
        self.memory_fraction = float(memory_fraction)
        self.cpu_workers = min(resolved_cpu_workers(cpu_workers), resolved_cpu_workers(-1))
        self.cancelled, self.diagnostics = cancelled, diagnostics
        self.started, self.last_emit = time.monotonic(), 0.
        self.status, self.stage, self.child_pid = "running", "admission", None
        self.source_read_stats = {'cells': 0, 'blocks': 0, 'candidate_points': 0, 'selected_points': 0, 'seconds': 0.}
        self.failure = None
        self.baseline_rss = _process().memory_info().rss
        self.total_memory = total_memory_bytes()
        self.available_at_start = available_memory_bytes()
        available_budget = int(self.available_at_start * self.memory_fraction)
        default_limit = min(self.baseline_rss + available_budget, int(self.total_memory * self.memory_fraction))
        self.memory_limit_bytes = min(default_limit, memory_limit_bytes) if memory_limit_bytes else default_limit
        self.working_budget = self.memory_limit_bytes - self.baseline_rss
        if self.working_budget < 16 * 1024**2:
            from ..sampling import release_completed_working_memory
            release_completed_working_memory()
            self.baseline_rss = _process().memory_info().rss
            self.available_at_start = available_memory_bytes()
            available_budget = int(self.available_at_start * self.memory_fraction)
            default_limit = min(self.baseline_rss + available_budget, int(self.total_memory * self.memory_fraction))
            self.memory_limit_bytes = min(default_limit, memory_limit_bytes) if memory_limit_bytes else default_limit
            self.working_budget = self.memory_limit_bytes - self.baseline_rss
        if self.working_budget < 16 * 1024**2:
            self.status = "failed"
            self.failure = ValueError(f"Insufficient available RAM for recognition at the {self.memory_fraction:.0%} ceiling")
            self.peak_rss = self.baseline_rss
            self.emit()
            raise self.failure
        self.chunk_points = min(chunk_points, 65536, max(1, self.working_budget // 4096))
        self.stage = "prepare"
        self.peak_rss, self.failure = self.baseline_rss, None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._monitor, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, kind, value, traceback):
        if value is not None:
            self.failure = value
        self.status = "cancelled" if kind and issubclass(kind, InterruptedError) else "failed" if kind else "complete"
        self.stop.set()
        self.thread.join(timeout=1.)
        self.emit()

    def _rss(self):
        total = _process().memory_info().rss
        if self.child_pid is not None:
            try:
                import psutil
                child = psutil.Process(self.child_pid)
                children = [child, *child.children(recursive=True)]
                for process in children:
                    proc = Path(f"/proc/{process.pid}/statm")
                    if proc.exists():
                        import os
                        total += int(proc.read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
                    else:
                        total += process.memory_info().rss
            except (OSError, ValueError, ImportError):
                pass
            except Exception as exc:
                # Process exit racing the poll is harmless; unexpected monitor
                # failures remain visible and never disable RAM checking.
                if exc.__class__.__name__ not in {"NoSuchProcess", "ZombieProcess"}:
                    self.failure = RuntimeError("Recognition child resource monitor failed: " + str(exc))
        return total

    def _monitor(self):
        while not self.stop.wait(.1):
            try:
                self.check()
            except (InterruptedError, MemoryError) as exc:
                self.failure = exc
            except Exception as exc:
                self.failure = exc

    def check(self):
        if self.failure is not None:
            raise self.failure
        if self.cancelled():
            raise InterruptedError("Recognition cancelled")
        rss = self._rss()
        self.peak_rss = max(self.peak_rss, rss)
        if rss > self.memory_limit_bytes:
            raise MemoryError(f"Recognition combined process RSS exceeded the declared {self.memory_fraction:.0%}-bounded cap")
        if time.monotonic() - self.last_emit >= 5.:
            self.emit()

    def emit(self):
        self.last_emit = time.monotonic()
        if self.diagnostics:
            self.diagnostics({"schema_version": 1, "status": self.status, "stage": self.stage,
                              "elapsed_seconds": self.last_emit - self.started,
                              "available_at_start_bytes": self.available_at_start,
                              "memory_limit_bytes": self.memory_limit_bytes, "fraction_limit": self.memory_fraction,
                              "total_physical_or_container_bytes": self.total_memory,
                              "working_budget_bytes": self.working_budget,
                              "baseline_process_rss_bytes": self.baseline_rss,
                              "peak_combined_process_rss_bytes": self.peak_rss,
                              "child_pid": self.child_pid,
                              "cpu_worker_budget": self.cpu_workers,
                              "source_read_stats": dict(self.source_read_stats),
                              "provider_timings": getattr(self, 'provider_timings', {}),
                              "active_provider_phase_seconds": (
                                  self.last_emit-self.provider_phase_started
                                  if getattr(self, 'provider_phase_started', None) is not None else None),
                              "error": str(self.failure) if self.failure is not None else None,
                              "scope": "sampled combined RSS, not an OS hard limit"})

    def reconstruction_diagnostics(self, report):
        self.check()


def _input_digests(cloud, directory, control):
    """Hash exact f64 values and integer identity, reject global duplicates.

    In-place disk-backed key sorting also catches duplicate IDs in different
    spatial tiles. IDs are never converted through float or renumbered.
    """
    count = len(cloud.points)
    fields = {"points": cloud.points, "scan_ids": cloud.scan_index,
              "record_ids": cloud.source_record_index, "working_rows": cloud.working_index}
    if fields["scan_ids"] is None or fields["record_ids"] is None:
        raise ValueError("Recognition requires original scan and record IDs, not preview row numbers")
    digesters = {name: hashlib.sha256() for name in fields}
    keys = mapped_array(directory / "identity-keys.npy", [("scan", "<u8"), ("record", "<u8"), ("working", "<u8")], (count,))
    try:
        for begin in range(0, count, control.chunk_points):
            control.check()
            end = min(count, begin + control.chunk_points)
            for name, values in fields.items():
                block = np.arange(begin, end, dtype="<u8") if values is None else values[begin:end]
                expected = "<f8" if name == "points" else "<u8"
                if name != "points" and (block.dtype.kind not in "iu" or np.any(block < 0)):
                    raise ValueError("Source identifiers must be nonnegative exact integers")
                packed = np.ascontiguousarray(block, dtype=expected)
                digesters[name].update(packed.tobytes())
                if name != "points":
                    keys[{"scan_ids": "scan", "record_ids": "record", "working_rows": "working"}[name]][begin:end] = packed
        keys.sort(order=["scan", "record"], kind="quicksort")
        for begin in range(1, count, control.chunk_points):
            control.check()
            a, b = keys[begin - 1:min(count - 1, begin + control.chunk_points - 1)], keys[begin:begin + control.chunk_points]
            if np.any((a["scan"] == b["scan"]) & (a["record"] == b["record"])):
                raise ValueError("Duplicate original scan/record identity in recognition source")
        keys.sort(order=["working"], kind="quicksort")
        for begin in range(1, count, control.chunk_points):
            control.check()
            if np.any(keys["working"][begin - 1:min(count - 1, begin + control.chunk_points - 1)] == keys["working"][begin:begin + control.chunk_points]):
                raise ValueError("Duplicate working-row identity in recognition source")
    finally:
        keys._mmap.close()
        (directory / "identity-keys.npy").unlink(missing_ok=True)
    return {name: digest.hexdigest() for name, digest in digesters.items()}


def _source_arrays(cloud, identity, directory, control):
    count, result, selected_count = len(cloud.points), {}, 0
    for name in ("scan_ids", "record_ids", "working_rows", "selected"):
        same=next((other for other in result if name!='selected' and other!='selected'
            and control.input_digests[name]==control.input_digests[other]),None)
        if same is not None:
            result[name]=deepcopy(result[same])
            continue  # Same canonical integer values, not copied or renumbered.
        original = {"working_rows": cloud.working_index, "scan_ids": cloud.scan_index,
                    "record_ids": cloud.source_record_index}.get(name)
        if (isinstance(original,np.memmap) and original.offset == 0
                and Path(original.filename).stat().st_size == original.nbytes
                and original.dtype.str in {'<u4','<u8','<i8'}):
            relative = name + '.source.bin'
            target = directory / relative
            try:
                os.link(original.filename, target)
            except OSError:
                pass  # Cross-device/non-NTFS storage uses the lossless NPY fallback.
            else:
                result[name] = {**array_descriptor(target,relative,original,control.cancelled),
                                'storage':'original_raw_hardlink'}
                continue
        relative = name + ".npy"
        value = mapped_array(directory / relative, ARRAY_TYPES[name], (count,))
        try:
            original = {"working_rows": cloud.working_index, "scan_ids": cloud.scan_index,
                        "record_ids": cloud.source_record_index}.get(name)
            for begin in range(0, count, control.chunk_points):
                control.check()
                end = min(count, begin + control.chunk_points)
                if name == "selected":
                    selected = crop_mask(cloud.points[begin:end], identity["crop"])
                    value[begin:end] = selected
                    selected_count += int(selected.sum())
                else:
                    value[begin:end] = np.arange(begin, end, dtype="<u8") if original is None else original[begin:end]
            value.flush()
            result[name] = array_descriptor(directory / relative, relative, value, control.cancelled)
        finally:
            value._mmap.close()
    if selected_count == 0:
        raise ValueError("Recognition crop contains no original points")
    return result, selected_count


def run_recognition(cloud, identity, provider, cache_directory, *, tile_settings=None,
                    fallback=None, memory_limit_bytes=0, chunk_points=65536,
                    cancelled=lambda: False, diagnostics=None, cpu_workers=0, memory_fraction=.80):
    """prepare -> infer_chunk -> combine_tiles -> validate -> atomic publish.

    Missing explicit model assets/device support can fall back to classical.
    Malformed output, cancellation and internal defects never silently fall
    back. Held-out annotations are not an argument to this function.
    """
    identity = deepcopy(identity)
    validate_identity(identity)
    settings = (tile_settings or TileSettings()).validate()
    release_mapped_source_pages(cloud)
    cache = ProposalCache(cache_directory)
    implementation = implementation_fingerprint()
    warnings = []
    with RecognitionControl(memory_limit_bytes, chunk_points, cancelled, diagnostics, cpu_workers, memory_fraction) as control:
        if min(settings.maximum_context_points, len(cloud.points)) * 2048 > control.working_budget // 2:
            raise ValueError("Tile context limit exceeds the recognition working budget; lower the explicit limit")
        with cache.stage() as stage:
            inputs = _input_digests(cloud, stage, control)
            control.input_digests = inputs
            provider.bind_source(cloud, control)
            requested = deepcopy(provider.descriptor())
            # A failed learned attempt publishes nothing. Its tiles and
            # partial labels are deleted before the classical fallback begins.
            for attempt in range(2):
                work = stage / ("attempt-" + str(attempt))
                work.mkdir()
                index = None
                try:
                    descriptor = deepcopy(provider.descriptor())
                    key = cache_key(identity, inputs, {"requested": requested, "used": descriptor,
                                                       "implementation_sha256": implementation}, asdict(settings))
                    cached = cache.get(key, control.cancelled)
                    if cached is not None:
                        control.stage = "cache_hit"
                        return *cached, True
                    control.stage = "prepare"
                    provider.prepare(cloud, identity, work, control)
                    index = TileIndex(cloud, settings, control.working_budget // 2, control.chunk_points, work, control.check)
                    control.stage = "prepare_instances"
                    provider.prepare_instances(cloud, identity, work, control, index.index)
                    shards, tiles = [], []
                    pending = list(index.tiles)
                    while pending:
                        cell = pending.pop(0)
                        control.stage = "infer_chunk"
                        try:
                            tile = index.get(cell, identity["crop"])
                        except TileOverflow as overflow:
                            if len(pending) + len(tiles) + len(overflow.children) > settings.maximum_tiles:
                                raise ProviderUnavailable(
                                    "Adaptive exact tiling exceeds the explicit tile limit; partition the crop")
                            pending[0:0] = overflow.children
                            continue
                        if tile is None:
                            continue
                        prediction = provider.infer_chunk(tile, work, control)
                        shards.append(write_vote_shard(tile, prediction, work))
                        tiles.append({"id": tile.id, "core_min_xy": tile.core_min_xy, "core_max_xy": tile.core_max_xy,
                                      "core_min_z": tile.core_min_z, "core_max_z": tile.core_max_z,
                                      "partition_depth": tile.partition_depth,
                                      "context_overlap_xyz": tile.context_overlap_xyz,
                                      "vote_overlap_xyz": tile.vote_overlap_xyz,
                                      "context_points": len(tile.points), "vote_points": int(tile.vote_mask.sum())})
                        del tile,prediction
                    control.stage = "combine_tiles"
                    labels = provider.combine_tiles(shards, len(cloud.points), stage, control)
                    arrays, selected_count = _source_arrays(cloud, identity, stage, control)
                    for name, relative in labels.items():
                        value = np.load(stage / relative, mmap_mode="r", allow_pickle=False)
                        try:
                            arrays[name] = array_descriptor(stage / relative, relative, value, control.cancelled)
                        finally:
                            value._mmap.close()
                    manifest = {"schema_version": 1, "status": "complete", "geometry_authority": "review_only",
                                "identity": identity, "cache_key": key, "input_digests": inputs,
                                "requested_provider": requested, "provider": descriptor,
                                "implementation_sha256": implementation,
                                "taxonomy_version": "punctora-building-v1", "taxonomy": list(TAXONOMY),
                                "source_point_count": len(cloud.points), "selected_point_count": selected_count,
                                "arrays": arrays, "settings": asdict(settings), "tiles": tiles,
                                "overlap_rule": "majority_count_then_lowest_taxonomy_id; score=max_native_winner_score",
                                "instances": deepcopy(list(provider.instances)),
                                "warnings": [*warnings, *provider.warnings],
                                "qualification": "Internal conformance only until the applicable real-scan and designated-computer responsibility checkpoint passes."}
                    extensions = provider.write_artifacts(stage, control)
                    if extensions:
                        manifest["extensions"] = extensions
                    index.close()
                    index = None
                    provider.close()
                    # No transient inputs/votes/runtime files enter the cache.
                    import shutil
                    shutil.rmtree(work)
                    control.stage = "validate_and_publish"
                    directory, manifest = cache.publish(stage, manifest, control.cancelled)
                    return directory, manifest, False
                except ProviderUnavailable as exc:
                    if fallback is None or attempt > 0:
                        raise
                    warnings.append(f"Requested {requested['id']} unavailable: {exc}; explicit classical CPU fallback used")
                    replacement = fallback
                finally:
                    if index is not None:
                        index.close()
                    provider.close()
                    if work.exists():
                        import shutil
                        shutil.rmtree(work)
                provider = replacement
                provider.bind_source(cloud, control)
    raise RuntimeError("Recognition provider did not publish a complete generation")
