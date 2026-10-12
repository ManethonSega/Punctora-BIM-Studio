"""Conservative wall consolidation and explicit topology corrections."""
from copy import deepcopy
from math import acos, degrees, dist, radians, sin

import numpy as np

from .model import BuildingModel, Wall


def _axis(wall):
    start, end = np.asarray(wall.start, dtype=float), np.asarray(wall.end, dtype=float)
    vector = end-start
    return start, end, vector/np.linalg.norm(vector), float(np.linalg.norm(vector))


def _compatible(first, second, angle_deg, lateral_m, gap_m, thickness_m):
    if first.storey_id != second.storey_id:
        return False
    if abs(first.base-second.base) > .05 or abs((first.base+first.height)-(second.base+second.height)) > .05:
        return False
    if abs(first.thickness-second.thickness) > thickness_m:
        return False
    a, b, direction, length = _axis(first)
    c, d, other_direction, _ = _axis(second)
    angle = degrees(acos(float(np.clip(abs(direction@other_direction), 0, 1))))
    if angle > angle_deg:
        return False
    normal = np.array([-direction[1], direction[0]])
    if abs(float((((c+d)/2)-((a+b)/2))@normal)) > lateral_m:
        return False
    low, high = sorted((float((c-a)@direction), float((d-a)@direction)))
    gap = max(0.0, low-length, -high)
    return gap <= gap_m


def _merged_wall(group, keep_id, *, user_supplied):
    reference = max(group, key=lambda wall: _axis(wall)[3])
    _, _, reference_direction, _ = _axis(reference)
    if reference_direction[0] < -1e-12 or (abs(reference_direction[0]) <= 1e-12 and reference_direction[1] < 0):
        reference_direction *= -1
    directions, weights, endpoints = [], [], []
    for wall in group:
        start, end, direction, length = _axis(wall)
        if direction@reference_direction < 0:
            direction *= -1
        directions.append(direction);weights.append(length);endpoints.extend((start, end))
    direction = np.average(np.asarray(directions), axis=0, weights=weights)
    direction /= np.linalg.norm(direction)
    normal = np.array([-direction[1], direction[0]])
    centres = np.asarray([(np.asarray(w.start)+w.end)/2 for w in group])
    origin = direction*float(np.average(centres@direction, weights=weights))+normal*float(np.average(centres@normal, weights=weights))
    projections = np.asarray(endpoints)@direction
    start = origin+(projections.min()-origin@direction)*direction
    end = origin+(projections.max()-origin@direction)*direction
    total = sum(weights)
    thickness = float(np.average([w.thickness for w in group], weights=weights))
    evidence_count = sum(w.evidence_count for w in group)
    errors = [(w.fit_rmse_m, max(1, w.evidence_count)) for w in group if w.fit_rmse_m is not None]
    rmse = None if not errors else float(np.sqrt(sum(error*error*count for error, count in errors)/sum(count for _, count in errors)))
    classification = "consolidated_candidate"
    provenance = deepcopy(reference.provenance)
    provenance.update(axis="user_supplied" if user_supplied else "inferred",
                      thickness="user_supplied" if user_supplied else provenance.get("thickness", "inferred"))
    observed = [deepcopy(face) for wall in group for face in wall.observed_faces]
    source_evidence = {wall.id: deepcopy(wall.evidence) for wall in group if wall.evidence}
    evidence = ({"scope": "Evidence retained from the source wall candidates.",
                 "source_wall_evidence": source_evidence} if source_evidence else {})
    if not user_supplied and reference.detection_method == "multi_slice":
        evidence.update(method="multi_slice", slices=[deepcopy(s) for w in group for s in w.evidence.get("slices", [])],
                        slice_count=max(w.evidence.get("slice_count", 0) for w in group),
                        vertical_continuity=min(w.evidence.get("vertical_continuity", 0) for w in group))
    review_states = {wall.review_state for wall in group}
    return Wall(keep_id, reference.storey_id, tuple(map(float, start)), tuple(map(float, end)),
                float(np.average([w.base for w in group], weights=weights)),
                float(np.average([w.height for w in group], weights=weights)), thickness,
                classification, provenance, evidence_count, rmse,
                next(iter(review_states)) if len(review_states) == 1 else "unreviewed",
                observed, evidence, reference.detection_method)


def consolidate_walls(walls, *, angle_deg=2.0, lateral_m=.08, gap_m=.35, thickness_m=.08):
    """Join only mutually compatible collinear fragments; keep stable first IDs."""
    remaining = set(range(len(walls)))
    groups = []
    while remaining:
        seed = min(remaining); remaining.remove(seed); group = [seed]
        changed = True
        while changed:
            changed = False
            for candidate in sorted(remaining):
                if any(_compatible(walls[index], walls[candidate], angle_deg, lateral_m, gap_m, thickness_m)
                       for index in group):
                    group.append(candidate);remaining.remove(candidate);changed=True
        groups.append(sorted(group))
    result, merged = [], []
    for group in groups:
        if len(group) == 1:
            result.append(walls[group[0]])
        else:
            members = [walls[index] for index in group]
            result.append(_merged_wall(members, members[0].id, user_supplied=False))
            merged.append([wall.id for wall in members])
    return result, {"input_walls": len(walls), "output_walls": len(result), "groups": merged}


def trim_walls_covered_by_paired_faces(walls, *, angle_deg=2.0, lateral_m=.08,
                                       minimum_length_m=.5):
    """Remove single-face spans already represented by a measured face pair.

    Partial face pairing can leave another candidate on one of the same source
    planes. Keep its unsupported tails, but do not export an overlapping wall
    solid or detect the same openings a second time over the paired span.
    """
    paired = [wall for wall in walls if wall.classification == "paired_faces"]
    result, report = [], []
    cosine = np.cos(np.deg2rad(angle_deg))

    def plane_values(wall, normal):
        return [float(np.mean(np.asarray([face["start"], face["end"]]), axis=0)@normal)
                for face in wall.observed_faces]

    def clipped_face(face, direction, low, high):
        points = np.asarray([face["start"], face["end"]], dtype=float)
        values = points@direction
        order = np.argsort(values)
        points, values = points[order], values[order]
        a, b = max(low, float(values[0])), min(high, float(values[1]))
        if b-a <= 1e-9:
            return None
        span = values[1]-values[0]
        start = points[0]+(a-values[0])/span*(points[1]-points[0])
        end = points[0]+(b-values[0])/span*(points[1]-points[0])
        return {**face, "start": start.tolist(), "end": end.tolist()}

    for wall in walls:
        if wall.classification == "paired_faces":
            result.append(wall)
            continue
        start, end, direction, length = _axis(wall)
        normal = np.array([-direction[1], direction[0]])
        wall_planes = plane_values(wall, normal)
        cuts = []
        for host in paired:
            host_start, host_end, host_direction, _ = _axis(host)
            if abs(direction@host_direction) < cosine:
                continue
            host_planes = plane_values(host, normal)
            if not wall_planes or not host_planes or min(abs(a-b) for a in wall_planes for b in host_planes) > lateral_m:
                continue
            values = sorted((float(host_start@direction), float(host_end@direction)))
            low, high = max(float(start@direction), values[0]), min(float(end@direction), values[1])
            if high-low >= minimum_length_m:
                cuts.append((low, high, host.id))
        if not cuts:
            result.append(wall)
            continue
        low, high = sorted((float(start@direction), float(end@direction)))
        intervals = [(low, high)]
        for cut_low, cut_high, _ in sorted(cuts):
            intervals = [(a, b) for first, last in intervals
                         for a, b in ((first, min(last, cut_low)), (max(first, cut_high), last))
                         if b-a >= minimum_length_m]
        kept = []
        for index, (piece_low, piece_high) in enumerate(intervals, 1):
            piece = deepcopy(wall)
            origin_normal = float(start@normal)
            piece.start = tuple(direction*piece_low+normal*origin_normal)
            piece.end = tuple(direction*piece_high+normal*origin_normal)
            piece.observed_faces = [clipped for face in wall.observed_faces
                if (clipped := clipped_face(face, direction, piece_low, piece_high)) is not None]
            if not piece.observed_faces:
                continue
            if index > 1:
                piece.id = f"{wall.id}-tail-{index}"
            piece.evidence = {**piece.evidence, "paired_face_trimming": {
                "source_wall_id": wall.id,
                "excluded_paired_wall_ids": sorted({identifier for _, _, identifier in cuts}),
                "scope": "unmatched observed face tail outside measured paired-wall spans"}}
            kept.append(piece)
        result.extend(kept)
        report.append({"wall_id": wall.id,
                       "paired_wall_ids": sorted({identifier for _, _, identifier in cuts}),
                       "retained_tail_ids": [piece.id for piece in kept]})
    return result, report


def reconcile_opening_supported_faces(walls, openings, *, angle_deg=2.0,
                                      minimum_thickness_m=.08, maximum_thickness_m=.6,
                                      minimum_length_m=.5):
    """Resolve parallel wall faces only when they repeat the same openings.

    The provisional opening raster supplies evidence unavailable to the wall
    slices alone. It distinguishes an occluded opposite wall face from an
    unrelated recessed filling plane without guessing from distance alone.
    """
    wall_by_id = {wall.id: wall for wall in walls}
    openings_by_wall = {}
    for opening in openings:
        openings_by_wall.setdefault(opening.host_wall_id, []).append(opening)
    cosine = np.cos(np.deg2rad(angle_deg))

    def opening_record(opening, wall):
        start, end, direction, _ = _axis(wall)
        centre = start+direction*(opening.offset+opening.width/2)
        return opening, centre

    def plane_clusters(wall, normal):
        values = sorted(float(np.mean(np.asarray([face["start"], face["end"]]), axis=0)@normal)
                        for face in wall.observed_faces)
        groups = []
        for value in values:
            if not groups or value-groups[-1][-1] > .04:
                groups.append([value])
            else:
                groups[-1].append(value)
        return [float(np.median(group)) for group in groups if len(group) >= 2] or values

    candidates = []
    for index, first in enumerate(walls):
        first_openings = openings_by_wall.get(first.id, [])
        if not first_openings:
            continue
        a, b, direction, first_length = _axis(first)
        normal = np.array([-direction[1], direction[0]])
        first_interval = sorted((float(a@direction), float(b@direction)))
        for second in walls[index+1:]:
            second_openings = openings_by_wall.get(second.id, [])
            if not second_openings:
                continue
            c, d, other_direction, second_length = _axis(second)
            if abs(direction@other_direction) < cosine:
                continue
            second_interval = sorted((float(c@direction), float(d@direction)))
            low, high = max(first_interval[0], second_interval[0]), min(first_interval[1], second_interval[1])
            overlap = high-low
            if overlap < minimum_length_m:
                continue
            matched, used = [], set()
            first_records = [opening_record(opening, first) for opening in first_openings]
            second_records = [opening_record(opening, second) for opening in second_openings]
            for opening, centre in first_records:
                choices = []
                for candidate_index, (other, other_centre) in enumerate(second_records):
                    if candidate_index in used or (opening.kind != other.kind
                            and "unknown" not in {opening.kind, other.kind}):
                        continue
                    along = abs(float((other_centre-centre)@direction))
                    if (along <= .15 and abs(opening.width-other.width) <= .2
                            and abs(opening.sill-other.sill) <= .1
                            and abs(opening.height-other.height) <= .15):
                        choices.append((along, candidate_index, other))
                if choices:
                    _, candidate_index, other = min(choices)
                    used.add(candidate_index); matched.append((opening.id, other.id))
            shorter_fraction = overlap/min(first_length, second_length)
            continuity = min(first.evidence.get("vertical_continuity", 1.),
                             second.evidence.get("vertical_continuity", 1.))
            if not matched or (len(matched) < 2
                    and "paired_faces" not in {first.classification, second.classification}
                    and (shorter_fraction < .8 or continuity > .5)):
                continue
            first_planes, second_planes = plane_clusters(first, normal), plane_clusters(second, normal)
            plane_pairs = [(abs(x-y), x, y) for x in first_planes for y in second_planes]
            valid = [item for item in plane_pairs
                     if minimum_thickness_m <= item[0] <= maximum_thickness_m]
            if not valid and min(plane_pairs)[0] > minimum_thickness_m:
                continue
            separation, first_plane, second_plane = (min(valid) if valid else min(plane_pairs))
            candidates.append({"first": first, "second": second, "low": low, "high": high,
                "matches": matched, "separation": separation,
                "first_plane": first_plane, "second_plane": second_plane,
                "action": ("trim_existing_pair" if first.classification == "paired_faces" else
                           "trim_existing_pair" if second.classification == "paired_faces" else
                           "pair" if valid else "same_plane")})

    candidates.sort(key=lambda item: (-len(item["matches"]), -(item["high"]-item["low"]),
                                      item["first"].id, item["second"].id))
    allocated = {wall.id: [] for wall in walls}
    pair_records, accepted = [], []
    def available(identifier, low, high):
        return all(min(high, b)-max(low, a) <= .05 for a, b in allocated[identifier])
    def interval_for(item, wall):
        reference_start, _, reference_direction, _ = _axis(item["first"])
        reference_normal = np.array([-reference_direction[1], reference_direction[0]])
        plane = float(reference_start@reference_normal)
        endpoints = [reference_direction*value+reference_normal*plane
                     for value in (item["low"], item["high"])]
        wall_direction = _axis(wall)[2]
        return sorted(float(point@wall_direction) for point in endpoints)
    for item in candidates:
        first, second = item["first"], item["second"]
        if item["action"] == "trim_existing_pair":
            target = second if first.classification == "paired_faces" else first
            low, high = interval_for(item, target)
            if not available(target.id, low, high):
                continue
            allocated[target.id].append((low, high)); accepted.append(item)
        elif item["action"] == "same_plane":
            target = min((first, second), key=lambda wall: (wall.evidence_count, wall.id))
            low, high = interval_for(item, target)
            if not available(target.id, low, high):
                continue
            allocated[target.id].append((low, high)); accepted.append(item)
        else:
            first_low, first_high = interval_for(item, first)
            second_low, second_high = interval_for(item, second)
            if (not available(first.id, first_low, first_high)
                    or not available(second.id, second_low, second_high)):
                continue
            allocated[first.id].append((first_low, first_high))
            allocated[second.id].append((second_low, second_high))
            pair_records.append(item); accepted.append(item)
    if not accepted:
        return walls, [], set(), []

    affected_ids = {identifier for identifier, intervals in allocated.items() if intervals}
    final, affected = [], []
    for wall in walls:
        intervals = allocated[wall.id]
        if not intervals:
            final.append(wall); continue
        start, _, direction, length = _axis(wall)
        normal = np.array([-direction[1], direction[0]])
        origin_value, origin_normal = float(start@direction), float(start@normal)
        pieces = [(origin_value, origin_value+length)]
        for cut_low, cut_high in sorted(intervals):
            pieces = [(a, b) for first, last in pieces
                      for a, b in ((first, min(last, cut_low)), (max(first, cut_high), last))
                      if b-a >= minimum_length_m]
        for piece_index, (low, high) in enumerate(pieces, 1):
            piece = deepcopy(wall)
            piece.id = f"{wall.id}-remainder-{piece_index}"
            piece.start = tuple(direction*low+normal*origin_normal)
            piece.end = tuple(direction*high+normal*origin_normal)
            piece.observed_faces = [face for face in (clipped_face_for_interval(
                face, direction, low, high) for face in wall.observed_faces) if face is not None]
            if piece.observed_faces:
                piece.evidence = {"method": "opening_supported_face_remainder",
                    "source_wall_id": wall.id, "source_wall_evidence": deepcopy(wall.evidence)}
                final.append(piece); affected.append(piece)
    for index, item in enumerate(pair_records, 1):
        first, second = item["first"], item["second"]
        direction = _axis(first)[2]; normal = np.array([-direction[1], direction[0]])
        low, high = item["low"], item["high"]
        centre_plane = (item["first_plane"]+item["second_plane"])/2
        observed = [dict(start=(direction*low+normal*plane).tolist(),
                         end=(direction*high+normal*plane).tolist(),
                         z_min=max(first.base, second.base),
                         z_max=min(first.base+first.height, second.base+second.height))
                    for plane in (item["first_plane"], item["second_plane"])]
        paired_wall = Wall(f"{first.id}-opening-pair-{index}", first.storey_id,
            tuple(direction*low+normal*centre_plane), tuple(direction*high+normal*centre_plane),
            max(first.base, second.base), min(first.base+first.height, second.base+second.height)-max(first.base,second.base),
            item["separation"], "paired_faces",
            {"axis": "measured", "thickness": "measured", "height": "inferred",
             "material": "unknown", "load_bearing": "unknown"},
            first.evidence_count+second.evidence_count,
            max(first.fit_rmse_m or 0., second.fit_rmse_m or 0.),
            observed_faces=observed,
            evidence={"method": "matching_openings_on_parallel_faces",
                      "source_wall_ids": [first.id, second.id],
                      "matching_opening_ids": [identifier for pair in item["matches"] for identifier in pair],
                      "source_wall_evidence": {first.id: deepcopy(first.evidence), second.id: deepcopy(second.evidence)}},
            detection_method="opening_supported_pair")
        final.append(paired_wall); affected.append(paired_wall)
    report = [{"first_wall_id": item["first"].id, "second_wall_id": item["second"].id,
               "action": item["action"], "matching_opening_count": len(item["matches"]),
               "overlap_m": item["high"]-item["low"], "plane_separation_m": item["separation"]}
              for item in accepted]
    return final, affected, affected_ids, report


def rehost_reconciled_openings(openings, source_walls, final_walls,
                               replaced_wall_ids, *, angle_deg=2.0,
                               maximum_axis_distance_m=.65,
                               endpoint_margin_m=.1):
    """Carry measured openings from removed faces onto the final wall axis.

    Re-detecting openings after face reconciliation remains authoritative, but
    a shorter final host can put a frame edge outside the new raster and lose a
    previously supported bay.  Preserve that evidence in global coordinates,
    then let :func:`merge_reconciled_openings` discard any duplicate found by
    the final-host raster.
    """
    sources = {wall.id: wall for wall in source_walls}
    cosine = np.cos(np.deg2rad(angle_deg))
    carried = []
    for opening in openings:
        if opening.host_wall_id not in replaced_wall_ids:
            continue
        source = sources.get(opening.host_wall_id)
        if source is None:
            continue
        source_start, _, source_direction, _ = _axis(source)
        centre = source_start+source_direction*(opening.offset+opening.width/2)
        candidates = []
        for wall in final_walls:
            if wall.storey_id != source.storey_id:
                continue
            start, _, direction, length = _axis(wall)
            if abs(float(source_direction@direction)) < cosine:
                continue
            along = float((centre-start)@direction)
            if (along-opening.width/2 < -endpoint_margin_m
                    or along+opening.width/2 > length+endpoint_margin_m):
                continue
            normal = np.array([-direction[1], direction[0]])
            distance = abs(float((centre-start)@normal))
            if distance > maximum_axis_distance_m:
                continue
            # Prefer a measured face pair, then the closest compatible axis.
            candidates.append((distance, wall.classification != "paired_faces",
                               abs(along-length/2), wall.id, wall, along))
        if not candidates:
            continue
        *_, wall, along = min(candidates)
        item = deepcopy(opening)
        original_id, original_host = item.id, item.host_wall_id
        item.host_wall_id = wall.id
        item.offset = max(0., min(float(along-item.width/2),
                                  _axis(wall)[3]-item.width))
        item.evidence = deepcopy(item.evidence)
        item.evidence.pop("facade_system", None)
        item.evidence["reconciled_host"] = {
            "source_opening_id": original_id,
            "source_wall_id": original_host,
            "host_wall_id": wall.id,
            "axis_distance_m": min(candidates)[0],
            "scope": "Opening dimensions retained in global coordinates after evidence-supported wall-face reconciliation",
        }
        carried.append(item)
    return carried


def merge_reconciled_openings(unaffected, carried, refreshed, walls,
                              *, angle_deg=2.0):
    """Merge final-host detections with carried evidence and remove repeats."""
    wall_by_id = {wall.id: wall for wall in walls}
    cosine = np.cos(np.deg2rad(angle_deg))

    def geometry(opening):
        wall = wall_by_id.get(opening.host_wall_id)
        if wall is None:
            return None
        start, _, direction, _ = _axis(wall)
        return wall, direction, start+direction*(opening.offset+opening.width/2)

    def duplicates(first, second):
        first_geometry, second_geometry = geometry(first), geometry(second)
        if first_geometry is None or second_geometry is None:
            return False
        first_wall, first_direction, first_centre = first_geometry
        second_wall, second_direction, second_centre = second_geometry
        if (first_wall.storey_id != second_wall.storey_id
                or abs(float(first_direction@second_direction)) < cosine
                or (first.kind != second.kind and "unknown" not in {first.kind, second.kind})
                or abs(first.sill-second.sill) > .1
                or abs(first.height-second.height) > .15
                or abs(first.width-second.width) > .2):
            return False
        delta = second_centre-first_centre
        normal = np.array([-first_direction[1], first_direction[0]])
        return (abs(float(delta@first_direction)) <= .15
                and abs(float(delta@normal)) <= .45)

    # Final-host measurements take precedence over old-host evidence.  Stable
    # input ordering then keeps unaffected opening IDs predictable.
    ranked = ([(2, opening) for opening in refreshed]
              + [(1, opening) for opening in unaffected]
              + [(0, opening) for opening in carried])
    ranked.sort(key=lambda item: (-item[0], -(item[1].confidence or 0.),
                                  item[1].host_wall_id, item[1].offset))
    accepted = []
    for _, opening in ranked:
        if not any(duplicates(opening, previous) for previous in accepted):
            accepted.append(opening)
    accepted.sort(key=lambda opening: (opening.host_wall_id, opening.offset,
                                        opening.sill, opening.width))
    counts = {}
    for opening in accepted:
        counts[opening.host_wall_id] = counts.get(opening.host_wall_id, 0)+1
        opening.id = f"{opening.host_wall_id}-opening-{counts[opening.host_wall_id]}"
    return accepted


def clipped_face_for_interval(face, direction, low, high):
    """Clip an observed face to a projected interval while retaining metadata."""
    points = np.asarray([face["start"], face["end"]], dtype=float)
    values = points@direction
    order = np.argsort(values); points, values = points[order], values[order]
    a, b = max(low, float(values[0])), min(high, float(values[1]))
    if b-a <= 1e-9:
        return None
    span = values[1]-values[0]
    start = points[0]+(a-values[0])/span*(points[1]-points[0])
    end = points[0]+(b-values[0])/span*(points[1]-points[0])
    return {**face, "start": start.tolist(), "end": end.tolist()}


def reconcile_observed_wall_overlaps(walls, *, minimum_length_m=.5,
                                     plane_tolerance_m=.03, angle_deg=2.):
    """Trim duplicate solids only when their refitted original planes agree.

    Unlike opening-based pairing, opaque walls can supply this evidence. Every
    observed plane of the trimmed candidate must already be represented by the
    retained host. Proximity of assumed solid footprints alone is insufficient.
    """
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    result = {w.id: deepcopy(w) for w in walls}
    removed, affected_ids, report = set(), set(), []
    cosine = np.cos(np.deg2rad(angle_deg))

    def supported_faces(wall):
        return [f for f in wall.observed_faces
                if f.get('original_inlier_fit_points', 0) >= 20
                and f.get('original_plane_fit_rmse_m', 1.) <= .02]

    def footprint(wall):
        return LineString([wall.start, wall.end]).buffer(wall.thickness/2, cap_style=2)

    def planes(faces, normal):
        return [float(np.asarray([f['start'],f['end']]).mean(axis=0)@normal)
                for f in faces]

    def distributed_height_support(wall, faces):
        # Judge the original observations over the whole host height. A sparse
        # slice at an opening edge must not veto otherwise distributed support.
        counts = np.zeros(12)
        for face in faces:
            bands = face.get('original_height_band_counts')
            if bands is None:
                bands = np.full(12, face.get('original_vertical_support_fraction', 0))
            bands = np.asarray(bands, float)
            if not len(bands):
                continue
            z = face['z_min']+(np.arange(len(bands))+.5)/len(bands)*(face['z_max']-face['z_min'])
            positions = np.clip(((z-wall.base)/wall.height*12).astype(int), 0, 11)
            if 'original_height_band_counts' in face:
                np.add.at(counts, positions, bands)
            else:
                np.maximum.at(counts, positions, bands*100)
        return float(np.mean(counts >= max(6, counts.sum()*.005)))

    ordered = sorted(walls, key=lambda w:(w.classification!='paired_faces',
                                          -w.evidence_count, w.id))
    for original_host in ordered:
        if original_host.id in removed:
            continue
        host = result[original_host.id]
        a, b, direction, host_length = _axis(host)
        normal = np.array([-direction[1], direction[0]])
        host_faces = supported_faces(host)
        if not host_faces:
            continue
        host_planes = planes(host_faces, normal)
        if (max(host_planes)-min(host_planes)>plane_tolerance_m
                and host.classification!='paired_faces'):
            continue
        for original_target in ordered:
            if original_target.id==host.id or original_target.id in removed:
                continue
            target = result[original_target.id]
            if target.id in affected_ids or target.storey_id != host.storey_id:
                continue
            c,d,other_direction,target_length = _axis(target)
            if (abs(direction@other_direction)<cosine or abs(host.base-target.base)>.05
                    or abs(host.base+host.height-target.base-target.height)>.05):
                continue
            target_faces = supported_faces(target)
            if len(target_faces)!=len(target.observed_faces) or not target_faces:
                continue
            target_planes=planes(target_faces,normal)
            shared=all(min(abs(value-old) for old in host_planes)<=plane_tolerance_m
                       for value in target_planes)
            # A measured body can also contain a return/recess plane that was
            # erroneously extruded as another wall. Keep that observation in
            # the evidence, but do not count the same opaque volume twice.
            contained=(host.classification=='paired_faces'
                and min(host_planes)-plane_tolerance_m<=min(target_planes)
                and max(target_planes)<=max(host_planes)+plane_tolerance_m)
            if not shared and not contained:
                continue
            overlap_area = footprint(host).intersection(footprint(target)).area
            if (overlap_area<=.02 or overlap_area/min(footprint(host).area,
                                                     footprint(target).area)<.5):
                continue
            if not shared and overlap_area/min(footprint(host).area,
                                               footprint(target).area)<.8:
                continue
            projected=sorted((float((c-a)@direction),float((d-a)@direction)))
            low,high=max(0.,projected[0]),min(host_length,projected[1])
            if high-low<minimum_length_m:
                continue
            # Preserve every tail with meaningful source geometry. A tiny
            # discarded tail must not contain any observed span >= the limit.
            target_normal=np.array([-other_direction[1],other_direction[0]])
            cut=sorted(float((a+direction*t)@other_direction) for t in (low,high))
            first,last=sorted((float(c@other_direction),float(d@other_direction)))
            tails=[]
            for lo,hi in ((first,min(last,cut[0])),(max(first,cut[1]),last)):
                if hi-lo<1e-8:
                    continue
                tail=deepcopy(target)
                tail.id=f'{target.id}-overlap-tail-{len(tails)+1}'
                plane=float(c@target_normal)
                tail.start=tuple(other_direction*lo+target_normal*plane)
                tail.end=tuple(other_direction*hi+target_normal*plane)
                tail.observed_faces=[f for face in target.observed_faces
                    if (f:=clipped_face_for_interval(face,other_direction,lo,hi)) is not None]
                if not tail.observed_faces:
                    continue
                tail.evidence={**tail.evidence,'overlap_reconciliation':{
                    'source_wall_id':target.id,'retained_host_id':host.id}}
                tails.append(tail)
            host.observed_faces.extend(f for face in target_faces
                if (f:=clipped_face_for_interval(face,direction,
                           float(a@direction)+low,float(a@direction)+high)) is not None)
            host.evidence.setdefault('overlap_source_wall_ids',[]).append(target.id)
            removed.add(target.id);affected_ids.add(host.id)
            for tail in tails:
                result[tail.id]=tail;affected_ids.add(tail.id)
            report.append({'retained_wall_id':host.id,'trimmed_wall_id':target.id,
                'overlap_area_m2':float(overlap_area),'source_basis':'refitted_original_planes',
                'decision':'shared_plane' if shared else 'contained_return_plane',
                'retained_tail_ids':[t.id for t in tails]})
    # Opposite exterior faces may both carry assumed thicknesses.
    # Independent original-point support allows one measured common span.
    remaining=[w for key,w in result.items() if key not in removed]
    for i,first in enumerate(remaining):
        if first.id in removed or first.classification!='exterior_candidate':continue
        af=supported_faces(first)
        if not af or len(af)!=len(first.observed_faces) or distributed_height_support(first,af)<.55:continue
        a,b,direction,length=_axis(first);normal=np.array([-direction[1],direction[0]])
        av=planes(af,normal)
        if max(av)-min(av)>plane_tolerance_m:continue
        for second in remaining[i+1:]:
            if second.id in removed or second.classification!='exterior_candidate':continue
            bf=supported_faces(second)
            if (not bf or first.storey_id!=second.storey_id or
                    len(bf)!=len(second.observed_faces) or distributed_height_support(second,bf)<.55):continue
            c,d,other_direction,other_length=_axis(second)
            bv=planes(bf,normal)
            separation=abs(float(np.median(av)-np.median(bv)))
            if (abs(direction@other_direction)<cosine or max(bv)-min(bv)>plane_tolerance_m
                    or not .08<=separation<=.3 or abs(first.base-second.base)>.05
                    or abs(first.base+first.height-second.base-second.height)>.05):continue
            area=footprint(first).intersection(footprint(second)).area
            if area<=.02 or area/min(footprint(first).area,footprint(second).area)<.5:continue
            values=sorted((float(c@direction),float(d@direction)))
            low,high=max(float(a@direction),values[0]),min(float(b@direction),values[1])
            if high-low<minimum_length_m:continue
            plane=float(np.median(av+bv))
            clipped_groups=[[f for face in w.observed_faces
                if (f:=clipped_face_for_interval(face,direction,low,high)) is not None]
                for w in (first,second)]
            if not all(clipped_groups):continue
            # The fitter's first two faces must be the two opposite planes,
            # rather than adjacent height slices of the same plane.
            paired_faces=[group[0] for group in clipped_groups]
            paired_faces.extend(f for group in clipped_groups for f in group[1:])
            pair=Wall(first.id+'-observed-pair',first.storey_id,
                tuple(direction*low+normal*plane),tuple(direction*high+normal*plane),
                first.base,first.height,separation,'paired_faces',
                {**first.provenance,'axis':'measured','thickness':'measured'},
                observed_faces=paired_faces,
                detection_method='original_face_pair',evidence={'source_wall_ids':[first.id,second.id]})
            result[pair.id]=pair;affected_ids.add(pair.id)
            tails=[]
            for wall in (first,second):
                start,end,axis,wall_length=_axis(wall);side=np.array([-axis[1],axis[0]])
                cuts=sorted(float((direction*t+normal*plane)@axis) for t in (low,high))
                first_t,last_t=sorted((float(start@axis),float(end@axis)))
                for lo,hi in ((first_t,min(last_t,cuts[0])),(max(first_t,cuts[1]),last_t)):
                    if hi-lo<1e-6:continue
                    tail=deepcopy(wall);tail.id=wall.id+f'-pair-tail-{len(tails)+1}'
                    offset=float(start@side)
                    tail.start=tuple(axis*lo+side*offset);tail.end=tuple(axis*hi+side*offset)
                    tail.observed_faces=[f for face in wall.observed_faces
                        if (f:=clipped_face_for_interval(face,axis,lo,hi)) is not None]
                    if not tail.observed_faces:continue
                    result[tail.id]=tail;affected_ids.add(tail.id);tails.append(tail)
            removed.update([first.id,second.id])
            report.append({'retained_wall_id':pair.id,'trimmed_wall_id':second.id,
                'source_wall_ids':[first.id,second.id],'source_basis':'independent_distributed_original_faces',
                'original_height_support_fractions':[distributed_height_support(first,af),
                                                     distributed_height_support(second,bf)],
                'decision':'measured_opposite_face_pair','overlap_area_m2':float(area),
                'retained_tail_ids':[t.id for t in tails]})
            break
    final=[w for identifier,w in result.items() if identifier not in removed]
    return final,[w for w in final if w.id in affected_ids],removed,report


def _cross(first, second):
    return float(first[0]*second[1]-first[1]*second[0])


def _line_intersection(first_start, first_end, second_start, second_end):
    first, second = first_end-first_start, second_end-second_start
    divisor = _cross(first, second)
    if abs(divisor) <= 1e-12:
        return None
    scale = _cross(second_start-first_start, second)/divisor
    point = first_start+scale*first
    return point if np.isfinite(point).all() else None


def _project_onto_segment(point, start, end):
    vector = end-start
    length = float(np.linalg.norm(vector))
    if length <= 1e-9:
        return None
    direction = vector/length
    along = float((point-start)@direction)
    if along < 0 or along > length:
        return None
    foot = start+along*direction
    return foot, float(np.linalg.norm(point-foot)), along, length


def _angle_degrees(first_start, first_end, second_start, second_end):
    first, second = first_end-first_start, second_end-second_start
    denominator = float(np.linalg.norm(first)*np.linalg.norm(second))
    if denominator <= 1e-12:
        return 0.0
    return degrees(acos(float(np.clip(abs(first@second)/denominator, 0, 1))))


def snap_wall_topology(walls, *, corner_tolerance_m=.3, t_tolerance_m=.1,
                       t_minimum_angle_deg=25.0, support_validator=None):
    """Snap corners and credible T-junctions from one immutable geometry snapshot.

    Corner endpoints are clustered through common axis intersections. T-junctions
    are restricted to nonparallel walls, and a wall with both ends beside the same
    host is never moved onto it. The returned endpoint records are keyed by stable
    wall IDs so filtering a collapsed candidate cannot corrupt the diagnostics.
    """
    if not walls:
        return {"corner_clusters": [], "t_junctions": [], "rejected": [],
                "endpoint_relations": []}
    if corner_tolerance_m <= 0 or t_tolerance_m <= 0 or not 0 < t_minimum_angle_deg < 90:
        raise ValueError("Wall topology tolerances and angle must be positive")
    if len({wall.id for wall in walls}) != len(walls):
        raise ValueError("Wall topology requires unique wall IDs")

    keys = [(wall.id, end) for wall in walls for end in ("start", "end")]
    original = {(wall.id, end): np.asarray(getattr(wall, end), dtype=float)
                for wall in walls for end in ("start", "end")}
    proposed = {key: value.copy() for key, value in original.items()}
    parent = {key: key for key in keys}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(first, second):
        first, second = find(first), find(second)
        if first != second:
            parent[max(first, second)] = min(first, second)

    support = {key: [] for key in keys}
    minimum_sine = sin(radians(10.0))
    for first_index, first in enumerate(walls):
        first_start, first_end = original[(first.id, "start")], original[(first.id, "end")]
        first_vector = first_end-first_start
        for second in walls[first_index+1:]:
            if first.storey_id != second.storey_id:
                continue
            second_start, second_end = original[(second.id, "start")], original[(second.id, "end")]
            second_vector = second_end-second_start
            denominator = float(np.linalg.norm(first_vector)*np.linalg.norm(second_vector))
            if denominator <= 1e-12 or abs(_cross(first_vector, second_vector))/denominator < minimum_sine:
                continue
            point = _line_intersection(first_start, first_end, second_start, second_end)
            if point is None:
                continue
            first_key = min(((first.id, end) for end in ("start", "end")),
                            key=lambda key: float(np.linalg.norm(original[key]-point)))
            second_key = min(((second.id, end) for end in ("start", "end")),
                             key=lambda key: float(np.linalg.norm(original[key]-point)))
            if (np.linalg.norm(original[first_key]-point) > corner_tolerance_m
                    or np.linalg.norm(original[second_key]-point) > corner_tolerance_m):
                continue
            support[first_key].append(point); support[second_key].append(point)
            union(first_key, second_key)

    clusters = {}
    for key in keys:
        if support[key]:
            clusters.setdefault(find(key), []).append(key)
    relations, cluster_records, rejected = {}, [], []
    for members in clusters.values():
        if len(members) < 2:
            continue
        target = np.mean([point for key in members for point in support[key]], axis=0)
        movements = {key: float(np.linalg.norm(original[key]-target)) for key in members}
        if max(movements.values()) > corner_tolerance_m+1e-9:
            rejected.append({"kind": "corner_cluster_drift", "wall_ends": [list(key) for key in members],
                             "maximum_displacement_m": max(movements.values())})
            continue
        if support_validator is not None:
            checks = [support_validator(next(w for w in walls if w.id == key[0]), key[1], target,
                      [w for w in walls if w.id in {k[0] for k in members} and w.id != key[0]]) for key in members]
            if not all(c['supported'] for c in checks):
                rejected.append(dict(kind='unsupported_corner',wall_ends=[list(k) for k in members],target=target.tolist(),evidence=checks))
                continue
        for key in members:
            proposed[key] = target.copy(); relations[key] = "shared_corner"
        cluster_records.append({"wall_ends": [list(key) for key in sorted(members)],
                                "target": target.tolist(),
                                "maximum_displacement_m": max(movements.values())})

    # Select every T-junction from the same post-corner snapshot. No selection
    # can influence a later one through in-place wall mutation.
    t_candidates = {}
    for wall in walls:
        source_start, source_end = proposed[(wall.id, "start")], proposed[(wall.id, "end")]
        for end in ("start", "end"):
            key = (wall.id, end)
            if key in relations:
                continue
            point = proposed[key]
            choices = []
            for host in walls:
                if host.id == wall.id or host.storey_id != wall.storey_id:
                    continue
                host_start, host_end = proposed[(host.id, "start")], proposed[(host.id, "end")]
                angle = _angle_degrees(source_start, source_end, host_start, host_end)
                if angle < t_minimum_angle_deg:
                    continue
                projection = _project_onto_segment(point, host_start, host_end)
                if projection is None:
                    continue
                foot, distance, along, length = projection
                intersection = _line_intersection(source_start,source_end,host_start,host_end)
                if intersection is None:
                    continue
                actual = _project_onto_segment(intersection,host_start,host_end)
                if actual is None:
                    continue
                foot,_,along,length = actual
                distance = float(np.linalg.norm(point-foot))
                if distance <= t_tolerance_m:
                    choices.append((distance, host.id, foot, along, length, angle))
            if choices:
                t_candidates[key] = min(choices, key=lambda item: (item[0], item[1]))

    for wall in walls:
        start, end = t_candidates.get((wall.id, "start")), t_candidates.get((wall.id, "end"))
        if start is not None and end is not None and start[1] == end[1]:
            rejected.append({"kind": "both_ends_near_same_host", "wall_id": wall.id,
                             "host_wall_id": start[1]})
            t_candidates.pop((wall.id, "start"), None)
            t_candidates.pop((wall.id, "end"), None)

    t_records = []
    for key, (distance, host_id, foot, along, host_length, angle) in sorted(t_candidates.items()):
        if support_validator is not None:
            check = support_validator(next(w for w in walls if w.id == key[0]),key[1],foot,[next(w for w in walls if w.id == host_id)])
            if not check['supported']:
                rejected.append(dict(kind='unsupported_t_junction',wall_ends=[list(key)],target=foot.tolist(),evidence=[check]))
                continue
        proposed[key] = foot; relations[key] = "t_junction"
        t_records.append({"wall_id": key[0], "end": key[1], "host_wall_id": host_id,
                          "distance_m": distance, "host_offset_m": along,
                          "host_length_m": host_length, "angle_deg": angle})

    for wall in walls:
        for end in ("start", "end"):
            key = (wall.id, end)
            target = proposed[key]
            if not np.allclose(original[key], target, atol=1e-9):
                setattr(wall, end, tuple(map(float, target)))
                wall.provenance["axis"] = "inferred"
    return {"corner_clusters": cluster_records, "t_junctions": t_records,
            "rejected": rejected,
            "endpoint_relations": [{"wall_id": key[0], "end": key[1], "relation": relation}
                                   for key, relation in sorted(relations.items())]}


def observed_junction_support(wall,end,target,partners):
    """Validate the observed face intersection, not a return inside solid material."""
    a,b,direction,_=_axis(wall)
    normal=np.array([-direction[1],direction[0]])
    if abs(float((target-a)@normal))>.05:
        return dict(wall_id=wall.id,end=end,supported=False,reason='correction_leaves_supported_axis')
    bands,checks=set(),[]
    for face in wall.observed_faces:
        a,b=np.asarray(face['start']),np.asarray(face['end'])
        length=np.linalg.norm(b-a)
        if length<1e-8:
            continue
        direction=(b-a)/length
        for partner in partners:
            for other in partner.observed_faces:
                if min(face['z_max'],other['z_max'])<=max(face['z_min'],other['z_min']):
                    continue
                c,d=np.asarray(other['start']),np.asarray(other['end'])
                point=_line_intersection(a,b,c,d)
                other_length=np.linalg.norm(d-c)
                if point is None or other_length<1e-8 or np.linalg.norm(point-target)>wall.thickness+partner.thickness+.05:
                    continue
                along=float((point-a)@direction)
                other_along=float((point-c)@(d-c)/other_length)
                if -.050001<=along<=length+.050001 and -.050001<=other_along<=other_length+.050001:
                    bands.add((face.get('slice_index'),face['z_min'],face['z_max']))
                    checks.append(dict(partner_wall_id=partner.id,face_intersection=point.tolist(),
                                       z_min=max(face['z_min'],other['z_min']),z_max=min(face['z_max'],other['z_max'])))
    required=2 if wall.detection_method=='multi_slice' else 1
    return dict(wall_id=wall.id,end=end,supported=len(bands)>=required,support_bands=len(bands),required_bands=required,face_intersections=checks)


def evidence_endpoint_report(walls,topology,gap_tolerance_m=.05):
    report=wall_connectivity_report(walls,topology,gap_tolerance_m)
    rejected={tuple(k) for r in topology['rejected'] for k in r.get('wall_ends',[])}
    for item in report['endpoints']:
        key=(item['wall_id'],item['end'])
        if key in rejected and item['status'] not in {'shared_corner','t_junction'}:
            item['status']='rejected_correction'
        elif item['status']=='shared_corner':
            item['status']='supported_corner'
        elif item['status']=='t_junction':
            item['status']='supported_t_junction'
        elif item['status'] in {'open_or_missing','connected_geometry'}:
            wall=next(w for w in walls if w.id==item['wall_id'])
            item['status']='intentional_open_end' if wall.evidence.get('intentional_open_ends',{}).get(item['end']) else 'unresolved_gap'
    report['counts']={s:sum(e['status']==s for e in report['endpoints']) for s in sorted({e['status'] for e in report['endpoints']})}
    for wall in walls:
        wall.evidence['endpoints']=[e for e in report['endpoints'] if e['wall_id']==wall.id]
    return report


def wall_connectivity_report(walls, topology, gap_tolerance_m=.05):
    """Classify every final endpoint without asserting that an open end is wrong."""
    relation = {(item["wall_id"], item["end"]): item["relation"]
                for item in topology.get("endpoint_relations", [])}
    endpoints = []
    exact = 1e-7
    for wall in walls:
        for end in ("start", "end"):
            key, point = (wall.id, end), np.asarray(getattr(wall, end), dtype=float)
            if key in relation:
                endpoints.append({"wall_id": wall.id, "end": end, "status": relation[key],
                                  "nearest_wall_distance_m": 0.0})
                continue
            nearest = None
            for other in walls:
                if other.id == wall.id or other.storey_id != wall.storey_id:
                    continue
                projection = _project_onto_segment(point, np.asarray(other.start, dtype=float),
                                                   np.asarray(other.end, dtype=float))
                if projection is not None:
                    nearest = projection[1] if nearest is None else min(nearest, projection[1])
            status = ("connected_geometry" if nearest is not None and nearest <= exact
                      else "unresolved_gap" if nearest is not None and nearest <= gap_tolerance_m
                      else "open_or_missing")
            endpoints.append({"wall_id": wall.id, "end": end, "status": status,
                              "nearest_wall_distance_m": nearest})
    counts = {}
    for endpoint in endpoints:
        counts[endpoint["status"]] = counts.get(endpoint["status"], 0)+1
    return {"endpoints": endpoints, "counts": counts}


def _reassign_opening(opening, source, target):
    source_start, _, source_direction, _ = _axis(source)
    target_start, _, target_direction, _ = _axis(target)
    first = source_start+source_direction*opening.offset
    second = first+source_direction*opening.width
    values = sorted((float((first-target_start)@target_direction), float((second-target_start)@target_direction)))
    opening.host_wall_id = target.id
    opening.offset = max(0.0, values[0])
    opening.width = values[1]-values[0]
    opening.provenance.update(host_wall_id="user_supplied", offset="user_supplied", width="user_supplied")


def merge_walls(model: BuildingModel, wall_ids: list[str]) -> BuildingModel:
    if not isinstance(wall_ids, list) or len(set(wall_ids)) < 2 or any(not isinstance(value, str) for value in wall_ids):
        raise ValueError("Select at least two different walls to merge")
    selected = [wall for wall in model.walls if wall.id in set(wall_ids)]
    if len(selected) != len(set(wall_ids)):
        raise ValueError("A selected wall is missing from the draft model")
    connected = {0}
    while True:
        added = {candidate for candidate in set(range(len(selected)))-connected
                 if any(_compatible(selected[first], selected[candidate], 5.0,
                                    max(.15, selected[first].thickness, selected[candidate].thickness), 2.5,
                                    max(.15, selected[first].thickness, selected[candidate].thickness))
                        for first in connected)}
        if not added:
            break
        connected.update(added)
    if len(connected) != len(selected):
        raise ValueError("Selected walls must form one collinear same-storey chain with gaps no larger than 2.5 m")
    keep = selected[0]
    combined = _merged_wall(selected, keep.id, user_supplied=True)
    sources = {wall.id: wall for wall in selected}
    for opening in model.openings:
        if opening.host_wall_id in sources:
            _reassign_opening(opening, sources[opening.host_wall_id], combined)
    selected_ids = set(wall_ids)
    model.walls = [combined if wall.id == keep.id else wall for wall in model.walls if wall.id not in selected_ids or wall.id == keep.id]
    model.spaces = []
    model.metadata["geometry_edited"] = True
    model.metadata.setdefault("edit_history", []).append({"operation": "merge_walls", "wall_ids": list(wall_ids),
        "result_wall_id": combined.id, "quality_scope": "Source observed faces and evidence are retained; the merged axis is user supplied."})
    model.validate()
    return model

def split_wall(model: BuildingModel, wall_id: str, offset: float) -> BuildingModel:
    wall = next((candidate for candidate in model.walls if candidate.id == wall_id), None)
    if wall is None:
        raise ValueError("Select a wall to split")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not np.isfinite(offset):
        raise ValueError("Split position must be a finite distance in metres")
    start, end, direction, length = _axis(wall)
    minimum = max(.1, wall.thickness/2)
    if not minimum <= offset <= length-minimum:
        raise ValueError(f"Split position must leave at least {minimum:.3g} m on each side")
    for opening in model.openings:
        if opening.host_wall_id == wall.id and opening.offset < offset < opening.offset+opening.width:
            raise ValueError(f"Split position crosses opening {opening.id}; choose a position outside the opening")
    split = start+direction*offset
    original_end = wall.end
    existing = {candidate.id for candidate in model.walls}
    number = 2
    new_id = f"{wall.id}-split-{number}"
    while new_id in existing:
        number += 1;new_id = f"{wall.id}-split-{number}"
    wall.end = tuple(map(float, split));wall.provenance["end"] = "user_supplied";wall.review_state = "unreviewed"
    second = deepcopy(wall);second.id = new_id;second.start = tuple(map(float, split));second.end = original_end
    second.provenance.update(start="user_supplied", end="user_supplied")
    for opening in model.openings:
        if opening.host_wall_id == wall.id and opening.offset >= offset:
            opening.host_wall_id = second.id;opening.offset -= offset
            opening.provenance.update(host_wall_id="user_supplied", offset="user_supplied")
    index = model.walls.index(wall);model.walls.insert(index+1, second)
    model.spaces = []
    model.metadata["geometry_edited"] = True
    model.metadata.setdefault("edit_history", []).append({"operation": "split_wall", "wall_id": wall_id,
        "offset": float(offset), "result_wall_ids": [wall.id, second.id],
        "quality_scope": "Observed faces and evidence describe the pre-split wall candidate."})
    model.validate()
    return model
