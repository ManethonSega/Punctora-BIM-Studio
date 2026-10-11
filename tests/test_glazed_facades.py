"""Observed façade frame geometry, IFC assembly/fallback and doorway regression."""
import numpy as np
import pytest
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
from punctora_core.cloud_io import CloudData
from punctora_core.features import detect_openings
from punctora_core.glazed_facades import supported_facade_groups
from punctora_core.ifc_export import create_ifc, validate_ifc
from punctora_core.model import BuildingModel, Storey, Wall
from punctora_core.projects import edit_model
from punctora_core.reconstruction import ReconstructionSettings, reconstruct
from punctora_core.spatial_index import SpatialPointIndex


def facade(pier=.1, recess=False, angle=0., height=4., sill=.1):
    panel=1.9
    length=6*panel+7*pier
    x,z=np.meshgrid(np.arange(.006,length,.02),np.arange(.006,height,.02))
    points=np.column_stack([x.ravel(),np.full(x.size,.1),z.ravel()])
    bays=np.zeros(len(points),bool)
    for i in range(6):
        left=pier+i*(panel+pier)
        bays|=(points[:,0]>=left)&(points[:,0]<left+panel)&(points[:,2]>=sill)&(points[:,2]<height-.1)
    if recess:
        points[bays,1]=.02
    else:
        points=points[~bays]
    rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    shift=np.array([125.123456789,-37.987654321])
    points[:,:2]=points[:,:2]@rotation.T+shift
    wall=Wall('facade','s',tuple(shift),tuple(np.array([length,0.])@rotation.T+shift),0.,height,.2,
        observed_faces=[{'start':(np.array([0.,.1])@rotation.T+shift).tolist(),
                         'end':(np.array([length,.1])@rotation.T+shift).tolist(),'z_min':0.,'z_max':height}])
    cloud=CloudData(points,scan_index=np.arange(len(points),dtype=np.uint32)%7,
        source_record_index=np.arange(len(points),dtype=np.uint64)+np.uint64(2**53+1))
    return cloud,wall


def model_for(wall,openings):
    return BuildingModel('Facade',[Storey('s','Ground',0.,4.,[(120,-40),(150,-40),(150,-10),(120,-10)])],
                         walls=[wall],openings=openings,metadata={'project_id':'test-facade'})


@pytest.mark.parametrize('recess,angle',[(False,0.),(True,0.),(False,.63),(True,1.57)])
def test_long_full_height_facade_has_six_window_bays_and_original_ids(recess,angle):
    cloud,wall=facade(recess=recess,angle=angle)
    before=[a.copy() for a in (cloud.points,cloud.scan_index,cloud.source_record_index)]
    openings=detect_openings(cloud,[wall],ReconstructionSettings())
    assert len(openings)==6
    assert all(o.kind=='window' and o.height>3.7 for o in openings)
    assert all(o.evidence['classification']=='floor_to_ceiling_glazing' for o in openings)
    assert all(not o.evidence['doorway_evidence']['supported'] for o in openings)
    frame=openings[0].evidence['facade_system']
    assert frame['representation']=='curtain_wall' and len(frame['mullions'])==5
    assert sum(o.width*o.height for o in openings)>.85*wall.height*np.linalg.norm(np.array(wall.end)-wall.start)
    for expected,actual in zip(before,(cloud.points,cloud.scan_index,cloud.source_record_index)):
        np.testing.assert_array_equal(expected,actual)


def test_curtain_wall_aggregates_panels_and_mullions_and_removes_opaque_zone():
    cloud,wall=facade(recess=True,angle=.63)
    model=model_for(wall,detect_openings(cloud,[wall],ReconstructionSettings()))
    file=create_ifc(model)
    report=validate_ifc(file)
    assert report['valid'],report
    parents=file.by_type('IfcCurtainWall')
    assert len(parents)==1 and parents[0].Representation is None
    assert len(file.by_type('IfcPlate'))==6 and len(file.by_type('IfcMember'))==5
    assert file.by_type('IfcSurfaceStyleRendering')[0].Transparency==.65
    assert not file.by_type('IfcDoor') and not file.by_type('IfcWindow')
    assert len(parents[0].IsDecomposedBy[0].RelatedObjects)==11
    assert parents[0].FillsVoids[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement==file.by_type('IfcWall')[0]
    settings=ifcopenshell.geom.settings()
    shape=ifcopenshell.geom.create_shape(settings,file.by_type('IfcWall')[0])
    assert ifcopenshell.util.shape.get_volume(shape.geometry)<.2*wall.height*np.linalg.norm(np.array(wall.end)-wall.start)*.2
    assert 'unverified' in ifcopenshell.util.element.get_psets(parents[0])['Punctora_Reconstruction']['RepresentationScope']


def test_wider_piers_export_repeated_windows_without_curtain_wall():
    cloud,wall=facade(pier=.4)
    model=model_for(wall,detect_openings(cloud,[wall],ReconstructionSettings()))
    assert len(model.openings)==6
    assert all(o.evidence['facade_system']['representation']=='repeated_windows' for o in model.openings)
    file=create_ifc(model)
    assert len(file.by_type('IfcWindow'))==6 and not file.by_type('IfcCurtainWall')
    assert validate_ifc(file)['valid']


@pytest.mark.parametrize('change',[{'width':1.8},{'review_state':'rejected'},{'review_state':'flagged'},{'kind':'door'}])
def test_changed_bay_invalidates_whole_zone_cut(change):
    cloud,wall=facade()
    original=model_for(wall,detect_openings(cloud,[wall],ReconstructionSettings()))
    data=edit_model({'project_id':'test-facade'},original.to_dict(),original.openings[0].id,change)
    model=BuildingModel.from_dict(data)
    assert not supported_facade_groups(model)
    file=create_ifc(model)
    assert not file.by_type('IfcCurtainWall')
    assert len(file.by_type('IfcOpeningElement'))==(5 if change.get('review_state')=='rejected' else 6)


def test_solid_and_unframed_clouds_do_not_create_facade_openings():
    cloud,wall=facade(recess=True)
    cloud.points[:, :2] += np.column_stack([np.zeros(len(cloud.points)),.1-cloud.points[:,1]])
    assert not detect_openings(cloud,[wall],ReconstructionSettings())
    assert not detect_openings(CloudData(cloud.points[::100]),[wall],ReconstructionSettings())


def test_indexed_facade_matches_full_cloud_and_excludes_remote_points():
    cloud,wall=facade(recess=True,angle=.63)
    points=np.vstack([cloud.points,cloud.points+[80.,0.,6.]])
    combined=CloudData(points,scan_index=np.tile(cloud.scan_index,2),
                       source_record_index=np.tile(cloud.source_record_index,2))
    settings=ReconstructionSettings()
    expected=detect_openings(combined,[wall],settings)
    index=SpatialPointIndex.build(combined,memory_budget_bytes=128*1024**2)
    try:
        actual=detect_openings(combined,[wall],settings,spatial_index=index)
        assert [o.__dict__ for o in actual]==[o.__dict__ for o in expected]
        assert index.report('openings')['unique_points_visited']<=len(cloud.points)
    finally:
        index.close()


def test_sparse_frame_detected_when_initial_wall_fit_follows_dominant_glass_plane():
    cloud,wall=facade(recess=True)
    for face in wall.observed_faces:
        face['start'][1]-=.08
        face['end'][1]-=.08
    openings=detect_openings(cloud,[wall],ReconstructionSettings())
    assert len(openings)==6 and all(o.kind=='window' for o in openings)
    assert all(o.evidence['facade_system']['representation']=='curtain_wall' for o in openings)
    assert all(o.evidence['face_offset_from_axis_m']==pytest.approx(.1) for o in openings)


def test_full_reconstruction_finds_facade_without_supplied_wall_geometry():
    cloud,wall=facade(recess=True)
    start=np.asarray(wall.start)
    length=np.linalg.norm(np.asarray(wall.end)-start)
    x,y=np.meshgrid(np.arange(0,length,.06),np.arange(-3,0,.06))
    floor=np.column_stack([x.ravel()+start[0],y.ravel()+start[1],np.zeros(x.size)])
    model=reconstruct(CloudData(np.vstack([cloud.points,floor,floor+[0.,0.,4.]])),
        settings=ReconstructionSettings(cpu_workers=1,detect_stairs_enabled=False))
    try:
        assert len(model.walls)==1 and len(model.openings)==6
        assert all(o.kind=='window' for o in model.openings)
        file=create_ifc(model)
        assert len(file.by_type('IfcCurtainWall'))==1 and not file.by_type('IfcDoor')
        assert validate_ifc(file)['valid']
    finally:
        model._spatial_index.close()
