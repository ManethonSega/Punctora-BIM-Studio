from copy import deepcopy
import uuid
import numpy as np
import pytest
from punctora_core.cloud_io import CloudData
from punctora_core.reconstruction import reconstruct,ReconstructionSettings
from punctora_core.level_bounds import validate_detection_options,LevelDetectionError
from punctora_core import projects

def facade_cloud():
    x,z=np.meshgrid(np.arange(0,8.01,.05),np.arange(.5,8.01,.05))
    points=np.c_[x.ravel(),np.zeros(x.size),z.ravel()]
    window=((points[:,0]>2)&(points[:,0]<3.5)&(points[:,2]>2)&(points[:,2]<3.5))
    return CloudData(points[~window])

def test_exterior_without_slabs_reconstructs_supported_walls_and_openings():
    cloud=facade_cloud()
    model=reconstruct(cloud,ReconstructionSettings(reconstruction_scope='exterior',cpu_workers=1,
                                                   detect_stairs_enabled=False))
    try:
        assert model.walls and model.openings and not model.slabs and not model.spaces
        assert model.storeys[0].provenance['elevation']=='unknown'
        assert model.metadata['reconstruction_scope']=='exterior'
        assert all(w.evidence['record_examples'] for w in model.walls)
    finally:model._spatial_index.close()

def test_automatic_fallback_does_not_invent_interior_floors():
    model=reconstruct(facade_cloud(),ReconstructionSettings(cpu_workers=1,detect_stairs_enabled=False))
    try:
        assert model.metadata['reconstruction_scope']=='exterior' and model.walls
        assert not model.slabs and model.metadata['slab_zones']['status']=='no_supported_slab_sequence'
    finally:model._spatial_index.close()

def test_failed_interior_job_retains_level_rejection_diagnostics():
    snapshots=[]
    with pytest.raises(LevelDetectionError):
        reconstruct(facade_cloud(),ReconstructionSettings(reconstruction_scope='interior',cpu_workers=1),
                    diagnostics=snapshots.append)
    assert snapshots[-1]['status']=='failed'
    stage=snapshots[-1]['stages'][0]
    assert stage['level_detection_failure'] and stage['points_processed']>0

def test_manual_bounds_save_reopen_and_reconstruct_through_project_worker(tmp_path):
    path=tmp_path/'manual.punctora'
    state=projects.create_project(path,uuid.uuid4().hex)
    setup={'scope':'exterior','manual_levels':[{'name':'Facade','bottom_m':0,'top_m':3}]}
    saved=projects.save_project(path,{'expected_revision':state['revision'],
        'model':deepcopy(state['model']),'reconstruction_options':setup})
    assert projects.load_project(path)['reconstruction_options']==validate_detection_options(setup)
    result=projects.reconstruct_project(path,{'job_id':uuid.uuid4().hex,
        'expected_revision':saved['revision'],'confirm_z_up':True,
        'settings':{'detect_stairs_enabled':False,'cpu_workers':1}})
    assert result['model']['storeys'][0]['name']=='Facade'
    assert result['model']['storeys'][0]['provenance']['elevation']=='user_supplied'
    assert not result['model']['slabs']
    assert result['model']['metadata']['manual_level_bounds']['points_processed']>0
    assert result['model']['metadata']['performance']['stages'][0]['method']=='user_supplied_level_bounds'

def test_changing_saved_level_settings_requires_redetection_before_export(tmp_path):
    path=tmp_path/'stale.punctora';state=projects.create_project(path,uuid.uuid4().hex)
    setup={'scope':'exterior','manual_levels':[]}
    state=projects.save_project(path,{'expected_revision':state['revision'],
        'model':state['model'],'reconstruction_options':setup})
    assert projects.load_project(path)['model_crop_stale']
    with pytest.raises(ValueError,match='Detect elements'):
        projects.export_project(path,{'expected_revision':state['revision'],
                                     'model':state['model'],'output':str(tmp_path/'stale.ifc')})

def test_manual_bounds_reject_nonfinite_and_overlapping_intervals():
    with pytest.raises(ValueError):validate_detection_options({'manual_levels':[{'bottom_m':0,'top_m':float('nan')}]})
    with pytest.raises(ValueError):validate_detection_options({'manual_levels':[{'bottom_m':0,'top_m':3},{'bottom_m':2,'top_m':4}]})
