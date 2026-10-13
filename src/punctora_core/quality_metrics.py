"""Deterministic, independent geometry and semantic comparisons in metre/f64 frames."""
from math import acos, degrees, dist

import numpy as np
from scipy.optimize import linear_sum_assignment
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .annotation_io import CLASSES, MATCHING, polygon, record_key


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def scores(tp, fp, fn):
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "iou": _ratio(tp, tp + fp + fn),
            "f1": _ratio(2 * tp, 2 * tp + fp + fn)}


def axis(geometry):
    start, end = np.asarray(geometry["start"], dtype=np.float64), np.asarray(geometry["end"], dtype=np.float64)
    direction = (end - start) / dist(start, end)
    return start, end, direction, np.array([-direction[1], direction[0]])


def footprint(geometry):
    if geometry["type"] == "surface":
        return polygon(geometry)
    start, end, _, normal = axis(geometry)
    width = geometry.get("thickness", geometry.get("width", .001))
    return Polygon([start - normal * width / 2, end - normal * width / 2,
                    end + normal * width / 2, start + normal * width / 2])


def vertical_interval(geometry):
    height = geometry.get("height", geometry.get("rise", geometry.get("thickness", .001)))
    if geometry["type"] == "stair":
        height = geometry["steps"] * geometry["rise"]
    return geometry["base"], geometry["base"] + height


def family(element):
    return "opening" if element["class"] in {"door", "window", "opening"} else element["class"]


def _excluded(element, exclusions):
    low, high = vertical_interval(element["geometry"])
    shape = footprint(element["geometry"])
    return any(low <= item["z_max"] and high >= item["z_min"]
               and shape.intersects(polygon(item)) for item in exclusions)


def _pair(truth, prediction, matching):
    if family(truth) != family(prediction):
        return None
    a, b = truth["geometry"], prediction["geometry"]
    if a["type"] != b["type"]:
        return None
    position = matching["position_m"]
    if a["type"] == "surface":
        pa, pb = footprint(a), footprint(b)
        plane_a, plane_b = a.get("plane", [0, 0, a["base"]]), b.get("plane", [0, 0, b["base"]])
        vertices = [*pa.exterior.coords, *pb.exterior.coords]
        height = max(abs((plane_a[0] - plane_b[0]) * x + (plane_a[1] - plane_b[1]) * y
                         + plane_a[2] - plane_b[2]) for x, y in vertices)
        if height > position:
            return None
    else:
        start, end, direction, normal = axis(a)
        c, d, direction_b, _ = axis(b)
        angle = degrees(acos(float(np.clip(abs(direction @ direction_b), 0, 1))))
        plane = max(abs(float((p - start) @ normal)) for p in (c, d))
        if angle > matching["angle_deg"] or plane > position:
            return None
        if a["type"] == "opening":
            # Compare opening rectangles in the independent truth wall frame.
            lo, hi = sorted([float((p - start) @ direction) for p in (c, d)])
            pa = box(0, a["base"], dist(start, end), a["base"] + a["height"])
            pb = box(lo, b["base"], hi, b["base"] + b["height"])
        else:
            if abs(a["base"] - b["base"]) > position:
                return None
            if a["type"] == "wall":
                # Wall matching uses its longitudinal/vertical profile, not a
                # thickness-dependent footprint IoU that hides an axis error.
                length = dist(start, end)
                pa = Polygon(a["profile_xz"]) if a.get("profile_xz") else box(0, 0, length, a["height"])
                profile = b.get("profile_xz") or [(0, 0), (dist(c, d), 0),
                                                   (dist(c, d), b["height"]), (0, b["height"])]
                pb = Polygon([(float((c + direction_b * x - start) @ direction),
                               z + b["base"] - a["base"]) for x, z in profile])
            else:
                pa, pb = footprint(a), footprint(b)
    union = pa.union(pb).area
    iou = pa.intersection(pb).area / union if union else 0.
    if iou < matching["minimum_iou"]:
        return None
    return {"iou": float(iou), "cost": 1 - float(iou)}


def match_instances(truth, predictions, matching):
    """Maximum-cardinality one-to-one assignment, then minimum geometry cost."""
    truth, predictions = sorted(truth, key=lambda e: e["id"]), sorted(predictions, key=lambda e: e["id"])
    if not truth or not predictions:
        return [], truth, predictions
    if len(truth) * len(predictions) > 4_000_000:
        raise ValueError("Annotation assignment exceeds the bounded evaluator matrix; partition the benchmark crop")
    # Invalid edges cost more than every valid edge combined. Stable IDs make
    # ties repeatable; point/element ordering cannot change assignment.
    penalty = len(truth) + len(predictions) + 1
    costs = np.full((len(truth), len(predictions)), float(penalty), dtype=np.float64)
    pairs = {}
    for i, a in enumerate(truth):
        for j, b in enumerate(predictions):
            pair = _pair(a, b, matching)
            if pair is not None:
                costs[i, j] = pair["cost"]
                pairs[i, j] = pair
    rows, columns = linear_sum_assignment(costs)
    matches, used_truth, used_predictions = [], set(), set()
    for i, j in zip(rows.tolist(), columns.tolist()):
        if (i, j) in pairs:
            matches.append((truth[i], predictions[j], pairs[i, j]))
            used_truth.add(i)
            used_predictions.add(j)
    return matches, [e for i, e in enumerate(truth) if i not in used_truth], [
        e for j, e in enumerate(predictions) if j not in used_predictions]


def semantic_metrics(truth, predictions):
    wanted = {record_key(s): s for s in truth.get("semantic_samples", [])}
    observed = {record_key(s): s for s in predictions.get("semantic_samples", [])}
    if not wanted:
        return {"status": "not_evaluated", "reason": "No independent semantic samples"}
    result = {}
    for name in CLASSES:
        if truth["class_states"][name] in {"uncertain", "out_of_scope"}:
            result[name] = {"status": "not_evaluated"}
            continue
        tp = fp = fn = boundary_tp = boundary_fp = boundary_fn = 0
        for key, sample in sorted(wanted.items()):
            predicted = observed.get(key, {})
            actual_label, predicted_label = sample["label"], predicted.get("label")
            tp += actual_label == name and predicted_label == name
            fp += actual_label != name and predicted_label == name
            fn += actual_label == name and predicted_label != name
            actual = sample.get("boundary", False) and actual_label == name
            proposed = predicted.get("boundary", False) and predicted_label == name
            boundary_tp += actual and proposed
            boundary_fp += not actual and proposed
            boundary_fn += actual and not proposed
        result[name] = {**scores(tp, fp, fn), "boundary": scores(boundary_tp, boundary_fp, boundary_fn)}
    return {"status": "evaluated", "sample_count": len(wanted),
            "missing_predictions": len(set(wanted) - set(observed)),
            "extra_predictions_outside_sample": len(set(observed) - set(wanted)), "classes": result,
            "scope": "Independent source-record samples only, not whole-cloud accuracy"}


def wall_metrics(a, b):
    start, end, direction, normal = axis(a)
    c, d, direction_b, _ = axis(b)
    length = dist(start, end)
    endpoints = min(max(dist(start, c), dist(end, d)), max(dist(start, d), dist(end, c)))
    lo, hi = sorted([float((p - start) @ direction) for p in (c, d)])
    result = {"endpoint_error_m": float(endpoints),
              "axis_offset_m": float(max(abs((p - start) @ normal) for p in (c, d))),
              "angle_error_deg": degrees(acos(float(np.clip(abs(direction @ direction_b), 0, 1)))),
              "thickness_error_m": abs(a["thickness"] - b["thickness"]),
              "height_error_m": abs(a["height"] - b["height"]),
              "base_error_m": abs(a["base"] - b["base"]),
              "unsupported_extension_m": max(0., -lo) + max(0., hi - length)}
    return result


def wall_coverage(reference, candidates, matching):
    result = []
    for element in sorted(reference, key=lambda e: e["id"]):
        a = element["geometry"]
        start, end, direction, normal = axis(a)
        length = dist(start, end)
        intervals, profiles = [], []
        reference_profile = Polygon(a["profile_xz"]) if a.get("profile_xz") else box(0, 0, length, a["height"])
        for candidate in candidates:
            b = candidate["geometry"]
            c, d, direction_b, _ = axis(b)
            if (abs(a["base"] - b["base"]) > matching["position_m"]
                    or degrees(acos(float(np.clip(abs(direction @ direction_b), 0, 1)))) > matching["angle_deg"]
                    or max(abs((p - start) @ normal) for p in (c, d)) > matching["position_m"]):
                continue
            lo, hi = sorted(float((p - start) @ direction) for p in (c, d))
            lo, hi = max(0., lo), min(length, hi)
            if hi > lo:
                intervals.append((lo, hi))
                profile = b.get("profile_xz") or [(0, 0), (dist(c, d), 0),
                                                  (dist(c, d), b["height"]), (0, b["height"])]
                profiles.append(Polygon([(float((c + direction_b * x - start) @ direction),
                                          z + b["base"] - a["base"]) for x, z in profile]))
        merged, total = [], sum(hi - lo for lo, hi in intervals)
        for lo, hi in sorted(intervals):
            if merged and lo <= merged[-1][1]:
                merged[-1][1] = max(hi, merged[-1][1])
            else:
                merged.append([lo, hi])
        cursor, missing = 0., []
        for lo, hi in merged:
            if lo > cursor:
                missing.append([cursor, lo])
            cursor = hi
        if cursor < length:
            missing.append([cursor, length])
        covered = sum(hi - lo for lo, hi in merged)
        result.append({"truth_id": element["id"], "coverage": covered / length,
                       "coverage_scope": "Longitudinal axis only; use profile_area_coverage for wall regions",
                       "profile_area_coverage": unary_union(profiles).intersection(reference_profile).area / reference_profile.area,
                       "missing_intervals_m": missing, "overlap_length_m": max(0., total - covered),
                       "largest_missing_region_m": max((hi - lo for lo, hi in missing), default=0.)})
    return result


def surface_metrics(a, b, tolerance):
    pa, pb = polygon(a), polygon(b)
    intersection, union = pa.intersection(pb).area, pa.union(pb).area
    precision = pb.boundary.intersection(pa.boundary.buffer(tolerance)).length / pb.boundary.length
    recall = pa.boundary.intersection(pb.boundary.buffer(tolerance)).length / pa.boundary.length
    plane_a, plane_b = a.get("plane", [0, 0, a["base"]]), b.get("plane", [0, 0, b["base"]])
    plane_error = max(abs((plane_a[0] - plane_b[0]) * x + (plane_a[1] - plane_b[1]) * y
                          + plane_a[2] - plane_b[2]) for x, y in [*pa.exterior.coords, *pb.exterior.coords])
    return {"area_iou": intersection / union, "symmetric_difference_m2": pa.symmetric_difference(pb).area,
            "boundary_distance_m": pa.boundary.hausdorff_distance(pb.boundary),
            "boundary_scope": "XY boundary distance; plane height evaluated separately",
            "plane_height_error_m": plane_error,
            "boundary_precision": precision, "boundary_recall": recall,
            "boundary_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.,
            "base_error_m": abs(a["base"] - b["base"]),
            "thickness_error_m": abs(a["thickness"] - b["thickness"]) if "thickness" in a and "thickness" in b else None}


def observed_face_metrics(reference, predictions, matching):
    """Independent visible face-area coverage, distinct from inferred axes."""
    results = []
    candidates = [face for element in predictions for face in element.get("observed_faces", [])]
    for element in reference:
        for index, face in enumerate(element.get("observed_faces", [])):
            start, end = np.asarray(face["start"], dtype=np.float64), np.asarray(face["end"], dtype=np.float64)
            length = dist(start, end)
            direction = (end - start) / length
            normal = np.array([-direction[1], direction[0]])
            truth_shape = box(0, face["z_min"], length, face["z_max"])
            pieces, residuals = [], []
            for other in candidates:
                a, b = np.asarray(other["start"], dtype=np.float64), np.asarray(other["end"], dtype=np.float64)
                other_direction = (b - a) / dist(a, b)
                angle = degrees(acos(float(np.clip(abs(direction @ other_direction), 0, 1))))
                residual = max(abs((p - start) @ normal) for p in (a, b))
                if angle > matching["angle_deg"] or residual > matching["position_m"]:
                    continue
                lo, hi = sorted(float((p - start) @ direction) for p in (a, b))
                piece = box(lo, other["z_min"], hi, other["z_max"]).intersection(truth_shape)
                if piece.area > 0:
                    pieces.append(piece)
                    residuals.append(float(residual))
            coverage = unary_union(pieces).area / truth_shape.area
            results.append({"truth_id": element["id"], "face_index": index, "area_coverage": coverage,
                            "maximum_matched_plane_error_m": max(residuals) if residuals else None})
    return {"status": "evaluated" if results else "not_evaluated", "faces": results,
            "scope": "Independently annotated visible rectangles, not all original points or unseen structure"}


def evaluate_geometry(truth, predictions, matching=None):
    matching = {**MATCHING, **(matching or {})}
    states, exclusions = truth["class_states"], truth.get("exclusions", [])
    reference = sorted((e for e in truth["elements"] if not _excluded(e, exclusions)), key=lambda e: e["id"])
    predicted = sorted((e for e in predictions["elements"] if states[e["class"]] not in {"uncertain", "out_of_scope"}
                        and not _excluded(e, exclusions)), key=lambda e: e["id"])
    predicted_by_id = {e["id"]: e for e in predictions["elements"]}

    def contained(element):
        host = predicted_by_id.get(element.get("host_id"))
        if host is None or host["class"] != "wall":
            return None
        a, b = host["geometry"], element["geometry"]
        start, end, direction, normal = axis(a)
        c, d, _, _ = axis(b)
        if max(abs((p - start) @ normal) for p in (c, d)) > a["thickness"] / 2 + 1e-8:
            return False
        lo, hi = sorted(float((p - start) @ direction) for p in (c, d))
        profile = Polygon(a["profile_xz"]) if a.get("profile_xz") else box(0, 0, dist(start, end), a["height"])
        return bool(profile.buffer(1e-8).covers(box(lo, b["base"] - a["base"], hi,
                                                  b["base"] + b["height"] - a["base"])))
    matches, missed, extra = match_instances(reference, predicted, matching)
    host_map = {a["id"]: b["id"] for a, b, _ in matches}
    instances = {}
    for name in CLASSES:
        if states[name] in {"uncertain", "out_of_scope"}:
            instances[name] = {"status": "not_evaluated", "truth_state": states[name]}
            continue
        tp = sum(a["class"] == b["class"] == name for a, b, _ in matches)
        count_truth = sum(e["class"] == name for e in reference)
        count_prediction = sum(e["class"] == name for e in predicted)
        instances[name] = {"status": "evaluated", "truth_state": states[name],
                           "truth_count": count_truth, "prediction_count": count_prediction,
                           **scores(tp, count_prediction - tp, count_truth - tp)}
    metrics = []
    for a, b, pair in matches:
        row = {"truth_id": a["id"], "prediction_id": b["id"], "class": a["class"],
               "predicted_class": b["class"], "class_correct": a["class"] == b["class"], "match_iou": pair["iou"]}
        ga, gb = a["geometry"], b["geometry"]
        if ga["type"] == "wall":
            row.update(wall_metrics(ga, gb))
        elif ga["type"] == "opening":
            row.update(width_error_m=abs(dist(ga["start"], ga["end"]) - dist(gb["start"], gb["end"])),
                       height_error_m=abs(ga["height"] - gb["height"]),
                       sill_error_m=abs(ga["base"] - gb["base"]),
                       host_correct=bool(a.get("host_id") and host_map.get(a["host_id"]) == b.get("host_id")),
                       void_only=a.get("void_only", False),
                       containment_valid=contained(b))
        elif ga["type"] == "surface":
            row.update(surface_metrics(ga, gb, matching["boundary_m"]))
            row["coverage_areas_m2"] = b.get("coverage_areas_m2")
        elif ga["type"] in {"stair", "ramp"}:
            row.update(width_error_m=abs(ga["width"] - gb["width"]),
                       rise_error_m=abs(ga["rise"] - gb["rise"]))
            if ga["type"] == "stair":
                row.update(step_count_error=abs(ga["steps"] - gb["steps"]),
                           going_error_m=abs(ga["going"] - gb["going"]),
                           observed_tread_count=len(b.get("observed_treads", [])),
                           inferred_tread_count=len(b.get("inferred_treads", [])))
            row["endpoint_associations"] = {label: (
                host_map.get(a.get("connections", {}).get(label)) == b.get("connections", {}).get(label)
                if a.get("connections", {}).get(label) else None) for label in ("lower", "upper")}
        if a["class"] == "landing":
            expected = sorted(host_map.get(i, "unmatched:" + i) for i in a.get("connected_ids", []))
            row["connections_correct"] = expected == sorted(b.get("connected_ids", []))
        metrics.append(row)
    duplicates = []
    for i, a in enumerate(predicted):
        for b in predicted[i + 1:]:
            pair = _pair(a, b, matching)
            if pair and pair["iou"] >= matching["duplicate_iou"] and a["class"] == b["class"]:
                duplicates.append([a["id"], b["id"]])
    parents = {e["id"]: e["id"] for e in predicted}

    def find(identifier):
        while parents[identifier] != identifier:
            identifier = parents[identifier]
        return identifier

    for a, b in duplicates:
        parents[find(b)] = find(a)
    groups = {}
    for element in predicted:
        groups.setdefault(find(element["id"]), []).append(element)
    duplicate_count = sum(len(group) - 1 for group in groups.values())
    duplicate_openings = sum(len(group) - 1 for group in groups.values() if family(group[0]) == "opening")
    containment = [e for e in predicted if family(e) == "opening" and contained(e) is False]
    unknown_containment = [e["id"] for e in predicted if family(e) == "opening" and contained(e) is None]
    cuts = predictions.get("cuts", [])
    unsafe_cuts = []
    unevaluated_cuts = []
    truth_by_id = {e["id"]: e for e in reference}
    reverse_hosts = {b: a for a, b in host_map.items()}
    for cut in cuts:
        if not cut.get("applied"):
            continue
        host = truth_by_id.get(reverse_hosts.get(cut.get("host_id")))
        if host is None:
            unevaluated_cuts.append(cut["id"])
            continue
        allowed = unary_union([Polygon(r) for r in host["geometry"].get("holes", [])])
        if Polygon(cut["footprint"]).difference(allowed.buffer(1e-8)).area > 1e-8:
            unsafe_cuts.append(cut["id"])
    return {"instances": instances, "matches": metrics,
            "observed_faces": observed_face_metrics([e for e in reference if e["class"] == "wall"],
                                                     [e for e in predicted if e["class"] == "wall"], matching),
            "missed_truth_ids": sorted(e["id"] for e in missed),
            "extra_prediction_ids": sorted(e["id"] for e in extra),
            "duplicate_pairs": sorted(duplicates), "duplicate_elements": duplicate_count,
            "duplicate_rate": _ratio(duplicate_count, len(predicted)),
            "walls": wall_coverage([e for e in reference if e["class"] == "wall"],
                                   [e for e in predicted if e["class"] == "wall"], matching),
            "safety": {"duplicate_openings": duplicate_openings,
                       "openings_outside_hosts": len(containment) if not unknown_containment else None,
                       "unevaluated_opening_ids": sorted(unknown_containment),
                       "unsafe_surface_cuts": len(unsafe_cuts) if not unevaluated_cuts else None,
                       "unsafe_cut_ids": sorted(unsafe_cuts), "unevaluated_cut_ids": sorted(unevaluated_cuts)},
            "not_evaluated_prediction_ids": sorted(e["id"] for e in predictions["elements"] if e not in predicted),
            "excluded_truth_ids": sorted(e["id"] for e in truth["elements"] if e not in reference),
            "matching": matching}
