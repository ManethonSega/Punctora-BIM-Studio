"""Slab gaps require independent evidence; legacy occlusion never proves clearance."""
import numpy as np
import pytest
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.shape
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from punctora_core.model import BuildingModel, Slab, SlabOpening, Storey, slab_opening_is_validated
from punctora_core.slab_zones import Surface, slab_zone_geometry, consolidate_scan_fragments
from punctora_core.reconstruction import ReconstructionSettings
from punctora_core.features import detect_stairs, derive_stair_slab_openings
from punctora_core.stair_voids import reconcile_stair_voids
from punctora_core.ifc_export import write_ifc
from punctora_core.projects import edit_model
from punctora_core.cloud_io import CloudData
from test_global_stairs import flight_points, levels


def zone_model(lower, upper, paired=True):
    surfaces = [Surface(z, shape, shape, np.arange(100), 1., (0.,0.,1.))
                for z,shape in [(1.05, lower), (1.25, upper)]]
    zone = dict(lower=0, upper=1, paired=paired, bottom_m=1.05,
                top_m=1.25, estimated_thickness_m=.2, confidence=.8)
    storey = Storey('s','Storey',0,3,list(box(-5,-5,20,20).exterior.coords)[:-1])
    slabs, gaps = slab_zone_geometry([zone], surfaces, [storey], ReconstructionSettings())
    return BuildingModel('Slab safety',[storey],slabs=slabs,slab_openings=gaps,
                         metadata={'project_id':'slab-safety'})


def volume(file):
    settings=ifcopenshell.geom.settings()
    total = 0.0
    for slab in file.by_type("IfcSlab"):
        shape = ifcopenshell.geom.create_shape(settings, slab)
        total += ifcopenshell.util.shape.get_volume(shape.geometry)
    return total


def preview_area(model):
    return sum(Polygon(t).area for slab in model.to_dict()['slabs']
               for t in slab['preview_geometry']['surface_triangles_xy'])


def fixture_shape():
    lamps=[box(.5+i%11*1.1,.5+i//11*2,.5+i%11*1.1+.6,.5+i//11*2+.6)
           for i in range(33)]
    return box(0,0,13,7).difference(unary_union(lamps))


@pytest.mark.parametrize('paired_pattern',[True,False])
def test_33_light_fixture_gaps_create_zero_ifc_cuts(tmp_path,paired_pattern):
    shape=fixture_shape()
    model=zone_model(shape,shape if paired_pattern else box(0,0,13,7))
    assert len(model.slab_openings)==33
    assert all(o.evidence['classification']=='light_fixture_pattern' for o in model.slab_openings)
    assert not any(slab_opening_is_validated(o) for o in model.slab_openings)
    assert preview_area(model)==pytest.approx(91)
    report=write_ifc(model,tmp_path/'lamps.ifc')
    file=ifcopenshell.open(tmp_path/'lamps.ifc')
    assert not file.by_type('IfcOpeningElement')
    assert volume(file)==pytest.approx(91*.2)
    assert len(report['slab_cut_policy']['review_only_ids'])==33


def test_matching_independent_faces_validate_a_real_opening(tmp_path):
    shape=box(0,0,8,6).difference(box(2,2,4,4))
    model=zone_model(shape,shape)
    assert len(model.slab_openings)==1
    opening=model.slab_openings[0]
    assert slab_opening_is_validated(opening)
    assert opening.evidence['validation_basis']=='matching_faces'
    assert preview_area(model)==pytest.approx(44)
    write_ifc(model,tmp_path/'matching.ifc')
    file=ifcopenshell.open(tmp_path/'matching.ifc')
    assert len(file.by_type('IfcRelVoidsElement'))==1
    assert volume(file)==pytest.approx(44*.2)


def test_single_face_gap_review_and_explicit_approval_survive_reopen(tmp_path):
    model=zone_model(box(0,0,8,6),box(0,0,8,6).difference(box(2,2,4,4)))
    opening=model.slab_openings[0]
    assert not slab_opening_is_validated(opening)
    assert preview_area(model)==pytest.approx(48)
    state={'project_id':'slab-safety'}
    reviewed=edit_model(state,model.to_dict(),opening.id,{'review_state':'reviewed'})
    assert not reviewed['slab_openings'][0]['preview_geometry']['ifc_cut_eligible']
    approved=edit_model(state,reviewed,opening.id,{'ifc_cut_approved':True})
    restored=BuildingModel.from_dict(approved)
    assert slab_opening_is_validated(restored.slab_openings[0])
    write_ifc(restored,tmp_path/'approved.ifc')
    assert len(ifcopenshell.open(tmp_path/'approved.ifc').by_type('IfcRelVoidsElement'))==1
    changed=edit_model(state,approved,opening.id,{'width':1})
    assert not changed['slab_openings'][0]['preview_geometry']['ifc_cut_eligible']
    assert not changed['slab_openings'][0]['ifc_cut_approved']
    with pytest.raises(ValueError,match='boolean'):
        edit_model(state,approved,opening.id,{'ifc_cut_approved':'yes'})


def test_old_holes_do_not_determine_stairwell_or_hide_clearance_conflicts(tmp_path):
    flights=detect_stairs(CloudData(flight_points()),levels(),ReconstructionSettings())
    assert len(flights)==1
    slab=Slab('floor','upper',[(-5,-5),(8,-5),(8,8),(-5,8)],1.05,.2)
    # Even a legacy "reviewed" hole covering every tread remains unvalidated.
    old=SlabOpening('old-false-hole','floor',(-1,.55),(4,.55),3,
                    review_state='reviewed',evidence={'method':'enclosed_horizontal_occupancy_gap'})
    _,uncut=reconcile_stair_voids([slab],[old],[],flights,[])
    assert uncut[0]['status']=='review_required'
    candidates,_=derive_stair_slab_openings(flights,[slab])
    empty,empty_report=reconcile_stair_voids([slab],[],candidates,flights,[])
    candidates2,_=derive_stair_slab_openings(flights,[slab])
    with_old,report=reconcile_stair_voids([slab],[old],candidates2,flights,[])
    assert candidates2[0].footprint==candidates[0].footprint
    assert candidates2[0].evidence['observed_overlap_m2']==0
    assert report[0]['status']==empty_report[0]['status']=='clear'
    model=BuildingModel('Detected stair',levels(),slabs=[slab],stairs=flights,slab_openings=with_old)
    result=write_ifc(model,tmp_path/'stair.ifc')
    file=ifcopenshell.open(tmp_path/'stair.ifc')
    assert len(file.by_type('IfcStairFlight'))==1
    assert len(file.by_type('IfcRelVoidsElement'))==1
    assert result['stairwell_verification'][0]['status']=='clear'
    expected=(Polygon(slab.footprint).area-Polygon(candidates[0].footprint).area)*slab.thickness
    assert volume(file)==pytest.approx(expected,abs=1e-5)
    flights[0].review_state='rejected'
    assert not slab_opening_is_validated(candidates2[0],flights)


def test_scan_seams_consolidate_without_hull_or_distant_bridge():
    a=box(0,0,3,4).difference(box(1,1,2,2))
    b=box(3.1,0,6,4)
    distant=box(8,0,9,4)
    joined,area=consolidate_scan_fragments(unary_union([a,b,distant]),.16)
    assert len(joined.geoms)==2
    assert area==pytest.approx(.4)
    assert not joined.covers(box(1,1,2,2).centroid)
    assert not joined.covers(box(6.2,0,7.8,4).centroid)
    model=zone_model(unary_union([a,b]),unary_union([a,b]))
    assert len(model.slabs)==1
    assert model.slabs[0].evidence['scan_seam_inferred_area_m2']==pytest.approx(.4)


def test_unconfirmed_stair_proposals_and_stale_sources_remain_filled():
    from punctora_core.model import Stair
    stair=Stair('proposal','s',(0,0),(2,0),0,1,.2,.25,8)
    slab=Slab('floor','s',[(-1,-1),(4,-1),(4,2),(-1,2)],1,.2)
    openings,_=derive_stair_slab_openings([stair],[slab])
    assert openings and not slab_opening_is_validated(openings[0],[stair])
    _,report=reconcile_stair_voids([slab],[],openings,[stair],[])
    assert report[0]['status']=='review_required'
    stair.review_state='reviewed'
    validated,_=derive_stair_slab_openings([stair],[slab])
    assert slab_opening_is_validated(validated[0],[stair])
    model=BuildingModel('Source edit',[Storey('s','s',0,3,slab.footprint)],
                        stairs=[stair],slabs=[slab],slab_openings=validated,
                        metadata={'project_id':'slab-safety'})
    data=edit_model({'project_id':'slab-safety'},model.to_dict(),stair.id,{'width':.9})
    assert not data['slab_openings'][0]['preview_geometry']['ifc_cut_eligible']
    assert data['slab_openings'][0]['review_state']=='flagged'
