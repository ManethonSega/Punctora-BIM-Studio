"""Bounded removal of numerical contour defects, never source-point edits."""
from math import isfinite
from shapely import make_valid, set_precision
from shapely.geometry import Polygon


def clean_profile(vertices, tolerance_m=1e-9):
    """Return one valid exterior, rejecting meaningful topology/area changes.

    STEP serialization rounds doubles. A nanometre contour grid keeps adjacent
    edges distinct through that round trip and collapses zero-width backtracks.
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
    if len(pieces) != 1 or pieces[0].interiors:
        raise ValueError("Profile repair would change components or introduce holes")
    cleaned = pieces[0].simplify(tolerance_m, preserve_topology=True)
    if not isinstance(cleaned, Polygon) or cleaned.is_empty or cleaned.interiors:
        raise ValueError("Profile cannot be repaired without a topology change")
    budget = max(1e-8, original.length*tolerance_m*4)
    area_change = abs(cleaned.area-original.area)
    if (area_change > budget or
            repaired.symmetric_difference(cleaned).area > budget):
        raise ValueError("Profile repair would change meaningful geometry")
    result = [(float(x), float(y)) for x,y in cleaned.exterior.coords[:-1]]
    # Check the representation actually passed to the IFC writer, not only GEOS.
    serialized = Polygon([(float(format(x, '.15g')), float(format(y, '.15g')))
                          for x,y in result])
    if not serialized.is_valid or serialized.area <= 0:
        raise ValueError("Profile is invalid after STEP numeric serialization")
    return result, {"input_valid": bool(original.is_valid),
                    "contour_precision_m": tolerance_m,
                    "area_change_m2": area_change,
                    "input_vertices": len(vertices), "output_vertices": len(result),
                    "scope": "bounded numerical profile repair; original points unchanged"}
