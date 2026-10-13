"""Exact original-order XY candidate index for proposal fitting."""
import numpy as np


def cluster_original_points(points, scan_ids, record_ids, radius_m=.25, minimum_points=6,
                            maximum_points=250000, maximum_neighbours=2048, check=lambda: None):
    """Bounded deterministic DBSCAN with exact IDs, not preview voxels.

    Core components are formed first. A border point touching two components
    belongs to the component with the lowest immutable source key, independent
    of input order or KD-tree neighbour enumeration. Dense neighbourhoods fail
    explicitly instead of silently truncating neighbours.
    """
    from scipy.spatial import cKDTree
    points = np.asarray(points, dtype=np.float64)
    scan_ids, record_ids = np.asarray(scan_ids), np.asarray(record_ids)
    if (points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all()
            or scan_ids.shape != (len(points),) or record_ids.shape != (len(points),)
            or scan_ids.dtype.kind not in "iu" or record_ids.dtype.kind not in "iu"
            or np.any(scan_ids < 0) or np.any(record_ids < 0)):
        raise ValueError("Clustering requires f64 points and exact nonnegative source IDs")
    if not np.isfinite(radius_m) or radius_m <= 0 or any(isinstance(v, bool) or not isinstance(v, int) or v < 1
            for v in (minimum_points, maximum_points, maximum_neighbours)):
        raise ValueError("Invalid clustering radius or declared point limits")
    if len(points) > maximum_points:
        raise ValueError("Clustering exceeds the explicit original-point limit")
    if not len(points):
        return []
    order = np.lexsort((record_ids, scan_ids))
    if np.any((scan_ids[order][1:] == scan_ids[order][:-1]) & (record_ids[order][1:] == record_ids[order][:-1])):
        raise ValueError("Clustering received duplicate immutable source IDs")
    tree = cKDTree(points[order])
    counts = np.empty(len(points), dtype=np.int64)
    for begin in range(0, len(points), 4096):
        check()
        counts[begin:begin + 4096] = tree.query_ball_point(points[order[begin:begin + 4096]], radius_m, return_length=True, workers=1)
    if counts.max() > maximum_neighbours:
        raise ValueError("Clustering neighbourhood exceeds the explicit neighbour limit")
    core = counts >= minimum_points
    component = np.full(len(points), -1, dtype=np.int64)
    number = 0
    for seed in np.flatnonzero(core):
        check()
        if component[seed] >= 0:
            continue
        component[seed] = number
        queue = [int(seed)]
        while queue:
            check()
            row = queue.pop()
            neighbours = np.asarray(tree.query_ball_point(points[order[row]], radius_m), dtype=np.int64)
            unseen = neighbours[core[neighbours] & (component[neighbours] < 0)]
            component[unseen] = number
            queue.extend(unseen.tolist())
        number += 1
    for row in np.flatnonzero(~core):
        check()
        neighbours = np.asarray(tree.query_ball_point(points[order[row]], radius_m), dtype=np.int64)
        known = component[neighbours[core[neighbours]]]
        if len(known):
            component[row] = known.min()
    return [order[component == i] for i in range(number) if int((component == i).sum()) >= minimum_points]


class PlanarPointIndex:
    def __init__(self,points,cell_m=.2,maximum_cells=5_000_000):
        self.points,self.cell=points,float(cell_m)
        if not len(points):
            self.fallback=True
            return
        self.origin=np.floor(points[:,:2].min(axis=0)/self.cell)*self.cell
        coordinates=np.floor((points[:,:2]-self.origin)/self.cell).astype(np.int64)
        self.dimensions=coordinates.max(axis=0)+1
        self.fallback=int(np.prod(self.dimensions))>maximum_cells
        if self.fallback:return
        keys=coordinates[:,0]+self.dimensions[0]*coordinates[:,1]
        self.order=np.argsort(keys,kind='stable')
        self.starts=np.r_[0,np.cumsum(np.bincount(keys,minlength=int(np.prod(self.dimensions))))]

    def near_segment(self,start,end,radius):
        if self.fallback:return np.arange(len(self.points))
        a,b=np.asarray(start,dtype=float),np.asarray(end,dtype=float);direction=b-a
        length=np.linalg.norm(direction)
        if length<=0:return np.empty(0,dtype=np.int64)
        direction/=length
        a,b=a-direction*radius,b+direction*radius
        low=np.maximum(0,np.floor((np.minimum(a,b)-radius-self.origin)/self.cell).astype(int))
        high=np.minimum(self.dimensions-1,np.floor((np.maximum(a,b)+radius-self.origin)/self.cell).astype(int))
        if np.any(high<low):return np.empty(0,dtype=np.int64)
        x,y=np.meshgrid(np.arange(low[0],high[0]+1),np.arange(low[1],high[1]+1))
        centres=np.c_[x.ravel(),y.ravel()]*self.cell+self.origin+self.cell/2
        along=np.clip((centres-a)@direction,0,np.linalg.norm(b-a))
        keep=np.linalg.norm(centres-a-along[:,None]*direction,axis=1)<=radius+self.cell*np.sqrt(2)/2+1e-10
        keys=(x.ravel()+self.dimensions[0]*y.ravel())[keep]
        parts=[self.order[self.starts[k]:self.starts[k+1]] for k in keys if self.starts[k+1]>self.starts[k]]
        return np.sort(np.concatenate(parts)) if parts else np.empty(0,dtype=np.int64)
