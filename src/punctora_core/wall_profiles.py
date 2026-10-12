"""Exterior wall outlines from distributed original face records, not global boxes."""
from math import dist
import numpy as np
from shapely.geometry import Polygon,box
from shapely.ops import unary_union
from shapely import constrained_delaunay_triangles


def fit_exterior_profiles(walls,openings=()):
    reports=[]
    for wall in walls:
        length=dist(wall.start,wall.end)
        rectangle_area=length*wall.height
        direction=(np.array(wall.end)-wall.start)/length
        cell=.04;n=max(1,int(np.ceil(length/cell)))
        lower=np.full(n,np.inf);upper=np.full(n,-np.inf)
        for face in wall.observed_faces:
            for column in face.get('supported_extent_columns',[]):
                a,b=sorted(float((np.array(column[k])-wall.start)@direction)
                           for k in ('start_xy','end_xy'))
                first=max(0,int(np.floor(a/cell)));last=min(n,int(np.ceil(b/cell)))
                if last<=first:continue
                lower[first:last]=np.minimum(lower[first:last],column['bottom_m'])
                upper[first:last]=np.maximum(upper[first:last],column['top_m'])
        valid=np.isfinite(lower)&np.isfinite(upper)&(upper-lower>=.15)
        if valid.mean()<.6:
            wall.review_state='flagged'
            reports.append({'wall_id':wall.id,'status':'review_required',
                'reason':'insufficient_distributed_vertical_extent_support','supported_column_fraction':float(valid.mean())})
            continue
        # Only bounded longitudinal occlusion is interpolated. Long blank spans
        # stay reviewable and are never filled merely to complete a rectangle.
        from .wall_slices import runs
        for a,b in runs(~valid):
            if a and b<n and (b-a)*cell<=.35:
                lower[a:b]=max(lower[a-1],lower[b]);upper[a:b]=min(upper[a-1],upper[b])
                valid[a:b]=upper[a:b]-lower[a:b]>=.15
        pieces=[box(i*cell,max(0.,lower[i]-wall.base),min(length,(i+1)*cell),
                    min(wall.height,upper[i]-wall.base)) for i in np.flatnonzero(valid)
                if min(wall.height,upper[i]-wall.base)>max(0.,lower[i]-wall.base)]
        shape=unary_union(pieces)
        if not isinstance(shape,Polygon) or shape.is_empty or not shape.is_valid:
            wall.review_state='flagged'
            reports.append({'wall_id':wall.id,'status':'review_required','reason':'disconnected_extent_support'})
            continue
        shape=shape.simplify(1e-8,preserve_topology=True)
        x0,z0,x1,z1=shape.bounds
        original_start=np.asarray(wall.start,dtype=float)
        wall.start=tuple(original_start+direction*x0);wall.end=tuple(original_start+direction*x1)
        wall.base+=z0;wall.height=z1-z0
        wall.profile_xz=[[float(x-x0),float(z-z0)] for x,z in shape.exterior.coords[:-1]]
        for opening in openings:
            if opening.host_wall_id==wall.id:
                opening.offset-=x0;opening.sill-=z0
        wall.provenance.update(base='inferred',height='inferred')
        wall.provenance['profile']='inferred'
        report={'wall_id':wall.id,'status':'profile_fitted','supported_column_fraction':float(valid.mean()),
                'rectangle_area_m2':rectangle_area,'profile_area_m2':float(shape.area),
                'removed_envelope_area_m2':float(rectangle_area-shape.area),
                'along_cell_m':cell,'height_cell_m':.05,
                'scope':'original plane inliers in distributed height cells; bounded outline discretization, not structural endpoint certification'}
        wall.evidence['exterior_profile']=report;reports.append(report)
    return reports


def preview_wall_mesh(wall,openings):
    length=dist(wall.start,wall.end);axis=(np.array(wall.end)-wall.start)/length
    normal=np.array([-axis[1],axis[0]])
    shape=Polygon(wall.profile_xz).difference(unary_union([
        box(o.offset,o.sill,o.offset+o.width,o.sill+o.height) for o in openings]))
    pieces=[shape] if isinstance(shape,Polygon) else list(shape.geoms)
    def point(x,z,side):
        xy=np.array(wall.start)+axis*x+normal*side
        return [float(xy[0]),float(xy[1]),float(wall.base+z)]
    triangles=[]
    for tri in constrained_delaunay_triangles(shape).geoms:
        ring=list(tri.exterior.coords)[:-1]
        triangles.append([point(x,z,-wall.thickness/2) for x,z in ring])
        triangles.append([point(x,z,wall.thickness/2) for x,z in reversed(ring)])
    for piece in pieces:
        for ring in [piece.exterior,*piece.interiors]:
            coords=list(ring.coords)
            for (a,z),(b,h) in zip(coords,coords[1:]):
                p,q=point(a,z,-wall.thickness/2),point(b,h,-wall.thickness/2)
                r,s=point(b,h,wall.thickness/2),point(a,z,wall.thickness/2)
                triangles.extend([[p,q,r],[p,r,s]])
    return {'triangles_xyz':triangles,'scope':'current supported wall profile minus current openings'}
