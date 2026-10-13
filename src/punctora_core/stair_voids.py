"""Review-only slab gaps and independently validated stair clearance cuts."""
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from .model import slab_opening_footprint, slab_opening_is_validated


def reconcile_stair_voids(slabs, observed, candidates, flights, landings, headroom_m=2.0,
                          exported_solids=None):
    """Keep observations intact; only validated geometry contributes to clearance.

    Overlapping IFC voids are legal and their union is the actual removed area.
    Keeping separate objects preserves each observation and causal boundary.
    No blanket stair bounding rectangle is used to enlarge an observed hole.
    """
    result = list(observed)
    report = []
    for opening in candidates:
        polygon = Polygon(slab_opening_footprint(opening))
        previous = [o for o in observed if o.host_slab_id == opening.host_slab_id
                    and slab_opening_is_validated(o, flights, landings)]
        observed_shape = unary_union([Polygon(slab_opening_footprint(o)) for o in previous])
        overlap = polygon.intersection(observed_shape).area
        opening.evidence.update({
            'observed_hole_ids': [o.id for o in previous
                if polygon.intersects(Polygon(slab_opening_footprint(o)))],
            'observed_overlap_m2': float(overlap),
            'additional_cut_area_m2': float(polygon.difference(observed_shape).area),
            'boundary_justification': {'flights': opening.evidence['source_stair_ids'],
                                       'landings': opening.evidence['source_landing_ids']}})
        for hole in observed:
            if (hole.host_slab_id == opening.host_slab_id
                    and polygon.intersects(Polygon(slab_opening_footprint(hole)))):
                hole.evidence['stair_validation'] = 'supported_by_stair_envelope'
                systems = hole.evidence.setdefault('supporting_system_ids', [])
                if opening.source_system_id not in systems:
                    systems.append(opening.source_system_id)
        result.append(opening)
    for hole in observed:
        hole.evidence.setdefault('stair_validation', 'pending_manual_review')
    # Independent tread-by-tread collision check against the final cut union.
    # Check physical treads and headroom separately; report both residuals.
    for slab in slabs:
        host = Polygon(slab.footprint)
        holes = unary_union([Polygon(slab_opening_footprint(o)) for o in result
                             if o.host_slab_id == slab.id and slab_opening_is_validated(o, flights, landings)])
        solid = (exported_solids[slab.id] if exported_solids is not None
                 else host.difference(holes))
        physical, clearance = [], []
        for flight in flights:
            dx = (flight.end[0]-flight.start[0])/flight.steps
            dy = (flight.end[1]-flight.start[1])/flight.steps
            for step in range(flight.steps):
                top = flight.base+(step+1)*flight.rise
                a = (flight.start[0]+dx*step, flight.start[1]+dy*step)
                b = (a[0]+dx, a[1]+dy)
                tread = LineString([a,b]).buffer(flight.width/2, cap_style=2)
                if top > slab.base+1e-8 and top-flight.tread_thickness < slab.base+slab.thickness-1e-8:
                    physical.append(tread.intersection(solid))
                if (top+headroom_m > slab.base+1e-8
                        and top-flight.tread_thickness < slab.base+slab.thickness-1e-8):
                    clearance.append(tread.intersection(solid))
        for landing in landings:
            if landing.evidence.get('source_floor_id') == slab.id:
                continue
            if (landing.base < slab.base+slab.thickness-1e-8
                    and landing.base+landing.thickness > slab.base+1e-8):
                physical.append(Polygon(landing.footprint).intersection(solid))
            if (landing.base+landing.thickness+headroom_m > slab.base+1e-8
                    and landing.base < slab.base+slab.thickness-1e-8):
                clearance.append(Polygon(landing.footprint).intersection(solid))
        residual = unary_union(physical).area
        headroom_residual = unary_union(clearance).area
        report.append({'host_slab_id': slab.id,
            'physical_intersection_area_m2': float(residual),
            'headroom_residual_area_m2': float(headroom_residual),
            'required_headroom_m': float(headroom_m),
            'solid_source': 'reopened_ifc_cap_mesh' if exported_solids is not None else 'model_footprint_minus_voids',
            'status': 'clear' if residual < 1e-6 and headroom_residual < 1e-6 else 'review_required'})
    return result, report
