"""Conservative wall consolidation and explicit topology corrections."""
from copy import deepcopy
from math import acos, degrees, dist

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
