"""Deterministic proposals with separate geometry, class and filling evidence."""
from copy import deepcopy
import numpy as np
from shapely.geometry import box

from ..annotation_io import content_digest
from .contracts import TAXONOMY


def canonical_source_rows(rows, cloud):
    rows = np.unique(np.asarray(rows, dtype=np.uint64))
    return rows[np.lexsort((cloud.source_record_index[rows], cloud.scan_index[rows]))]


def projected_semantic_regions(projection, labels, scores, classical_regions=(), minimum_points=6, maximum_regions=512, check=lambda: None):
    """Recover closed flush fillings which cannot appear as occupancy voids.

    Existing bounded voids already consume point-label evidence and retain
    their individual bays. A semantic blob mostly covered by those masks is
    not added as a broad duplicate envelope spanning the same repeated bays.
    """
    import cv2
    covered = np.zeros(projection.frame.shape, dtype=bool)
    for region in classical_regions:
        if region["class"] == "opening": covered |= region["mask"]
    result = []
    point_labels = labels[projection.source_rows]
    for kind in ("door", "window"):
        check()
        selected = point_labels == TAXONOMY.index(kind)
        if int(selected.sum()) < minimum_points: continue
        occupancy = np.zeros(projection.frame.shape, dtype=np.uint8)
        occupancy.ravel()[projection.pixel_ids[selected]] = 1
        count, components, stats, _ = cv2.connectedComponentsWithStats(occupancy, 8)
        for component in range(1, count):
            check()
            x, z, width, height, area = map(int, stats[component])
            mask = components == component
            if int((mask & covered).sum()) >= .5 * int(mask.sum()): continue
            support = selected & mask.ravel()[projection.pixel_ids]
            if int(support.sum()) < minimum_points or width * projection.frame.cell_m < .2 or height * projection.frame.cell_m < .4: continue
            result.append({"class": kind, "box": [x, z, x + width, z + height], "mask": mask,
                           "native_score": float(scores[projection.source_rows[support]].max()), "score_kind": "upstream_native_score",
                           "evidence": {"method": "projected_semantic_component", "classification": "suggested",
                                        "source_points": int(support.sum()), "filling": "unknown", "host_validation": "pending_run4"}})
            if len(result) > maximum_regions: raise ValueError("Projected semantic regions exceed the explicit limit")
    return result


def region_evidence(projection, region, cloud, labels, scores, face_band_m=.025, minimum_class_points=6):
    mask = region["mask"]
    interior = canonical_source_rows(projection.rows_for_mask(mask), cloud)
    x0, z0, x1, z1 = region["box"]
    border = np.zeros(mask.shape, dtype=bool)
    border[max(0, z0 - 2):min(mask.shape[0], z1 + 2), max(0, x0 - 2):min(mask.shape[1], x1 + 2)] = True
    border[z0:z1, x0:x1] = False
    frame_rows = canonical_source_rows(projection.rows_for_mask(border, near_face=True, face_band_m=face_band_m), cloud)
    samples = labels[interior]
    known = samples >= 0
    counts = {TAXONOMY[i]: int((samples == i).sum()) for i in np.unique(samples[known])}
    filling = sum(counts.get(c, 0) for c in ("door", "window"))
    claims = []
    for kind in ("door", "window"):
        if counts.get(kind, 0) >= minimum_class_points and counts[kind] / max(1, int(known.sum())) >= .6:
            claims.append({"class": kind, "basis": "original_point_semantic_labels", "count": counts[kind],
                           "native_score": float(scores[interior[samples == TAXONOMY.index(kind)]].max()),
                           "score_kind": "upstream_native_score"})
    # A 2D class can be a suggested hypothesis only when the region also
    # back-projects actual filling points. Empty voids keep class unknown.
    if (region["class"] in {"door", "window", "glazing"} and len(interior) >= minimum_class_points
            and region.get("evidence", {}).get("method") != "projected_semantic_component"):
        claims.append({"class": "window" if region["class"] == "glazing" else region["class"],
                       "basis": "2d_detector_with_original_returns", "native_score": region.get("native_score"),
                       "score_kind": region["score_kind"]})
    return {"interior_rows": interior, "frame_rows": frame_rows, "support_rows": canonical_source_rows(np.r_[interior, frame_rows], cloud),
            "class_claims": claims, "semantic_counts": counts, "unknown_points": int((~known).sum()),
            "unsupported_semantic_classes": {k: v for k, v in counts.items() if k not in {"wall", "opening", "door", "window", "column"}},
            "void_only": len(interior) == 0, "filling": "unknown", "filling_semantic_points": filling}


def fuse_opening_candidates(candidates, walls, source_sha256, duplicate_iou=.7, boundary_tolerance_m=.15):
    """Complete-link groups preserve repeated bays and class disagreements.

    Native score scales never rank geometry or get averaged. A projected
    frame/void defines its measured raster envelope; alternative masks/boxes
    and providers remain attached as separate hypotheses. Final host/shape
    validity is deliberately pending Run 4.
    """
    groups = []
    ordered = sorted(candidates, key=lambda c: (c["host_id"], c["bounds"], c["id"]))
    def duplicate(a, b):
        if a["host_id"] != b["host_id"]:
            return False
        pa, pb = box(*a["bounds"]), box(*b["bounds"])
        return (pa.intersection(pb).area / pa.union(pb).area >= duplicate_iou
                and np.max(np.abs(np.array(a["bounds"]) - b["bounds"])) <= boundary_tolerance_m)
    for candidate in ordered:
        group = next((g for g in groups if all(duplicate(candidate, other) for other in g)), None)
        if group is None: groups.append([candidate])
        else: group.append(candidate)
    result = []
    for group in groups:
        # Frame-supported envelope outranks an arbitrary detector box, not
        # because its score is larger but because it has explicit geometry.
        chosen = min(group, key=lambda c: (c["kind"] != "projected_observed_face_void", c["bounds"], c["id"]))
        low, bottom, high, top = chosen["bounds"]
        frame = chosen["frame"]
        wall = walls[chosen["host_id"]]
        claims = [claim for c in group for claim in c["class_claims"]]
        kinds = {c["class"] for c in claims}
        kind = next(iter(kinds)) if len(kinds) == 1 else "opening"
        axis = np.asarray(frame.along_xy)
        start, end = np.asarray(frame.origin_xy) + axis * low, np.asarray(frame.origin_xy) + axis * high
        geometry = {"type": "opening", "start": start.tolist(), "end": end.tolist(), "base": frame.base_m + bottom, "height": top - bottom}
        identifier = "hybrid:opening:" + content_digest({"source": source_sha256, "host": chosen["host_id"], "geometry": geometry})[:24]
        corners = np.array([[*start, geometry["base"]], [*end, geometry["base"] + geometry["height"]]])
        result.append({"id": identifier, "class": kind, "status": "proposed", "geometry": geometry,
                       "bounds_m": [corners.min(axis=0).tolist(), corners.max(axis=0).tolist()],
                       "host_id": chosen["host_id"], "wall_local_bounds_m": [low, bottom, high, top],
                       "host_validation_state": "pending_run4", "cut_applied": False,
                       "classification_state": "conflicting" if len(kinds) > 1 else "suggested" if kinds else "unknown",
                       "support_state": "unknown" if any(c.get("support_count", 0) for c in group) else "unsupported",
                       "filling": "unknown", "void_only": all(c["void_only"] for c in group),
                       "provenance": {"dimensions": "raster_quantized_proposal", "kind": "inferred" if kinds else "unknown", "host": "proposed", "filling": "unknown"},
                       "support_reference": "ProposalSet source arrays, independently revalidate before acceptance",
                       "native_score": None, "native_score_kind": "separate_evidence_scores_no_combined_probability",
                       "evidence_ids": sorted(c["id"] for c in group), "class_claims": claims,
                       "candidate_count": len(group), "scope": "bounded occupancy/semantic hypothesis, no accepted IFC cut"})
    return sorted(result, key=lambda i: i["id"])


def column_instance(rows, cloud, source_sha256, evidence_id, context_wall_id=None):
    """Observed bounding component only, no inferred column completion."""
    rows = canonical_source_rows(rows, cloud)
    points = cloud.points[rows]
    minimum, maximum = points.min(axis=0), points.max(axis=0)
    if maximum[2] - minimum[2] < .4:
        return None
    anchor = points[:, :2].mean(axis=0)
    values = points[:, :2] - anchor
    eigen, vectors = np.linalg.eigh(values.T @ values / len(points))
    direction = vectors[:, 1]
    if direction[np.abs(direction).argmax()] < 0: direction *= -1
    normal = np.array([-direction[1], direction[0]])
    along, across = values @ direction, values @ normal
    start = anchor + direction * along.min() + normal * (across.min() + across.max()) / 2
    end = anchor + direction * along.max() + normal * (across.min() + across.max()) / 2
    width = float(across.max() - across.min())
    geometry = None if np.linalg.norm(end - start) < 1e-8 or width < 1e-8 else {
        "type": "column", "start": start.tolist(), "end": end.tolist(), "base": float(minimum[2]),
        "height": float(maximum[2] - minimum[2]), "width": width}
    keys = np.empty(len(rows), dtype=[("scan", "<u8"), ("record", "<u8")])
    keys["scan"], keys["record"] = cloud.scan_index[rows], cloud.source_record_index[rows]
    import hashlib
    stable = hashlib.sha256(keys.tobytes()).hexdigest()
    identifier = "hybrid:column:" + content_digest({"source": source_sha256, "source_keys": stable})[:24]
    item = {"id": identifier, "class": "column", "status": "proposed", "geometry": geometry,
            "geometry_state": "observed_component_envelope" if geometry else "insufficient_for_parametric_geometry",
            "bounds_m": [minimum.tolist(), maximum.tolist()], "evidence_ids": [evidence_id],
            "structural_role": "unknown", "completion": "none", "classification_state": "suggested",
            "provenance": {"bounds": "measured", "class": "inferred", "structural_role": "unknown"},
            "native_score": None, "native_score_kind": "separate_evidence_scores_no_combined_probability",
            "support_reference": "ProposalSet source arrays, independently revalidate before acceptance", "cut_applied": False}
    if context_wall_id: item["context_wall_id"] = context_wall_id
    return item
