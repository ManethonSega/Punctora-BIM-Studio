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

from .model import Landing, Opening, SlabOpening, Stair
from .sampling import adaptive_point_limit, resolved_cpu_workers, voxel_sample


def detect_openings(cloud, walls, settings, workers=None):
    workers = resolved_cpu_workers(settings.cpu_workers) if workers is None else workers
    if workers > 1 and len(walls) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(walls))) as executor:
            groups = executor.map(lambda wall: detect_openings(cloud, [wall], settings, 1), walls)
            return [opening for group in groups for opening in group]
    result = []
    cell = max(0.05, settings.grid_size_m)
    for wall in walls:
        start = np.asarray(wall.start, dtype=float)
        direction = np.asarray(wall.end, dtype=float)-start
        length = float(np.linalg.norm(direction))
        direction /= length
        normal = np.array([-direction[1], direction[0]])
        nx, nz = int(np.ceil(length/cell)), int(np.ceil(wall.height/cell))
        if nx < 10 or nz < 20 or nx*nz > settings.maximum_grid_cells:
            continue
        occupancy = np.zeros((nz, nx), np.uint8)
        face_depth = np.zeros((nz, nx), np.float32)
        support = 0
        for begin in range(0, len(cloud.points), settings.processing_chunk_points):
            points = cloud.points[begin:begin+settings.processing_chunk_points]
            relative = points[:, :2]-start
            along, across, z = relative@direction, relative@normal, points[:, 2]-wall.base
            # Restrict evidence to the host's face envelope; furniture farther
            # into the room must not fill a genuine void.
            keep = ((along >= 0) & (along < length) & (z >= 0) & (z < wall.height)
                    & (np.abs(across) <= wall.thickness/2+0.08))
            x, h = (along[keep]/cell).astype(int), (z[keep]/cell).astype(int)
            occupancy[h, x] = 1
            np.maximum.at(face_depth, (h, x), np.abs(across[keep]).astype(np.float32))
            support += len(x)
        if support < 100:
            continue
        kernel = np.ones((3, 3), np.uint8)
        filled = cv2.morphologyEx(occupancy, cv2.MORPH_CLOSE, kernel)
        observed_depth = face_depth[occupancy > 0]
        reference_depth = float(np.percentile(observed_depth, 75)) if len(observed_depth) else 0.0
        recessed = ((occupancy > 0) & (reference_depth-face_depth >= settings.opening_recess_depth_m)).astype(np.uint8)
        recessed = cv2.morphologyEx(cv2.morphologyEx(recessed, cv2.MORPH_CLOSE, kernel), cv2.MORPH_OPEN, kernel)
        candidates = []
        for method, mask in (("wall_occupancy_gap", 1-filled), ("recessed_filling_plane", recessed)):
            count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
            for index in range(1, count):
                x, z, width, height, area = map(int, stats[index])
                candidates.append((method, x, z, width, height, area))
        accepted = []
        for method, x, z, width, height, area in candidates:
            w, h = width*cell, height*cell
            # Allow floor-touching doors, but never candidates at a wall end or
            # open ceiling boundary. Require a mostly rectangular empty region.
            if x < 2 or x+width > nx-2 or z+height > nz-2 or area/(width*height) < 0.8:
                continue
            if not 0.5 <= w <= 3.2 or not 0.55 <= h <= 2.8:
                continue
            sill = z*cell
            kind = "door" if sill <= 0.18 and h >= 1.65 else "window" if 0.35 <= sill <= 1.8 else "unknown"
            if kind == "unknown" and not (sill <= 0.25 or 0.2 <= sill <= 1.9):
                continue
            strips = [filled[z:z+height, x-2:x], filled[z:z+height, x+width:x+width+2],
                      filled[z+height:z+height+2, x:x+width]]
            if kind != "door":
                strips.append(filled[max(0, z-2):z, x:x+width])
            edge = [float(s.mean()) if s.size else 0.0 for s in strips]
            if min(edge) < settings.opening_minimum_edge_support:
                continue
            interior = float(occupancy[z:z+height, x:x+width].mean())
            inside_depth = face_depth[z:z+height, x:x+width]
            inside_depth = inside_depth[inside_depth > 0]
            depth_contrast = max(0.0, reference_depth-float(np.median(inside_depth))) if len(inside_depth) else 0.0
            if method == "wall_occupancy_gap":
                if interior > 0.15:
                    continue
                score = min(edge)*(1-interior)
            else:
                if interior < 0.55 or depth_contrast < settings.opening_recess_depth_m*.8:
                    continue
                score = min(0.95, min(edge)*(0.55+min(depth_contrast/.12, .4))*interior)
            actual_sill = 0.0 if kind == "door" else sill
            actual_height = min(h+sill if kind == "door" else h, wall.height-actual_sill)
            box = (x*cell, actual_sill, min(w, length-x*cell), actual_height)
            duplicate = next((item for item in accepted
                              if min(item[0]+item[2], box[0]+box[2])-max(item[0], box[0]) > .6*min(item[2], box[2])
                              and min(item[1]+item[3], box[1]+box[3])-max(item[1], box[1]) > .6*min(item[3], box[3])), None)
            evidence = {"method": method, "cell_size_m": cell,
                        "edge_support_fractions": edge, "interior_occupancy": interior,
                        "wall_face_reference_depth_m": reference_depth,
                        "interior_depth_contrast_m": depth_contrast,
                        "host_support_points": support,
                        "scope": ("bounded host-wall void with supported jamb/head edges; occlusion can imitate an opening"
                                  if method == "wall_occupancy_gap" else
                                  "bounded recessed return plane with supported frame edges; filling type remains unknown")}
            candidate = Opening("", wall.id, kind, *box,
                                {"dimensions": "measured", "kind": "inferred", "filling": "unknown"},
                                confidence=score, evidence=evidence)
            if duplicate is None:
                accepted.append((*box, candidate))
            elif candidate.confidence > duplicate[4].confidence:
                accepted[accepted.index(duplicate)] = (*box, candidate)
        accepted.sort(key=lambda item: (item[0], item[1]))
        for index, item in enumerate(accepted, 1):
            item[4].id = f"{wall.id}-opening-{index}"
            result.append(item[4])
    return result


def detect_stairs(cloud, storeys, settings, backend=None, statistics=None, landing_output=None):
    flights = []
    detected_landings = []
    workers = resolved_cpu_workers(settings.cpu_workers)
    point_limit = adaptive_point_limit(settings.maximum_detection_points,
                                       settings.maximum_working_memory_gb, bytes_per_point=256)
    for storey in storeys:
        flight_start = len(flights)
        sample = voxel_sample(cloud.points, max(0.035, settings.detection_voxel_size_m),
                              point_limit, settings.processing_chunk_points,
                              (storey.elevation+0.08, storey.ceiling-0.05), workers, backend)
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
        for begin in range(0, len(points), 2048):
            distances, indices = tree.query(points[begin:begin+2048], k=min(12, len(points)), workers=workers)
            neighbours = points[indices]
            centre = neighbours.mean(axis=1, keepdims=True)
            covariance = np.einsum("nki,nkj->nij", neighbours-centre, neighbours-centre)
            values, vectors = np.linalg.eigh(covariance)
            horizontal[begin:begin+len(indices)] = ((np.abs(vectors[:, 2, 0]) > 0.96)
                & (values[:, 0]/np.maximum(values.sum(axis=1), 1e-12) < 0.025)
                & (distances[:, -1] < 0.22))
        points = points[horizontal]
        if len(points) < 40:
            continue
        zcells = np.floor((points[:, 2]-storey.elevation)/0.03).astype(int)
        levels = np.unique(zcells)
        groups = np.split(levels, np.where(np.diff(levels) > 1)[0]+1)
        patches, landing_patches = [], []
        for group in groups:
            plane = points[np.isin(zcells, group)]
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
                    landing_patches.append({"footprint": [tuple(map(float, point)) for point in corners],
                                            "z": float(np.median(patch[:, 2])), "count": len(patch),
                                            "coverage": float(min(1.0, coverage))})
                if not 0.6 <= width <= 3.0 or not 0.16 <= depth <= 0.5 or coverage < 0.5:
                    continue
                patches.append({"xy": centre+((low+high)/2)@axes,
                                "z": float(np.median(patch[:, 2])), "width": float(width),
                                "axis": axes[0], "count": len(patch)})
        patches.sort(key=lambda p: (p["z"], *p["xy"]))
        used = set()
        for first in range(len(patches)):
            if first in used:
                continue
            chain, direction = [first], None
            while len(chain) < 100:
                a = patches[chain[-1]]
                choices = []
                for j, b in enumerate(patches):
                    if j in used or j in chain:
                        continue
                    rise = b["z"]-a["z"]
                    delta = b["xy"]-a["xy"]
                    going = float(np.linalg.norm(delta))
                    if not 0.10 <= rise <= 0.24 or not 0.18 <= going <= 0.45:
                        continue
                    d = delta/going
                    if abs(d@a["axis"]) > 0.2 or abs(d@b["axis"]) > 0.2:
                        continue
                    if abs(b["width"]-a["width"]) > 0.2 or (direction is not None and d@direction < 0.98):
                        continue
                    choices.append((going, j, d))
                if not choices:
                    break
                _, j, d = min(choices, key=lambda c: (c[0], c[1]))
                direction = d if direction is None else direction
                chain.append(j)
            if len(chain) < 4:
                continue
            selected = [patches[i] for i in chain]
            rises = np.diff([p["z"] for p in selected])
            goings = np.linalg.norm(np.diff([p["xy"] for p in selected], axis=0), axis=1)
            if np.ptp(rises) > 0.035 or np.ptp(goings) > 0.045:
                continue
            rise, going = float(np.median(rises)), float(np.median(goings))
            start = selected[0]["xy"]-direction*going/2
            end = start+direction*going*len(chain)
            flights.append(Stair(f"{storey.id}-stair-{len(flights)+1}", storey.id, tuple(start), tuple(end),
                                 selected[0]["z"]-rise, float(np.median([p["width"] for p in selected])),
                                 rise, going, len(chain), provenance={"treads": "measured", "run": "inferred",
                                     "tread_thickness": "inferred", "structure": "unknown"},
                                 confidence=0.75, evidence={"method": "repeated_horizontal_treads",
                                     "tread_support_counts": [p["count"] for p in selected],
                                     "observed_tread_elevations_m": [p["z"] for p in selected],
                                     "rise_spread_m": float(np.ptp(rises)), "going_spread_m": float(np.ptp(goings)),
                                     "sample_voxel_size_m": sample.voxel_size_m,
                                     "scope": "measured straight flight within a connected stair-system candidate; support structure and railings are unknown"}))
            used.update(chain)
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
                    f"{storey.id}-landing-{len(detected_landings)+1}", storey.id,
                    patch["footprint"], patch["z"]-.06, .12,
                    connected_stair_ids=connected,
                    provenance={"footprint": "measured", "base": "measured", "thickness": "inferred"},
                    confidence=min(.9, .55+.35*patch["coverage"]), evidence={
                        "method": "horizontal_patch_at_flight_endpoint",
                        "support_points": patch["count"], "connected_stair_ids": connected,
                        "scope": "horizontal landing candidate connected to measured flight endpoints; structure and finish are unknown"}))
        _assign_stair_systems(local_flights, [landing for landing in detected_landings
                                              if landing.storey_id == storey.id])
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
        for flight_index, flight in enumerate(group, 1):
            flight.system_id, flight.flight_index = system_id, flight_index
            flight.evidence["system_id"] = system_id
            flight.evidence["flight_index"] = flight_index
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
            if slab.kind != "FLOOR":
                continue
            qualifying = []
            for stair in flights:
                top = stair.base+stair.steps*stair.rise
                low, high = slab.base, slab.base+slab.thickness
                distance = 0.0 if low <= top <= high else min(abs(top-low), abs(top-high))
                if slab.storey_id != stair.storey_id and distance <= vertical_tolerance_m:
                    qualifying.append((distance, stair))
            if qualifying:
                candidates.append((min(item[0] for item in qualifying), slab.base, slab.id, slab, qualifying))
        if not candidates:
            diagnostics.append({"system_id": system_id, "stair_id": flights[-1].id,
                                "status": "no_intersected_slab",
                                "stair_top_m": max(s.base+s.steps*s.rise for s in flights)})
            continue
        for distance, _, _, slab, qualifying in sorted(candidates, key=lambda item: item[:3]):
            shapes, contributing = [], []
            for stair in flights:
                start, end = np.asarray(stair.start, dtype=float), np.asarray(stair.end, dtype=float)
                top = stair.base+stair.steps*stair.rise
                if stair.base > slab.base+vertical_tolerance_m or top < slab.base-headroom_m:
                    continue
                total_rise = max(stair.steps*stair.rise, 1e-9)
                fraction = float(np.clip((slab.base-headroom_m-stair.base)/total_rise, 0, 1))
                clipped_start = start+(end-start)*fraction
                if np.linalg.norm(end-clipped_start) <= 1e-6:
                    continue
                shapes.append(LineString([clipped_start, end]).buffer(
                    stair.width/2+margin_m, cap_style=2, join_style=2))
                contributing.append(stair.id)
            connected_landings = [landing for landing in landings
                                  if landing.system_id == system_id
                                  and slab.base-headroom_m <= landing.base+landing.thickness
                                  <= slab.base+slab.thickness+vertical_tolerance_m]
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

