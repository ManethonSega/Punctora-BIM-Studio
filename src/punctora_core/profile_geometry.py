"""Bounded removal of numerical contour defects, never source-point edits."""
from math import isfinite
from shapely import make_valid, set_precision
from shapely.geometry import Polygon
from shapely.ops import unary_union


def clean_profile(vertices, tolerance_m=1e-9):
    """Return one valid exterior, rejecting meaningful topology/area changes.

    Callers supporting several bodies must use clean_profiles explicitly.
    """
    profiles, report = clean_profiles(vertices, tolerance_m)
    if len(profiles) != 1:
        raise ValueError("Profile repair would change components or introduce holes")
    return profiles[0], report


def clean_profiles(vertices, tolerance_m=1e-9):
    """Return every bounded numerical component of an exterior contour.

    STEP serialization rounds doubles. A nanometre contour grid keeps adjacent
    edges distinct through that round trip and collapses zero-width backtracks.
    A valid outline can split at a sub-grid neck. Preserve all resulting bodies
    explicitly; never pass a kernel-unstable neck or only the largest remnant.
    Canonical f64 source coordinates and evidence selectors are untouched.
    """
    if (len(vertices) < 3 or any(len(p) != 2 or not all(isfinite(x) for x in p)
                                 for p in vertices)):
        raise ValueError("Profile requires finite 2D vertices")
    original = Polygon(vertices)
    if original.area <= 0:
        raise ValueError("Profile has zero area")
    repaired = make_valid(original)
    rounded = set_precision(repaired, tolerance_m)
    pieces = ([rounded] if isinstance(rounded, Polygon) else
              [p for p in getattr(rounded, "geoms", ()) if isinstance(p, Polygon)])
    if not pieces or any(p.interiors for p in pieces) or (len(pieces)>1 and not original.is_valid):
        raise ValueError("Profile repair would change components or introduce holes")
    cleaned = [p.simplify(tolerance_m, preserve_topology=True) for p in pieces]
    if any(not isinstance(p, Polygon) or p.is_empty or not p.is_valid or p.interiors for p in cleaned):
        raise ValueError("Profile cannot be repaired without a topology change")
    cleaned.sort(key=lambda p:(-p.area,p.bounds))
    combined = unary_union(cleaned)
    budget = max(1e-8, original.length*tolerance_m*4)
    area_change = abs(combined.area-original.area)
    if (area_change > budget or
            repaired.symmetric_difference(combined).area > budget):
        raise ValueError("Profile repair would change meaningful geometry")
    result = [[(float(x), float(y)) for x,y in p.exterior.coords[:-1]] for p in cleaned]
    # Check the representation actually passed to the IFC writer, not only GEOS.
    serialized = [Polygon([(float(format(x, '.15g')), float(format(y, '.15g')))
                           for x,y in ring]) for ring in result]
    if any(not p.is_valid or p.area <= 0 for p in serialized):
        raise ValueError("Profile is invalid after STEP numeric serialization")
    return result, {"input_valid": bool(original.is_valid),
                    "contour_precision_m": tolerance_m,
                    "strategy": "bounded_component_split" if len(result)>1 else "nanometre_grid",
                    "output_components": len(result),
                    "area_change_m2": area_change,
                    "input_vertices": len(vertices), "output_vertices": sum(map(len,result)),
                    "scope": "bounded numerical profile repair; original points unchanged"}
