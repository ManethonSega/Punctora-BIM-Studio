"""Geometry signatures independent of IDs, worker plans and record ordering."""
import hashlib,json
from math import dist
import numpy as np
from shapely import normalize,set_precision
from shapely.geometry import Polygon


def quality_snapshot_signature(snapshot, tolerance_m=1e-6):
    """ID/order-independent geometry and relationships, including surface holes.

    Separate from the legacy reconstruction signature, whose reporting scope
    predates surface cuts and endpoint/landing associations. No source array
    is rounded or changed, only the comparison representation.
    """
    from .annotation_io import canonical_json, number
    number(tolerance_m, "signature tolerance", True)

    def scalar(value):
        return int(round(float(value) / tolerance_m))

    def ring(vertices):
        shape = normalize(set_precision(Polygon(vertices), tolerance_m))
        if not isinstance(shape, Polygon) or shape.is_empty:
            raise ValueError("Signature tolerance collapses an element polygon")
        return [[scalar(x), scalar(y)] for x, y in shape.exterior.coords[:-1]]

    def geometry(element):
        result = dict(element["geometry"])
        if result["type"] in {"wall", "opening", "column"} and result["start"] > result["end"]:
            length = dist(result["start"], result["end"])
            result["start"], result["end"] = result["end"], result["start"]
            if result.get("profile_xz"):
                result["profile_xz"] = [[length - x, z] for x, z in result["profile_xz"]]
        for key in ("footprint", "profile_xz"):
            if result.get(key):
                result[key] = ring(result[key])
        if "holes" in result:
            result["holes"] = sorted(ring(r) for r in result["holes"])
        for key, value in list(result.items()):
            if key in {"footprint", "profile_xz", "holes", "type", "steps"}:
                continue
            if isinstance(value, (int, float)):
                result[key] = scalar(value)
            elif isinstance(value, (list, tuple)):
                result[key] = [scalar(v) for v in value]
        return [element["class"], result]

    geometries = {e["id"]: geometry(e) for e in snapshot["elements"]}
    shapes = []
    for element in snapshot["elements"]:
        relationships = {"host": geometries.get(element.get("host_id")),
                         "connections": {k: geometries.get(v) for k, v in element.get("connections", {}).items()},
                         "connected": sorted((geometries[v] for v in element.get("connected_ids", []) if v in geometries),
                                             key=canonical_json),
                         "observed_treads": sorted(element.get("observed_treads", [])),
                         "inferred_treads": sorted(element.get("inferred_treads", []))}
        shapes.append([geometries[element["id"]], relationships])
    encoded = canonical_json(sorted(shapes, key=canonical_json)).encode("utf-8")
    return {"geometry_sha256": hashlib.sha256(encoded).hexdigest(),
            "comparison_tolerance_m": tolerance_m,
            "scope": "class, geometry, holes, hosts, endpoint relations and tread states; no source rounding"}


def geometry_signature(model,tolerance_m=1e-6):
    def scalar(value):return int(round(float(value)/tolerance_m))
    def point(value):return tuple(scalar(v) for v in value)
    def ring(vertices):
        p=normalize(set_precision(Polygon(vertices),tolerance_m))
        # Reporting precision can split a valid, connected model footprint.
        # Hash every resulting component and hole; never change the model or
        # select only the largest piece merely to produce this diagnostic.
        pieces=[] if p.is_empty else [p] if isinstance(p,Polygon) else list(p.geoms)
        return sorted([[ [point(v) for v in part.exterior.coords[:-1]],
                         sorted([point(v) for v in hole.coords[:-1]] for hole in part.interiors)]
                       for part in pieces])
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
    if model.facade_panels:
        shapes['facade_panels']=sorted([sorted([point(p.start),point(p.end)]),scalar(p.base),
            scalar(p.height),scalar(p.thickness)] for p in model.facade_panels)
    encoded=json.dumps(shapes,sort_keys=True,separators=(',',':')).encode()
    return {'geometry_sha256':hashlib.sha256(encoded).hexdigest(),
            'signature_version':2,
            'comparison_tolerance_m':tolerance_m,
            'scope':'export geometry at reporting precision; source coordinates remain f64'}
