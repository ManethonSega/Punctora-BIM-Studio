from copy import deepcopy
from math import dist
import json
import uuid

import pytest
from punctora_core.model import BuildingModel, Opening, Storey, Wall
from punctora_core.opening_bounds import validate_generated_openings, invalidate_changed_facade_groups
from punctora_core.wall_editing import (rehost_reconciled_openings,
    merge_reconciled_openings, reconcile_opening_supported_faces)
from punctora_core import features, projects


def host(identifier='host',length=3.,base=0.,height=3.,plane=0.):
    return Wall(identifier,'s',(0,plane),(length,plane),base,height,.2,
        observed_faces=[dict(start=[0,plane],end=[length,plane],z_min=base,z_max=base+height)]*2,
        evidence={'vertical_continuity':.4})


def test_oversized_transfer_uses_a_fully_containing_host_without_shrinking():
    source,short,long=host('source'),host('short',2.95),host('long',4.,plane=.1)
    opening=Opening('wide','source','window',0,.5,3.,1.)
    carried=rehost_reconciled_openings([opening],[source],[short,long],{'source'})
    assert len(carried)==1 and carried[0].host_wall_id=='long'
    assert (carried[0].offset,carried[0].width)==(0.,3.)
    assert opening.host_wall_id=='source' and opening.width==3.


def test_unhosted_supported_dimensions_and_world_pose_are_retained_for_review():
    source,short=host('source',base=4.),host('short',2.95,base=4.)
    opening=Opening('wide','source','window',0,.5,3.,1.,evidence={'edge_support':[.9]*4})
    reports=[]
    assert not rehost_reconciled_openings([opening],[source],[short],{'source'},diagnostics=reports)
    report=reports[0]
    assert report['action']=='review_only'
    assert report['opening']['width']==3. and report['opening']['evidence']==opening.evidence
    assert report['world_bounds']['bottom_z_m']==4.5
    assert report['world_bounds']['end_xy']==[3.,0.]


def test_transfer_translates_sill_to_preserve_absolute_elevation():
    source,target=host('source',base=4.),host('target',base=4.25,height=2.75)
    opening=Opening('window','source','window',.4,1.,1.,1.)
    moved=rehost_reconciled_openings([opening],[source],[target],{'source'})[0]
    assert moved.sill==.75 and target.base+moved.sill==source.base+opening.sill
    assert moved.height==opening.height
    too_low=host('low',base=4.,height=1.8)
    assert not rehost_reconciled_openings([opening],[source],[too_low],{'source'})


def test_opposite_faces_match_openings_in_world_height_not_relative_sill():
    first,second=host('first',length=6.,height=4.),host('second',length=6.,base=1.,height=3.,plane=.2)
    openings=[Opening('a','first','window',2.,1.2,1.,1.),
              Opening('b','second','window',2.,.2,1.,1.)]
    final,_,replaced,report=reconcile_opening_supported_faces([first,second],openings)
    assert report and replaced=={'first','second'}
    moved=rehost_reconciled_openings(openings,[first,second],final,replaced)
    assert len(moved)==2 and all(o.sill==pytest.approx(.2) for o in moved)
    merged=merge_reconciled_openings([],moved,[],final)
    assert len(merged)==1


def test_separate_height_bands_are_neither_paired_nor_deduplicated():
    lower,upper=host('lower',length=6.),host('upper',length=6.,base=4.,plane=.2)
    openings=[Opening('a','lower','window',2.,1.,1.,1.),Opening('b','upper','window',2.,1.,1.,1.)]
    assert not reconcile_opening_supported_faces([lower,upper],openings)[3]
    assert len(merge_reconciled_openings(openings,[],[],[lower,upper]))==2


def test_boundary_guard_repairs_roundoff_and_keeps_material_conflicts_out_of_ifc():
    wall=host()
    numerical=Opening('epsilon','host','window',-2e-7,.5,3.+4e-7,1.)
    conflict=Opening('oversized','host','window',0,.5,3.05,1.)
    original=deepcopy([numerical,conflict])
    accepted,reports=validate_generated_openings([numerical,conflict],[wall])
    assert len(accepted)==1 and accepted[0].offset==0 and accepted[0].width==3.
    assert [r['action'] for r in reports]==['numerical_clamp','review_only']
    assert numerical==original[0] and conflict==original[1]
    assert wall.evidence['opening_review_candidates'][0]['opening']['width']==3.05
    model=BuildingModel('Bounds',[Storey('s','S',0,3,[(0,0),(4,0),(4,2),(0,2)])],
                        walls=[wall],openings=accepted)
    model.validate()
    model.openings=[conflict]
    with pytest.raises(ValueError,match='Opening exceeds its host wall: oversized on host'):
        model.validate()


def test_one_bad_bay_does_not_discard_an_unrelated_curtain_system():
    wall=host()
    first=Opening('first','host','window',.1,.5,1.,1.,
        evidence={'facade_system':{'system_id':'changed','representation':'curtain_wall'}})
    other=Opening('other','host','window',1.5,.5,1.,1.,
        evidence={'facade_system':{'system_id':'keep','representation':'curtain_wall'}})
    bad=Opening('bad','host','window',0,.5,3.05,1.,
        evidence={'facade_system':{'system_id':'changed','representation':'curtain_wall'}})
    accepted,reports=validate_generated_openings([first,other,bad],[wall])
    invalidate_changed_facade_groups(accepted,reports)
    assert 'facade_system' not in first.evidence
    assert other.evidence['facade_system']['representation']=='curtain_wall'


def test_detect_save_reopen_export_survives_one_invalid_automatic_proposal(tmp_path,monkeypatch):
    path=tmp_path/'exterior.punctora'
    state=projects.create_project(path,uuid.uuid4().hex)
    detect=features.detect_openings
    def invalid_candidate(cloud,walls,settings,*args,**kwargs):
        openings=detect(cloud,walls,settings,*args,**kwargs)
        if walls:
            w=walls[0]
            openings.append(Opening('outside-host',w.id,'window',0,.2,
                dist(w.start,w.end)+1.,.6,evidence={'original_frame':'retained'}))
        return openings
    monkeypatch.setattr(features,'detect_openings',invalid_candidate)
    result=projects.reconstruct_project(path,{'job_id':uuid.uuid4().hex,
        'expected_revision':state['revision'],'confirm_z_up':True,
        'reconstruction_options':{'scope':'exterior','manual_levels':[]},
        'settings':{'cpu_workers':1,'detect_stairs_enabled':False}})
    model=result['model']
    assert model['walls'] and not model['slabs']
    reports=model['metadata']['opening_boundary_validation']
    assert any(r['action']=='review_only' and r['opening']['evidence'].get('original_frame')=='retained'
               for r in reports)
    assert any('retained for review' in warning for warning in model['warnings'])
    assert projects.load_project(path)['model']['metadata']['opening_boundary_validation']==reports
    exported=projects.export_project(path,{'expected_revision':result['revision'],
        'model':model,'output':str(tmp_path/'safe.ifc')})
    assert exported['validation']['valid']
    assert json.loads(json.dumps(reports))==reports
