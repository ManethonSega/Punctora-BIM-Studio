"""Horizontal surface evidence, slab-zone sequencing and nonconvex slab bodies.

No elevations, storey counts or footprints from customer scans are hardcoded.
Scores measure geometric support, not probabilities. Point IDs refer to the
unchanged working cloud; single-face thickness remains an explicit assumption.
"""
from dataclasses import dataclass
import cv2
import numpy as np
from scipy.signal import find_peaks
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, MultiPolygon, MultiPoint, LineString, box
from shapely.ops import unary_union

from .model import Slab, SlabOpening, Storey
from .sampling import resolved_cpu_workers


@dataclass
class Surface:
    elevation: float
    geometry: object
    raw_geometry: object
    indices: np.ndarray
    normal_z: float
    normal: tuple


def _polygons(geometry):
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [g for g in getattr(geometry, "geoms", ()) if isinstance(g, Polygon)]


def occupancy_geometry(xy, cell, close_gap, maximum_cells):
    """Raster polygons, keeping concavity, components and internal rings.

    Union row runs rather than thousands of individual cells. Closing is padded
    and bounded in physical metres; it never fills a large enclosed void.
    """
    origin = np.floor(xy.min(axis=0)/cell)*cell-cell*3
    cells = np.floor((xy-origin)/cell+1e-8).astype(int)
    shape = cells.max(axis=0)+4
    if int(shape[0])*int(shape[1]) > maximum_cells:
        raise ValueError("Slab evidence exceeds raster budget; crop the scan")
    raw = np.zeros((int(shape[1]), int(shape[0])), np.uint8)
    raw[cells[:, 1], cells[:, 0]] = 1
    radius = int(np.floor(close_gap/(2*cell)))
    filled = cv2.morphologyEx(raw, cv2.MORPH_CLOSE,
                             np.ones((2*radius+1, 2*radius+1), np.uint8)) if radius else raw

    def polygons(mask):
        rectangles = []
        for y, row in enumerate(mask):
            changes = np.diff(np.pad(row.astype(np.int8), (1, 1)))
            for a, b in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)):
                rectangles.append(box(origin[0]+a*cell, origin[1]+y*cell,
                                      origin[0]+b*cell, origin[1]+(y+1)*cell))
        return unary_union(rectangles)
    return polygons(filled), polygons(raw)


def horizontal_surfaces(sample, settings):
    points = sample.points
    if len(points) < 12:
        raise ValueError("Insufficient spatial evidence for horizontal surfaces")
    tree = cKDTree(points)
    keep, normals = np.zeros(len(points), bool), np.zeros(len(points))
    workers = resolved_cpu_workers(settings.cpu_workers)
    for begin in range(0, len(points), 4096):
        distance, ids = tree.query(points[begin:begin+4096], k=12, workers=workers)
        neighbours = points[ids]
        centred = neighbours-neighbours.mean(axis=1, keepdims=True)
        values, vectors = np.linalg.eigh(np.einsum("nki,nkj->nij", centred, centred))
        vertical = np.abs(vectors[:, 2, 0])
        normals[begin:begin+len(ids)] = vertical
        keep[begin:begin+len(ids)] = ((vertical >= .97)
            & (values[:, 0]/np.maximum(values.sum(axis=1), 1e-12) <= .025)
            & (distance[:, -1] <= max(.30, 4*sample.voxel_size_m)))
    indices = np.flatnonzero(keep)
    if len(indices) < 24:
        raise ValueError("No supported horizontal planes; provide explicit storeys")
    horizontal = points[indices]
    size = min(.025, settings.level_bin_size_m)
    first = int(np.floor(horizontal[:, 2].min()/size))
    bins = np.floor(horizontal[:, 2]/size+1e-8).astype(int)-first
    histogram = np.bincount(bins)
    smooth = np.convolve(histogram, [.2, .6, .2], mode="same")
    peaks, _ = find_peaks(smooth, prominence=max(8., smooth.max()*.006), distance=3)
    ends = [i for i in (0, len(smooth)-1) if smooth[i] >= max(8., smooth.max()*.006)
            and smooth[i] >= smooth[1 if i == 0 else -2]]
    peaks = np.unique(np.r_[peaks, ends]).astype(int)
    surfaces = []
    for peak in peaks:
        selected = indices[np.abs(bins-peak) <= 1]
        if len(selected) < 20:
            continue
        xyz = points[selected]
        z = float(np.median(xyz[:, 2]))
        selected = selected[np.abs(xyz[:, 2]-z) <= settings.slab_surface_tolerance_m]
        if len(selected) < 20:
            continue
        # Recover coplanar edge records whose normal neighbourhood contains a
        # wall/corner. Their proximity to horizontal support prevents unrelated
        # vertical faces elsewhere in this height band from becoming slabs.
        near = np.flatnonzero(np.abs(points[:, 2]-z) <= settings.slab_surface_tolerance_m)
        edge_distance, _ = cKDTree(points[selected, :2]).query(points[near, :2], workers=workers)
        selected = near[edge_distance <= 1.5*settings.slab_raster_cell_m]
        geometry, raw = occupancy_geometry(points[selected, :2], settings.slab_raster_cell_m,
                                          settings.slab_close_gap_m, settings.maximum_grid_cells)
        # Trim pixel overhang, never use the hull to fill concavity or holes.
        extent = MultiPoint(points[selected, :2]).convex_hull
        geometry, raw = geometry.intersection(extent), raw.intersection(extent)
        pieces = [p for p in _polygons(geometry) if p.area >= settings.slab_minimum_component_area_m2]
        geometry = unary_union(pieces)
        if geometry.area < settings.minimum_footprint_area_m2:
            continue
        planar = points[selected]
        coefficients, *_ = np.linalg.lstsq(np.column_stack([planar[:, :2], np.ones(len(planar))]),
                                           planar[:, 2], rcond=None)
        normal = np.array([-coefficients[0], -coefficients[1], 1.])
        normal /= np.linalg.norm(normal)
        surfaces.append(Surface(z, geometry, raw.intersection(geometry),
                                sample.cloud_indices[selected], float(np.median(normals[selected])), tuple(normal)))
    return sorted(surfaces, key=lambda s: s.elevation), {
        "normal_tested_points": len(points), "horizontal_points": int(keep.sum()),
        "normal_z_minimum": .97, "height_bin_m": size,
        "evidence_index_semantics": "original working-cloud row (not preview row)",
    }


def detect_slab_zones(sample, settings):
    surfaces, statistics = horizontal_surfaces(sample, settings)
    if len(surfaces) < 2:
        raise ValueError("Fewer than two supported horizontal boundary surfaces")
    largest = max(s.geometry.area for s in surfaces)
    minimum_area = max(settings.minimum_footprint_area_m2, largest*settings.slab_minimum_area_fraction)
    candidates = []
    for i, lower in enumerate(surfaces):
        # Single observed boundaries are necessary for scans with no slab
        # underside. They are never labelled measured thickness.
        candidates.append({"lower": i, "upper": i, "paired": False})
        for j in range(i+1, len(surfaces)):
            upper = surfaces[j]
            thickness = upper.elevation-lower.elevation
            if thickness > settings.slab_maximum_thickness_m:
                break
            overlap = lower.geometry.intersection(upper.geometry).area/min(lower.geometry.area, upper.geometry.area)
            angle = float(np.degrees(np.arccos(np.clip(np.dot(lower.normal,upper.normal),-1,1))))
            if (thickness >= settings.slab_minimum_thickness_m and overlap >= settings.slab_minimum_face_overlap
                    and angle <= 5.):
                candidates.append({"lower": i, "upper": j, "paired": True})
            elif (j == i+1 and thickness >= settings.slab_minimum_thickness_m
                  and overlap < .01 and min(lower.geometry.area, upper.geometry.area) >= minimum_area):
                # Separate partial floor plates can delimit a short vertical
                # transition, but their nonoverlapping faces do NOT measure a
                # slab thickness. Keep this boundary explicitly unpaired.
                candidates.append({"lower": i, "upper": j, "paired": False,
                                   "disconnected_boundary_transition": True})
    for candidate in candidates:
        a, b = surfaces[candidate["lower"]], surfaces[candidate["upper"]]
        area = max(a.geometry.area, b.geometry.area)
        candidate.update(bottom_m=a.elevation, top_m=b.elevation,
                         horizontal_support_area_m2=area,
                         upper_lower_overlap_fraction=(a.geometry.intersection(b.geometry).area/
                             min(a.geometry.area, b.geometry.area)),
                         confidence=min(.95, .45+.25*area/largest+(.2 if candidate["paired"] else 0)),
                         rejection_reasons=[] if area >= minimum_area else ["insufficient_building_scale_horizontal_support"])
        candidate["score"] = (1.+area/largest+(1.2 if candidate["paired"] else 0)
                              +(.6*min(a.geometry.area,b.geometry.area)/largest if candidate["paired"] else 0)
                              -(.8*abs(b.elevation-a.elevation-settings.assumed_slab_thickness_m)
                                if candidate["paired"] else 0))
        if candidate.get("disconnected_boundary_transition"):
            candidate["score"] += .4
    eligible = [c for c in candidates if not c["rejection_reasons"]]
    eligible.sort(key=lambda c: (c["top_m"], c["bottom_m"]))
    # Dynamic programming evaluates the complete sequence. Landings cannot
    # coexist with adjacent full-storey boundaries merely because they peak.
    paths = []
    for i, current in enumerate(eligible):
        best = (current["score"], [i])
        for j in range(i):
            previous = eligible[j]
            clear = current["bottom_m"]-previous["top_m"]
            spacing = current["top_m"]-previous["top_m"]
            if (clear < settings.minimum_storey_height_m
                    or spacing > settings.slab_maximum_storey_spacing_m):
                continue
            score = paths[j][0]+current["score"]-.15*abs(spacing-3.2)
            if score > best[0]:
                best = (score, paths[j][1]+[i])
        paths.append(best)
    if not paths:
        raise ValueError("No building-scale slab sequence; provide explicit storeys")
    _, selected_ids = max(paths, key=lambda p: (len(p[1]) >= 2, p[0]))
    zones = [eligible[i] for i in selected_ids]
    if len(zones) < 2:
        raise ValueError("No supported floor-to-floor sequence; provide explicit storeys")
    selected = {id(c) for c in zones}
    for c in candidates:
        c["selected"] = id(c) in selected
        if not c["selected"] and not c["rejection_reasons"]:
            c["rejection_reasons"] = ["incompatible_or_lower_scoring_vertical_sequence"]
        a, b = surfaces[c["lower"]], surfaces[c["upper"]]
        c["estimated_thickness_m"] = b.elevation-a.elevation if c["paired"] else settings.assumed_slab_thickness_m
        c["component_count"] = len(_polygons(a.geometry.union(b.geometry)))
        c["normal_z"] = [a.normal_z, b.normal_z]
        c["upper_lower_normal_angle_deg"] = float(np.degrees(np.arccos(np.clip(np.dot(a.normal,b.normal),-1,1))))
        c["source_point_evidence"] = {
            "lower_working_indices": a.indices.tolist(), "upper_working_indices": b.indices.tolist(),
            "scope": "spatially distributed original source representatives classified horizontal"}
    levels = []
    for i, (low, high) in enumerate(zip(zones, zones[1:])):
        floor_surface = surfaces[low["upper"]]
        # Storey envelope is a clipping/search boundary, not a slab solid.
        # Allow a hull here because disconnected scans can have one storey.
        near = np.abs(sample.points[:, 2]-floor_surface.elevation) <= settings.slab_surface_tolerance_m
        envelope = MultiPoint(sample.points[near, :2]).convex_hull
        levels.append(Storey(f"storey-{i+1}", f"Storey {i+1}", low["top_m"], high["bottom_m"],
                             list(envelope.exterior.coords)[:-1],
                             {"elevation": "measured", "ceiling": "measured", "footprint": "inferred"}))
    report = {"method": "horizontal_slab_zone_sequence", **statistics,
              "candidates": candidates, "selected_zone_count": len(zones),
              "minimum_support_area_m2": minimum_area,
              "scope": "geometric slab proposals, not structural or survey confirmation"}
    return levels, zones, surfaces, report


def consolidate_scan_fragments(geometry, maximum_gap):
    """Bridge bounded coplanar scan seams, never replace contours by a hull."""
    pieces = _polygons(geometry)
    if len(pieces) < 2:
        return geometry, 0.0
    # Mitred closing keeps straight roof edges exact. Restrict added area to
    # corridors supported on both sides, avoiding corner-only connections.
    bridges = []
    radius = maximum_gap / 2 + 1e-8
    for i, a in enumerate(pieces):
        for b in pieces[i+1:]:
            if a.distance(b) > maximum_gap:
                continue
            nearby = a.boundary.intersection(b.buffer(maximum_gap + 1e-8)).length
            if nearby < max(.5, 3 * maximum_gap):
                continue
            closed = a.union(b).buffer(radius, join_style=2).buffer(-radius, join_style=2)
            addition = closed.difference(a.union(b))
            if len(_polygons(closed)) == 1 and addition.area <= maximum_gap * nearby * 1.1:
                bridges.append(addition)
    bridge = unary_union(bridges).difference(geometry)
    return geometry.union(bridge), float(bridge.area)


def _face_holes(face):
    return [Polygon(r) for p in _polygons(face.raw_geometry) for r in p.interiors]


def _matching_hole(hole, candidates):
    return max((hole.intersection(p).area / hole.union(p).area for p in candidates), default=0.0)


def _fixture_pattern(hole, candidates):
    # Repeated small, similarly shaped gaps are typical fixture occlusion.
    # Keep them reviewable even if both scans contain the same pattern.
    def dimensions(p):
        c = list(p.minimum_rotated_rectangle.exterior.coords)
        return sorted([LineString(c[:2]).length, LineString(c[1:3]).length])
    size = dimensions(hole)
    if max(size) > 1.2:
        return False
    similar = [p for p in candidates if all(abs(a-b) <= max(.08, a*.15)
                for a,b in zip(size, dimensions(p)))]
    return len(similar) >= 3


def slab_zone_geometry(zones, surfaces, storeys, settings, walls=()):
    slabs, openings = [], []
    for index, zone in enumerate(zones):
        lower, upper = surfaces[zone["lower"]], surfaces[zone["upper"]]
        geometry = lower.geometry.union(upper.geometry) if zone["paired"] else upper.geometry
        raw = lower.raw_geometry.union(upper.raw_geometry) if zone["paired"] else upper.raw_geometry
        geometry, seam_area = consolidate_scan_fragments(geometry, settings.slab_close_gap_m)
        face_holes = [_face_holes(lower), _face_holes(upper)]
        owner = storeys[min(index, len(storeys)-1)]
        # A wall outline can resolve only a narrow occluded strip adjacent to
        # observed horizontal support. Protect all large interior gaps. Original
        # observed faces, not inferred/snapped wall extents, constrain this fill.
        protected = unary_union([Polygon(r) for p in _polygons(geometry) for r in p.interiors
                                 if Polygon(r).area >= settings.slab_minimum_hole_area_m2])
        wall_strips = []
        for wall in walls:
            if (wall.storey_id != owner.id or wall.evidence_count < 20
                    or wall.fit_rmse_m is None or wall.fit_rmse_m > settings.slab_surface_tolerance_m):
                continue
            for face in wall.observed_faces:
                wall_strips.append(LineString([face["start"], face["end"]]).buffer(
                    settings.slab_raster_cell_m/2, cap_style=2))
        addition = (unary_union(wall_strips).intersection(geometry.buffer(settings.slab_close_gap_m/2))
                    .difference(protected).difference(geometry))
        # Never create a disconnected outline-only "slab" with zero horizontal
        # support. Narrow additions must actually touch the observed body.
        addition = unary_union([p for p in _polygons(addition) if p.distance(geometry) <= 1e-8])
        geometry = geometry.union(addition)
        base = zone["bottom_m"]
        thickness = zone["estimated_thickness_m"]
        if not zone["paired"] and index == 0:
            base -= thickness
        elif zone.get("disconnected_boundary_transition"):
            base = upper.elevation-thickness
        components = sorted(_polygons(geometry), key=lambda p: (-p.area, p.bounds))
        for number, piece in enumerate(components, 1):
            if piece.area < settings.slab_minimum_component_area_m2:
                continue
            exterior = Polygon(piece.exterior).simplify(1e-9, preserve_topology=True)
            prefix = "top-slab" if index == len(zones)-1 else f"{owner.id}-floor"
            slab_id = prefix if len(components) == 1 else f"{prefix}-component-{number}"
            # Preserve gaps seen on just one face as review candidates too.
            gaps = unary_union([*face_holes[0], *face_holes[1],
                                *[Polygon(r) for r in piece.interiors]]).intersection(exterior)
            retained_holes = [p for p in _polygons(gaps)
                              if p.area >= settings.slab_minimum_hole_area_m2]
            exported = exterior
            support = exported.intersection(raw).area
            inferred = max(0., exported.area-support)
            evidence = {"method": "separate_face_occupancy_union", "zone_index": index,
                        "lower_surface_m": lower.elevation, "upper_surface_m": upper.elevation,
                        "paired_faces": zone["paired"], "raster_cell_m": settings.slab_raster_cell_m,
                        "maximum_closed_gap_m": settings.slab_close_gap_m,
                        "wall_outline_inferred_area_m2": piece.intersection(addition).area,
                        "scan_seam_inferred_area_m2": seam_area,
                        "cut_policy": "occupancy_gaps_require_independent_validation",
                        "net_polygon_area_m2": exported.area, "supported_area_m2": support,
                        "inferred_area_m2": inferred, "supported_percent": 100*support/exported.area,
                        "inferred_percent": 100*inferred/exported.area,
                        "unsupported_gaps": [{"classification": "unsupported_gap", "area_m2": Polygon(r).area,
                                             "decision": "below_hole_threshold_filled_and_counted_inferred"}
                                            for r in piece.interiors if Polygon(r).area < settings.slab_minimum_hole_area_m2],
                        "scope": "horizontal occupancy support; empty interiors are candidate holes, not confirmed stairwells"}
            slabs.append(Slab(slab_id, owner.id, list(exterior.exterior.coords)[:-1], base, thickness,
                              "NOTDEFINED" if index == len(zones)-1 else "FLOOR",
                              {"thickness": "measured" if zone["paired"] else "inferred",
                               "footprint": "inferred", "material": "unknown"},
                              confidence=zone["confidence"], evidence=evidence))
            for hole_index, hole in enumerate(retained_holes, 1):
                # Independent face holes, not perimeter support alone, validate a cut.
                from .features import _opening_frame
                start, end, width = _opening_frame(hole)
                band = hole.boundary.buffer(settings.slab_raster_cell_m)
                face_support = [face.geometry.intersection(band).area/band.area for face in (lower, upper)]
                matches = [_matching_hole(hole, candidates) for candidates in face_holes]
                pattern = _fixture_pattern(hole, retained_holes)
                matching = (zone["paired"] and zone["lower"] != zone["upper"]
                            and min(matches) >= .8 and min(face_support) >= .25 and not pattern)
                classification = ("light_fixture_pattern" if pattern else
                                  "observed_hole" if matching else "partially_observed_hole")
                openings.append(SlabOpening(f"{slab_id}-observed-hole-{hole_index}", slab_id,
                    start, end, width, provenance={"footprint": "inferred", "host_slab_id": "measured"},
                    confidence=zone["confidence"], footprint=list(hole.exterior.coords)[:-1],
                    evidence={"method": "enclosed_horizontal_occupancy_gap", "area_m2": hole.area,
                              "classification": classification, "face_boundary_support_fractions": face_support,
                              "face_hole_overlap_fractions": matches,
                              "validation_state": "validated" if matching else "review_required",
                              "validation_basis": "matching_faces" if matching else None,
                              "ifc_policy": "cut_only_after_independent_validation_or_explicit_user_approval",
                              "stairwell_state": "pending_stair_system_validation",
                              "scope": "enclosed unsampled region; matching independent faces can validate a cut; single-face and fixture patterns remain filled"}))
    return slabs, openings
