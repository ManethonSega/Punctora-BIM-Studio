from copy import deepcopy
import uuid
import json
import numpy as np
import pytest
from punctora_core.model import BuildingModel,Storey,Wall,Opening,Slab
from punctora_core.model_merge import merge_models
from punctora_core import projects


def model(project_id='p',source_hash='same',origin=(0,0,0)):
    matrix=np.eye(4);matrix[:3,3]=origin
    metadata={'project_id':project_id,'source':{'sha256':source_hash,'filename':'test.e57'},
              'coordinate_mapping':{'working_to_source_matrix':matrix.tolist(),
                                    'working_to_source_translation_m':list(origin)}}
    return BuildingModel('test',[Storey('s','Level',0,3,[(0,-1),(6,-1),(6,3),(0,3)])],
        walls=[Wall('w','s',(0,0),(6,0),0,3,.2,evidence_count=10,evidence={'records':{'path':'generations/test/w.npy','row_count':10}})],
        openings=[Opening('o','w','window',2,1,1,1)],
        slabs=[Slab('floor','s',[(0,-1),(6,-1),(6,3),(0,3)],-.2,.2)],metadata=metadata)


def test_repeat_add_removes_duplicates_preserves_edits_and_evidence():
    existing=model();incoming=model()
    existing.walls[0].thickness=.27;existing.walls[0].provenance['thickness']='user_supplied'
    existing.walls[0].review_state='reviewed'
    result,report=merge_models(existing,incoming)
    assert len(result.walls)==1 and len(result.openings)==1 and len(result.slabs)==1
    assert result.walls[0].thickness==.27 and result.walls[0].review_state=='reviewed'
    assert result.walls[0].evidence['records']==existing.walls[0].evidence['records']
    assert result.walls[0].evidence['additional_sources'][0]['evidence']['records']==incoming.walls[0].evidence['records']
    assert report['duplicates_removed']=={'walls':1,'slabs':1,'openings':1,'stairs':0,'landings':0}
    again,_=merge_models(result,incoming)
    assert len(again.walls)==1 and len(again.openings)==1
    assert incoming.walls[0].id=='w' and not incoming.walls[0].evidence.get('source_context')


def test_different_origins_are_aligned_before_deduplication_and_unknown_frames_require_confirmation():
    target=model(project_id='target',source_hash='target',origin=(100,200,30))
    incoming=model(project_id='incoming',source_hash='incoming',origin=(102,201,31))
    incoming.walls[0].start=(-2,-1);incoming.walls[0].end=(4,-1);incoming.walls[0].base=-1
    incoming.storeys[0].elevation=-1;incoming.storeys[0].ceiling=2
    incoming.slabs=[]
    with pytest.raises(ValueError,match='confirmed shared source'):merge_models(target,incoming)
    result,report=merge_models(target,incoming,confirm_shared_frame=True)
    assert len(result.walls)==1 and len(result.openings)==1
    assert np.allclose(np.asarray(report['to_project_matrix'])[:3,3],[2,1,1])
    assert result.walls[0].evidence['additional_sources'][0]['source_context']['source']['sha256']=='incoming'
    tilted=np.eye(4);tilted[2,2]=2
    with pytest.raises(ValueError,match='rigid'):merge_models(target,incoming,alignment_matrix=tilted)


def test_explicit_rotation_adds_distinct_geometry_and_keeps_hosts():
    incoming=model(project_id='incoming',source_hash='incoming');incoming.slabs=[]
    matrix=[[0,-1,0,10],[1,0,0,0],[0,0,1,0],[0,0,0,1]]
    result,report=merge_models(model(),incoming,alignment_matrix=matrix)
    assert len(result.walls)==2 and len(result.openings)==2
    wall=next(w for w in result.walls if w.id!='w')
    opening=next(o for o in result.openings if o.id!='o')
    assert np.allclose(wall.start,[10,0]) and np.allclose(wall.end,[10,6])
    assert opening.host_wall_id==wall.id
    BuildingModel.from_dict(result.to_dict()).validate()


def test_saved_project_add_copies_evidence_and_survives_cleanup_reopen_and_ifc(tmp_path):
    target=tmp_path/'target.punctora';source=tmp_path/'source.punctora'
    a=projects.create_project(target,uuid.uuid4().hex);b=projects.create_project(source,uuid.uuid4().hex)
    generation=b['generations'][-1];root=projects.assets_for(source)
    record=root/'generations'/generation/'extra.npy';np.save(record,np.array([[3,0,7]],dtype=np.int64))
    b['model']['walls'][0]['evidence']['records']={'path':f'generations/{generation}/extra.npy','row_count':1}
    projects.atomic_json(source,b)
    result=projects.add_project_model(target,{'expected_revision':a['revision'],'source_project':str(source),
        'confirm_shared_source_frame':True,'job_id':uuid.uuid4().hex})
    projects.cleanup_project(target);reopened=projects.load_project(target)
    additional=reopened['model']['walls'][0]['evidence']['additional_sources'][0]
    copied=projects.assets_for(target)/additional['evidence']['records']['path']
    assert copied.read_bytes()==record.read_bytes()
    assert len(reopened['model']['walls'])==len(a['model']['walls'])
    exported=projects.export_project(target,{'expected_revision':result['revision'],
        'model':result['model'],'output':str(tmp_path/'combined.ifc')})
    assert exported['validation']['valid']


def test_additive_redetection_retains_old_generations_and_current_model(tmp_path):
    path=tmp_path/'run.punctora';state=projects.create_project(path,uuid.uuid4().hex)
    old_model=deepcopy(state['model']);old_generations=list(state['generations'])
    result=projects.reconstruct_project(path,{'expected_revision':state['revision'],'confirm_z_up':True,
        'job_id':uuid.uuid4().hex,'model_action':'add'})
    assert set(old_generations)<=set(result['generations'])
    assert result['model']['metadata']['additive_runs']
    assert len(result['model']['walls'])>=len(old_model['walls'])
    projects.cleanup_project(path);projects.load_project(path)
