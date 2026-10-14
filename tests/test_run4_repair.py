from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import time
import numpy as np
import pytest
from shapely.geometry import Polygon, box

from punctora_core.cloud_io import CloudData
from punctora_core.model import BuildingModel, Storey, Wall
from punctora_core.reconstruction import ReconstructionSettings
from punctora_core.recognition.streaming_views import SourceBox, plan_image, stitch_proposals
from punctora_core.recognition.specialist_frames import plan_frame, rasterize_plan
from punctora_core.recognition.tiling import TileIndex, TileSettings, TileOverflow
from punctora_core.recognition.geometry_fusion import fuse_geometry
from punctora_core.recognition.job import run_recognition
from punctora_core.recognition.contracts import load_proposal_set, open_proposal_array
from punctora_core.ceiling_completion import complete_ceiling_rooms
from punctora_core.project_storage import storage_report


class Control:
    chunk_points=31
    working_budget=2**30
    cancelled=staticmethod(lambda:False)
    check=staticmethod(lambda:None)


def source(points):
    n=len(points)
    return CloudData(np.asarray(points,dtype='<f8'),scan_index=np.zeros(n,dtype='<u8'),
        source_record_index=np.arange(2**53,2**53+n,dtype='<u8'),working_index=np.arange(n,dtype='<u8'))


def index_for(cloud,tmp_path,cap=100000):
    return TileIndex(cloud,TileSettings(maximum_context_points=cap),64*1024**2,31,tmp_path)


def test_streamed_dense_raster_is_identical_and_cap_is_per_materialization(tmp_path):
    p=np.array([[x,y,z] for x in np.linspace(-1,1,31) for y in np.linspace(-1,1,31) for z in (1.5,1.6)])
    cloud=source(p);index=index_for(cloud,tmp_path)
    try:
        view=SourceBox(cloud,index.index,[-2,-2,0],[2,2,3],Control(),17)
        frame=plan_frame('dense',[0,0],10.24,1024,30.,True,1.4,1.7)
        expected,_=rasterize_plan(frame,p)
        actual,stats=plan_image(view,frame)
        assert np.array_equal(actual,expected)
        assert stats['input_points']==len(p)>17 and stats['maximum_materialized_points']<=17
    finally:index.close()


def test_exact_core_ownership_reduced_model_context_and_separate_normal_halo(tmp_path):
    p=np.array([[x,y,1.] for x in np.arange(.002,2.,.008) for y in np.arange(.002,2.,.008)])
    cloud=source(p)
    settings=TileSettings(size_m=2.,overlap_m=.03,vertical_overlap_m=.03,normal_radius_m=.3,
        separate_normal_context=True,adaptive_partition=True,maximum_context_points=10000,minimum_core_m=.1)
    index=TileIndex(cloud,settings,128*1024**2,4096,tmp_path)
    pending=list(index.tiles);votes=[];context=0;normal=0
    try:
        while pending:
            try:tile=index.get(pending.pop(0),None)
            except TileOverflow as e:pending[:0]=e.children;continue
            if tile is None:continue
            assert len(tile.points)<=10000
            context+=len(tile.points);normal+=len(tile.normal_points)
            votes.extend(tile.context_rows[tile.vote_mask].tolist())
        assert sorted(votes)==list(range(len(p)))
        assert context/len(p)<2.
        assert normal>context  # Neighbour I/O is separately reported, never hidden as unique work.
    finally:index.close()


def proposal(identifier,polygon):
    return {'id':identifier,'branch':'D','class':'wall','status':'proposed',
        'geometry_authority':'review_only','polygon_xy_m':polygon,'z_min_m':0.,'z_max_m':3.}


def test_stitching_is_order_independent_and_does_not_bridge_wall_corners():
    a=proposal('a',list(box(0,0,1,.1).exterior.coords)[:-1]);b=proposal('b',list(box(1.02,0,2,.1).exterior.coords)[:-1])
    c=proposal('c',list(box(2,0,2.1,1).exterior.coords)[:-1])
    supports={'a':np.array([1,2],dtype='<u8'),'b':np.array([3],dtype='<u8'),'c':np.array([4],dtype='<u8')}
    first,refs=stitch_proposals([a,b,c],supports)
    second,other=stitch_proposals([c,b,a],supports)
    assert first==second and len(first)==2
    assert all(np.array_equal(refs[k],other[k]) for k in refs)
    assert any(v.tolist()==[1,2,3] for v in refs.values())


def room_walls():
    ring=[(0,0),(4,0),(4,4),(0,4)]
    return [Wall(str(i),'s',a,b,0,3,.2,evidence_count=100,fit_rmse_m=.005)
            for i,(a,b) in enumerate(zip(ring,ring[1:]+ring[:1]))]


def test_ceiling_completes_fixture_occlusion_but_not_real_void_or_open_boundary():
    owner=Storey('s','S',0,3,[(0,0),(4,0),(4,4),(0,4)])
    hole=box(1.6,1.6,2.4,2.4);raw=box(0,0,4,4).difference(hole)
    completed,added,report=complete_ceiling_rooms(raw,raw,box(0,0,4,4),room_walls(),owner,3,Polygon())
    assert completed.area==pytest.approx(16) and added.area==pytest.approx(.64)
    assert report[0]['state']=='justified_completion'
    protected,_,_=complete_ceiling_rooms(raw,raw,box(0,0,4,4),room_walls(),owner,3,hole)
    assert protected.area==pytest.approx(raw.area)
    opened,addition,_=complete_ceiling_rooms(raw,raw,box(0,0,4,4),room_walls()[:-1],owner,3,Polygon())
    assert addition.is_empty and opened.equals(raw)


def model():
    return BuildingModel('Generated',[Storey('s','S',0,3,[(-1,-1),(5,-1),(5,4),(-1,4)])])


def fusion_fixture(tmp_path,kind='wall',frame=False):
    x,z=np.meshgrid(np.arange(0,4.001,.05),np.arange(0,3.001,.05))
    cloud=source(np.column_stack((x.ravel(),np.zeros(x.size),z.ravel())))
    label={'wall':0,'window':2}[kind]
    labels=np.full(len(cloud.points),label,dtype='<i2')
    if frame:
        p=cloud.points
        labels[(p[:,0]<.11)|(p[:,0]>3.89)|(p[:,2]<.11)|(p[:,2]>2.89)]=0
    rows=np.flatnonzero(labels==label).astype('<u8')
    for name,value in [('labels',labels),('support',rows[:4096])]:np.save(tmp_path/f'{name}.npy',value)
    item=proposal('I:test',[[-.05,-.05],[4.05,-.05],[4.05,.05],[-.05,.05]])
    item.update(branch='I',**{'class':kind})
    (tmp_path/'proposals.json').write_text(json.dumps({'proposals':[item]}))
    (tmp_path/'support.json').write_text(json.dumps({'entries':[{'id':'I:test','offset':0,'count':min(4096,len(rows))}]}))
    manifest={'cache_key':'a'*64,'proposal_sha256':'b'*64,'arrays':{'labels':{'path':'labels.npy'}},
        'extensions':{'specialist_v1':{'proposals_path':'proposals.json','support_index_path':'support.json',
                                     'support_rows':{'path':'support.npy'}}}}
    return cloud,manifest


def test_real_geometry_fusion_adds_missing_wall_from_original_points(tmp_path):
    cloud,manifest=fusion_fixture(tmp_path);index=index_for(cloud,tmp_path);m=model()
    try:report=fuse_geometry(cloud,m,manifest,tmp_path,index.index,Control(),ReconstructionSettings())
    finally:index.close()
    assert len(m.walls)==1 and report['added_wall_ids']==[m.walls[0].id]
    assert m.walls[0].review_state=='unreviewed' and m.walls[0].evidence_count>100
    assert m.walls[0].height==pytest.approx(3) and np.linalg.norm(np.array(m.walls[0].end)-m.walls[0].start)==pytest.approx(4)
    assert report['user_acceptance_changes']==report['accepted_cuts']==0


def test_wall_wide_window_needs_independent_frame_and_no_opaque_host(tmp_path):
    cloud,manifest=fusion_fixture(tmp_path,'window',frame=True);index=index_for(cloud,tmp_path);m=model()
    try:report=fuse_geometry(cloud,m,manifest,tmp_path,index.index,Control(),ReconstructionSettings())
    finally:index.close()
    assert len(m.facade_panels)==1 and not m.walls and not m.openings
    loaded=BuildingModel.from_dict(m.to_dict())
    assert loaded.facade_panels[0].evidence['independent_frame_support_fractions']
    from punctora_core.ifc_export import create_ifc
    file=create_ifc(loaded)
    assert len(file.by_type('IfcWindow'))==1 and not file.by_type('IfcWall') and not file.by_type('IfcOpeningElement')


def test_semantic_window_without_independent_frame_cannot_create_geometry(tmp_path):
    cloud,manifest=fusion_fixture(tmp_path,'window');index=index_for(cloud,tmp_path);m=model()
    try:report=fuse_geometry(cloud,m,manifest,tmp_path,index.index,Control(),ReconstructionSettings())
    finally:index.close()
    assert not m.facade_panels and not m.openings
    assert report['rejected_proposals'][0]['reason']=='independent_frame_support_failed'


def test_runtime_total_cannot_claim_completion_before_publication(tmp_path,monkeypatch):
    from punctora_core import projects
    ticks=iter([10.,11.,3611.])
    monkeypatch.setattr(projects.time,'perf_counter',lambda:next(ticks))
    path=tmp_path/'p.punctora';projects.assets_for(path).mkdir()
    write,_=projects._performance_writer(path,'a'*32,'reconstruct')
    interim=write({'status':'completed','total_seconds':104.,'recognition':{'elapsed_seconds':3500.}})
    final=write({'status':'completed','total_seconds':104.},final=True)
    assert interim['status']=='running' and final['status']=='completed'
    assert final['total_seconds']==3601. and final['geometry_and_evidence_seconds']==104.


def test_storage_counts_hardlinked_original_ids_once_and_retains_them(tmp_path):
    import os
    (tmp_path/'working-cache').mkdir();(tmp_path/'recognition').mkdir()
    values=np.arange(12,dtype='<u8');values.tofile(tmp_path/'working-cache'/'record_ids.bin')
    os.link(tmp_path/'working-cache'/'record_ids.bin',tmp_path/'recognition'/'record_ids.source.bin')
    report=storage_report(tmp_path)
    assert report['total_logical_bytes']==192 and report['total_unique_file_bytes']==96
    assert report['shared_hardlink_bytes']==96
    descriptor={'path':'record_ids.source.bin','storage':'original_raw_hardlink','dtype':'<u8','shape':[12]}
    array=open_proposal_array(tmp_path/'recognition',descriptor)
    try:assert np.array_equal(array,values)
    finally:array._mmap.close()


@pytest.mark.parametrize('failed_branch',[None,'F'])
def test_all_raster_branches_execute_above_old_view_cap_and_cleanup(tmp_path,monkeypatch,failed_branch):
    from test_specialist_provider import make_provider,fixture_resolution,identity
    provider=make_provider(tmp_path,monkeypatch)
    monkeypatch.setattr('punctora_core.recognition.specialist_provider.resolve_model_pack',
                        lambda *a,**k:fixture_resolution('ABCDEFGHIJ'))
    from punctora_core.recognition.specialist_provider import SpecialistSettings
    provider.settings=SpecialistSettings(level_bounds=({'name':'S','bottom_m':100.,'top_m':103.},),
                                         maximum_view_points=17)
    calls=[]
    def image(branch,image,identifier,control):
        calls.append(branch)
        if branch==failed_branch:
            from punctora_core.recognition.contracts import ProviderUnavailable
            raise ProviderUnavailable('Generated single-branch unavailable fixture')
        if branch in 'DEFGH':
            channels=3 if branch in 'DE' else 2
            logits=np.zeros((1,channels,512,512),dtype=np.float32);logits[:,1]=1
            output={'logits':logits}
        else:
            output={'dets':np.zeros((1,300,4),dtype=np.float32),
                    'labels':np.full((1,300,3 if branch=='J' else 2 if branch=='B' else 1),-20.,dtype=np.float32)}
            if branch=='J':output['angles']=np.zeros((1,300,1),dtype=np.float32)
        return output,{'schema_version':1,'status':'complete','branch':branch}
    monkeypatch.setattr(provider,'_infer_image',image)
    x,z=np.meshgrid(np.arange(0,1.,.05),np.arange(100,103.001,.05))
    cloud=source(np.column_stack((x.ravel()+7_000_000.,np.full(x.size,5_000_000.),z.ravel())))
    directory,report,_=run_recognition(cloud,identity(),provider,tmp_path/'cache',
                                      tile_settings=TileSettings(maximum_context_points=10000))
    branches=report['extensions']['specialist_v1']['branches']
    assert set(calls)==set('ABCDEFGHJ')
    assert all(v['status']=='active' and v['executed_views']>0 for b,v in branches.items() if b!=failed_branch)
    if failed_branch:
        assert branches[failed_branch]['status']=='failed' and branches[failed_branch]['failure']
    assert not list(directory.rglob('tensor.npy')) and not list(directory.rglob('feed.json'))
    assert not list((tmp_path/'cache').glob('.proposal-stage-*'))
    assert load_proposal_set(directory)==report


def test_recognition_references_raw_original_ids_without_conversion_or_copy(tmp_path):
    from test_recognition import FixtureProvider,identity,tiles
    cloud=source(np.array([[.2,0,1.],[.8,0,1.],[1.5,0,1.]]))
    for name,dtype in [('scan_index','<u4'),('source_record_index','<u8'),('working_index','<i8')]:
        original=np.asarray(getattr(cloud,name),dtype=dtype)
        path=tmp_path/(name+'.bin');original.tofile(path)
        setattr(cloud,name,np.memmap(path,dtype=dtype,shape=(3,),mode='r'))
    try:
        directory,report,_=run_recognition(cloud,identity(),FixtureProvider(),tmp_path/'cache',tile_settings=tiles())
        assert not (directory/'scan_ids.npy').exists()
        for key,name in [('scan_ids','scan_index'),('record_ids','source_record_index'),('working_rows','working_index')]:
            descriptor=report['arrays'][key]
            assert descriptor['storage']=='original_raw_hardlink'
            assert (directory/descriptor['path']).stat().st_ino==Path(getattr(cloud,name).filename).stat().st_ino
        assert load_proposal_set(directory)==report
    finally:
        for name in ('scan_index','source_record_index','working_index'):getattr(cloud,name)._mmap.close()


def test_riser_consensus_corrects_occluded_centroid_bias_without_wall_snapping():
    from punctora_core.stair_sequences import refine_lattice_direction
    angle=np.deg2rad(5.7);direction=np.array([np.cos(angle),np.sin(angle)])
    fitted={'direction':direction,'first_xy':np.array([.14,0.]),'going':.28,'steps':6,
            'rise':.17,'observed_steps':[0,3,4,5]}
    patches=[{'width':1.,'xy':np.array([.14+i*.28,(i-2.5)*.015])} for i in fitted['observed_steps']]
    points=np.array([[i*.28,y,z] for i in range(6) for y in np.arange(-.45,.46,.05)
                     for z in np.arange(i*.17,(i+1)*.17,.03)])
    normals=np.tile([1.,0.,0.],(len(points),1))
    result,report=refine_lattice_direction(fitted,patches,points,normals,())
    assert report['direction_changed'] and abs(result['direction'][1])<1e-9
    assert report['wall_alignment']=='not_established'


def test_desktop_orchestration_consumes_proposals_into_unreviewed_geometry(tmp_path,monkeypatch):
    from punctora_core import projects
    cloud,manifest=fusion_fixture(tmp_path)
    manifest.update(provider={'id':'PunctoraSpecialistProvider'},warnings=[],instances=[])
    manifest['extensions']['specialist_v1'].update(branches={'I':{'status':'active','graph_sha256':'c'*64}},
                                                 point_model_view_population=len(cloud.points))
    monkeypatch.setattr('punctora_core.recognition.job.run_recognition',lambda *a,**k:(tmp_path,manifest,False))
    state={'project_id':'a'*32,'import_manifest':{'source':{'sha256':'b'*64},
           'coordinate_mapping':{'working_to_source_translation_m':[0,0,0]}},
           'crop':{'polygon':None,'z_min':None,'z_max':None},'reconstruction_options':{'manual_levels':[]}}
    m=model();m.metadata['performance']={}
    try:
        report=projects._desktop_recognition(state,cloud,m,{'recognition_mode':'specialist',
            'specialist_model_directory':str(tmp_path),'job_id':'c'*32},tmp_path,lambda *a:None,lambda *a:None)
        assert len(m.walls)==1 and report['geometry_fusion']['added_wall_ids']
        assert m.walls[0].review_state=='unreviewed'
        assert 'original-point validated' in report['geometry_authority']
        assert m.metadata['performance']['recognition']['elapsed_seconds']>0
    finally:
        if getattr(m,'_spatial_index',None):m._spatial_index.close()


def test_semantic_horizontal_plane_is_refit_without_promoting_a_learned_cut(tmp_path):
    cloud,manifest=fusion_fixture(tmp_path)
    x,y=np.meshgrid(np.arange(0,4.001,.05),np.arange(-.5,.501,.05))
    cloud=source(np.column_stack((x.ravel(),y.ravel(),np.full(x.size,3.))))
    np.save(tmp_path/'labels.npy',np.full(len(cloud.points),5,dtype='<i2'))
    np.save(tmp_path/'support.npy',np.arange(min(4096,len(cloud.points)),dtype='<u8'))
    item=proposal('I:test',[[-.01,-.51],[4.01,-.51],[4.01,.51],[-.01,.51]])
    item.update(branch='I',**{'class':'slab'})
    (tmp_path/'proposals.json').write_text(json.dumps({'proposals':[item]}))
    (tmp_path/'support.json').write_text(json.dumps({'entries':[{'id':'I:test','offset':0,'count':len(cloud.points)}]}))
    index=index_for(cloud,tmp_path);m=model()
    try:report=fuse_geometry(cloud,m,manifest,tmp_path,index.index,Control(),ReconstructionSettings())
    finally:index.close()
    assert m.slabs and report['added_surface_ids'] and not m.slab_openings
    assert m.slabs[0].base==pytest.approx(3.)
    assert m.slabs[0].provenance['elevation']=='measured' and m.slabs[0].provenance['thickness']=='inferred'


def test_standalone_window_survives_model_composition_and_evaluation(tmp_path):
    from punctora_core.model_merge import merge_models
    from punctora_core.quality_benchmark import model_snapshot
    from test_recognition import identity
    cloud,manifest=fusion_fixture(tmp_path,'window',frame=True);index=index_for(cloud,tmp_path);m=model()
    try:fuse_geometry(cloud,m,manifest,tmp_path,index.index,Control(),ReconstructionSettings())
    finally:index.close()
    m.metadata.update(project_id='a'*32,source={'sha256':'b'*64})
    merged,_=merge_models(m,m)
    assert len(merged.facade_panels)==1 and not merged.walls
    snapshot=model_snapshot(merged,identity())
    assert snapshot['elements'][0]['class']=='window' and snapshot['elements'][0].get('host_id') is None


def test_j_instance_is_original_point_refit_not_only_a_display_box(tmp_path):
    cloud,manifest=fusion_fixture(tmp_path)
    (tmp_path/'proposals.json').write_text(json.dumps({'proposals':[]}))
    manifest['instances']=[{'id':'I:test','class':'wall','geometry':{'type':'wall','start':[0.,0.],
        'end':[4.,0.],'base':0.,'height':3.,'thickness':.2}}]
    index=index_for(cloud,tmp_path);m=model()
    try:report=fuse_geometry(cloud,m,manifest,tmp_path,index.index,Control(),ReconstructionSettings())
    finally:index.close()
    assert report['added_wall_ids'] and m.walls[0].detection_method=='specialist_original_point_refit'
    assert m.walls[0].fit_rmse_m<.001 and m.walls[0].provenance['thickness']=='inferred'
