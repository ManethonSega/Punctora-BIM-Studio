"""Bounded removal of numerical contour defects, never source-point edits."""
from math import isfinite
from hashlib import sha256
import shapely
from shapely import make_valid, set_precision
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union, split
from shapely.validation import explain_validity
from shapely.errors import GEOSException


class ProfileGeometryError(ValueError):
    """A bounded, replayable contour diagnostic, without source-point copies."""
    def __init__(self,message,reason,vertices,tolerance_m):
        super().__init__(message)
        original = Polygon(vertices)
        wkb = original.wkb
        self.diagnostics = {'reason':reason,'input_vertices':len(vertices),
            'input_valid':bool(original.is_valid),'validity_reason':explain_validity(original),
            'input_area_m2':original.area if isfinite(original.area) else None,
            'contour_precision_m':tolerance_m,'input_geometry_sha256':sha256(wkb).hexdigest(),
            'shapely_version':shapely.__version__,'geos_version':shapely.geos_version_string,
            'capture':'complete' if len(vertices)<=8192 else 'omitted_above_8192_vertices'}
        if len(vertices)<=8192:
            self.diagnostics['original_wkb_hex'] = wkb.hex().upper()


def _polygon_parts(geometry):
    pending, result = [geometry], []
    while pending:
        item = pending.pop()
        if isinstance(item,Polygon):
            result.append(item)
        else:
            pending.extend(getattr(item,'geoms',()))
    return result


def _hole_free_parts(pieces):
    """Partition existing voids into exterior bays, without filling or cutting area."""
    pending, result = list(pieces), []
    while pending:
        piece = pending.pop()
        if not piece.interiors:
            result.append(piece)
            continue
        hole = min((Polygon(r) for r in piece.interiors),key=lambda p:(p.bounds,p.area))
        anchor = hole.representative_point()
        left,bottom,right,top = piece.bounds
        margin = max(right-left,top-bottom,1.)
        lines = (LineString([(left-margin,anchor.y),(right+margin,anchor.y)]),
                 LineString([(anchor.x,bottom-margin),(anchor.x,top+margin)]))
        for line in lines:
            children = [p for p in split(piece,line).geoms if isinstance(p,Polygon) and not p.is_empty]
            if len(children)>1 and sum(len(p.interiors) for p in children)<len(piece.interiors):
                pending.extend(children)
                break
        else:
            raise ValueError('Profile void could not be partitioned without a topology change')
    return result


def clean_profile(vertices, tolerance_m=1e-9):
    """Return one valid exterior, rejecting meaningful topology/area changes.

    Callers supporting several bodies must use clean_profiles explicitly.
    """
    profiles, report = clean_profiles(vertices, tolerance_m)
    if len(profiles) != 1:
        raise ProfileGeometryError("Profile repair would change components or introduce holes",
                                   'single_profile_components',vertices,tolerance_m)
    return profiles[0], report


def clean_profiles(vertices, tolerance_m=1e-9):
    """Return every bounded numerical component of an exterior contour.

    STEP serialization rounds doubles. A nanometre contour grid keeps adjacent
    edges distinct through that round trip and collapses zero-width backtracks.
    Touching rings and sub-grid necks can change the number of rings or bodies.
    Preserve the occupied set within the same physical error budget, representing
    every body and existing void with explicit hole-free pieces.
    Canonical f64 source coordinates and evidence selectors are untouched.
    """
    if (len(vertices) < 3 or any(len(p) != 2 or not all(isfinite(x) for x in p)
                                 for p in vertices)):
        raise ValueError("Profile requires finite 2D vertices")
    original = Polygon(vertices)
    def reject(message,reason):
        raise ProfileGeometryError(message,reason,vertices,tolerance_m)
    if original.area <= 0:
        reject("Profile has zero area",'zero_area')
    try:
        repaired = make_valid(original)
        rounded = set_precision(repaired, tolerance_m)
        pieces = _polygon_parts(rounded)
        if not pieces or any(p.is_empty for p in pieces):
            reject("Profile collapsed to empty geometry",'empty_after_precision')
        hole_count = sum(len(p.interiors) for p in pieces)
        try:
            parts = _hole_free_parts(pieces)
        except (ValueError,GEOSException) as exc:
            reject(str(exc),'void_partition')
        cleaned = [p.simplify(tolerance_m, preserve_topology=True) for p in parts]
        if any(not isinstance(p, Polygon) or p.is_empty or not p.is_valid or p.interiors for p in cleaned):
            reject("Profile cannot be repaired without a topology change",'invalid_cleaned_profile')
        cleaned.sort(key=lambda p:(-p.area,p.bounds))
        combined = unary_union(cleaned)
        budget = max(1e-8, original.length*tolerance_m*4)
        area_change = abs(combined.area-original.area)
        difference = repaired.symmetric_difference(combined).area
        overlap = max(0.,sum(p.area for p in cleaned)-combined.area)
        if area_change > budget or difference > budget or overlap > budget:
            reject("Profile repair would change meaningful geometry",'meaningful_geometry_change')
        result = [[(float(x), float(y)) for x,y in p.exterior.coords[:-1]] for p in cleaned]
        # Check the representation actually passed to the IFC writer, not only GEOS.
        serialized = [Polygon([(float(format(x, '.15g')), float(format(y, '.15g')))
                               for x,y in ring]) for ring in result]
        if any(not p.is_valid or p.area <= 0 for p in serialized):
            reject("Profile is invalid after STEP numeric serialization",'step_serialization')
        return result, {"input_valid": bool(original.is_valid),
                        "contour_precision_m": tolerance_m,
                        "strategy": "bounded_void_partition" if hole_count else "bounded_component_split" if len(result)>1 else "nanometre_grid",
                        "output_components": len(result),
                        "partitioned_voids":hole_count,"area_budget_m2":budget,
                        "symmetric_difference_m2":difference,"component_overlap_m2":overlap,
                        "area_change_m2": area_change,
                        "input_vertices": len(vertices), "output_vertices": sum(map(len,result)),
                        "scope": "bounded numerical profile repair; original points unchanged"}
    except GEOSException as exc:
        reject(str(exc),'geos_processing')
