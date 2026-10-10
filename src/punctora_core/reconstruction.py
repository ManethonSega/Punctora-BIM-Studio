"""Headless contour reconstruction adapted from the Cloud2BIM workflow.

Cloud2BIM's histogram/contour/parallel-face strategy is retained, with selected
MIT geometry helpers. Original orchestration, fitting and element model are
Punctora code. No plots, fabricated materials or cross-floor wall accumulation.
"""
from dataclasses import asdict, dataclass, replace
from concurrent.futures import ThreadPoolExecutor
from math import isfinite
import os
import time
import cv2
import numpy as np
from scipy.signal import find_peaks
from shapely.errors import GEOSException
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import polygonize, unary_union

from .cloud_io import CloudData
from .cloud2bim_geometry import (
    check_overlap_parallel_segments, distance_between_points,
    distance_points_to_line_np, merge_collinear_segments, segments_angle,
)
from .model import BuildingModel, Slab, Space, Storey, Wall
from .sampling import (DetectionSample, adaptive_point_limit, available_memory_bytes,
                       point_batches, resolved_cpu_workers, voxel_sample)
from .surfaces import region_growing
from .wall_editing import consolidate_walls, snap_wall_topology, wall_connectivity_report
from .compute import ComputeBackend
from .performance import ResourcePlan, StageProfiler
from threadpoolctl import threadpool_limits


@dataclass(frozen=True)
class ReconstructionSettings:
    grid_size_m: float = 0.02
    contour_tolerance_m: float = 0.04
    minimum_wall_length_m: float = 0.5
    minimum_wall_thickness_m: float = 0.08
    maximum_wall_thickness_m: float = 0.6
    assumed_wall_thickness_m: float = 0.2
    exterior_wall_thickness_m: float = 0.3
    assumed_slab_thickness_m: float = 0.2
    level_bin_size_m: float = 0.05
    level_density_fraction: float = 0.35
    minimum_storey_height_m: float = 2.0
    minimum_footprint_area_m2: float = 1.0
    minimum_space_area_m2: float = 1.0
    maximum_grid_cells: int = 20_000_000
    surface_method: str = "contour"
    detection_voxel_size_m: float = 0.02
    maximum_level_detection_points: int = 5_000_000
    maximum_detection_points: int = 5_000_000
    processing_chunk_points: int = 1_000_000
    maximum_working_memory_gb: float = 20.0
    cpu_workers: int = 0
    compute_backend: str = "auto"
    gpu_memory_mb: int = 256
    region_neighbours: int = 24
    region_neighbour_radius_m: float = 0.2
    region_normal_radius_m: float = 0.1
    region_minimum_points: int = 30
    region_normal_angle_deg: float = 15.0
    region_plane_tolerance_m: float = 0.025
    region_maximum_curvature: float = 0.04
    region_vertical_tolerance_deg: float = 3.0
    region_minimum_wall_height_fraction: float = 0.6
    region_adaptive: bool = False
    detect_openings_enabled: bool = True
    detect_stairs_enabled: bool = True
    opening_recess_depth_m: float = 0.03
    opening_minimum_edge_support: float = 0.65
    stair_headroom_m: float = 2.0
    stair_void_margin_m: float = 0.1
    consolidate_walls_enabled: bool = True
    wall_merge_angle_deg: float = 2.0
    wall_merge_lateral_tolerance_m: float = 0.08
    wall_merge_gap_m: float = 0.35
    wall_merge_thickness_tolerance_m: float = 0.08
    corner_snap_tolerance_m: float = 0.3
    t_junction_snap_tolerance_m: float = 0.2
    t_junction_minimum_angle_deg: float = 25.0
    topology_gap_tolerance_m: float = 0.05
    slab_surface_tolerance_m: float = 0.035
    slab_raster_cell_m: float = 0.08
    slab_close_gap_m: float = 0.16
    slab_minimum_component_area_m2: float = 0.25
    slab_minimum_hole_area_m2: float = 0.25
    slab_minimum_area_fraction: float = 0.20
    slab_minimum_thickness_m: float = 0.08
    slab_maximum_thickness_m: float = 0.60
    slab_minimum_face_overlap: float = 0.45
    slab_maximum_storey_spacing_m: float = 5.50

    def validate(self):
        for name, value in asdict(self).items():
            if name in {"surface_method", "region_adaptive", "detect_openings_enabled", "detect_stairs_enabled", "consolidate_walls_enabled", "cpu_workers", "compute_backend"}:
                continue
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.surface_method not in {"contour", "region_growing"}:
            raise ValueError("surface_method must be contour or region_growing")
        if self.compute_backend not in {"auto", "cpu", "cuda", "opencl"}:
            raise ValueError("compute_backend must be auto, cpu, cuda or opencl")
        if not isinstance(self.gpu_memory_mb, int) or isinstance(self.gpu_memory_mb, bool) or self.gpu_memory_mb < 32:
            raise ValueError("gpu_memory_mb must be an integer >=32")
        if not isinstance(self.region_adaptive, bool):
            raise ValueError("region_adaptive must be a boolean")
        if (not isinstance(self.detect_openings_enabled, bool) or not isinstance(self.detect_stairs_enabled, bool)
                or not isinstance(self.consolidate_walls_enabled, bool)):
            raise ValueError("Feature detection switches must be booleans")
        for name in ["maximum_level_detection_points", "maximum_detection_points", "processing_chunk_points", "region_neighbours", "region_minimum_points", "cpu_workers"]:
            if not isinstance(getattr(self, name), int) or isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be an integer")
        if self.maximum_level_detection_points < 30 or self.maximum_detection_points < 30 or not 6 <= self.region_neighbours <= 128:
            raise ValueError("Detection budget must be >=30 and region_neighbours between 6 and 128")
        if self.cpu_workers < -1:
            raise ValueError("cpu_workers must be -1 (all), 0 (automatic) or a positive integer")
        if self.region_minimum_points < 6 or self.region_minimum_points > self.maximum_detection_points:
            raise ValueError("region_minimum_points exceeds the detection budget or is below 6")
        if not 0 < self.region_minimum_wall_height_fraction <= 1:
            raise ValueError("region_minimum_wall_height_fraction must be <=1")
        if not 0 < self.region_normal_angle_deg < 90 or not 0 < self.region_vertical_tolerance_deg < 45:
            raise ValueError("Invalid region-growing angle tolerance")
        if self.region_maximum_curvature >= 1/3:
            raise ValueError("region_maximum_curvature must be below 1/3")
        if self.t_junction_minimum_angle_deg >= 90:
            raise ValueError("t_junction_minimum_angle_deg must be below 90")
        if not isinstance(self.maximum_grid_cells, int) or isinstance(self.maximum_grid_cells, bool):
            raise ValueError("maximum_grid_cells must be an integer")
        if self.level_density_fraction > 1:
            raise ValueError("level_density_fraction cannot exceed 1")
        if self.opening_minimum_edge_support > 1:
            raise ValueError("opening_minimum_edge_support cannot exceed 1")
        if self.slab_minimum_area_fraction > 1 or self.slab_minimum_face_overlap > 1:
            raise ValueError("Slab coverage fractions cannot exceed 1")
        if self.slab_minimum_thickness_m >= self.slab_maximum_thickness_m:
            raise ValueError("Slab thickness bounds are reversed")
        if self.minimum_wall_thickness_m >= self.maximum_wall_thickness_m:
            raise ValueError("Wall thickness bounds are reversed")
        for name in ["assumed_wall_thickness_m", "exterior_wall_thickness_m"]:
            if not self.minimum_wall_thickness_m <= getattr(self, name) <= self.maximum_wall_thickness_m:
                raise ValueError(f"{name} must lie within wall thickness bounds")


def detect_storeys(points: np.ndarray, settings: ReconstructionSettings) -> list[Storey]:
    """Density peaks propose horizontal levels; short gaps represent slab zones.

    This is a candidate detector, not confirmation that every peak is a slab.
    Convex floor envelopes can bridge holes and concave outlines and need review.
    """
    z = points[:, 2]
    lo, hi = float(z.min()), float(z.max())
    if hi - lo < settings.minimum_storey_height_m:
        raise ValueError("Insufficient vertical extent for a supported storey")
    count = int(np.ceil((hi - lo) / settings.level_bin_size_m)) + 1
    if count > settings.maximum_grid_cells:
        raise ValueError("Vertical extent exceeds the level histogram limit")
    indices = np.floor((z - lo) / settings.level_bin_size_m + 1e-9).astype(int)
    histogram = np.bincount(indices, minlength=count)
    selected = np.flatnonzero(histogram >= max(20, settings.level_density_fraction * histogram.max()))
    groups = np.split(selected, np.where(np.diff(selected) > 1)[0] + 1)

    def supported_levels(candidate_groups):
        levels = []
        for group in candidate_groups:
            if not len(group):
                continue
            mask = np.isin(indices, group)
            surface = points[mask]
            hull = MultiPoint(surface[:, :2]).convex_hull
            if isinstance(hull, Polygon) and hull.area >= settings.minimum_footprint_area_m2:
                levels.append((float(np.median(surface[:, 2])), hull))
        return levels

    levels = supported_levels(groups)
    if len(levels) < 2:
        # A dominant floor can make a relative global threshold hide less dense
        # ceilings or upper storeys. Search for locally prominent horizontal
        # peaks, then reject candidates without a building-scale XY footprint.
        smooth = np.convolve(histogram.astype(float), [.25, .5, .25], mode="same")
        maximum = float(smooth.max())
        minimum_height = max(8.0, maximum * .025)
        peaks, _ = find_peaks(smooth, height=minimum_height,
                              prominence=max(4.0, maximum * .015),
                              distance=max(2, int(round(.10 / settings.level_bin_size_m))))
        # scipy deliberately excludes array endpoints, but the scan's lowest
        # floor and highest ceiling commonly occupy exactly those bins.
        endpoints = [index for index in (0, len(smooth)-1)
                     if smooth[index] >= minimum_height
                     and (len(smooth) == 1 or smooth[index] >= smooth[1 if index == 0 else -2])]
        peaks = np.unique(np.concatenate([peaks, endpoints])).astype(int)
        peak_groups = [np.arange(max(0, peak-1), min(len(histogram), peak+2)) for peak in peaks]
        fallback = supported_levels(peak_groups)
        if fallback:
            largest = max(hull.area for _, hull in fallback)
            fallback = [(z, hull) for z, hull in fallback
                        if hull.area >= max(settings.minimum_footprint_area_m2, largest * .15)]
            fallback.sort(key=lambda item: item[0])
            levels = []
            for candidate in fallback:
                if levels and candidate[0]-levels[-1][0] < max(.10, 2*settings.level_bin_size_m):
                    if candidate[1].area > levels[-1][1].area:
                        levels[-1] = candidate
                else:
                    levels.append(candidate)
    storeys = []
    for (floor, hull), (ceiling, _) in zip(levels, levels[1:]):
        if ceiling - floor >= settings.minimum_storey_height_m:
            storeys.append(Storey(f"storey-{len(storeys)+1}", f"Storey {len(storeys)+1}", floor, ceiling,
                                  [tuple(map(float, p)) for p in list(hull.exterior.coords)[:-1]],
                                  {"elevation": "measured", "ceiling": "measured", "footprint": "inferred"}))
    if not storeys:
        raise ValueError("No floor/ceiling candidates found; provide explicit storey bounds")
    return storeys


def _hash_xy_cells(cells):
    """Deterministic spatial hash used to retain distributed level evidence."""
    x, y = cells[:, 0].astype(np.uint64), cells[:, 1].astype(np.uint64)
    value = x * np.uint64(0x9E3779B185EBCA87) ^ y * np.uint64(0xC2B2AE3D27D4EB4F)
    value ^= value >> np.uint64(30)
    value *= np.uint64(0xBF58476D1CE4E5B9)
    value ^= value >> np.uint64(27)
    value *= np.uint64(0x94D049BB133111EB)
    return value ^ (value >> np.uint64(31))


def streaming_level_sample(points, settings):
    """Use every source Z value, then retain spatial evidence only near peaks."""
    size = settings.level_bin_size_m
    counts, source_count = {}, 0
    workers = resolved_cpu_workers(settings.cpu_workers)
    starts = range(0, len(points), settings.processing_chunk_points)
    def histogram_chunk(begin):
        batch = points[begin:begin+settings.processing_chunk_points]
        bins, amount = np.unique(np.floor(batch[:, 2] / size + 1e-9).astype(np.int64), return_counts=True)
        return bins, amount, len(batch)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = executor.map(histogram_chunk, starts)
        for bins, amount, batch_count in results:
            source_count += batch_count
            for key, value in zip(bins, amount):
                counts[int(key)] = counts.get(int(key), 0) + int(value)
    if not counts:
        raise ValueError("The working cloud contains no points")
    first, last = min(counts), max(counts)
    if last-first+1 > settings.maximum_grid_cells:
        raise ValueError("Vertical extent exceeds the level histogram limit")
    histogram = np.zeros(last-first+1, dtype=np.int64)
    for key, value in counts.items():
        histogram[key-first] = value
    smooth = np.convolve(histogram.astype(float), [.2, .6, .2], mode="same")
    maximum = float(smooth.max())
    minimum_height = max(20.0, maximum * .002)
    peaks, _ = find_peaks(smooth, height=minimum_height,
                          prominence=max(10.0, maximum * .001),
                          distance=max(2, int(round(.10 / size))))
    endpoints = [index for index in (0, len(smooth)-1)
                 if smooth[index] >= minimum_height
                 and (len(smooth) == 1 or smooth[index] >= smooth[1 if index == 0 else -2])]
    peaks = np.unique(np.concatenate([peaks, endpoints])).astype(int)
    if len(peaks) < 2:
        order = np.argsort(smooth, kind="stable")[::-1]
        selected = list(peaks)
        distance = max(2, int(round(.10 / size)))
        for candidate in order:
            if smooth[candidate] < 20 or any(abs(int(candidate)-old) < distance for old in selected):
                continue
            selected.append(int(candidate))
            if len(selected) >= 32:
                break
        peaks = np.asarray(sorted(selected), dtype=int)
    if len(peaks) > 64:
        strongest = np.argsort(smooth[peaks], kind="stable")[-64:]
        peaks = np.sort(peaks[strongest])
    absolute_peaks = peaks + first
    total_limit = adaptive_point_limit(settings.maximum_level_detection_points,
                                       settings.maximum_working_memory_gb, bytes_per_point=96)
    # Keep the combined level evidence inside the requested budget.  The old
    # lower bound of 10,000 points per level could silently exceed the budget
    # on a scan with only one or two strong height peaks.
    per_level = max(1, total_limit // max(1, len(absolute_peaks)))
    retained_hashes = [np.empty(0, dtype=np.uint64) for _ in absolute_peaks]
    retained_points = [np.empty((0, 3), dtype=float) for _ in absolute_peaks]
    retained_indices = [np.empty(0, dtype=np.int64) for _ in absolute_peaks]
    footprint_cell = max(.04, 2 * settings.grid_size_m)
    for batch, cloud_indices in point_batches(points, settings.processing_chunk_points):
        zbin = np.floor(batch[:, 2] / size + 1e-9).astype(np.int64)
        positions = np.searchsorted(absolute_peaks, zbin)
        right = np.minimum(positions, len(absolute_peaks)-1)
        left = np.maximum(positions-1, 0)
        choose_right = np.abs(zbin-absolute_peaks[right]) < np.abs(zbin-absolute_peaks[left])
        nearest = np.where(choose_right, right, left)
        near = np.abs(zbin-absolute_peaks[nearest]) <= 1
        for level in np.unique(nearest[near]):
            mask = near & (nearest == level)
            candidate = batch[mask]
            ids = cloud_indices[mask]
            cells = np.floor(candidate[:, :2] / footprint_cell + 1e-9).astype(np.int64)
            hashes = _hash_xy_cells(cells)
            _, unique = np.unique(hashes, return_index=True)
            hashes, candidate, ids = hashes[unique], candidate[unique], ids[unique]
            hashes = np.concatenate([retained_hashes[level], hashes])
            candidate = np.concatenate([retained_points[level], candidate])
            ids = np.concatenate([retained_indices[level], ids])
            _, unique = np.unique(hashes, return_index=True)
            hashes, candidate, ids = hashes[unique], candidate[unique], ids[unique]
            if len(hashes) > per_level:
                keep = np.argpartition(hashes, per_level-1)[:per_level]
                hashes, candidate, ids = hashes[keep], candidate[keep], ids[keep]
            retained_hashes[level], retained_points[level], retained_indices[level] = hashes, candidate, ids
    available = [index for index, values in enumerate(retained_points) if len(values) >= 20]
    if len(available) < 2:
        raise ValueError("No spatially supported floor/ceiling candidates found; add or adjust explicit storey bounds")
    sample_points = np.concatenate([retained_points[index] for index in available])
    sample_indices = np.concatenate([retained_indices[index] for index in available])
    return DetectionSample(sample_points, sample_indices, footprint_cell, source_count), {
        "method": "full_cloud_streaming_histogram", "source_points_scanned": source_count,
        "histogram_bins": len(histogram),
        "candidate_level_bins": [int(absolute_peaks[index]) for index in available],
        "retained_spatial_points": len(sample_points),
        "working_memory_limit_gb": settings.maximum_working_memory_gb,
        "cpu_workers": workers,
    }


def _segments(points: np.ndarray, settings: ReconstructionSettings) -> list:
    pixel = settings.grid_size_m
    low, high = points[:, :2].min(axis=0), points[:, :2].max(axis=0)
    for _ in range(16):
        origin = low - 2 * pixel
        dimensions = np.ceil((high-origin)/pixel).astype(int)+3
        cells = int(dimensions[0])*int(dimensions[1])
        if cells <= settings.maximum_grid_cells:
            break
        pixel *= max(1.05, np.sqrt(cells/settings.maximum_grid_cells)*1.01)
        if pixel > max(.10, 8*settings.grid_size_m):
            raise ValueError("Scan extent exceeds the contour-grid limit; crop outliers or segment the cloud")
    else:
        raise ValueError("Scan extent cannot be represented within the contour-grid memory limit")
    cells = np.floor((points[:, :2] - origin) / pixel + 1e-9).astype(int)
    mask = np.zeros((int(dimensions[1]), int(dimensions[0])), dtype=np.uint8)
    mask[cells[:, 1], cells[:, 0]] = 255
    # Pad is retained by construction. No roll/wrap or unexplained pixel shift.
    # Connect sparse diagonal samples for candidate extraction. The dilated
    # contour is only a proposal; final faces are refitted to original points.
    mask = cv2.dilate(mask, np.ones((3, 3), dtype=np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    segments = []
    for contour in contours:
        approx = cv2.approxPolyDP(contour, settings.contour_tolerance_m / pixel, True)
        for i in range(len(approx)):
            start = approx[i-1, 0].astype(float) * pixel + origin + pixel / 2
            end = approx[i, 0].astype(float) * pixel + origin + pixel / 2
            if np.linalg.norm(end-start) >= settings.minimum_wall_length_m:
                segments.append([start.tolist(), end.tolist()])
    # Merge duplicate contour edges only within a small raster distance, rather
    # than the full allowed wall thickness, to keep two observed wall faces apart.
    return merge_collinear_segments(segments, 5 * pixel, 4 * pixel)


def _fit_face(segment, points, radius):
    start, end = np.asarray(segment, dtype=float)
    direction = (end-start) / np.linalg.norm(end-start)
    projected = (points[:, :2]-start) @ direction
    near = points[(distance_points_to_line_np(points[:, :2], start, end) <= radius)
                  & (projected >= -radius) & (projected <= np.linalg.norm(end-start)+radius)]
    if len(near) < 6:
        return None
    xy = near[:, :2]
    # Trim off perpendicular junction points before final fitting. This prevents
    # a few corner/partition points from biasing a clean observed wall plane.
    for _ in range(4):
        centre = xy.mean(axis=0)
        _, _, axes = np.linalg.svd(xy-centre, full_matrices=False)
        normal = np.array([-axes[0, 1], axes[0, 0]])
        residual = (xy-centre) @ normal
        offset = np.median(residual)
        mad = np.median(np.abs(residual-offset))
        trimmed = xy[np.abs(residual-offset) <= max(radius/4, 3*mad)]
        if len(trimmed) < 6 or len(trimmed) == len(xy):
            break
        xy = trimmed
    centre = xy.mean(axis=0)
    _, _, axes = np.linalg.svd(xy-centre, full_matrices=False)
    direction = axes[0]
    reference = end-start
    if np.dot(direction, reference) < 0:
        direction *= -1
    if abs(np.dot(direction, reference / np.linalg.norm(reference))) < 0.98:
        return None  # Junction/furniture mixed into this contour candidate.
    along = (xy-centre) @ direction
    normal = np.array([-direction[1], direction[0]])
    residual = (xy-centre) @ normal
    return [centre+along.min()*direction, centre+along.max()*direction], len(xy), float(np.sqrt(np.mean(residual**2)))


def _paired_axis(first, second):
    """Use signed offsets and common projected extent, not unsigned offset guessing."""
    a, b = np.asarray(first)
    c, d = np.asarray(second)
    direction = (b-a) / np.linalg.norm(b-a)
    normal = np.array([-direction[1], direction[0]])
    offset = float(((c+d)/2-a) @ normal)
    low = max(0.0, min(float((c-a)@direction), float((d-a)@direction)))
    high = min(float(np.linalg.norm(b-a)), max(float((c-a)@direction), float((d-a)@direction)))
    return [a+low*direction+offset/2*normal, a+high*direction+offset/2*normal], abs(offset)


def _coalesce_faces(faces, section, settings):
    """Unify overlapping refitted contours on the same observed plane.

    The upstream endpoint-nearness test misses a short segment lying inside a
    long one. Use signed transverse separation and projected interval overlap.
    """
    lines = [[np.asarray(face[0]), np.asarray(face[1])] for face, _, _ in faces]
    changed = True
    while changed:
        changed = False
        for i, (a, b) in enumerate(lines):
            direction = (b-a)/np.linalg.norm(b-a)
            normal = np.array([-direction[1], direction[0]])
            length = float(np.linalg.norm(b-a))
            for j in range(i+1, len(lines)):
                c, d = lines[j]
                if not segments_angle([a, b], [c, d]):
                    continue
                if max(abs((c-a)@normal), abs((d-a)@normal)) > settings.grid_size_m/2:
                    continue
                low, high = sorted([float((c-a)@direction), float((d-a)@direction)])
                if low > length+settings.maximum_wall_thickness_m or high < -settings.maximum_wall_thickness_m:
                    continue
                lines[i] = [a+min(0.0, low)*direction, a+max(length, high)*direction]
                lines.pop(j)
                changed = True
                break
            if changed:
                break
    result = []
    for line in lines:
        fit = _fit_face(line, section, 2*settings.grid_size_m)
        if fit is not None:
            result.append(fit)
    return result


def detect_walls(points, storey: Storey, settings: ReconstructionSettings, workers=1) -> list[Wall]:
    from .wall_slices import multi_slice_walls
    return multi_slice_walls(points, storey, settings, workers)


def _walls_from_faces(faces, storey, settings, z_bounds, pair_validator=None):
    height = storey.ceiling-storey.elevation
    faces.sort(key=lambda f: tuple(np.round(np.mean(f[0], axis=0), 6)))
    used, walls = set(), []
    footprint = Polygon(storey.footprint)
    centroid = np.array(footprint.centroid.coords[0])
    for i, (face, count, rmse) in enumerate(faces):
        if i in used:
            continue
        used.add(i)
        axis, thickness, provenance, label = face, None, "inferred", "unclassified"
        observed = [face]
        for j, (other, other_count, other_rmse) in enumerate(faces):
            if j in used or not segments_angle(face, other):
                continue
            if pair_validator is not None and not pair_validator(face,other):
                continue
            candidate, separation = _paired_axis(face, other)
            if (settings.minimum_wall_thickness_m <= separation <= settings.maximum_wall_thickness_m
                    and check_overlap_parallel_segments(face, other, settings.minimum_wall_length_m)):
                axis, thickness, provenance = candidate, separation, "measured"
                label, count, rmse = "paired_faces", count+other_count, max(rmse, other_rmse)
                used.add(j)
                observed.append(other)
                break
        if thickness is None:
            midpoint = np.mean(face, axis=0)
            direction = np.asarray(face[1])-face[0]
            direction /= np.linalg.norm(direction)
            normal = np.array([-direction[1], direction[0]])
            if footprint.boundary.distance(Point(midpoint)) <= 3*settings.grid_size_m:
                label, thickness = "exterior_candidate", settings.exterior_wall_thickness_m
                # Scanned interior face -> centreline displaced toward exterior.
                if np.dot(normal, centroid-midpoint) > 0:
                    normal *= -1
                axis = [np.asarray(p)+normal*thickness/2 for p in face]
            else:
                label, thickness = "single_face_candidate", settings.assumed_wall_thickness_m
        walls.append(Wall(f"{storey.id}-wall-{len(walls)+1}", storey.id,
                          tuple(map(float, axis[0])), tuple(map(float, axis[1])), storey.elevation,
                          height, float(thickness), label,
                          {"axis": "inferred" if provenance == "inferred" else "measured",
                           "thickness": provenance,
                           "height": "inferred" if storey.provenance.get("ceiling") == "measured" else "user_supplied",
                           "material": "unknown",
                           "load_bearing": "unknown"}, count, rmse,
                          observed_faces=[{"start": np.asarray(f[0]).tolist(), "end": np.asarray(f[1]).tolist(),
                                           "z_min": float(z_bounds[0]), "z_max": float(z_bounds[1])} for f in observed],
                          detection_method=settings.surface_method))
    return walls


def _snap_walls(walls, settings):
    from .wall_editing import observed_junction_support, evidence_endpoint_report
    topology = snap_wall_topology(
        walls, corner_tolerance_m=settings.corner_snap_tolerance_m,
        t_tolerance_m=settings.t_junction_snap_tolerance_m,
        t_minimum_angle_deg=settings.t_junction_minimum_angle_deg,
        support_validator=observed_junction_support)
    retained = []
    dropped = []
    for wall in walls:
        # A clustered junction must never reintroduce a zero-length GEOS edge.
        if (not np.isfinite(np.asarray([wall.start, wall.end], dtype=float)).all()
                or distance_between_points(wall.start, wall.end) < settings.minimum_wall_length_m):
            dropped.append(wall.id)
            continue
        retained.append(wall)
    walls[:] = retained
    topology["dropped_wall_ids"] = dropped
    topology["connectivity"] = evidence_endpoint_report(
        walls, topology, settings.topology_gap_tolerance_m)
    return topology


def _region_walls(cloud, storey, settings, backend=None):
    point_limit = adaptive_point_limit(settings.maximum_detection_points,
                                       settings.maximum_working_memory_gb, bytes_per_point=256)
    sample = voxel_sample(cloud.points, settings.detection_voxel_size_m,
                          point_limit, settings.processing_chunk_points,
                          (storey.elevation, storey.ceiling),
                          resolved_cpu_workers(settings.cpu_workers), backend)
    patches, statistics = region_growing(sample, settings)
    height = storey.ceiling-storey.elevation
    faces = []
    for patch in patches:
        if patch.orientation != "vertical" or patch.bounds[1][2]-patch.bounds[0][2] < height*settings.region_minimum_wall_height_fraction:
            continue
        points = cloud.points[np.asarray(patch.representative_cloud_indices, dtype=np.int64)]
        normal = np.asarray(patch.normal[:2])
        direction = np.array([-normal[1], normal[0]]) / np.linalg.norm(normal)
        centre = np.asarray(patch.centroid[:2])
        extent = (points[:, :2]-centre) @ direction
        segment = [centre+extent.min()*direction, centre+extent.max()*direction]
        fit = _fit_face(segment, points, settings.region_plane_tolerance_m)
        if fit and distance_between_points(*fit[0]) >= settings.minimum_wall_length_m:
            faces.append(fit)
    faces = _coalesce_faces(faces, sample.points, settings)
    # Exclude floor/ceiling strips from original wall-face fitting. Merely being
    # near a vertical plane does not make a horizontal surface wall evidence.
    walls = _walls_from_faces(faces, storey, settings,
                             (storey.elevation+settings.region_plane_tolerance_m,
                              storey.ceiling-settings.region_plane_tolerance_m))
    # Surface proposals remain separate from IFC elements and preserve sampled
    # working-cloud IDs for later provider comparisons and desktop inspection.
    return walls, [patch.to_dict() for patch in patches], statistics


def spaces_for_storey(storey: Storey, walls: list[Wall], minimum_area: float = 1.0,
                      warnings: list[str] | None = None) -> list[Space]:
    """Polygonise only this storey's axes, then remove observed/assumed wall bodies."""
    local = [wall for wall in walls if wall.storey_id == storey.id
             and np.isfinite(np.asarray([wall.start, wall.end], dtype=float)).all()
             and distance_between_points(wall.start, wall.end) > 1e-8]
    if not local:
        return []
    try:
        lines = [LineString([w.start, w.end]) for w in local]
        bodies = unary_union([line.buffer(w.thickness/2, cap_style="flat", join_style="mitre")
                              for line, w in zip(lines, local)])
        spaces = []
        for polygon in polygonize(unary_union(lines)):
            interior = polygon.difference(bodies).intersection(Polygon(storey.footprint))
            parts = list(interior.geoms) if interior.geom_type == "MultiPolygon" else [interior]
            for part in parts:
                if part.geom_type != "Polygon" or part.area < minimum_area or part.interiors:
                    continue  # Holes/complex topology require a later profile adapter.
                vertices = [tuple(map(float, p)) for p in list(part.exterior.coords)[:-1]]
                spaces.append(Space(f"{storey.id}-space-{len(spaces)+1}", storey.id, vertices,
                                    storey.elevation, storey.ceiling-storey.elevation,
                                    {"footprint": "inferred",
                                     "height": "measured" if storey.provenance.get("ceiling") == "measured" else "user_supplied",
                                     "function": "unknown"}))
        return spaces
    except GEOSException as exc:
        # Room topology is derived output. A pathological overlay must not
        # discard an hour of successfully detected physical elements.
        if warnings is not None:
            warnings.append(f"{storey.id}: room-space topology skipped after GEOS rejected a degenerate edge ({exc})")
        return []


def _reconstruct_storey(cloud, level, settings, backend, profiler):
    """Process one storey independently, returning only storey-owned objects."""
    from .evidence import attach_evidence, storey_source_cloud
    from .features import detect_openings, detect_stairs
    workers = resolved_cpu_workers(settings.cpu_workers)
    warnings = []
    with profiler.stage("wall_proposals", storey_id=level.id, point_budget=settings.maximum_detection_points) as record:
        if settings.surface_method == "region_growing":
            walls, patches, statistics = _region_walls(cloud, level, settings, backend)
            proposals = [{**p, "id": f"{level.id}-{p['id']}", "storey_id": level.id,
                          "provider": "region_growing"} for p in patches]
        else:
            height = level.ceiling-level.elevation
            sample = voxel_sample(cloud.points, settings.detection_voxel_size_m,
                                  settings.maximum_detection_points, settings.processing_chunk_points,
                                  (level.elevation+.04, level.ceiling-.04),
                                  workers, backend)
            walls = detect_walls(sample.points, level, settings, workers)
            proposals = []
            statistics = {"sample_points": len(sample.points), "source_point_count": sample.source_point_count,
                          "voxel_size_m": sample.voxel_size_m}
        record.update(statistics, sample_points=statistics.get("sample_points"),
                      detected_elements={"walls": len(walls)})
    with profiler.stage("wall_consolidation", storey_id=level.id) as record:
        if settings.consolidate_walls_enabled:
            walls, consolidation = consolidate_walls(
                walls, angle_deg=settings.wall_merge_angle_deg,
                lateral_m=settings.wall_merge_lateral_tolerance_m,
                gap_m=0.0 if settings.surface_method == "contour" else settings.wall_merge_gap_m,
                thickness_m=settings.wall_merge_thickness_tolerance_m)
        else:
            consolidation = {"input_walls": len(walls), "output_walls": len(walls), "groups": []}
        record["detected_elements"] = {"walls": len(walls)}
    with profiler.stage('storey_source_scope',storey_id=level.id,source_points=len(cloud.points)) as record:
        source_cloud=storey_source_cloud(cloud,level.elevation,level.ceiling,settings.processing_chunk_points,
                                        min(int(settings.maximum_working_memory_gb*1024**3/4),2*1024**3))
        record.update(sample_points=len(source_cloud.points),materialized=source_cloud is not cloud,
                      sampling='all source rows in storey, no reduction')
    with profiler.stage("original_wall_fitting", storey_id=level.id, source_points=len(cloud.points)) as record:
        attach_evidence(source_cloud, walls, settings.processing_chunk_points,
                        endpoint_margin=max(.08, 3*settings.grid_size_m),
                        radius=settings.region_plane_tolerance_m if settings.surface_method == "region_growing" else settings.grid_size_m/2,
                        workers=workers)
        topology = _snap_walls(walls, settings)
        counts = topology["connectivity"]["counts"]
        if topology["dropped_wall_ids"]:
            warnings.append(f"{level.id}: discarded {len(topology['dropped_wall_ids'])} wall candidate(s) collapsed by junction snapping")
        if counts.get("unresolved_gap", 0):
            warnings.append(f"{level.id}: {counts['unresolved_gap']} wall endpoint(s) retain a small unresolved topology gap; verify against the point cloud")
        if counts.get("rejected_correction", 0):
            warnings.append(f"{level.id}: {counts['rejected_correction']} endpoint correction(s) rejected because observed-face support is missing")
        if counts.get("open_or_missing", 0):
            warnings.append(f"{level.id}: {counts['open_or_missing']} wall endpoint(s) are open or may indicate missing geometry; verify against the point cloud")
        record.update(sample_points=len(cloud.points), sampling="full source wall selectors",
                      support_points=sum(w.evidence_count for w in walls),
                      detected_elements={"walls": len(walls)},
                      topology_counts=counts,
                      corner_clusters=len(topology["corner_clusters"]),
                      t_junctions=len(topology["t_junctions"]))
    with profiler.stage("space_topology", storey_id=level.id) as record:
        spaces = spaces_for_storey(level, walls, settings.minimum_space_area_m2, warnings)
        record.update(sample_points=len(walls), detected_elements={"spaces": len(spaces)},
                      warnings=list(warnings))
    with profiler.stage("openings", storey_id=level.id, source_points=len(cloud.points)) as record:
        openings = detect_openings(source_cloud, walls, settings, workers) if settings.detect_openings_enabled else []
        record.update(sample_points=len(cloud.points) if settings.detect_openings_enabled else 0,
                      sampling="full source wall selectors", detected_elements={"openings": len(openings)})
    with profiler.stage("stairs", storey_id=level.id) as record:
        stair_statistics = []
        landings = []
        stairs = detect_stairs(source_cloud, [level], settings, backend, stair_statistics,
                               landings) if settings.detect_stairs_enabled else []
        record.update(sample_points=sum(x["sample_points"] for x in stair_statistics),
                      sampling=stair_statistics,
                      detected_elements={"stairs": len(stairs), "landings": len(landings)})
    return walls, spaces, openings, stairs, landings, statistics, proposals, consolidation, topology, warnings


def reconstruct(cloud: CloudData, settings: ReconstructionSettings | None = None,
                storeys: list[Storey] | None = None, name: str = "Punctora reconstruction",
                progress=lambda *_: None, diagnostics=None) -> BuildingModel:
    """Run adaptive multicore reconstruction with optional bounded GPU arithmetic."""
    started = time.perf_counter()
    settings = settings or ReconstructionSettings()
    settings.validate()
    backend = ComputeBackend(settings.compute_backend, settings.gpu_memory_mb)
    profiler = StageProfiler(backend)
    try:
        with threadpool_limits(limits=1, user_api="blas"):
            initial_plan = ResourcePlan.create(settings, len(cloud.points))
            workers = initial_plan.workers
            level_sample = None
            level_statistics = None
            slab_zones, slab_surfaces, slab_report = None, None, None
            if storeys is None:
                with profiler.stage("level_detection", source_points=len(cloud.points)) as record:
                    level_sample, level_statistics = streaming_level_sample(cloud.points, settings)
                    if cloud.working_index is not None:
                        level_sample.cloud_indices = cloud.working_index[level_sample.cloud_indices]
                    from .slab_zones import detect_slab_zones
                    levels, slab_zones, slab_surfaces, slab_report = detect_slab_zones(level_sample, settings)
                    record.update(sample_points=len(level_sample.points),
                                  detected_elements={"storeys": len(levels)},
                                  method=level_statistics["method"])
            else:
                levels = storeys
            model = BuildingModel(name, list(levels))
            model.validate()
            sorted_levels = sorted(levels, key=lambda s: s.elevation)
            if any(a.ceiling > b.elevation + 1e-8 for a, b in zip(sorted_levels, sorted_levels[1:])):
                raise ValueError("Storey clear-height intervals overlap")
            plan = ResourcePlan.create(settings, len(cloud.points), len(sorted_levels))
            local_settings = replace(settings, cpu_workers=plan.workers_per_storey,
                                     maximum_detection_points=plan.point_limit,
                                     region_minimum_points=min(settings.region_minimum_points, plan.point_limit),
                                     processing_chunk_points=plan.chunk_points)
            progress(20, f"Compute: {backend.name}; {plan.workers} CPU workers")
            progress(35, f"Processing {len(sorted_levels)} storeys with {plan.concurrent_storeys} parallel workers")
            with ThreadPoolExecutor(max_workers=plan.concurrent_storeys) as executor:
                results = list(executor.map(lambda level: _reconstruct_storey(
                    cloud, level, local_settings, backend, profiler), sorted_levels))
            detection, proposals, consolidation, wall_topology, inter_storey_gaps = [], [], [], [], []
            for index, (level, result) in enumerate(zip(sorted_levels, results)):
                local_walls, spaces, openings, stairs, landings, statistics, local_proposals, report, topology, local_warnings = result
                proposals.extend(local_proposals)
                consolidation.append({"storey_id": level.id, **report})
                wall_topology.append({"storey_id": level.id, **topology})
                detection.append({"storey_id": level.id, **statistics,
                                  "configured_point_limit": settings.maximum_detection_points,
                                  "effective_point_limit": plan.point_limit})
                if statistics.get("voxel_size_m", settings.detection_voxel_size_m) > settings.detection_voxel_size_m:
                    model.warnings.append(f"{level.id}: detection voxels enlarged to {statistics['voxel_size_m']:.6g} m to respect the point budget; small features may be missed")
                for wall in local_walls:
                    if wall.evidence_count < 6:
                        model.warnings.append(f"{wall.id}: fewer than six supporting source records; geometric review required")
                model.walls.extend(local_walls)
                model.spaces.extend(spaces)
                model.openings.extend(openings)
                model.stairs.extend(stairs)
                model.landings.extend(landings)
                model.warnings.extend(local_warnings)
                if not local_walls:
                    model.warnings.append(f"{level.id}: no supported wall candidates detected")
                gap = level.elevation-sorted_levels[index-1].ceiling if index else None
                if index and 0 < gap <= settings.maximum_wall_thickness_m:
                    thickness, base, state = gap, sorted_levels[index-1].ceiling, "measured"
                else:
                    thickness, base, state = settings.assumed_slab_thickness_m, level.elevation-settings.assumed_slab_thickness_m, "inferred"
                    if index and gap > settings.maximum_wall_thickness_m:
                        zone = {"lower_storey_id": sorted_levels[index-1].id,
                                "upper_storey_id": level.id,
                                "from_m": sorted_levels[index-1].ceiling,
                                "to_m": level.elevation, "height_m": gap,
                                "status": "unresolved_vertical_zone"}
                        inter_storey_gaps.append(zone)
                        model.warnings.append(
                            f"{level.id}: unresolved {gap:.3g} m vertical zone above {sorted_levels[index-1].id}; "
                            "the upper floor slab keeps its assumed thickness instead of filling the gap")
                if slab_zones is None:
                    model.slabs.append(Slab(f"{level.id}-floor", level.id, level.footprint, base, thickness,
                                            "FLOOR", {"thickness": state, "footprint": "inferred", "material": "unknown"}))
            if not sorted_levels:
                raise ValueError("No storeys available for reconstruction")
            last = sorted_levels[-1]
            if level_sample is not None and level_sample.voxel_size_m > settings.detection_voxel_size_m:
                model.warnings.append(f"Level detection voxels enlarged to {level_sample.voxel_size_m:.6g} m; horizontal levels and footprints need review")
            if slab_zones is None:
                model.slabs.append(Slab("top-slab", last.id, last.footprint,
                                        last.ceiling, settings.assumed_slab_thickness_m, "NOTDEFINED",
                                        {"thickness": "inferred", "footprint": "inferred", "material": "unknown"}))
            else:
                from .slab_zones import slab_zone_geometry
                model.slabs, model.slab_openings = slab_zone_geometry(
                    slab_zones, slab_surfaces, sorted_levels, settings, model.walls)
            from .features import derive_stair_slab_openings
            if slab_zones is None:
                model.slab_openings, slab_opening_diagnostics = derive_stair_slab_openings(
                    model.stairs, model.slabs, model.landings,
                    margin_m=settings.stair_void_margin_m,
                    headroom_m=settings.stair_headroom_m)
            else:
                slab_opening_diagnostics = []
                model.warnings.append("Observed slab gaps are pending stair-system validation; no stair-derived enlargement was performed.")
            skipped_openings = sum(item["status"] != "candidate_created"
                                   for item in slab_opening_diagnostics)
            if skipped_openings and model.stairs:
                model.warnings.append(
                    f"{skipped_openings} stair flight(s) did not produce a slab-opening candidate because no reached slab or contained footprint was established")
            model.warnings.extend([
                "All detected elements are unreviewed candidates; synthetic checks do not establish survey accuracy.",
                "Single-face wall and boundary-slab thicknesses are assumptions; materials and structural status are unknown.",
                "Horizontal slab-zone sequences and occupancy polygons need review for occlusion and unsupported gaps.",
                "Openings combine supported wall gaps and recessed return planes; glazing, closed leaves and occlusion still require review.",
                "Stair systems contain measured straight-flight and landing candidates; curved flights, railings and support structure are not reconstructed.",
                "Candidate scores are geometric support indicators, not calibrated accuracy probabilities. No whole-cloud deviation report is implemented.",
            ])
            perf = profiler.report()
            model.metadata = {"engine": settings.surface_method, "settings": asdict(settings),
                              "source_points": len(cloud.points),
                              "coordinate_frame": cloud.metadata.get("coordinate_frame", "caller-supplied metres, Z up"),
                              "fit_rmse_scope": "original points selected near observed wall faces, not whole-cloud deviation",
                              "detection": detection, "surface_proposals": proposals,
                              "wall_consolidation": consolidation,
                              "wall_topology": wall_topology,
                              "inter_storey_gaps": inter_storey_gaps,
                              "slab_opening_detection": slab_opening_diagnostics,
                              "slab_zones": slab_report,
                              "level_detection": None if level_sample is None else {
                                  "sample_points": len(level_sample.points), "voxel_size_m": level_sample.voxel_size_m,
                                  **(level_statistics or {})},
                              "performance": {"total_seconds": time.perf_counter()-started,
                                              "cpu_workers": plan.workers,
                                              "logical_cpu_count": os.cpu_count(),
                                              "available_memory_gb_at_start": plan.available_at_start/1024**3,
                                              "working_memory_limit_gb": settings.maximum_working_memory_gb,
                                              "resource_plan": plan.report(),
                                              "compute_backend": backend.name,
                                              **perf},
                              "element_schema_version": 2}
            model.validate()
            return model
    finally:
        if diagnostics is not None:
            diagnostics(profiler.report())

