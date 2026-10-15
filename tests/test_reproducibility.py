from copy import deepcopy
import numpy as np
from punctora_core.model import BuildingModel,Storey,Wall,Opening,Slab
from punctora_core.reproducibility import geometry_signature
from punctora_core.evidence import _refine_face

def test_original_face_fit_is_independent_of_processing_chunk_plan():
    x,z=np.meshgrid(np.linspace(0,5,241),np.linspace(0,3,101))
    points=np.c_[x.ravel(),.002*np.sin(x.ravel()*10),z.ravel()]
    face=dict(start=[0,0],end=[5,0],z_min=0,z_max=3)
    a=_refine_face(points,face,.01,.08,317)
    b=_refine_face(points,face,.01,.08,78218)
    assert a==b

def test_signature_ignores_ids_order_and_axis_reversal_but_catches_real_change():
    model=BuildingModel('Test',[Storey('s','S',0,3,[(0,0),(5,0),(5,5),(0,5)])],
        walls=[Wall('w','s',(0,0),(5,0),0,3,.2)],
        openings=[Opening('o','w','window',1,1,1,1)])
    same=deepcopy(model);same.walls[0].id='other';same.openings[0].host_wall_id='other'
    same.walls[0].start,same.walls[0].end=same.walls[0].end,same.walls[0].start
    same.openings[0].offset=3
    assert geometry_signature(model)==geometry_signature(same)
    same.openings[0].height+=.05
    assert geometry_signature(model)!=geometry_signature(same)


def test_signature_preserves_valid_surface_when_reporting_grid_splits_it():
    from shapely import set_precision
    from shapely.geometry import box
    from shapely.ops import unary_union
    shape=unary_union([box(0,0,1,1),box(2,0,3,1),
                       box(.5,.4999999,2.5,.5000001)])
    assert shape.is_valid and set_precision(shape,1e-6).geom_type=='MultiPolygon'
    m=BuildingModel('Thin connection',[Storey('s','S',0,3,[(0,0),(4,0),(4,4),(0,4)])],
        slabs=[Slab('a','s',list(shape.exterior.coords)[:-1],0,.2),
               Slab('b','s',[(0,2),(1,2),(1,3),(0,3)],0,.2)])
    original=deepcopy(m.slabs)
    m.validate()
    assert m.to_dict()['slabs']
    signature=geometry_signature(m)
    assert signature['signature_version']==2
    reordered=deepcopy(m)
    reordered.slabs.reverse()
    for slab in reordered.slabs:slab.footprint=list(reversed(slab.footprint))
    assert geometry_signature(reordered)==signature
    changed=deepcopy(m)
    changed.slabs[0].footprint=[(x+.1 if x>=2 else x,y) for x,y in changed.slabs[0].footprint]
    assert geometry_signature(changed)['geometry_sha256']!=signature['geometry_sha256']
    assert m.slabs==original
