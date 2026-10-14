"""Topology-bounded ceiling completion, not floor-to-ceiling copying."""
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union


def complete_ceiling_rooms(geometry, raw, floor, walls, owner, elevation, protected):
    lines = []
    for wall in walls:
        if (wall.storey_id == owner.id and wall.evidence_count >= 20
                and wall.fit_rmse_m is not None and wall.fit_rmse_m <= .035
                and wall.base+wall.height >= elevation-.15):
            lines.append(LineString([wall.start,wall.end]))
    # Only explicitly bounded endpoint gaps may close a room, not arbitrary hulls.
    joins = []
    ends = [p for line in lines for p in (line.coords[0],line.coords[-1])]
    for i,a in enumerate(ends):
        for b in ends[i+1:]:
            gap = LineString([a,b])
            if 1e-8 < gap.length <= .12:
                joins.append(gap)
    rooms = list(polygonize(unary_union([*lines,*joins]))) if lines else []
    additions, report = [], []
    for room in sorted(rooms,key=lambda r:r.bounds):
        if room.area < 1.:
            continue
        observed = room.intersection(raw)
        floor_fraction = room.intersection(floor).area / room.area
        ceiling_fraction = observed.area / room.area
        if ceiling_fraction < .45 or floor_fraction < .80:
            continue
        # Only gaps near observed coplanar ceiling and inside a closed room.
        # Large unscanned rooms, atria and scan boundaries remain unresolved.
        fill = room.intersection(raw.buffer(1.,join_style=2)).difference(geometry).difference(protected)
        if fill.is_empty:
            continue
        additions.append(fill)
        report.append({'room_area_m2':room.area,'measured_ceiling_fraction':ceiling_fraction,
            'floor_support_fraction':floor_fraction,'completion_area_m2':fill.area,
            'maximum_distance_to_ceiling_m':1.,'maximum_endpoint_join_m':.12,
            'state':'justified_completion','rule':'closed_observed_wall_room_with_floor_and_coplanar_ceiling'})
    addition = unary_union(additions)
    return geometry.union(addition), addition, report
