from copy import deepcopy
import numpy as np
from punctora_core.model import BuildingModel,Storey,Wall,Opening
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
