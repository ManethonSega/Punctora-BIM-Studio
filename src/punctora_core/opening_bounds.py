"""Bound automatic opening proposals without weakening saved-model validation."""
from copy import deepcopy
from dataclasses import asdict
from math import dist, isfinite

NUMERICAL_TOLERANCE_M = 1e-6


def boundary_excess(opening, host):
    length = dist(host.start, host.end)
    return {"left": max(0., -opening.offset),
            "right": max(0., opening.offset+opening.width-length),
            "below": max(0., -opening.sill),
            "above": max(0., opening.sill+opening.height-host.height)}


def proposal_record(opening, host, reason, action="review_only"):
    record = {"action": action, "reason": reason, "opening": asdict(opening),
              "host_wall_id": opening.host_wall_id}
    if host is not None:
        length = dist(host.start, host.end)
        direction = [(b-a)/length for a, b in zip(host.start, host.end)]
        start = [a+d*opening.offset for a, d in zip(host.start, direction)]
        end = [a+d*opening.width for a, d in zip(start, direction)]
        record.update(host_geometry={"start": list(host.start), "end": list(host.end),
            "base": host.base, "height": host.height, "thickness": host.thickness,
            "storey_id": host.storey_id, "observed_faces": deepcopy(host.observed_faces)},
            world_bounds={"start_xy": start, "end_xy": end,
                "bottom_z_m": host.base+opening.sill,
                "top_z_m": host.base+opening.sill+opening.height},
            excess_m=boundary_excess(opening, host))
    return record


def fit_generated_opening(opening, host):
    """Return a valid proposal or retain the unchanged conflict for review.

    Only sub-micrometre arithmetic overhang is repaired. Larger inconsistencies
    never shrink measured dimensions or enlarge an unsupported host.
    """
    if not all(isfinite(v) for v in (opening.offset, opening.sill, opening.width, opening.height)):
        raise ValueError(f"Nonfinite generated opening: {opening.id} on {opening.host_wall_id}")
    if host is None:
        return None, proposal_record(opening, host, "final_host_missing")
    if opening.width <= NUMERICAL_TOLERANCE_M or opening.height <= NUMERICAL_TOLERANCE_M:
        return None, proposal_record(opening, host, "collapsed_opening")
    excess = boundary_excess(opening, host)
    if max(excess.values()) > NUMERICAL_TOLERANCE_M:
        return None, proposal_record(opening, host, "opening_outside_final_host")
    if not any(excess.values()):
        return opening, None
    bounded = deepcopy(opening)
    left, right = max(0., opening.offset), min(dist(host.start, host.end), opening.offset+opening.width)
    bottom, top = max(0., opening.sill), min(host.height, opening.sill+opening.height)
    bounded.offset, bounded.width = left, right-left
    bounded.sill, bounded.height = bottom, top-bottom
    if min(bounded.width, bounded.height) <= NUMERICAL_TOLERANCE_M:
        return None, proposal_record(opening, host, "collapsed_after_numerical_clamp")
    report = proposal_record(opening, host, "arithmetic_overhang", "numerical_clamp")
    bounded.evidence["host_boundary_clamp"] = {"excess_m": excess,
        "tolerance_m": NUMERICAL_TOLERANCE_M, "original_dimensions_m":
        [opening.offset, opening.sill, opening.width, opening.height]}
    return bounded, report


def validate_generated_openings(openings, walls):
    """Separate unsafe automatic proposals; manual edits remain strict."""
    hosts = {wall.id: wall for wall in walls}
    accepted, reports = [], []
    for opening in openings:
        host = hosts.get(opening.host_wall_id)
        bounded, report = fit_generated_opening(opening, host)
        if report is not None:
            reports.append(report)
            if report["action"] == "review_only" and host is not None:
                host.evidence.setdefault("opening_review_candidates", []).append(deepcopy(report))
        if bounded is not None:
            accepted.append(bounded)
    return accepted, reports
