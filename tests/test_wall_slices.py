import numpy as np
import pytest
from punctora_core.cloud_io import CloudData
from punctora_core.model import BuildingModel, Storey, Wall
from punctora_core.reconstruction import ReconstructionSettings, detect_walls, _snap_walls
from punctora_core.features import detect_openings
from punctora_core.evidence import attach_evidence


def cloud_face():
    x,z=np.meshgrid(np.arange(0,6.001,.025),np.arange(0,3.001,.025))
    return np.column_stack((x.ravel(),np.zeros(x.size),z.ravel()))


def level():
    return Storey('s','S',0,3,[(-1,-1),(7,-1),(7,2),(-1,2)])


def test_multi_slice_shortens_extension_seen_only_at_ceiling():
    points=cloud_face()
    points=points[(points[:,0]<=4)|(points[:,2]>=2.4)]
    walls=detect_walls(points,level(),ReconstructionSettings(),1)
    assert len(walls)==1
    assert max(walls[0].start[0],walls[0].end[0])<=4.05
    old=(walls[0].start,walls[0].end)
    attach_evidence(CloudData(points),walls)
    assert (walls[0].start,walls[0].end)==old
    assert len(walls[0].evidence['slices'])>=4


def test_through_height_gap_stays_separate_but_framed_windows_keep_host():
    points=cloud_face()
    gap=(points[:,0]>2)&(points[:,0]<4)
    assert len(detect_walls(points[~gap],level(),ReconstructionSettings(),1))==2
    window=gap&(points[:,2]>.8)&(points[:,2]<2.1)
    walls=detect_walls(points[~window],level(),ReconstructionSettings(),1)
    assert len(walls)==1
    assert abs(walls[0].end[0]-walls[0].start[0])>5.9


@pytest.mark.parametrize('depth',[0.,.12,-.12])
def test_two_windows_with_thin_supported_mullion_and_signed_depth(depth):
    points=cloud_face()
    windows=(((points[:,0]>=1)&(points[:,0]<2.5))|((points[:,0]>=2.6)&(points[:,0]<4.1)))&(points[:,2]>=.9)&(points[:,2]<2.1)
    if depth:
        points[windows,1]=depth
    else:
        points=points[~windows]
    wall=Wall('w','s',(0,0),(6,0),0,3,.2,observed_faces=[dict(start=[0,0],end=[6,0],z_min=0,z_max=3)])
    openings=detect_openings(CloudData(points),[wall],ReconstructionSettings(),1)
    assert len(openings)==2
    assert all(o.kind=='window' for o in openings)
    assert [o.offset for o in openings]==pytest.approx([1,2.6],abs=.05)
    if depth:
        assert all(o.evidence['signed_interior_depth_m']==pytest.approx(depth,abs=.01) for o in openings)
    copy=BuildingModel.from_dict(BuildingModel('Test',[level()],walls=[wall],openings=openings).to_dict())
    assert copy.openings[0].evidence==openings[0].evidence


def test_corner_correction_requires_two_measured_bands():
    faces=[dict(start=[0,0],end=[3,0],z_min=a,z_max=b,slice_index=i) for i,(a,b) in enumerate(((.3,1.2),(1.5,2.4)))]
    others=[{**f,'start':[3,0],'end':[3,3]} for f in faces]
    first=Wall('a','s',(0,0),(2.9,0),0,3,.2,observed_faces=faces,detection_method='multi_slice')
    second=Wall('b','s',(3,.1),(3,3),0,3,.2,observed_faces=others,detection_method='multi_slice')
    report=_snap_walls([first,second],ReconstructionSettings())
    assert np.linalg.norm(np.array(first.end)-second.start)<=.05
    assert report['connectivity']['counts']['supported_corner']==2
    first=Wall('a','s',(0,0),(2.9,0),0,3,.2,observed_faces=[{**f,'end':[2.7,0]} for f in faces],detection_method='multi_slice')
    second=Wall('b','s',(3,.1),(3,3),0,3,.2,observed_faces=others,detection_method='multi_slice')
    report=_snap_walls([first,second],ReconstructionSettings())
    assert first.end==(2.9,0)
    assert report['connectivity']['counts']['rejected_correction']>=1


def test_single_height_patch_does_not_become_full_storey_wall():
    points=cloud_face()
    assert not detect_walls(points[(points[:,2]>=1.1)&(points[:,2]<1.3)],level(),ReconstructionSettings(),1)


def test_recessed_window_plane_does_not_shorten_host_as_opposite_wall_face():
    points=cloud_face()
    recess=(points[:,0]>=1)&(points[:,0]<2.5)&(points[:,2]>=.9)&(points[:,2]<2.1)
    points[recess,1]=.12
    walls=detect_walls(points,level(),ReconstructionSettings(),1)
    host=max(walls,key=lambda w:abs(w.end[0]-w.start[0]))
    assert abs(host.end[0]-host.start[0])>5.9
    assert host.classification!='paired_faces'
    assert detect_openings(CloudData(points),[host],ReconstructionSettings(),1)


def test_oversized_void_is_not_bridged_as_solid_wall():
    points=cloud_face()
    void=(points[:,0]>.7)&(points[:,0]<5.3)&(points[:,2]>.5)&(points[:,2]<2.5)
    walls=detect_walls(points[~void],level(),ReconstructionSettings(),1)
    assert walls
    assert all(abs(w.end[0]-w.start[0])<2 for w in walls)


def test_exact_storey_working_set_preserves_cropped_source_identities(monkeypatch,tmp_path):
    from punctora_core import sampling
    from punctora_core.evidence import storey_source_cloud,write_wall_evidence
    points=cloud_face();rows=np.arange(len(points),dtype=np.int64)
    cloud=CloudData(points,scan_index=(rows%2).astype(np.int32),source_record_index=rows+1000,working_index=rows+500)
    monkeypatch.setattr(sampling,'available_memory_bytes',lambda:10**10)
    scoped=storey_source_cloud(cloud,.5,2.,317,10**9)
    keep=(points[:,2]>=.5)&(points[:,2]<=2.)
    assert scoped is not cloud
    assert np.array_equal(scoped.points,points[keep])
    assert np.array_equal(scoped.working_index,cloud.working_index[keep])
    assert np.array_equal(scoped.source_record_index,cloud.source_record_index[keep])
    assert np.array_equal(scoped.scan_index,cloud.scan_index[keep])
    wall=Wall('w','s',(0,0),(6,0),0,3,.2,observed_faces=[dict(start=[0,0],end=[6,0],z_min=.5,z_max=2.)])
    attach_evidence(scoped,[wall],317)
    write_wall_evidence(cloud,[wall],tmp_path/'evidence',317)
    records=np.load(tmp_path/'evidence'/'wall-1.npy')
    assert len(records)==wall.evidence_count
    assert set(records[:,0])==set(cloud.working_index[keep])
    assert np.array_equal(records[:,2]-records[:,0],np.full(len(records),500))
    assert storey_source_cloud(cloud,.5,2.,317,1) is cloud


def test_spatial_wall_cells_preserve_source_records_without_scanning_far_points():
    from punctora_core.spatial_index import SpatialPointIndex
    near = cloud_face()
    far = near + np.array([100., 100., 0.])
    points = np.vstack([near, far])
    rows = np.arange(len(points), dtype=np.int64)
    cloud = CloudData(points, scan_index=(rows % 3).astype(np.int32),
                      source_record_index=rows+700, working_index=rows+900)
    index = SpatialPointIndex.build(cloud, .20)
    face = dict(start=[0,0], end=[6,0], z_min=0, z_max=3)
    local, selected = index.local_cloud([face], .05, .08)
    assert local is not None
    assert len(selected) <= len(points)/2
    assert selected.max() < len(near)
    assert np.array_equal(local.working_index, cloud.working_index[selected])
    assert np.array_equal(local.scan_index, cloud.scan_index[selected])
    assert np.array_equal(local.source_record_index, cloud.source_record_index[selected])
