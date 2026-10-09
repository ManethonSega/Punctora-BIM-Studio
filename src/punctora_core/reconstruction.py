"""Headless contour reconstruction adapted from the Cloud2BIM workflow.

Cloud2BIM's histogram/contour/parallel-face strategy is retained, with selected
MIT geometry helpers. Original orchestration, fitting and element model are
Punctora code. No plots, fabricated materials or cross-floor wall accumulation.
"""
from dataclasses import asdict, dataclass
from math import isfinite
import cv2
import numpy as np
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import polygonize, unary_union

from .cloud_io import CloudData
from .cloud2bim_geometry import (
    adjust_intersections, check_overlap_parallel_segments, distance_between_points,
    distance_points_to_line_np, merge_collinear_segments, segments_angle,
)
from .model import BuildingModel, Slab, Space, Storey, Wall
from .sampling import voxel_sample
from .surfaces import region_growing
from .wall_editing import consolidate_walls


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
    maximum_detection_points: int = 50_000
    processing_chunk_points: int = 100_000
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
    consolidate_walls_enabled: bool = True
    wall_merge_angle_deg: float = 2.0
    wall_merge_lateral_tolerance_m: float = 0.08
    wall_merge_gap_m: float = 0.35
    wall_merge_thickness_tolerance_m: float = 0.08

    def validate(self):
        for name, value in asdict(self).items():
            if name in {"surface_method", "region_adaptive", "detect_openings_enabled", "detect_stairs_enabled", "consolidate_walls_enabled"}:
                continue
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.surface_method not in {"contour", "region_growing"}:
            raise ValueError("surface_method must be contour or region_growing")
        if not isinstance(self.region_adaptive, bool):
            raise ValueError("region_adaptive must be a boolean")
        if (not isinstance(self.detect_openings_enabled, bool) or not isinstance(self.detect_stairs_enabled, bool)
                or not isinstance(self.consolidate_walls_enabled, bool)):
            raise ValueError("Feature detection switches must be booleans")
        for name in ["maximum_detection_points", "processing_chunk_points", "region_neighbours", "region_minimum_points"]:
            if not isinstance(getattr(self, name), int) or isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be an integer")
        if self.maximum_detection_points < 30 or not 6 <= self.region_neighbours <= 128:
            raise ValueError("Detection budget must be >=30 and region_neighbours between 6 and 128")
        if self.region_minimum_points < 6 or self.region_minimum_points > self.maximum_detection_points:
            raise ValueError("region_minimum_points exceeds the detection budget or is below 6")
        if not 0 < self.region_minimum_wall_height_fraction <= 1:
            raise ValueError("region_minimum_wall_height_fraction must be <=1")
        if not 0 < self.region_normal_angle_deg < 90 or not 0 < self.region_vertical_tolerance_deg < 45:
            raise ValueError("Invalid region-growing angle tolerance")
        if self.region_maximum_curvature >= 1/3:
            raise ValueError("region_maximum_curvature must be below 1/3")
        if not isinstance(self.maximum_grid_cells, int) or isinstance(self.maximum_grid_cells, bool):
            raise ValueError("maximum_grid_cells must be an integer")
        if self.level_density_fraction > 1:
            raise ValueError("level_density_fraction cannot exceed 1")
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
    levels = []
    for group in groups:
        if not len(group):
            continue
        mask = np.isin(indices, group)
        surface = points[mask]
        hull = MultiPoint(surface[:, :2]).convex_hull
        if isinstance(hull, Polygon) and hull.area >= settings.minimum_footprint_area_m2:
            levels.append((float(np.median(surface[:, 2])), hull))
    storeys = []
    for (floor, hull), (ceiling, _) in zip(levels, levels[1:]):
        if ceiling - floor >= settings.minimum_storey_height_m:
            storeys.append(Storey(f"storey-{len(storeys)+1}", f"Storey {len(storeys)+1}", floor, ceiling,
                                  [tuple(map(float, p)) for p in list(hull.exterior.coords)[:-1]],
                                  {"elevation": "measured", "ceiling": "measured", "footprint": "inferred"}))
    if not storeys:
        raise ValueError("No floor/ceiling candidates found; provide explicit storey bounds")
    return storeys


def _segments(points: np.ndarray, settings: ReconstructionSettings) -> list:
    pixel = settings.grid_size_m
    origin = points[:, :2].min(axis=0) - 2 * pixel
    dimensions = np.ceil((points[:, :2].max(axis=0) - origin) / pixel).astype(int) + 3
    if int(dimensions[0]) * int(dimensions[1]) > settings.maximum_grid_cells:
        raise ValueError("Scan extent exceeds the contour-grid limit; segment the cloud or enlarge the grid")
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


def detect_walls(points, storey: Storey, settings: ReconstructionSettings) -> list[Wall]:
    height = storey.ceiling-storey.elevation
    # A section within the clear height, not a band extending beyond the ceiling.
    mask = (points[:, 2] >= storey.elevation+0.7*height) & (points[:, 2] <= storey.elevation+0.9*height)
    section = points[mask]
    if len(section) < 6:
        return []
    faces = []
    for segment in _segments(section, settings):
        fit = _fit_face(segment, section, 2 * settings.grid_size_m)
        if fit is None:
            continue
        face, count, rmse = fit
        if distance_between_points(*face) < settings.minimum_wall_length_m:
            continue
        # Inner/outer raster contours may refit to the same observed surface.
        if any(segments_angle(face, old[0]) and
               distance_points_to_line_np(np.asarray(face), *old[0]).max() < 3*settings.grid_size_m
               for old in faces):
            continue
        faces.append((face, count, rmse))
    faces = _coalesce_faces(faces, section, settings)
    return _walls_from_faces(faces, storey, settings,
                             (storey.elevation+0.7*height, storey.elevation+0.9*height))


def _walls_from_faces(faces, storey, settings, z_bounds):
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
    _snap_walls(walls, settings)
    return walls


def _snap_walls(walls, settings):
    axes = adjust_intersections([[list(w.start), list(w.end)] for w in walls], settings.maximum_wall_thickness_m)
    for wall, axis in zip(walls, axes):
        if not np.allclose(axis, [wall.start, wall.end], atol=1e-9):
            wall.provenance["axis"] = "inferred"  # Snapped junction, not an observed endpoint.
        wall.start, wall.end = tuple(axis[0]), tuple(axis[1])


def _region_walls(cloud, storey, settings):
    sample = voxel_sample(cloud.points, settings.detection_voxel_size_m,
                          settings.maximum_detection_points, settings.processing_chunk_points,
                          (storey.elevation, storey.ceiling))
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


def spaces_for_storey(storey: Storey, walls: list[Wall], minimum_area: float = 1.0) -> list[Space]:
    """Polygonise only this storey's axes, then remove observed/assumed wall bodies."""
    local = [wall for wall in walls if wall.storey_id == storey.id]
    if not local:
        return []
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


def reconstruct(cloud: CloudData, settings: ReconstructionSettings | None = None,
                storeys: list[Storey] | None = None, name: str = "Punctora reconstruction") -> BuildingModel:
    settings = settings or ReconstructionSettings()
    settings.validate()
    level_sample = None
    if storeys is None:
        level_sample = voxel_sample(cloud.points, settings.detection_voxel_size_m,
                                    settings.maximum_detection_points, settings.processing_chunk_points)
        levels = detect_storeys(level_sample.points, settings)
    else:
        levels = storeys
    model = BuildingModel(name, list(levels))
    model.validate()
    sorted_levels = sorted(levels, key=lambda s: s.elevation)
    if any(a.ceiling > b.elevation + 1e-8 for a, b in zip(sorted_levels, sorted_levels[1:])):
        raise ValueError("Storey clear-height intervals overlap")
    detection, proposals, consolidation = [], [], []
    for index, level in enumerate(sorted_levels):
        if settings.surface_method == "region_growing":
            local_walls, patches, statistics = _region_walls(cloud, level, settings)
            proposals.extend({**p, "id": f"{level.id}-{p['id']}", "storey_id": level.id,
                              "provider": "region_growing"} for p in patches)
        else:
            height = level.ceiling-level.elevation
            sample = voxel_sample(cloud.points, settings.detection_voxel_size_m,
                                  settings.maximum_detection_points, settings.processing_chunk_points,
                                  (level.elevation+0.7*height, level.elevation+0.9*height))
            local_walls = detect_walls(sample.points, level, settings)
            statistics = {"sample_points": len(sample.points), "source_point_count": sample.source_point_count,
                          "voxel_size_m": sample.voxel_size_m}
        if settings.consolidate_walls_enabled:
            local_walls, report = consolidate_walls(
                local_walls, angle_deg=settings.wall_merge_angle_deg,
                lateral_m=settings.wall_merge_lateral_tolerance_m,
                gap_m=settings.wall_merge_gap_m,
                thickness_m=settings.wall_merge_thickness_tolerance_m)
        else:
            report = {"input_walls": len(local_walls), "output_walls": len(local_walls), "groups": []}
        consolidation.append({"storey_id": level.id, **report})
        detection.append({"storey_id": level.id, **statistics})
        if statistics.get("voxel_size_m", settings.detection_voxel_size_m) > settings.detection_voxel_size_m:
            model.warnings.append(f"{level.id}: detection voxels enlarged to {statistics['voxel_size_m']:.6g} m to respect the point budget; small features may be missed")
        from .evidence import attach_evidence
        attach_evidence(cloud, local_walls, settings.processing_chunk_points,
                        # Raster fitting can trim a junction zone. Search up to
                        # half the configured maximum thickness beyond each
                        # endpoint, retaining a finite, recorded support window.
                        endpoint_margin=max(settings.maximum_wall_thickness_m/2, 4*settings.grid_size_m,
                                            2*statistics.get("voxel_size_m", settings.detection_voxel_size_m)),
                        radius=settings.region_plane_tolerance_m if settings.surface_method == "region_growing" else settings.grid_size_m/2)
        _snap_walls(local_walls, settings)
        for wall in local_walls:
            if wall.evidence_count < 6:
                model.warnings.append(f"{wall.id}: fewer than six supporting source records; geometric review required")
        model.walls.extend(local_walls)
        model.spaces.extend(spaces_for_storey(level, local_walls, settings.minimum_space_area_m2))
        if not local_walls:
            model.warnings.append(f"{level.id}: no supported wall candidates detected")
        if index and 0 < level.elevation-sorted_levels[index-1].ceiling <= settings.maximum_wall_thickness_m:
            thickness = level.elevation-sorted_levels[index-1].ceiling
            base, state = sorted_levels[index-1].ceiling, "measured"
        else:
            thickness, base, state = settings.assumed_slab_thickness_m, level.elevation-settings.assumed_slab_thickness_m, "inferred"
        model.slabs.append(Slab(f"{level.id}-floor", level.id, level.footprint, base, thickness,
                                "FLOOR", {"thickness": state, "footprint": "inferred", "material": "unknown"}))
    last = sorted_levels[-1]
    if level_sample is not None and level_sample.voxel_size_m > settings.detection_voxel_size_m:
        model.warnings.append(f"Level detection voxels enlarged to {level_sample.voxel_size_m:.6g} m; horizontal levels and footprints need review")
    model.slabs.append(Slab("top-slab", last.id, last.footprint, last.ceiling,
                            settings.assumed_slab_thickness_m, "NOTDEFINED",
                            {"thickness": "inferred", "footprint": "inferred", "material": "unknown"}))
    from .features import detect_openings, detect_stairs
    model.openings = detect_openings(cloud, model.walls, settings) if settings.detect_openings_enabled else []
    model.stairs = detect_stairs(cloud, sorted_levels, settings) if settings.detect_stairs_enabled else []
    model.warnings.extend([
        "All detected elements are unreviewed candidates; synthetic checks do not establish survey accuracy.",
        "Single-face wall and boundary-slab thicknesses are assumptions; materials and structural status are unknown.",
        "Horizontal density peaks and convex slab envelopes need review for furniture, voids and concave footprints.",
        "Openings are empty wall-gap proposals; glazing, closed doors and occlusion require manual review.",
        "Stairs are straight-flight tread envelopes; landings, railings and support structure are not reconstructed.",
        "Candidate scores are geometric support indicators, not calibrated accuracy probabilities. No whole-cloud deviation report is implemented.",
    ])
    model.metadata = {"engine": settings.surface_method, "settings": asdict(settings),
                      "source_points": len(cloud.points),
                      "coordinate_frame": cloud.metadata.get("coordinate_frame", "caller-supplied metres, Z up"),
                      "fit_rmse_scope": "original points selected near observed wall faces, not whole-cloud deviation",
                      "detection": detection, "surface_proposals": proposals,
                      "wall_consolidation": consolidation,
                      "level_detection": None if level_sample is None else {
                          "sample_points": len(level_sample.points), "voxel_size_m": level_sample.voxel_size_m},
                      "element_schema_version": 2}
    model.validate()
    return model
