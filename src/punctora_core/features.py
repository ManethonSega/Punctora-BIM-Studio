"""Conservative multi-evidence opening and stair-system proposals, in metres.

Scores describe geometric support, not calibrated probabilities or scan accuracy.
Missing returns alone never establish an opening. No pretrained models are used.
"""
import cv2
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from .model import Landing, Opening, SlabOpening, Stair, Storey
from .stair_sequences import fit_tread_sequences
from .sampling import adaptive_point_limit, resolved_cpu_workers, voxel_sample


def detect_openings(cloud, walls, settings, workers=None):
    from .opening_raster import detect_signed_openings
    return detect_signed_openings(cloud, walls, settings, workers)


def detect_stairs(cloud, storeys, settings, backend=None, statistics=None, landing_output=None):
    flights = []
    detected_landings = []
    workers = resolved_cpu_workers(settings.cpu_workers)
    point_limit = adaptive_point_limit(settings.maximum_detection_points,
                                       settings.maximum_working_memory_gb, bytes_per_point=256)
    if not storeys:
        return []
    actual_storeys = sorted(storeys, key=lambda s: s.elevation)
    global_scope = Storey("building", "Global stair evidence",
        actual_storeys[0].elevation, max(s.ceiling for s in actual_storeys),
        actual_storeys[0].footprint)
    for storey in [global_scope]:
        flight_start = len(flights)
        sample = voxel_sample(cloud.points, max(0.035, settings.detection_voxel_size_m),
                              point_limit, settings.processing_chunk_points,
                              (storey.elevation+0.02, storey.ceiling-0.02), workers, backend)
        if statistics is not None:
            statistics.append({"storey_id": storey.id, "sample_points": len(sample.points),
                               "source_point_count": sample.source_point_count,
                               "voxel_size_m": sample.voxel_size_m})
        points = sample.points
        if len(points) < 60:
            continue
        # Estimate local horizontal support with bounded batches. A vertical
        # riser or wall section is not accepted as a tread just for sharing Z.
        tree = cKDTree(points)
        horizontal = np.zeros(len(points), bool)
        vertical = np.zeros(len(points), bool)
        normals = np.zeros_like(points)
        for begin in range(0, len(points), 2048):
            distances, indices = tree.query(points[begin:begin+2048], k=min(12, len(points)), workers=workers)
            neighbours = points[indices]
            centre = neighbours.mean(axis=1, keepdims=True)
            covariance = np.einsum("nki,nkj->nij", neighbours-centre, neighbours-centre)
            values, vectors = np.linalg.eigh(covariance)
            normals[begin:begin+len(indices)] = vectors[:, :, 0]
            vertical[begin:begin+len(indices)] = ((np.abs(vectors[:, 2, 0]) < .2)
                & (values[:, 0]/np.maximum(values.sum(axis=1), 1e-12) < .025)
                & (distances[:, -1] < .22))
            horizontal[begin:begin+len(indices)] = ((np.abs(vectors[:, 2, 0]) > 0.96)
                & (values[:, 0]/np.maximum(values.sum(axis=1), 1e-12) < 0.025)
                & (distances[:, -1] < 0.22))
        riser_points, riser_normals = points[vertical], normals[vertical]
        horizontal_source_rows = sample.cloud_indices[horizontal]
        if cloud.working_index is not None:
            horizontal_source_rows = cloud.working_index[horizontal_source_rows]
        points = points[horizontal]
        if len(points) < 40:
            continue
        zcells = np.floor((points[:, 2]-storey.elevation)/0.03).astype(int)
        levels = np.unique(zcells)
        groups = np.split(levels, np.where(np.diff(levels) > 1)[0]+1)
        patches, landing_patches = [], []
        for group in groups:
            plane_mask = np.isin(zcells, group)
            plane = points[plane_mask]
            plane_rows = horizontal_source_rows[plane_mask]
            if len(plane) < 20 or np.ptp(plane[:, 2]) > 0.07:
                continue
            origin = plane[:, :2].min(axis=0)-0.06
            cells = np.floor((plane[:, :2]-origin)/0.06).astype(int)
            shape = cells.max(axis=0)+3
            if int(shape[0])*int(shape[1]) > settings.maximum_grid_cells:
                continue
            mask = np.zeros((int(shape[1]), int(shape[0])), np.uint8)
            mask[cells[:, 1], cells[:, 0]] = 1
            connected = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            count, labels = cv2.connectedComponents(connected, 8)
            ids = labels[cells[:, 1], cells[:, 0]]
            for index in range(1, count):
                patch = plane[ids == index]
                source_examples = plane_rows[ids == index][:12].astype(int).tolist()
                if len(patch) < 20:
                    continue
                centre = patch[:, :2].mean(axis=0)
                _, _, axes = np.linalg.svd(patch[:, :2]-centre, full_matrices=False)
                xy = (patch[:, :2]-centre)@axes.T
                low, high = xy.min(axis=0), xy.max(axis=0)
                width, depth = high-low
                if width <= 1e-6 or depth <= 1e-6:
                    continue
                # Require broad support, avoiding a line mistaken for a tread.
                coverage = len(np.unique(np.floor(xy/0.06).astype(int), axis=0))*0.06**2/(width*depth)
                if coverage < 0.45:
                    continue
                corners = np.array([[low[0], low[1]], [high[0], low[1]],
                                    [high[0], high[1]], [low[0], high[1]]])@axes+centre
                if 0.6 <= width <= 4.0 and 0.55 <= depth <= 4.0 and width*depth <= 12.0:
                    component = np.uint8(labels == index)
                    contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    boundary = max(contours, key=cv2.contourArea)[:, 0, :]
                    if len(boundary) < 3:
                        continue
                    supported_shape = Polygon(origin+(boundary+.5)*.06).buffer(.03, join_style=2)
                    if not isinstance(supported_shape, Polygon) or supported_shape.area < .3:
                        continue
                    landing_patches.append({"footprint": [tuple(map(float, point))
                                            for point in list(supported_shape.exterior.coords)[:-1]],
                                            "z": float(np.median(patch[:, 2])), "count": len(patch),
                                            "coverage": float(min(1.0, coverage)),
                                            "source_working_row_examples": source_examples})
                # Normal estimation loses narrow strips beside risers. The
                # measured patch depth may be smaller than the fitted going.
                if not 0.6 <= width <= 3.0 or not 0.12 <= depth <= 0.5 or coverage < 0.5:
                    continue
                patches.append({"xy": centre+((low+high)/2)@axes,
                                "z": float(np.median(patch[:, 2])), "width": float(width),
                                "axis": axes[0], "count": len(patch),
                                "source_working_row_examples": source_examples})
        patches.sort(key=lambda p: (p["z"], *p["xy"]))
        for fitted in fit_tread_sequences(patches):
            selected = [patches[i] for i in fitted["indices"]]
            rise, going, direction = fitted["rise"], fitted["going"], fitted["direction"]
            start = fitted["first_xy"]-direction*going/2
            end = start+direction*going*fitted["steps"]
            base = fitted["first_z"]-rise
            width = float(np.median([p["width"] for p in selected]))
            owner = max((s for s in actual_storeys if s.elevation <= base+.15),
                        key=lambda s: s.elevation, default=actual_storeys[0])
            # Independent vertical returns are supporting evidence, not a
            # requirement that would reject a scan containing only top faces.
            along = (riser_points[:, :2]-start)@direction
            side = (riser_points[:, :2]-start)@np.array([-direction[1], direction[0]])
            step_indices = np.rint(along/going).astype(int)
            expected_top = base+(step_indices+1)*rise
            riser_mask = ((step_indices >= 0) & (step_indices < fitted["steps"])
                & (np.abs(along-step_indices*going) <= .045)
                & (np.abs(side) <= width/2+.03)
                & (riser_points[:, 2] >= expected_top-rise-.025)
                & (riser_points[:, 2] <= expected_top+.025)
                & (np.abs(riser_normals[:, :2]@direction) > .9))
            riser_counts = [int(np.sum(riser_mask & (step_indices == i)))
                            for i in range(fitted["steps"])]
            top = base+fitted["steps"]*rise
            upper = min(actual_storeys, key=lambda s: abs(s.elevation-top))
            missing = sorted(set(range(fitted["steps"]))-set(fitted["observed_steps"]))
            flights.append(Stair(f"building-stair-{len(flights)+1}", owner.id,
                tuple(start), tuple(end), base, width, rise, going, fitted["steps"],
                provenance={"treads": "measured" if not missing else "inferred",
                            "run": "inferred", "tread_thickness": "inferred", "structure": "unknown"},
                confidence=max(.5, .8-.03*len(missing)),
                evidence={"method": "global_tread_riser_lattice",
                    "tread_support_counts": [p["count"] for p in selected],
                    "observed_tread_elevations_m": [p["z"] for p in selected],
                    "source_working_row_examples_by_tread": [p["source_working_row_examples"] for p in selected],
                    "observed_step_indices": fitted["observed_steps"],
                    "inferred_missing_step_indices": missing,
                    "riser_support_counts": riser_counts,
                    "lower_storey_id": owner.id,
                    "upper_storey_id": upper.id if abs(upper.elevation-top) <= .3 else None,
                    "upper_association_distance_m": float(abs(upper.elevation-top)),
                    "sample_voxel_size_m": sample.voxel_size_m,
                    "scope": "building-wide straight-flight proposal; missing interior treads are inferred, end treads are not extrapolated"}))
        local_flights = flights[flight_start:]
        for patch in landing_patches:
            polygon = Polygon(patch["footprint"])
            connected = []
            for stair in local_flights:
                endpoints = ((stair.start, stair.base),
                             (stair.end, stair.base+stair.steps*stair.rise))
                if any(abs(patch["z"]-height) <= .12 and polygon.buffer(.4).covers(Point(xy))
                       for xy, height in endpoints):
                    connected.append(stair.id)
            if connected:
                detected_landings.append(Landing(
                    f"building-landing-{len(detected_landings)+1}",
                    max((s for s in actual_storeys if s.elevation <= patch["z"]+.12),
                        key=lambda s: s.elevation, default=actual_storeys[0]).id,
                    patch["footprint"], patch["z"]-.12, .12,
                    connected_stair_ids=connected,
                    provenance={"footprint": "measured", "base": "inferred", "thickness": "inferred"},
                    confidence=min(.9, .55+.35*patch["coverage"]), evidence={
                        "method": "horizontal_patch_at_flight_endpoint",
                        "support_points": patch["count"], "connected_stair_ids": connected,
                        "observed_upper_surface_m": patch["z"],
                        "source_working_row_examples": patch["source_working_row_examples"],
                        "scope": "horizontal landing candidate connected to measured flight endpoints; structure and finish are unknown"}))
        _assign_stair_systems(local_flights, detected_landings)
    if landing_output is not None:
        landing_output.extend(detected_landings)
    return flights


def _assign_stair_systems(flights, landings):
    """Group flights through shared landing evidence and assign stable indices."""
    if not flights:
        return
    parent = {flight.id: flight.id for flight in flights}

    def root(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(first, second):
        a, b = root(first), root(second)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for landing in landings:
        for stair_id in landing.connected_stair_ids[1:]:
            union(landing.connected_stair_ids[0], stair_id)
    groups = {}
    for flight in flights:
        groups.setdefault(root(flight.id), []).append(flight)
    for index, group in enumerate(sorted(groups.values(), key=lambda value: min(item.id for item in value)), 1):
        system_id = f"{group[0].storey_id}-stair-system-{index}"
        group.sort(key=lambda item: (item.base, item.id))
        directions = [(np.asarray(f.end)-f.start)/(f.steps*f.going) for f in group]
        turns = [float(a@b) for a,b in zip(directions,directions[1:])]
        layout = ("straight" if not turns or all(t > .95 for t in turns) else
                  "U" if len(turns) == 1 and turns[0] < -.95 else
                  "L" if len(turns) == 1 and abs(turns[0]) < .2 else "multi_turn")
        for flight_index, flight in enumerate(group, 1):
            flight.system_id, flight.flight_index = system_id, flight_index
            flight.evidence["system_id"] = system_id
            flight.evidence["flight_index"] = flight_index
            flight.evidence["system_layout"] = layout
        member_ids = {flight.id for flight in group}
        for landing in landings:
            if member_ids.intersection(landing.connected_stair_ids):
                landing.system_id = system_id


def _opening_frame(polygon):
    rectangle = list(polygon.minimum_rotated_rectangle.exterior.coords)[:-1]
    edges = [(np.asarray(rectangle[(i+1) % 4])-rectangle[i], i) for i in range(4)]
    vector, _ = max(edges, key=lambda item: np.linalg.norm(item[0]))
    length = float(np.linalg.norm(vector))
    direction = vector/length
    centre = np.asarray(polygon.centroid.coords[0])
    width = float(polygon.minimum_rotated_rectangle.area/length)
    return tuple(centre-direction*length/2), tuple(centre+direction*length/2), width


def derive_stair_slab_openings(stairs, slabs, landings=None, margin_m=.1,
                               vertical_tolerance_m=.05, headroom_m=2.0):
    """Create reviewable, host-clipped stairwell polygons using headroom evidence."""
    openings, diagnostics = [], []
    landings = landings or []
    systems = {}
    for stair in stairs:
        systems.setdefault(stair.system_id or stair.id, []).append(stair)
    for system_id, flights in sorted(systems.items()):
        candidates = []
        for slab in slabs:
            qualifying = []
            for stair in flights:
                top = stair.base+stair.steps*stair.rise
                low, high = slab.base, slab.base+slab.thickness
                distance = 0.0 if low <= top <= high else min(abs(top-low), abs(top-high))
                # Every obstructing slab is checked, including roof slabs and
                # a slab crossed by a flight whose measured top is slightly
                # below it. Headroom does not require exact endpoint equality.
                if (low > stair.base+.05 and low <= top+max(.25, vertical_tolerance_m)
                        and high >= stair.base+stair.rise):
                    qualifying.append((distance, stair))
            if qualifying:
                candidates.append((min(item[0] for item in qualifying), slab.base, slab.id, slab, qualifying))
        if not candidates:
            diagnostics.append({"system_id": system_id, "stair_id": flights[-1].id,
                                "status": "no_intersected_slab",
                                "stair_top_m": max(s.base+s.steps*s.rise for s in flights)})
            continue
        for distance, _, _, slab, qualifying in sorted(candidates, key=lambda item: item[:3]):
            shapes, contributing, source_steps = [], [], {}
            for stair in flights:
                start, end = np.asarray(stair.start, dtype=float), np.asarray(stair.end, dtype=float)
                top = stair.base+stair.steps*stair.rise
                if stair.base > slab.base+vertical_tolerance_m or top < slab.base-headroom_m:
                    continue
                # Stepped treads, rather than a continuous ramp or rectangular
                # flight box, determine the required clearance at each XY cell.
                indices = [i for i in range(stair.steps)
                           if stair.base+(i+1)*stair.rise+headroom_m > slab.base+1e-8
                           and stair.base+(i+1)*stair.rise-stair.tread_thickness
                           < slab.base+slab.thickness+vertical_tolerance_m]
                if not indices:
                    continue
                for i in indices:
                    a = start+(end-start)*i/stair.steps
                    b = start+(end-start)*(i+1)/stair.steps
                    shapes.append(LineString([a,b]).buffer(
                        stair.width/2+margin_m, cap_style=2, join_style=2))
                contributing.append(stair.id)
                source_steps[stair.id] = indices
            connected_landings = [landing for landing in landings
                                  if landing.system_id == system_id
                                  and slab.base-headroom_m <= landing.base+landing.thickness
                                  <= slab.base+slab.thickness+max(.12, vertical_tolerance_m)]
            shapes.extend(Polygon(landing.footprint).buffer(margin_m, join_style=2)
                          for landing in connected_landings)
            if not shapes:
                diagnostics.append({"system_id": system_id, "host_slab_id": slab.id,
                                    "status": "no_headroom_envelope"})
                continue
            raw = unary_union(shapes).buffer(0)
            host = Polygon(slab.footprint)
            clipped = raw.intersection(host).buffer(0)
            if clipped.is_empty or clipped.area < .05:
                diagnostics.append({"system_id": system_id, "stair_id": qualifying[0][1].id,
                                    "host_slab_id": slab.id, "status": "outside_host_footprint"})
                continue
            pieces = list(clipped.geoms) if isinstance(clipped, MultiPolygon) else [clipped]
            for piece_index, piece in enumerate(sorted(pieces, key=lambda item: (-item.area, item.centroid.x, item.centroid.y)), 1):
                if piece.area < .05:
                    continue
                footprint = [tuple(map(float, point)) for point in list(piece.exterior.coords)[:-1]]
                start, end, width = _opening_frame(piece)
                source = min(qualifying, key=lambda item: (item[0], item[1].id))[1]
                opening = SlabOpening(
                    f"{system_id}-{slab.id}-opening-{piece_index}", slab.id,
                    start, end, width, source.id,
                    {"footprint": "inferred", "host_slab_id": "inferred", "headroom": "inferred"},
                    confidence=min((stair.confidence or 0 for stair in flights), default=0),
                    evidence={"method": "stair_system_headroom_envelope",
                              "source_stair_ids": contributing,
                              "source_step_indices": source_steps,
                              "source_landing_ids": [landing.id for landing in connected_landings],
                              "host_slab_base_m": float(slab.base),
                              "vertical_distance_m": float(distance), "margin_m": float(margin_m),
                              "headroom_m": float(headroom_m),
                              "clipped_to_host": bool(clipped.area < raw.area-1e-8),
                              "scope": "flight and landing headroom envelope clipped to the detected host slab; structural trimming requires review"},
                    footprint=footprint, source_system_id=system_id)
                openings.append(opening)
                diagnostics.append({"system_id": system_id, "stair_id": source.id,
                                    "host_slab_id": slab.id, "slab_opening_id": opening.id,
                                    "status": "candidate_created", "headroom_m": headroom_m,
                                    "clipped_to_host": opening.evidence["clipped_to_host"]})
    return openings, diagnostics

