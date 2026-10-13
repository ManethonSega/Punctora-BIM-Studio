"""Geometry signatures independent of IDs, worker plans and record ordering."""
import hashlib,json
from math import dist
import numpy as np
from shapely import normalize,set_precision
from shapely.geometry import Polygon


def geometry_signature(model,tolerance_m=1e-6):
    def scalar(value):return int(round(float(value)/tolerance_m))
    def point(value):return tuple(scalar(v) for v in value)
    def ring(vertices):
        p=normalize(set_precision(Polygon(vertices),tolerance_m))
        return [point(v) for v in p.exterior.coords[:-1]]
    walls={w.id:[sorted([point(w.start),point(w.end)]),scalar(w.base),
                         scalar(w.height),scalar(w.thickness)] for w in model.walls}
    shapes={'walls':sorted(walls.values()),
            'slabs':sorted([ring(s.footprint),scalar(s.base),scalar(s.thickness)] for s in model.slabs),
            'openings':[], 'stairs':[], 'landings':[]}
    if any(w.profile_xz for w in model.walls):
        shapes['wall_profiles']=sorted([walls[w.id],ring(w.profile_xz)] for w in model.walls if w.profile_xz)
    hosts={w.id:w for w in model.walls}
    for o in model.openings:
        w=hosts[o.host_wall_id];d=(np.array(w.end)-w.start)/dist(w.start,w.end)
        centre=np.array(w.start)+d*(o.offset+o.width/2)
        shapes['openings'].append([o.kind,point(centre),scalar(w.base+o.sill),
                                   scalar(o.width),scalar(o.height)])
    shapes['openings'].sort()
    shapes['stairs']=sorted([point(s.start),point(s.end),scalar(s.base),scalar(s.width),
                            scalar(s.rise),scalar(s.going),s.steps] for s in model.stairs)
    shapes['landings']=sorted([ring(s.footprint),scalar(s.base),scalar(s.thickness)] for s in model.landings)
    encoded=json.dumps(shapes,sort_keys=True,separators=(',',':')).encode()
    return {'geometry_sha256':hashlib.sha256(encoded).hexdigest(),
            'comparison_tolerance_m':tolerance_m,
            'scope':'export geometry at reporting precision; source coordinates remain f64'}
