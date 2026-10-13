"""Exact original-order XY candidate index for proposal fitting."""
import numpy as np


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
