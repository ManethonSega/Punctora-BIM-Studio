from shapely.geometry import box
from punctora_core.model import Stair,Slab
from punctora_core.stair_connections import verify_stair_connections

def flight():
    return Stair('f','s',(0,0),(2,0),0,1,.2,.25,8,
                 evidence={'observed_step_indices':[0,1,2,7],
                           'inferred_missing_step_indices':[3,4,5,6]})

def test_matching_height_on_a_distant_slab_is_not_a_connection():
    s=flight();slab=Slab('far','s',list(box(20,20,25,25).exterior.coords)[:-1],1.4,.2)
    r=verify_stair_connections([s],[slab],[],[{'geometry':box(20,20,25,25),'z':1.6,'count':100}])
    assert r[0]['connection_status']=='unresolved' and s.evidence['upper_slab_id'] is None
    assert s.evidence['inferred_missing_step_indices']==[3,4,5,6]

def test_observed_endpoint_surfaces_confirm_both_connections():
    s=flight();footprint=list(box(-1,-1,3,1).exterior.coords)[:-1]
    slabs=[Slab('lower','s',footprint,-.2,.2),Slab('upper','s',footprint,1.4,.2)]
    surfaces=[{'geometry':box(-1,-1,3,1),'z':z,'count':100} for z in [0,1.6]]
    assert verify_stair_connections([s],slabs,[],surfaces)[0]['connection_status']=='connected'
    assert s.evidence['upper_slab_id']=='upper' and s.evidence['lower_slab_id']=='lower'

def test_an_inferred_slab_alone_does_not_certify_a_measured_connection():
    s=flight();slab=Slab('slab','s',list(box(-1,-1,3,1).exterior.coords)[:-1],1.4,.2)
    result=verify_stair_connections([s],[slab],[])
    assert result[0]['endpoints']['upper']['slab_candidate_id']=='slab'
    assert result[0]['connection_status']=='unresolved'
