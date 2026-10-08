"""Bounded voxel representatives, with indices into the unchanged working cloud."""
from dataclasses import dataclass
import numpy as np


@dataclass
class DetectionSample:
    points: np.ndarray
    cloud_indices: np.ndarray
    voxel_size_m: float
    source_point_count: int


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
                 chunk_points=100_000, z_bounds=None):
    """Keep the first record in each voxel; enlarge voxels instead of truncating.

    Each pass holds at most maximum_points + chunk_points candidate records.
    Sampling does not construct an N-point mask or copy a complete storey.
    The grid is anchored to the selected data minimum, independent of chunk size.
    """
    if (not np.isfinite(voxel_size_m) or voxel_size_m <= 0
            or not isinstance(maximum_points, int) or isinstance(maximum_points, bool) or maximum_points < 3
            or not isinstance(chunk_points, int) or isinstance(chunk_points, bool) or chunk_points <= 0):
        raise ValueError("Invalid voxel sampling limits")
    origin, count = np.full(3, np.inf), 0
    for batch, _ in point_batches(points, chunk_points, z_bounds):
        origin = np.minimum(origin, batch.min(axis=0))
        count += len(batch)
    if not count:
        return DetectionSample(np.empty((0, 3)), np.empty(0, dtype=np.int64), voxel_size_m, 0)
    size = voxel_size_m
    for _ in range(64):
        retained = np.empty(0, dtype=np.int64)
        overflow = False
        for batch, indices in point_batches(points, chunk_points, z_bounds):
            candidates = np.concatenate([retained, indices])
            coordinates = np.concatenate([points[retained], batch])
            scaled = np.floor((coordinates - origin) / size + 1e-9)
            if not np.isfinite(scaled).all() or scaled.max() > np.iinfo(np.int64).max / 2:
                raise ValueError("Coordinate extent exceeds the voxel index limit")
            _, first = np.unique(scaled.astype(np.int64), axis=0, return_index=True)
            retained = np.sort(candidates[first])
            if len(retained) > maximum_points:
                overflow = True
                break
        if not overflow:
            return DetectionSample(points[retained], retained, size, count)
        size *= 2
    raise ValueError("Unable to reduce detection cloud within its point budget")
