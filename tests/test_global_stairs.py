import json
import numpy as np
import pytest
import ifcopenshell
import ifcopenshell.util.element
from shapely.geometry import Polygon

from punctora_core.cloud_io import CloudData
from punctora_core.features import detect_stairs, derive_stair_slab_openings
from punctora_core.stair_voids import reconcile_stair_voids
from punctora_core.model import BuildingModel, Slab, SlabOpening, Stair, Storey
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
                  evidence={'inferred_missing_step_indices':[4]})
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
    reopened = ifcopenshell.open(tmp_path/'stairs.ifc')
    assert len(reopened.by_type('IfcStair')) == len(reopened.by_type('IfcStairFlight')) == 1
    assert len(reopened.by_type('IfcRelVoidsElement')) == 2
    psets = ifcopenshell.util.element.get_psets(reopened.by_type('IfcStairFlight')[0])
    assert json.loads(psets['Punctora_Reconstruction']['GeometricEvidence'])['inferred_missing_step_indices'] == [4]


def test_collision_check_reports_missing_void_instead_of_claiming_success():
    stair = Stair('f','s',(0,0),(2,0),0,1,.2,.25,8)
    slab = Slab('slab','s',[(-1,-1),(4,-1),(4,2),(-1,2)],1,.2)
    _, report = reconcile_stair_voids([slab],[],[],[stair],[])
    assert report[0]['status'] == 'review_required'
    assert report[0]['physical_intersection_area_m2'] > 0
