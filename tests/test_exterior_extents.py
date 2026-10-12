import numpy as np
import pytest
from punctora_core.model import Wall
from punctora_core.wall_editing import snap_wall_topology


def test_transitive_corner_cluster_cannot_delete_a_supported_short_wall():
    walls = [Wall('short','s',(0.,0.),(.5,0.),0,3,.2),
             Wall('left','s',(-.8,-1.),(.3,.1),0,3,.2),
             Wall('right','s',(1.3,-1.),(.2,.1),0,3,.2)]
    report = snap_wall_topology(walls, minimum_wall_length_m=.5)
    assert walls[0].start == (0.,0.) and walls[0].end == (.5,0.)
    assert any(r['kind']=='snap_would_collapse_supported_wall' and r['wall_id']=='short'
               for r in report['rejected'])
    assert not any(r['wall_id']=='short' for r in report['endpoint_relations'])


def test_original_columns_do_not_extrude_chimney_height_or_ground_trace_across_facade():
    from punctora_core.cloud_io import CloudData
    from punctora_core.evidence import attach_evidence
    from punctora_core.wall_profiles import fit_exterior_profiles
    from punctora_core.model import Opening
    from shapely.geometry import Polygon,Point
    x,z=np.meshgrid(np.arange(0,6.001,.025),np.arange(4,18.001,.025))
    keep=(z<=14)|(x<=1.2)
    points=np.column_stack([x[keep],np.zeros(keep.sum()),z[keep]])
    trace=np.column_stack([np.arange(0,6.001,.025),np.zeros(241),np.zeros(241)])
    points=np.vstack([points,trace])
    wall=Wall('w','s',(0.,0.),(6.,0.),0,18,.2,observed_faces=[
        dict(start=[0.,0.],end=[6.,0.],z_min=0,z_max=18)])
    attach_evidence(CloudData(points),[wall])
    opening=Opening('window','w','window',2,8,1,2)
    report=fit_exterior_profiles([wall],[opening])
    assert report[0]['status']=='profile_fitted'
    profile=Polygon([(x,z+wall.base) for x,z in wall.profile_xz])
    assert wall.base==pytest.approx(4.) and wall.height==pytest.approx(14.,abs=.05)
    assert wall.base+opening.sill==pytest.approx(8.)
    assert report[0]['rectangle_area_m2']==pytest.approx(108.)
    assert profile.covers(Point(.5,17))
    assert profile.covers(Point(4,10))
    assert not profile.covers(Point(4,17))
    assert not profile.covers(Point(4,1))
    assert profile.area==pytest.approx(64.8,abs=1.)


def test_profile_host_validation_preview_and_reopened_ifc_agree(tmp_path):
    import ifcopenshell,ifcopenshell.geom,ifcopenshell.util.shape
    from punctora_core.model import Storey,BuildingModel,Opening
    from punctora_core.opening_bounds import validate_generated_openings
    from punctora_core.ifc_export import write_ifc
    wall=Wall('w','s',(0.,0.),(6.,0.),4,14,.2,
        profile_xz=[[0,0],[6,0],[6,10],[1.2,10],[1.2,14],[0,14]])
    good=Opening('good','w','window',2,1,1,2)
    bad=Opening('bad','w','window',3,11,1,2)
    accepted,reviews=validate_generated_openings([good,bad],[wall])
    assert accepted==[good] and reviews[0]['reason']=='opening_outside_supported_wall_profile'
    model=BuildingModel('profile',[Storey('s','s',0,20,[(0,-1),(7,-1),(7,2),(0,2)])],walls=[wall],openings=accepted)
    saved=model.to_dict();restored=BuildingModel.from_dict(saved)
    mesh=saved['walls'][0]['preview_geometry']['triangles_xyz']
    assert mesh and all(p[2]<=14.000001 for t in mesh for p in t if p[0]>1.200001)
    write_ifc(restored,tmp_path/'profile.ifc')
    f=ifcopenshell.open(tmp_path/'profile.ifc')
    shape=ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(),f.by_type('IfcWall')[0])
    assert ifcopenshell.util.shape.get_volume(shape.geometry)==pytest.approx((64.8-2)*.2)
