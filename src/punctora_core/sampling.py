"""Bounded voxel representatives, with indices into the unchanged working cloud."""
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import ctypes
import os
import numpy as np


@dataclass
class DetectionSample:
    points: np.ndarray
    cloud_indices: np.ndarray
    voxel_size_m: float
    source_point_count: int
    full_cloud_passes: int = 0


def available_memory_bytes():
    """Best-effort currently available physical memory, without psutil.

    On Linux containers, cap the host value by the cgroup limit so the 20 GiB
    policy cannot mistake host RAM for memory available to the worker.
    """
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total_physical", ctypes.c_ulonglong), ("available_physical", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                        ("available_extended_virtual", ctypes.c_ulonglong)]
        status = MemoryStatus(); status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.available_physical)
    host_available = None
    try:
        with open("/proc/meminfo", encoding="ascii") as file:
            for line in file:
                if line.startswith("MemAvailable:"):
                    host_available = int(line.split()[1]) * 1024
                    break
    except OSError:
        pass
    if host_available is not None:
        try:
            with open("/sys/fs/cgroup/memory.max", encoding="ascii") as limit_file:
                limit_text = limit_file.read().strip()
            with open("/sys/fs/cgroup/memory.current", encoding="ascii") as current_file:
                current = int(current_file.read().strip())
            if limit_text != "max":
                host_available = min(host_available, max(0, int(limit_text)-current))
        except (OSError, ValueError):
            pass
        return host_available
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return 4 * 1024**3


def adaptive_point_limit(requested, maximum_working_memory_gb=20.0, bytes_per_point=192):
    """Cap a requested working set by both user policy and available RAM."""
    automatic = int(available_memory_bytes() * .70)
    policy = automatic if maximum_working_memory_gb == 0 else int(maximum_working_memory_gb * 1024**3)
    usable = min(policy, automatic)
    return max(30, min(int(requested), usable // bytes_per_point))


def resolved_cpu_workers(configured=0):
    """Resolve 0 to all logical processors except one for the desktop UI."""
    if configured == -1:
        return max(1, os.cpu_count() or 1)
    if configured == 0:
        return max(1, (os.cpu_count() or 2) - 1)
    return configured


def point_batches(points, chunk_points=100_000, z_bounds=None):
    for begin in range(0, len(points), chunk_points):
        batch = points[begin:begin + chunk_points]
        indices = np.arange(begin, begin + len(batch), dtype=np.int64)
        if z_bounds is not None:
            selected = (batch[:, 2] >= z_bounds[0]) & (batch[:, 2] <= z_bounds[1])
            batch, indices = batch[selected], indices[selected]
        if len(batch):
            yield batch, indices


def voxel_sample(points, voxel_size_m=0.05, maximum_points=50_000,
                 chunk_points=100_000, z_bounds=None, workers=1, backend=None):
    """Keep the first record in each voxel; enlarge voxels instead of truncating.

    Each parallel wave holds at most maximum_points + workers*chunk_points
    candidate records. Results remain deterministic across worker counts.
    Sampling does not construct an N-point mask or copy a complete storey.
    The grid is anchored to the selected data minimum, independent of chunk size.
    """
    if (not np.isfinite(voxel_size_m) or voxel_size_m <= 0
            or not isinstance(maximum_points, int) or isinstance(maximum_points, bool) or maximum_points < 3
            or not isinstance(chunk_points, int) or isinstance(chunk_points, bool) or chunk_points <= 0
            or not isinstance(workers, int) or isinstance(workers, bool) or workers <= 0):
        raise ValueError("Invalid voxel sampling limits")
    starts = list(range(0, len(points), chunk_points))
    def selected_chunk(begin):
        batch = points[begin:begin+chunk_points]
        indices = np.arange(begin, begin+len(batch), dtype=np.int64)
        if z_bounds is not None:
            selected = (batch[:, 2] >= z_bounds[0]) & (batch[:, 2] <= z_bounds[1])
            batch, indices = batch[selected], indices[selected]
        return batch, indices
    def extent(begin):
        batch, _ = selected_chunk(begin)
        return (batch.min(axis=0), len(batch)) if len(batch) else (np.full(3, np.inf), 0)
    origin, count = np.full(3, np.inf), 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for local_origin, amount in executor.map(extent, starts):
            origin = np.minimum(origin, local_origin)
            count += amount
    if not count:
        return DetectionSample(np.empty((0, 3)), np.empty(0, dtype=np.int64), voxel_size_m, 0, 1)
    size = voxel_size_m
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for attempt in range(64):
            retained, overflow = np.empty(0, dtype=np.int64), False
            def local_voxels(begin):
                batch, indices = selected_chunk(begin)
                if not len(batch):
                    return np.empty(0, dtype=np.int64)
                scaled = (backend.voxel_indices(batch, origin, size) if backend is not None
                          else np.floor((batch-origin)/size+1e-9))
                if not np.isfinite(scaled).all() or scaled.max() > np.iinfo(np.int64).max / 2:
                    raise ValueError("Coordinate extent exceeds the voxel index limit")
                _, first = np.unique(scaled.astype(np.int64), axis=0, return_index=True)
                return indices[first]
            for wave in range(0, len(starts), workers):
                local = list(executor.map(local_voxels, starts[wave:wave+workers]))
                candidates = np.concatenate([retained, *local])
                if not len(candidates):
                    continue
                coordinates = points[candidates]
                scaled = (backend.voxel_indices(coordinates, origin, size) if backend is not None
                          else np.floor((coordinates-origin)/size+1e-9))
                if not np.isfinite(scaled).all() or scaled.max() > np.iinfo(np.int64).max / 2:
                    raise ValueError("Coordinate extent exceeds the voxel index limit")
                _, first = np.unique(scaled.astype(np.int64), axis=0, return_index=True)
                retained = np.sort(candidates[first])
                if len(retained) > maximum_points:
                    overflow = True
                    break
            if not overflow:
                return DetectionSample(points[retained], retained, size, count, 2+attempt)
            size *= 2
    raise ValueError("Unable to reduce detection cloud within its point budget")

