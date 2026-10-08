"""Punctora CPU surface proposals, independently authored under Apache-2.0.

Research reference: Florent Poux and Alex Key (2026), LLM-Supervised Point
Cloud Processing, DOI 10.5194/isprs-archives-XLIX-B2-2026-1311-2026.
Normal-based growth and spatial patches inform this experiment. This is not
their implementation, benchmark reproduction, semantic model or LLM agent.
"""
from dataclasses import asdict, dataclass
from collections import deque
import numpy as np
from scipy.spatial import cKDTree
from .sampling import DetectionSample


@dataclass
class SurfacePatch:
    id: str
    normal: list[float]
    centroid: list[float]
    bounds: list[list[float]]
    sample_count: int
    fit_rmse_m: float
    orientation: str
    representative_cloud_indices: list[int]

    def to_dict(self):
        return asdict(self)


def region_growing(sample: DetectionSample, settings):
    """Grow spatial neighbours agreeing with normals AND a fitted patch plane.

    Plane-distance tests prevent normal-only chaining between parallel faces.
    KD-tree and adjacency arrays are capped by the detection point budget.
    Normals are sign invariant. No colour, GPU, learned weights or uploads.
    """
    points = sample.points
    n = len(points)
    if n < settings.region_minimum_points:
        return [], {"sample_points": n, "patches": 0, "unassigned_points": n}
    tree = cKDTree(points)
    k = min(settings.region_neighbours, n)
    radius = max(settings.region_neighbour_radius_m, 2.5 * sample.voxel_size_m)
    normal_radius = max(settings.region_normal_radius_m, 1.45 * sample.voxel_size_m)
    neighbours = np.full((n, k), n, dtype=np.int32)
    normals = np.zeros((n, 3))
    curvature = np.ones(n)
    # Batched covariance calculation avoids an N x k x 3 temporary.
    for start in range(0, n, 2048):
        part = points[start:start + 2048]
        _, growth_ids = tree.query(part, k=k, distance_upper_bound=radius, workers=1)
        neighbours[start:start + len(part)] = growth_ids
        distances, ids = tree.query(part, k=k, distance_upper_bound=normal_radius, workers=1)
        valid = np.isfinite(distances)
        local = points[np.minimum(ids, n - 1)] - part[:, None, :]
        counts = valid.sum(axis=1)
        mean = (local * valid[:, :, None]).sum(axis=1) / np.maximum(counts[:, None], 1)
        centred = (local - mean[:, None, :]) * valid[:, :, None]
        covariance = np.einsum("nki,nkj->nij", centred, centred) / np.maximum(counts[:, None, None], 1)
        values, axes = np.linalg.eigh(covariance)
        usable = (counts >= 6) & (values[:, 1] > 1e-12)
        normals[start:start + len(part)][usable] = axes[usable, :, 0]
        curvature[start:start + len(part)][usable] = values[usable, 0] / np.maximum(values[usable].sum(axis=1), 1e-12)
        # Sparse neighbourhoods need a wider search, but simply enlarging PCA
        # mixes opposite faces of thin partitions. Deterministic local plane
        # hypotheses select coherent inliers before covariance fitting instead.
        needs_fallback = ~usable | (curvature[start:start + len(part)] > settings.region_maximum_curvature)
        if needs_fallback.any():
            rows = np.flatnonzero(needs_fallback)
            wide_ids = growth_ids[rows]
            wide_valid = wide_ids < n
            wide = points[np.minimum(wide_ids, n-1)]-part[rows, None, :]
            best_count = np.zeros(len(rows), dtype=int)
            best_mask = np.zeros(wide_ids.shape, dtype=bool)
            pairs = [(1, 5), (2, 7), (3, 11), (4, 13), (5, 17), (7, 19), (9, 21), (11, 23)]
            for first, second in pairs:
                if second >= k:
                    continue
                candidate = np.cross(wide[:, first], wide[:, second])
                lengths = np.linalg.norm(candidate, axis=1)
                candidate /= np.maximum(lengths[:, None], 1e-15)
                residual = np.abs(np.einsum("nki,ni->nk", wide, candidate))
                inliers = wide_valid & (residual <= settings.region_plane_tolerance_m/2)
                inliers &= (lengths > 1e-10)[:, None]
                amounts = inliers.sum(axis=1)
                improve = amounts > best_count
                best_count[improve], best_mask[improve] = amounts[improve], inliers[improve]
            means = (wide*best_mask[:, :, None]).sum(axis=1)/np.maximum(best_count[:, None], 1)
            offsets = (wide-means[:, None, :])*best_mask[:, :, None]
            covariance = np.einsum("nki,nkj->nij", offsets, offsets)/np.maximum(best_count[:, None, None], 1)
            eigenvalues, eigenvectors = np.linalg.eigh(covariance)
            accepted = (best_count >= 6) & (eigenvalues[:, 1] > 1e-12)
            target = start+rows[accepted]
            normals[target] = eigenvectors[accepted, :, 0]
            curvature[target] = eigenvalues[accepted, 0]/np.maximum(eigenvalues[accepted].sum(axis=1), 1e-12)
    usable = curvature <= settings.region_maximum_curvature
    angle = settings.region_normal_angle_deg
    if settings.region_adaptive:
        ids = neighbours[:, 1]
        valid = (ids < n) & usable
        valid &= usable[np.minimum(ids, n - 1)]
        dot = np.abs(np.einsum("ij,ij->i", normals[valid], normals[ids[valid]]))
        if len(dot):
            # Bounded heuristic, evaluated separately from fixed parameters.
            deviation = np.degrees(np.arccos(np.clip(dot, 0, 1)))
            angle = float(np.clip(3 * np.percentile(deviation, 75), 5, angle))
    cosine = np.cos(np.radians(angle))
    visited = np.zeros(n, dtype=bool)
    regions = []
    for seed in np.argsort(curvature, kind="stable"):
        if visited[seed] or not usable[seed]:
            continue
        visited[seed] = True
        queue, region = deque([int(seed)]), []
        seed_normal = normals[seed]
        plane_centre, plane_normal = points[seed], seed_normal
        sums, products = np.zeros(3), np.zeros((3, 3))
        while queue:
            current = queue.popleft()
            region.append(current)
            offset = points[current]-points[seed]
            sums += offset
            products += np.outer(offset, offset)
            # Refit a growing patch, retaining a single plane-distance gate.
            # This avoids extrapolating a noisy small-neighbourhood normal over
            # an entire wall, without allowing unrestricted normal-only chaining.
            if len(region) >= 12 and (len(region) == 12 or len(region)%64 == 0):
                mean = sums/len(region)
                _, axes = np.linalg.eigh(products/len(region)-np.outer(mean, mean))
                plane_normal, plane_centre = axes[:, 0], points[seed]+mean
            ids = neighbours[current]
            ids = ids[ids < n]
            ids = ids[~visited[ids] & usable[ids]]
            if not len(ids):
                continue
            aligned = np.abs(normals[ids] @ plane_normal) >= cosine
            on_plane = np.abs((points[ids] - plane_centre) @ plane_normal) <= settings.region_plane_tolerance_m
            accepted = ids[aligned & on_plane]
            visited[accepted] = True
            queue.extend(map(int, accepted))
        if len(region) >= settings.region_minimum_points:
            regions.append(np.asarray(region, dtype=np.int64))
    patches = []
    for ids in regions:
        local = points[ids]
        centre = local.mean(axis=0)
        _, _, axes = np.linalg.svd(local - centre, full_matrices=False)
        normal = axes[-1]
        if normal[np.argmax(np.abs(normal))] < 0:
            normal *= -1
        residual = (local - centre) @ normal
        vertical = abs(normal[2]) <= np.sin(np.radians(settings.region_vertical_tolerance_deg))
        horizontal = abs(normal[2]) >= np.cos(np.radians(settings.region_vertical_tolerance_deg))
        patches.append(SurfacePatch(
            f"patch-{len(patches)+1}", normal.tolist(), centre.tolist(),
            [local.min(axis=0).tolist(), local.max(axis=0).tolist()], len(ids),
            float(np.sqrt(np.mean(residual ** 2))),
            "vertical" if vertical else "horizontal" if horizontal else "inclined",
            sample.cloud_indices[ids].tolist()))
    return patches, {"sample_points": n, "voxel_size_m": sample.voxel_size_m,
                     "source_point_count": sample.source_point_count,
                     "neighbour_radius_m": radius, "normal_radius_m": normal_radius, "normal_angle_deg": angle,
                     "adaptive": settings.region_adaptive, "patches": len(patches),
                     "unassigned_points": n - sum(p.sample_count for p in patches)}
