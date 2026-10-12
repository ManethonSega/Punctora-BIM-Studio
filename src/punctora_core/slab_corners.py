"""Bounded slab-corner completion constrained by independently observed wall faces."""
import numpy as np
from shapely.geometry import Point,Polygon,LineString
from shapely.ops import unary_union


def complete_wall_corners(geometry,walls,elevation,settings,storey_id):
    from .wall_editing import _line_intersection,observed_junction_support
    maximum_gap=max(.40,3*settings.slab_close_gap_m)
    nearby=[]
    for wall in walls:
        if wall.storey_id!=storey_id or wall.evidence_count<20:continue
        if elevation<wall.base-.30 or elevation>wall.base+wall.height+.30:continue
        candidates=[f for f in wall.observed_faces if f.get('original_inlier_fit_points',0)>=20
            and f.get('original_plane_fit_rmse_m',1.)<=settings.slab_surface_tolerance_m
            and f.get('original_vertical_support_fraction',1.)>=.25]
        if candidates:
            face=min(candidates,key=lambda f:(max(f['z_min']-elevation,elevation-f['z_max'],0.),
                                              -f.get('original_inlier_fit_points',0)))
            nearby.append((wall,face,np.asarray(wall.start,dtype=float),np.asarray(wall.end,dtype=float)))
    protected=unary_union([Polygon(r) for p in ([geometry] if isinstance(geometry,Polygon) else geometry.geoms)
                          for r in p.interiors])
    additions=[];reports=[];seen=set()
    for i,(first,af,a,b) in enumerate(nearby):
        for second,bf,c,d in nearby[i+1:]:
            da,db=b-a,d-c
            cosine=abs(float(da@db)/(np.linalg.norm(da)*np.linalg.norm(db)))
            if cosine>np.cos(np.deg2rad(25.)):continue
            corner=_line_intersection(a,b,c,d)
            if corner is None:continue
            if min(np.linalg.norm(corner-a),np.linalg.norm(corner-b))>settings.corner_snap_tolerance_m+.05:continue
            if min(np.linalg.norm(corner-c),np.linalg.norm(corner-d))>settings.corner_snap_tolerance_m+.05:continue
            first_end='start' if np.linalg.norm(corner-a)<np.linalg.norm(corner-b) else 'end'
            second_end='start' if np.linalg.norm(corner-c)<np.linalg.norm(corner-d) else 'end'
            checks=[observed_junction_support(first,first_end,corner,[second]),
                    observed_junction_support(second,second_end,corner,[first])]
            if not all(check['supported'] for check in checks):continue
            key=tuple(np.round(corner,3))
            if key in seen:continue
            seen.add(key);gap=float(Point(corner).distance(geometry))
            if gap<=.005:continue
            record={'wall_ids':[first.id,second.id],'corner_xy_m':corner.tolist(),
                    'original_gap_m':gap,'maximum_completion_gap_m':maximum_gap,
                    'source_plane_m':float(elevation),'face_fit_point_counts':[
                        af['original_inlier_fit_points'],bf['original_inlier_fit_points']],
                    'observed_corner_support':checks}
            if gap>maximum_gap:
                reports.append({**record,'status':'review_required','reason':'gap_exceeds_bounded_completion'})
                continue
            va=(b if np.linalg.norm(b-corner)>np.linalg.norm(a-corner) else a)-corner
            vb=(d if np.linalg.norm(d-corner)>np.linalg.norm(c-corner) else c)-corner
            reach=2*maximum_gap
            p=corner+va/np.linalg.norm(va)*min(reach,np.linalg.norm(va))
            q=corner+vb/np.linalg.norm(vb)*min(reach,np.linalg.norm(vb))
            patch=Polygon([corner,p,q])
            if (patch.area<1e-8 or geometry.intersection(patch).area<patch.area*.30
                    or any(geometry.intersection(LineString([corner,t]).buffer(
                           max(.04,wall.thickness/2+settings.slab_raster_cell_m/2))).area
                           <min(reach,np.linalg.norm(t-corner))*.02 for t,wall in ((p,first),(q,second)))):
                reports.append({**record,'status':'review_required','reason':'corner_wedge_lacks_adjacent_slab_support'})
                continue
            addition=patch.difference(geometry).difference(protected)
            if addition.is_empty:continue
            additions.append(addition)
            reports.append({**record,'status':'inferred_completion','added_area_m2':float(addition.area),
                'basis':'two original wall planes near this horizontal level and adjacent slab support on both arms'})
    added=unary_union(additions)
    return geometry.union(added),added,reports
