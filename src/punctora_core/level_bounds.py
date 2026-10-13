"""Explicit detection bounds and exterior search scopes, not invented floors."""
from math import isfinite
import numpy as np
from shapely.geometry import box
from .model import Storey


class LevelDetectionError(ValueError):
    def __init__(self,message,diagnostics=None):
        super().__init__(message)
        self.diagnostics=diagnostics or {}


def validate_detection_options(options=None):
    options=options or {}
    if not isinstance(options,dict) or set(options)-{'scope','manual_levels'}:
        raise ValueError('Invalid reconstruction options')
    scope=options.get('scope','auto')
    if scope not in {'auto','interior','exterior'}:raise ValueError('Invalid reconstruction scope')
    levels=options.get('manual_levels',[])
    if not isinstance(levels,list) or len(levels)>100:raise ValueError('Manual levels must be a list of at most 100 bounds')
    result=[]
    for index,level in enumerate(levels,1):
        if not isinstance(level,dict) or set(level)-{'name','bottom_m','top_m'}:
            raise ValueError('Invalid manual level fields')
        bottom,top=level.get('bottom_m'),level.get('top_m')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) for v in (bottom,top)) or top<=bottom:
            raise ValueError('Manual bounds need finite bottom < top in local metres')
        name=level.get('name',f'Level {index}')
        if not isinstance(name,str) or not name.strip():raise ValueError('Manual level name cannot be empty')
        result.append({'name':name,'bottom_m':float(bottom),'top_m':float(top)})
    result.sort(key=lambda v:(v['bottom_m'],v['top_m'],v['name']))
    if any(a['top_m']>b['bottom_m']+1e-8 for a,b in zip(result,result[1:])):
        raise ValueError('Manual level intervals overlap')
    return {'scope':scope,'manual_levels':result}


def source_search_bounds(cloud,settings,manual_levels=()):
    low,high=np.full(3,np.inf),np.full(3,-np.inf)
    for start in range(0,len(cloud.points),settings.processing_chunk_points):
        p=cloud.points[start:start+settings.processing_chunk_points]
        low=np.minimum(low,p.min(axis=0));high=np.maximum(high,p.max(axis=0))
    margin=max(.08,settings.grid_size_m*2)
    ring=list(box(low[0]-margin,low[1]-margin,high[0]+margin,high[1]+margin).exterior.coords)[:-1]
    if manual_levels:
        levels=[Storey(f'manual-storey-{i}',entry['name'],entry['bottom_m'],entry['top_m'],ring,
            {'elevation':'user_supplied','ceiling':'user_supplied','footprint':'inferred'})
            for i,entry in enumerate(manual_levels,1)]
    else:
        if high[2]-low[2]<settings.minimum_storey_height_m:
            raise LevelDetectionError('Insufficient vertical extent for exterior walls',{'bounds_min':low.tolist(),'bounds_max':high.tolist()})
        levels=[Storey('exterior-scope','Exterior search bounds',float(low[2]),float(high[2]),ring,
                      {'elevation':'unknown','ceiling':'unknown','footprint':'inferred'})]
    return levels,{'source_points_scanned':len(cloud.points),'points_processed':len(cloud.points),
                   'full_cloud_passes':1,'bounds_min':low.tolist(),'bounds_max':high.tolist(),
                   'scope':'user bounds or observed cloud search extent; no measured floors inferred'}
