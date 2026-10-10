"""Signed observed-face rasters with separately supported opening frames."""
from concurrent.futures import ThreadPoolExecutor
import cv2
import numpy as np
from .model import Opening
from .sampling import resolved_cpu_workers
from .wall_slices import runs


def _one_wall(cloud,wall,settings):
    start=np.asarray(wall.start,float)
    direction=np.asarray(wall.end,float)-start
    length=float(np.linalg.norm(direction))
    if length<.5:
        return []
    direction/=length
    normal=np.array([-direction[1],direction[0]])
    cell=max(.05,settings.grid_size_m)
    nx,nz=int(np.ceil(length/cell)),int(np.ceil(wall.height/cell))
    if nx<10 or nz<20 or nx*nz>settings.maximum_grid_cells:
        return []
    offsets=sorted(float((np.mean([f['start'],f['end']],axis=0)-start)@normal) for f in wall.observed_faces)
    planes=[]
    for offset in offsets:
        if not planes or abs(offset-planes[-1])>.04:
            planes.append(offset)
    if not planes:
        histogram=np.zeros(81,np.int64)
        for begin in range(0,len(cloud.points),settings.processing_chunk_points):
            p=cloud.points[begin:begin+settings.processing_chunk_points]
            along=(p[:,:2]-start)@direction
            d=(p[:,:2]-start)@normal
            keep=(along>=0)&(along<length)&(p[:,2]>=wall.base)&(p[:,2]<wall.base+wall.height)
            histogram+=np.histogram(d[keep],bins=np.linspace(-.405,.405,82))[0]
        planes=[float((np.argmax(histogram)-40)*.01)]
    candidates=[]
    for reference in planes:
        face=np.zeros((nz,nx),np.uint8)
        returns=np.zeros_like(face)
        depth=np.full((nz,nx),np.inf,np.float32)
        signed=np.full((nz,nx),np.nan,np.float32)
        counts=np.zeros((nz,nx),np.int64)
        sums=np.zeros((nz,nx),float)
        support=0
        for begin in range(0,len(cloud.points),settings.processing_chunk_points):
            points=cloud.points[begin:begin+settings.processing_chunk_points]
            # Filter height before projecting unrelated storeys.
            points=points[(points[:,2]>=wall.base)&(points[:,2]<wall.base+wall.height)]
            relative=points[:,:2]-start
            along,across,z=relative@direction,relative@normal-reference,points[:,2]-wall.base
            keep=(along>=0)&(along<length)&(np.abs(across)<=.35)
            x,h,d=(along[keep]/cell).astype(int),(z[keep]/cell).astype(int),across[keep]
            returns[h,x]=1
            near=np.abs(d)<=max(.02,settings.grid_size_m)
            face[h[near],x[near]]=1
            np.add.at(counts,(h,x),1)
            np.add.at(sums,(h,x),d)
            np.minimum.at(depth,(h,x),np.abs(d).astype(np.float32))
            support+=int(near.sum())
        if support<100:
            continue
        np.divide(sums,counts,out=signed,where=counts>0)
        filled=cv2.morphologyEx(face,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        missing=1-filled
        count,labels,stats,_=cv2.connectedComponentsWithStats(missing,8)
        boxes=[]
        for index in range(1,count):
            x,z,width,height,area=map(int,stats[index])
            if width<8 or height<10:
                continue
            columns=face[z:z+height,x:x+width].mean(axis=0)
            strips=[(a,b) for a,b in runs(columns>=settings.opening_minimum_edge_support) if a>=8 and b<=width-8]
            parts,last=[],0
            for a,b in strips:
                parts.append((last,a));last=b
            parts.append((last,width))
            boxes.extend((x+a,z,b-a,height,len(parts)>1) for a,b in parts if b-a>=8)
        for x,z,width,height,divided in boxes:
            w,h,sill=width*cell,height*cell,z*cell
            if x<2 or x+width>nx-2 or z+height>nz-2 or not .5<=w<=3.2 or not .55<=h<=2.8:
                continue
            vacancy=float(missing[z:z+height,x:x+width].mean())
            if vacancy<.8:
                continue
            kind='door' if sill<=.18 and h>=1.65 else 'window' if .35<=sill<=1.8 else 'unknown'
            strips={'left_jamb':filled[z:z+height,x-2:x],'right_jamb':filled[z:z+height,x+width:x+width+2],
                    'head':filled[z+height:z+height+2,x:x+width]}
            if kind!='door':
                strips['sill']=filled[max(0,z-2):z,x:x+width]
            edge={k:float(v.mean()) if v.size else 0. for k,v in strips.items()}
            if min(edge.values())<settings.opening_minimum_edge_support:
                continue
            interior=returns[z:z+height,x:x+width]
            occupied=float(interior.mean())
            distances=depth[z:z+height,x:x+width]
            valid=(interior>0)&np.isfinite(distances)
            measured=float(np.median(distances[valid])) if valid.any() else None
            values=signed[z:z+height,x:x+width][valid]
            signed_depth=float(np.median(values)) if len(values) else None
            consistency=float(max((values>0).mean(),(values<0).mean())) if len(values) else 0.
            recessed=occupied>=.55 and measured is not None and measured>=settings.opening_recess_depth_m*.8 and consistency>=.8
            if not (recessed or occupied<=.15):
                continue
            actual_sill=0. if kind=='door' else sill
            actual_height=min(h+sill if kind=='door' else h,wall.height-actual_sill)
            evidence=dict(method='recessed_filling_plane' if recessed else 'wall_occupancy_gap',raster_method='signed_observed_face',
                          cell_size_m=cell,face_offset_from_axis_m=reference,edge_support=edge,edge_support_fractions=list(edge.values()),
                          jamb_positions_m=[x*cell,(x+width)*cell],sill_elevation_m=wall.base+actual_sill,
                          head_elevation_m=wall.base+actual_sill+actual_height,interior_occupancy=occupied,empty_space_continuity=vacancy,
                          wall_face_reference_depth_m=reference,interior_depth_contrast_m=measured or 0.,
                          signed_interior_depth_m=signed_depth,signed_depth_consistency=consistency,
                          divided_by_supported_mullion=divided,host_support_points=support,
                          scope='Supported jambs, head and sill on an observed host face; geometric door/window proposal, filling remains unknown')
            evidence['raster_frame']=dict(along_origin_xy=start.tolist(),along_direction_xy=direction.tolist(),
                                          signed_depth_normal_xy=normal.tolist(),z_origin_m=wall.base,
                                          face_offset_from_axis_m=reference,shape_rows_columns=[nz,nx])
            evidence['edge_contrast']={
                'left_jamb':float(((filled[z:z+height,x-1]>0)&(filled[z:z+height,x]==0)).mean()),
                'right_jamb':float(((filled[z:z+height,x+width]>0)&(filled[z:z+height,x+width-1]==0)).mean()),
                'head':float(((filled[z+height,x:x+width]>0)&(filled[z+height-1,x:x+width]==0)).mean())}
            if z>0:
                evidence['edge_contrast']['sill']=float(((filled[z-1,x:x+width]>0)&(filled[z,x:x+width]==0)).mean())
            score=min(.95,min(edge.values())*(.8 if recessed else 1-occupied))
            candidates.append(Opening('',wall.id,kind,x*cell,actual_sill,min(w,length-x*cell),actual_height,
                                      {'dimensions':'measured','kind':'inferred','filling':'unknown'},confidence=score,evidence=evidence))
    accepted=[]
    for candidate in sorted(candidates,key=lambda c:-c.confidence):
        if any(min(c.offset+c.width,candidate.offset+candidate.width)-max(c.offset,candidate.offset)>.6*min(c.width,candidate.width)
               and min(c.sill+c.height,candidate.sill+candidate.height)-max(c.sill,candidate.sill)>.6*min(c.height,candidate.height) for c in accepted):
            continue
        accepted.append(candidate)
    accepted.sort(key=lambda c:(c.offset,c.sill))
    for index,candidate in enumerate(accepted,1):
        candidate.id=f'{wall.id}-opening-{index}'
    return accepted


def detect_signed_openings(cloud,walls,settings,workers=None):
    workers=resolved_cpu_workers(settings.cpu_workers) if workers is None else workers
    if workers>1 and len(walls)>1:
        with ThreadPoolExecutor(max_workers=min(workers,len(walls))) as pool:
            return [o for group in pool.map(lambda w:_one_wall(cloud,w,settings),walls) for o in group]
    return [o for w in walls for o in _one_wall(cloud,w,settings)]
