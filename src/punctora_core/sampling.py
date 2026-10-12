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
                reclaimable=0
                try:
                    with open('/sys/fs/cgroup/memory.stat',encoding='ascii') as statistics:
                        memory_stats=dict(line.split() for line in statistics)
                    reclaimable=int(memory_stats.get('inactive_file',0))
                except (OSError,ValueError):pass
                host_available = min(host_available, max(0, int(limit_text)-current+reclaimable))
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


def release_mapped_source_pages(cloud):
    """Evict clean mapped cache pages; preserve all files, arrays and source IDs."""
    import mmap
    mapped=False
    for name in ('points','colors','intensity','scan_index','source_record_index'):
        array=getattr(cloud,name,None)
        while array is not None:
            if isinstance(array,np.memmap):
                mapped=True
                if array.mode=='r' and hasattr(array._mmap,'madvise'):
                    array._mmap.madvise(mmap.MADV_DONTNEED)
                    try:
                        with open(array.filename,'rb') as stream:
                            os.posix_fadvise(stream.fileno(),0,0,os.POSIX_FADV_DONTNEED)
                    except (AttributeError,OSError):pass
                break
            array=getattr(array,'base',None)
    return mapped


def resolved_cpu_workers(configured=0):
    """Resolve 0 to all logical processors except one for the desktop UI."""
    processors=os.cpu_count() or 1
    try:
        with open('/sys/fs/cgroup/cpu.max',encoding='ascii') as stream:
            quota,period=stream.read().split()
        if quota!='max':processors=min(processors,max(1,int(quota)//int(period)))
    except (OSError,ValueError):pass
    if configured == -1:
        return max(1, processors)
    if configured == 0:
        return max(1, processors - 1)
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
                 chunk_points=100_000, z_bounds=None, workers=1, backend=None,
                 representatives_per_voxel=1):
    """Keep deterministic source records per voxel; enlarge rather than truncate.

    One representative keeps the first original row. Two keeps the first and
    last row, which is useful when callers need both faces of a thin feature.

    Each parallel wave holds at most maximum_points + workers*chunk_points
    candidate records. Results remain deterministic across worker counts.
    Sampling does not construct an N-point mask or copy a complete storey.
    The grid is anchored to the selected data minimum, independent of chunk size.
    """
    if (not np.isfinite(voxel_size_m) or voxel_size_m <= 0
            or not isinstance(maximum_points, int) or isinstance(maximum_points, bool) or maximum_points < 3
            or not isinstance(chunk_points, int) or isinstance(chunk_points, bool) or chunk_points <= 0
            or not isinstance(workers, int) or isinstance(workers, bool) or workers <= 0
            or representatives_per_voxel not in {1, 2}):
        raise ValueError("Invalid voxel sampling limits")
    dimensions = None
    def representatives(scaled):
        # An injective integer key avoids repeated lexicographic sorting of
        # three-column records. It preserves the exact same voxel groups/IDs.
        if dimensions is not None:
            keys=(scaled[:,0]*dimensions[1]+scaled[:,1])*dimensions[2]+scaled[:,2]
            _,first=np.unique(keys,return_index=True)
        else:
            keys=None
            _, first = np.unique(scaled, axis=0, return_index=True)
        if representatives_per_voxel == 1:
            return first
        _, reverse = (np.unique(keys[::-1],return_index=True) if keys is not None
                      else np.unique(scaled[::-1], axis=0, return_index=True))
        last = len(scaled)-1-reverse
        return np.unique(np.concatenate([first,last]))
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
        return (batch.min(axis=0),batch.max(axis=0),len(batch)) if len(batch) else (np.full(3,np.inf),np.full(3,-np.inf),0)
    origin, maximum, count = np.full(3, np.inf),np.full(3,-np.inf),0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for local_origin, local_maximum, amount in executor.map(extent, starts):
            origin = np.minimum(origin, local_origin)
            maximum = np.maximum(maximum,local_maximum)
            count += amount
    if not count:
        return DetectionSample(np.empty((0, 3)), np.empty(0, dtype=np.int64), voxel_size_m, 0, 1)
    size = voxel_size_m
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for attempt in range(64):
            candidate_dimensions=np.floor((maximum-origin)/size+1e-9).astype(np.int64)+1
            dimensions=(candidate_dimensions if np.prod(candidate_dimensions.astype(object))<=np.iinfo(np.int64).max else None)
            retained, overflow = np.empty(0, dtype=np.int64), False
            def local_voxels(begin):
                batch, indices = selected_chunk(begin)
                if not len(batch):
                    return np.empty(0, dtype=np.int64)
                scaled = (backend.voxel_indices(batch, origin, size) if backend is not None
                          else np.floor((batch-origin)/size+1e-9))
                if not np.isfinite(scaled).all() or scaled.max() > np.iinfo(np.int64).max / 2:
                    raise ValueError("Coordinate extent exceeds the voxel index limit")
                return indices[representatives(scaled.astype(np.int64))]
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
                retained = np.sort(candidates[representatives(scaled.astype(np.int64))])
                if len(retained) > maximum_points:
                    overflow = True
                    break
            if not overflow:
                return DetectionSample(points[retained], retained, size, count, 2+attempt)
            size *= 2
    raise ValueError("Unable to reduce detection cloud within its point budget")

