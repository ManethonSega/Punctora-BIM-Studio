"""Repeated horizontal wall-face evidence and robust supported extents."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import numpy as np


def runs(mask):
    delta = np.diff(np.r_[False, mask, False].astype(int))
    return list(zip(np.flatnonzero(delta == 1), np.flatnonzero(delta == -1)))


def multi_slice_walls(points, storey, settings, workers=1):
    from .reconstruction import _segments, _fit_face, _walls_from_faces
    height = storey.ceiling-storey.elevation
    count = max(6, min(12, int(np.ceil(height/.4))))
    edges = np.linspace(storey.elevation+.04, storey.ceiling-.04, count+1)
    records = []
    tolerance = max(.025,min(settings.wall_merge_lateral_tolerance_m,settings.minimum_wall_thickness_m*.8))
    # Normal-based whole-storey patches supply stable plane proposals where
    # several windows fragment individual contours. They do not bypass the
    # independent slice occupancy or supported endpoint tests below.
    from .sampling import voxel_sample
    from .surfaces import region_growing
    seed_sample=voxel_sample(points,max(.04,settings.detection_voxel_size_m),100000,
                            min(100000,settings.processing_chunk_points),workers=workers)
    patches,_=region_growing(seed_sample,replace(settings,cpu_workers=workers,region_normal_angle_deg=8.))
    seeds=[]
    for patch in patches:
        if patch.orientation!='vertical' or patch.bounds[1][2]-patch.bounds[0][2]<height*.5:
            continue
        cloud_indices=np.asarray(patch.representative_cloud_indices,int)
        patch_points=points[cloud_indices]
        normal=np.asarray(patch.normal[:2]);direction=np.array([-normal[1],normal[0]])/np.linalg.norm(normal)
        centre=np.asarray(patch.centroid[:2]);along=(patch_points[:,:2]-centre)@direction
        seed=[centre+along.min()*direction,centre+along.max()*direction]
        if np.linalg.norm(seed[1]-seed[0])>=settings.minimum_wall_length_m:
            seeds.append(seed)
    for index, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
        section = points[(points[:, 2] >= low)&(points[:, 2] < high)]
        if len(section) < 12:
            continue
        segments = _segments(section, settings)+seeds
        def fit(segment):
            return _fit_face(segment, section, max(.025, 2*settings.grid_size_m))
        if workers > 1 and len(segments) > 1:
            with ThreadPoolExecutor(max_workers=min(workers, len(segments))) as pool:
                fits = list(pool.map(fit, segments))
        else:
            fits = list(map(fit, segments))
        for item in fits:
            if item is None:
                continue
            face, amount, error = item
            if np.linalg.norm(face[1]-face[0]) >= settings.minimum_wall_length_m and error <= .035:
                records.append(dict(face=face, slice=index, count=amount, rmse=error))
    records.sort(key=lambda r: (-np.linalg.norm(r['face'][1]-r['face'][0]), r['slice']))
    clusters = []
    angle = np.cos(np.deg2rad(settings.wall_merge_angle_deg))
    for record in records:
        a,b = record['face']
        direction = (b-a)/np.linalg.norm(b-a)
        target = None
        for cluster in clusters:
            origin,axis = cluster['origin'],cluster['direction']
            normal = np.array([-axis[1],axis[0]])
            if abs(direction@axis) >= angle and abs(((a+b)/2-origin)@normal) <= tolerance:
                target = cluster
                break
        if target is None:
            target = dict(origin=a,direction=direction,records=[])
            clusters.append(target)
        target['records'].append(record)
    faces,evidence = [],[]
    cell = max(.04,2*settings.grid_size_m)
    for cluster in clusters:
        records = cluster['records']
        ids = sorted({r['slice'] for r in records})
        if len(ids) < 2 or (max(ids)-min(ids)+1)/count < .35:
            continue
        directions=[]
        for record in records:
            a,b=record['face'];direction=(b-a)/np.linalg.norm(b-a)
            if direction@cluster['direction']<0:
                direction=-direction
            directions.append(direction)
        axis=np.median(directions,axis=0);axis/=np.linalg.norm(axis)
        normal = np.array([-axis[1],axis[0]])
        offset = float(np.median([np.median([np.mean(r['face'],axis=0)@normal
                       for r in records if r['slice'] == i]) for i in ids]))
        intervals = [sorted(float(p@axis) for p in r['face']) for r in records]
        low,high = min(a for a,b in intervals)-.12,max(b for a,b in intervals)+.12
        bins = int(np.ceil((high-low)/cell))+1
        if bins*count > settings.maximum_grid_cells:
            continue
        occupied = np.zeros((count,bins),bool)
        nearby = points[np.abs(points[:,:2]@normal-offset) <= tolerance]
        x = np.floor((nearby[:,:2]@axis-low)/cell).astype(int)
        z = np.searchsorted(edges,nearby[:,2],side='right')-1
        keep = (x>=0)&(x<bins)&(z>=0)&(z<count)
        occupied[z[keep],x[keep]] = True
        repeated = occupied.sum(axis=0) >= 2
        # Long regions supported only at their header/sill cannot silently
        # become a filled wall when they exceed plausible opening dimensions.
        weak=(occupied.sum(axis=0)<=max(2,int(np.floor(count*.5))))&repeated
        for a,b in runs(weak):
            if (b-a)*cell>3.2:
                repeated[a:b]=False
        for a,b in runs(~repeated):
            if a>0 and b<bins and (b-a)*cell <= .08 and np.count_nonzero(occupied[:,a-1]&occupied[:,b]) >= 2:
                repeated[a:b] = True
        for first,last in runs(repeated):
            extents = [np.flatnonzero(occupied[i,first:last])+first for i in ids]
            extents = [e for e in extents if len(e)>=3]
            if len(extents)<2:
                continue
            first = max(first,int(np.median([e.min() for e in extents])))
            last = min(last,int(np.median([e.max()+1 for e in extents])))
            start,end = low+first*cell,min(high,low+last*cell)
            if end-start < settings.minimum_wall_length_m:
                continue
            slices,observed = [],[]
            for i in ids:
                support = np.flatnonzero(occupied[i,first:last])+first
                local = [r for r,interval in zip(records,intervals) if r['slice']==i and interval[1]>=start and interval[0]<=end]
                if len(support)<3 or not local:
                    continue
                a,b = max(start,low+support.min()*cell),min(end,low+(support.max()+1)*cell)
                p,q = axis*a+normal*offset,axis*b+normal*offset
                record = dict(slice_index=i,z_min=float(edges[i]),z_max=float(edges[i+1]),start=p.tolist(),end=q.tolist(),
                              support_bins=len(support),coverage=float(len(support)/(last-first)),
                              proposal_support_points=sum(r['count'] for r in local),fit_rmse_m=float(max(r['rmse'] for r in local)))
                slices.append(record)
                observed.append({k:record[k] for k in ('start','end','z_min','z_max','slice_index')})
            if len(slices)<2 or len(slices)/count<.35:
                continue
            face = [axis*start+normal*offset,axis*end+normal*offset]
            faces.append((face,sum(r['proposal_support_points'] for r in slices),max(r['fit_rmse_m'] for r in slices)))
            evidence.append(dict(face=face,observed=observed,slices=slices,vertical_continuity=len(slices)/count,
                                 cell_size_m=cell,raster_along_origin_xy=(axis*low+normal*offset).tolist(),
                                 raster_direction_xy=axis.tolist(),slice_occupancy_runs=[dict(slice_index=i,intervals_m=[
                                    [float((a+first)*cell),float((b+first)*cell)] for a,b in runs(occupied[i,first:last])]) for i in ids]))
    def support_for(face):
        return min(evidence,key=lambda e:np.linalg.norm(np.asarray(e['face'])-face))
    def credible_pair(face,other):
        first,second=support_for(face),support_for(other)
        # Glazing or a leaf observed only inside a frame is not the far side
        # of a full-height wall. Require repeated broad support on both sides.
        if min(first['vertical_continuity'],second['vertical_continuity'])<.6:
            return False
        a,b=np.asarray(face)
        axis=(b-a)/np.linalg.norm(b-a)
        values=sorted(float((p-a)@axis) for p in other)
        overlap=max(0.,min(np.linalg.norm(b-a),values[1])-max(0.,values[0]))
        return overlap/max(np.linalg.norm(b-a),np.linalg.norm(np.asarray(other[1])-other[0]))>=.75
    walls = _walls_from_faces(faces,storey,settings,(float(edges[0]),float(edges[-1])),pair_validator=credible_pair)
    for wall in walls:
        matches = [min(evidence,key=lambda e:np.linalg.norm(np.asarray(e['face'])-[f['start'],f['end']])) for f in wall.observed_faces]
        wall.observed_faces = [f for match in matches for f in match['observed']]
        wall.detection_method = 'multi_slice'
        wall.evidence = dict(method='multi_slice',slices=[r for m in matches for r in m['slices']],
                             vertical_continuity=min(m['vertical_continuity'] for m in matches),slice_count=count,cell_size_m=cell,
                             face_support=[{k:v for k,v in m.items() if k not in {'face','observed','slices'}} for m in matches],
                             extent_policy='two independent height bands per longitudinal cell; median endpoints across bands')
    return walls
