import json
import numpy as np
import pytest
import ifcopenshell
import ifcopenshell.util.element
from shapely.geometry import Polygon

from punctora_core.cloud_io import CloudData
from punctora_core.features import detect_stairs, derive_stair_slab_openings
from punctora_core.stair_voids import reconcile_stair_voids
from punctora_core.model import BuildingModel, Landing, Slab, SlabOpening, Stair, Storey
from punctora_core.reconstruction import ReconstructionSettings
from punctora_core.ifc_export import write_ifc


def flight_points(start=(0, 0), angle=0, base=0, missing=(), risers=True):
    result = []
    direction = np.array([np.cos(angle), np.sin(angle)])
    side = np.array([-direction[1], direction[0]])
    for i in range(8):
        if i in missing:
            continue
        x, y = np.meshgrid(np.arange(i*.28, (i+1)*.28, .02), np.arange(0, 1.1, .02))
        xy = np.array(start)+x.ravel()[:,None]*direction+y.ravel()[:,None]*side
        result.append(np.column_stack([xy, np.full(x.size, base+(i+1)*.17)]))
        if risers:
            y, z = np.meshgrid(np.arange(0, 1.1, .02), np.arange(base+i*.17, base+(i+1)*.17, .015))
            xy = np.array(start)+i*.28*direction+y.ravel()[:,None]*side
            result.append(np.column_stack([xy, z.ravel()]))
    return np.vstack(result)


def levels():
    footprint = [(-5,-5),(8,-5),(8,8),(-5,8)]
    return [Storey('lower','Lower',0,1.05,footprint),
            Storey('upper','Upper',1.2,3.5,footprint)]


@pytest.mark.parametrize('angle', [0, .63, 1.57])
def test_global_flight_crosses_storey_boundary_and_fits_missing_treads(angle):
    cloud = CloudData(flight_points(angle=angle, missing=(2,5)))
    stats = []
    flights = detect_stairs(cloud, levels(), ReconstructionSettings(), statistics=stats)
    assert len(flights) == 1
    flight = flights[0]
    assert flight.steps == 8
    assert flight.evidence['inferred_missing_step_indices'] == [2,5]
    assert flight.rise == pytest.approx(.17,abs=.01)
    assert flight.going == pytest.approx(.28,abs=.015)
    assert sum(flight.evidence['riser_support_counts']) > 0
    assert flight.storey_id == 'lower'
    assert flight.evidence['upper_storey_id'] == 'upper'
    assert len(stats) == 1 and stats[0]['storey_id'] == 'building'


@pytest.mark.parametrize('turn', ['L', 'U'])
def test_global_system_groups_changed_directions_only_through_landing(turn):
    first = flight_points(risers=False)
    if turn == 'L':
        second = flight_points(start=(3.1,0),angle=np.pi/2,base=1.44,risers=False)
        x,y = np.meshgrid(np.arange(2.24,3.34,.02),np.arange(0,1.1,.02))
    else:
        second = flight_points(start=(2.24,2.7),angle=np.pi,base=1.44,risers=False)
        x,y = np.meshgrid(np.arange(2.24,3.34,.02),np.arange(0,2.7,.02))
    landing = np.column_stack([x.ravel(),y.ravel(),np.full(x.size,1.44)])
    landings = []
    flights = detect_stairs(CloudData(np.vstack([first,second,landing])),levels(),
                           ReconstructionSettings(),landing_output=landings)
    assert len(flights) == 2
    assert len({f.system_id for f in flights}) == 1
    assert any(set(l.connected_stair_ids) == {f.id for f in flights} for l in landings)
    disconnected = detect_stairs(CloudData(np.vstack([first,second])),levels(),ReconstructionSettings())
    assert len({f.system_id for f in disconnected}) == 2


def test_observed_partial_hole_is_preserved_and_headroom_is_cut_and_exported(tmp_path):
    footprint = [(0,0),(10,0),(10,10),(0,10)]
    storeys = [Storey('lower','Lower',0,3,footprint),Storey('upper','Upper',3.2,6,footprint)]
    stair = Stair('flight','lower',(2,2),(6,2),0,1,.2,.25,16,system_id='system',flight_index=1,
                  evidence={'inferred_missing_step_indices':[4]}, review_state='reviewed')
    slab = Slab('slab','upper',footprint,3,.2)
    observed = SlabOpening('observed','slab',(5,2),(6,2),.7,
                           footprint=[(5,1.65),(6,1.65),(6,2.35),(5,2.35)])
    cuts,_ = derive_stair_slab_openings([stair],[slab])
    holes,report = reconcile_stair_voids([slab],[observed],cuts,[stair],[])
    assert holes[0] is observed
    assert observed.evidence['stair_validation'] == 'supported_by_stair_envelope'
    assert cuts[0].evidence['additional_cut_area_m2'] > 0
    assert cuts[0].evidence['boundary_justification']['flights'] == ['flight']
    assert report[0]['physical_intersection_area_m2'] == pytest.approx(0)
    assert report[0]['headroom_residual_area_m2'] == pytest.approx(0)
    model = BuildingModel('Global stairs',storeys,stairs=[stair],slabs=[slab],slab_openings=holes)
    assert BuildingModel.from_dict(model.to_dict()).to_dict() == model.to_dict()
    validation = write_ifc(model,tmp_path/'stairs.ifc')
    assert validation['valid']
    assert validation['stairwell_verification'][0]['solid_source'] == 'reopened_ifc_cap_mesh'
    assert validation['stairwell_verification'][0]['status'] == 'clear'
    reopened = ifcopenshell.open(tmp_path/'stairs.ifc')
    assert len(reopened.by_type('IfcStair')) == len(reopened.by_type('IfcStairFlight')) == 1
    flight = reopened.by_type('IfcStairFlight')[0]
    assert any(r.RelatingStructure.Name == 'Lower' for r in flight.ReferencedInStructures)
    assert len(reopened.by_type('IfcRelVoidsElement')) == 1
    assert observed.evidence.get('validation_state') != 'validated'
    psets = ifcopenshell.util.element.get_psets(reopened.by_type('IfcStairFlight')[0])
    assert json.loads(psets['Punctora_Reconstruction']['GeometricEvidence'])['inferred_missing_step_indices'] == [4]


def test_collision_check_reports_missing_void_instead_of_claiming_success():
    stair = Stair('f','s',(0,0),(2,0),0,1,.2,.25,8, review_state='reviewed')
    slab = Slab('slab','s',[(-1,-1),(4,-1),(4,2),(-1,2)],1,.2)
    _, report = reconcile_stair_voids([slab],[],[],[stair],[])
    assert report[0]['status'] == 'review_required'
    assert report[0]['physical_intersection_area_m2'] > 0


def test_roof_headroom_is_checked_without_exact_flight_endpoint_match():
    stair = Stair('f','s',(0,0),(2,0),0,1,.2,.25,8, review_state='reviewed')
    slab = Slab('roof','s',[(-1,-1),(4,-1),(4,2),(-1,2)],3,.2,'NOTDEFINED')
    candidates,_ = derive_stair_slab_openings([stair],[slab],headroom_m=2)
    assert candidates
    assert candidates[0].evidence['source_step_indices']['f'] == [5,6,7]
    _,report = reconcile_stair_voids([slab],[],candidates,[stair],[],headroom_m=2)
    assert report[0]['headroom_residual_area_m2'] == pytest.approx(0)
    _,uncut = reconcile_stair_voids([slab],[],[],[stair],[],headroom_m=2)
    assert uncut[0]['physical_intersection_area_m2'] == 0
    assert uncut[0]['headroom_residual_area_m2'] > 0


def test_terminal_tread_requires_an_independently_supported_landing():
    treads = flight_points(missing=(7,),risers=False)
    without = detect_stairs(CloudData(treads),levels(),ReconstructionSettings())
    assert without[0].steps == 7
    x,y = np.meshgrid(np.arange(1.96,3.1,.02),np.arange(0,1.1,.02))
    landing = np.column_stack([x.ravel(),y.ravel(),np.full(x.size,1.36)])
    flights = detect_stairs(CloudData(np.vstack([treads,landing])),levels(),ReconstructionSettings())
    assert len(flights) == 1 and flights[0].steps == 8
    assert flights[0].evidence['inferred_missing_step_indices'] == [7]
    assert flights[0].evidence['landing_anchored_terminal_step']['support_area_fraction'] >= .5


def test_floor_integrated_landing_does_not_duplicate_or_cut_its_floor(tmp_path):
    footprint = [(-1,-1),(4,-1),(4,2),(-1,2)]
    stair = Stair('f','s',(0,0),(2,0),.2,1,.2,.25,8,system_id='system')
    floor = Slab('floor','s',footprint,0,.2)
    landing = Landing('landing','s',[(-.5,-.5),(.5,-.5),(.5,.5),(-.5,.5)],.08,.12,
                      'system',['f'],evidence={'floor_integrated':True,'source_floor_id':'floor'})
    candidates,_ = derive_stair_slab_openings([stair],[floor],[landing])
    assert not candidates
    _,report = reconcile_stair_voids([floor],[],[],[stair],[landing])
    assert report[0]['status'] == 'clear'
    model = BuildingModel('Integrated landing',[Storey('s','Storey',.2,3.5,footprint)],
                          slabs=[floor],stairs=[stair],landings=[landing])
    assert write_ifc(model,tmp_path/'integrated.ifc')['valid']
    file = ifcopenshell.open(tmp_path/'integrated.ifc')
    entity = next(e for e in file.by_type('IfcSlab') if e.PredefinedType == 'LANDING')
    assert entity.Representation is None
    assert entity.Decomposes[0].RelatingObject.is_a('IfcStair')
    assert not file.by_type('IfcOpeningElement')
    from punctora_core.projects import edit_model
    model.metadata['project_id'] = 'integration-test'
    state = {'project_id':'integration-test','model':model.to_dict(),
             'coordinate_confirmation':{'z_up':True}}
    changed = edit_model(state,model.to_dict(),'landing',{'base':.3})
    assert changed['landings'][0]['evidence']['floor_integrated'] is False
    assert changed['landings'][0]['review_state'] == 'flagged'


def test_small_host_fragment_is_not_discarded_when_it_obstructs_headroom():
    stair = Stair('f','s',(0,0),(4,0),0,1,.2,.25,16, review_state='reviewed')
    slab = Slab('fragment','s',[(2,-.51),(2.04,-.51),(2.04,-.49),(2,-.49)],3,.2)
    candidates,_ = derive_stair_slab_openings([stair],[slab])
    assert len(candidates) == 1
    assert Polygon(candidates[0].footprint).area < .05
    _,report = reconcile_stair_voids([slab],[],candidates,[stair],[])
    assert report[0]['headroom_residual_area_m2'] == pytest.approx(0)


def test_observed_slab_face_anchors_missing_terminal_tread_and_cross_storey_system():
    first = flight_points(missing=(7,),risers=False)
    second = flight_points(start=(3.1,0),angle=np.pi/2,base=1.36,risers=False)
    surface = {'geometry':Polygon([(1.96,0),(3.34,0),(3.34,1.1),(1.96,1.1)]),
               'z':1.36,'count':1000,'coverage':1.,'zone_index':1,
               'source_working_row_examples':[1,2,3]}
    landings = []
    flights = detect_stairs(CloudData(np.vstack([first,second])),levels(),ReconstructionSettings(),
                           landing_output=landings,floor_surfaces=[surface])
    assert len(flights) == 2 and len({f.system_id for f in flights}) == 1
    assert flights[0].steps == 8
    assert flights[0].evidence['inferred_missing_step_indices'] == [7]
    assert len(landings) == 1
    assert landings[0].evidence['source_slab_zone_index'] == 1
    assert Polygon(landings[0].footprint).difference(surface['geometry']).area == pytest.approx(0)


def test_sparse_horizontal_noise_between_treads_does_not_merge_all_height_bins():
    # Reproduces the field failure without shipping customer points: unrelated
    # small surfaces fill the Z bins between broad, genuine tread surfaces.
    noise = []
    for index,z in enumerate(np.arange(.033,1.4,.03)):
        x,y = np.meshgrid(np.arange(0,.14,.02),np.arange(0,.14,.02))
        noise.append(np.column_stack([x.ravel()+3+(index%5)*.3,
                                      y.ravel()+3+(index//5)*.3,np.full(x.size,z)]))
    cloud = CloudData(np.vstack([flight_points(risers=False),*noise]))
    flights = detect_stairs(cloud,levels(),ReconstructionSettings())
    assert len(flights) == 1
    assert flights[0].steps == 8
    assert flights[0].rise == pytest.approx(.17,abs=.01)
