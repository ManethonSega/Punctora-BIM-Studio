"""Topology-bounded ceiling completion, not floor-to-ceiling copying."""
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union


def _nearby_axis_junctions(lines):
    """Extend observed axes only to a shared nearby crossing, never a hull.

    An endpoint can meet the interior of an independently observed wall. Two
    offset corner endpoints can also meet their common crossing. Each extension
    keeps the existing 0.12 m limit; parallel portal gaps get no new policy.
    """
    joins = []
    nodes = [[(0., line.coords[0]), (1., line.coords[-1])] for line in lines]
    for i, first in enumerate(lines):
        a, b = first.coords[0], first.coords[-1]
        u = (b[0]-a[0], b[1]-a[1])
        for j, second in enumerate(lines[i+1:], i+1):
            c, d = second.coords[0], second.coords[-1]
            v = (d[0]-c[0], d[1]-c[1])
            cross = u[0]*v[1]-u[1]*v[0]
            if abs(cross) <= 1e-8 * first.length * second.length:
                continue
            delta = (c[0]-a[0], c[1]-a[1])
            t = (delta[0]*v[1]-delta[1]*v[0])/cross
            s = (delta[0]*u[1]-delta[1]*u[0])/cross
            if not (-.12/first.length <= t <= 1+.12/first.length
                    and -.12/second.length <= s <= 1+.12/second.length):
                continue
            crossing = (a[0]+t*u[0], a[1]+t*u[1])
            extensions = []
            for line, position in ((first, t), (second, s)):
                if position < 0 or position > 1:
                    endpoint = line.coords[0] if position < 0 else line.coords[-1]
                    extension = LineString([endpoint, crossing])
                    if 1e-8 < extension.length <= .12+1e-12:
                        extensions.append(extension)
            if extensions:
                # Explicitly split receiving segments at this identical f64
                # vertex. Recomputing each segment's projection independently
                # can leave a numerical gap after rotation/translation.
                joins.extend(extensions)
                for number, position in ((i, t), (j, s)):
                    if 0. < position < 1.:
                        nodes[number].append((position, crossing))
    noded = []
    for vertices in nodes:
        ordered = [point for _, point in sorted(vertices)]
        noded.extend(LineString([a, b]) for a, b in zip(ordered, ordered[1:]) if a != b)
    return noded, joins


def complete_ceiling_rooms(geometry, raw, floor, walls, owner, elevation, protected):
    lines = []
    for wall in walls:
        if (wall.storey_id == owner.id and wall.evidence_count >= 20
                and wall.fit_rmse_m is not None and wall.fit_rmse_m <= .035
                and wall.base+wall.height >= elevation-.15):
            line = LineString([wall.start,wall.end])
            if line.length > 1e-8:
                lines.append(line)
    # Only explicitly bounded endpoint gaps may close a room, not arbitrary hulls.
    joins = []
    ends = [p for line in lines for p in (line.coords[0],line.coords[-1])]
    for i,a in enumerate(ends):
        for b in ends[i+1:]:
            gap = LineString([a,b])
            if 1e-8 < gap.length <= .12:
                joins.append(gap)
    lines, axis_joins = _nearby_axis_junctions(lines)
    joins.extend(axis_joins)
    rooms = list(polygonize(unary_union([*lines,*joins]))) if lines else []
    additions, report = [], []
    useful, supported = 0, 0
    for room in sorted(rooms,key=lambda r:r.bounds):
        if room.area < 1.:
            continue
        useful += 1
        observed = room.intersection(raw)
        floor_fraction = room.intersection(floor).area / room.area
        ceiling_fraction = observed.area / room.area
        facts = {'room_area_m2':room.area,'measured_ceiling_fraction':ceiling_fraction,
                 'floor_support_fraction':floor_fraction,'completion_area_m2':0.,
                 'maximum_distance_to_ceiling_m':1.,'maximum_endpoint_join_m':.12}
        if ceiling_fraction < .45 or floor_fraction < .80:
            report.append({**facts,'state':'rejected_completion',
                'reason':'insufficient_measured_ceiling_support' if ceiling_fraction < .45 else 'insufficient_floor_support'})
            continue
        supported += 1
        # Only gaps near observed coplanar ceiling and inside a closed room.
        # Large unscanned rooms, atria and scan boundaries remain unresolved.
        fill = room.intersection(raw.buffer(1.,join_style=2)).difference(geometry).difference(protected)
        if fill.is_empty:
            continue
        additions.append(fill)
        report.append({**facts,'completion_area_m2':fill.area,
            'state':'justified_completion','rule':'closed_observed_wall_room_with_floor_and_coplanar_ceiling'})
    if not supported:
        report.append({'state':'topology_diagnostic',
            'reason':'no_closed_useful_wall_rooms' if not useful else 'no_supported_wall_rooms',
            'candidate_room_count':len(rooms),'useful_room_count':useful,
            'supported_room_count':supported,'completion_area_m2':0.,'maximum_endpoint_join_m':.12})
    addition = unary_union(additions)
    return geometry.union(addition), addition, report
