import uuid
from types import SimpleNamespace
import numpy as np
import pytest
from punctora_core import storage,projects


def test_mapped_reservation_rejects_low_disk_before_creating_a_file(tmp_path,monkeypatch):
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:SimpleNamespace(free=0))
    path=tmp_path/'temporary.npy'
    with pytest.raises(ValueError,match='Insufficient temporary disk space'):
        storage.mapped_array(path,np.float64,(100,3))
    assert not path.exists()


def test_low_disk_reconstruction_keeps_saved_model_and_failed_diagnostics(tmp_path,monkeypatch):
    path=tmp_path/'saved.punctora';state=projects.create_project(path,uuid.uuid4().hex)
    before=path.read_bytes()
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:SimpleNamespace(free=0))
    with pytest.raises(ValueError,match='Insufficient temporary disk space'):
        projects.reconstruct_project(path,{'expected_revision':state['revision'],'confirm_z_up':True,'job_id':uuid.uuid4().hex})
    assert path.read_bytes()==before
    report=projects.read_json(projects.assets_for(path)/'last-performance.json')
    assert report['status']=='failed'
