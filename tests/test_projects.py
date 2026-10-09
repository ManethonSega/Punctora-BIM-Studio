"""Desktop persistence, correction, worker-death and IFC boundary regressions."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import uuid

import ifcopenshell
import ifcopenshell.util.element
import numpy as np
import pytest

from punctora_core import projects
from punctora_core.cloud_io import CloudData
from test_e57_io import _write_building_e57


def token():
    return uuid.uuid4().hex


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "review.punctora"
    state = projects.create_project(path, token(), two_storeys=True)
    return path, state


def request(state, **extra):
    return {"expected_revision": state["revision"], "model": deepcopy(state["model"]), **extra}


def test_edit_save_reopen_copy_and_ifc_identity(project, tmp_path):
    path, state = project
    before = projects.export_project(path, request(state, output=str(tmp_path / "before.ifc")))
    wall = state["model"]["walls"][0]
    corrected = projects.edit_model(state, state["model"], wall["id"], {"thickness": .27, "review_state": "reviewed"})
    corrected = projects.edit_model(state, corrected, corrected["slabs"][0]["id"], {"review_state": "reviewed"})
    assert corrected["walls"][0]["observed_faces"] == wall["observed_faces"]
    assert corrected["walls"][0]["evidence"] == wall["evidence"]
    state = projects.save_project(path, request(state, model=corrected, name="Renamed"))
    reopened = projects.load_project(path)
    assert reopened["model"]["walls"][0]["thickness"] == .27
    assert reopened["model"]["walls"][0]["provenance"]["thickness"] == "user_supplied"
    copied = tmp_path / "portable" / "copy.punctora"
    copy_state = projects.save_copy(path, copied, request(state))
    assert projects.load_project(copied)["model"] == reopened["model"]
    report = projects.export_project(copied, request(copy_state, output=str(tmp_path / "after.ifc")))
    assert before["validation"]["valid"] and report["validation"]["valid"]
    first, second = [ifcopenshell.open(str(tmp_path / name)) for name in ("before.ifc", "after.ifc")]
    for kind in ("IfcProject", "IfcBuilding", "IfcBuildingStorey", "IfcWall", "IfcSlab"):
        assert {o.GlobalId for o in first.by_type(kind)} == {o.GlobalId for o in second.by_type(kind)}
    assert not second.by_type("IfcSpace")  # Old inferred rooms must not survive changed walls.
    assert ifcopenshell.util.element.get_psets(second.by_type("IfcSlab")[0])["Punctora_Reconstruction"]["ReviewState"] == "reviewed"


def test_crop_is_draft_only_until_save_and_survives_reopen_and_copy(project, tmp_path):
    path, state = project
    crop = {"polygon": [[0, 0], [4, 0], [4, 3], [0, 3]], "z_min": .2, "z_max": 2.8}
    saved = path.read_bytes()
    draft = projects.edit_crop(state, crop)
    assert path.read_bytes() == saved
    assert draft["crop"] == crop
    assert draft["model_crop_stale"]
    state = projects.save_project(path, request(state, crop=draft["crop"], model_crop_stale=True))
    assert projects.load_project(path)["crop"] == crop
    with pytest.raises(ValueError, match="Detect elements"):
        projects.export_project(path, request(state, output=str(tmp_path / "stale.ifc")))
    destination = tmp_path / "crop-copy.punctora"
    copied = projects.save_copy(path, destination, request(state, crop=state["crop"]))
    assert copied["crop"] == projects.load_project(destination)["crop"] == crop


def test_old_project_without_crop_opens_with_inactive_crop(project):
    path, state = project
    del state["crop"]
    del state["model_crop"]
    del state["model_crop_stale"]
    projects.atomic_json(path, state)
    assert projects.load_project(path)["crop"] == {"polygon": None, "z_min": None, "z_max": None}


def test_reconstruction_uses_saved_crop_without_altering_source(project):
    path, state = project
    source_path = projects.assets_for(path) / "generations" / state["cloud"]["generation"] / "points.npy"
    source_before = source_path.read_bytes()
    crop = {"polygon": [[-.1, -.1], [6.1, -.1], [6.1, 4.1], [-.1, 4.1]],
            "z_min": -.1, "z_max": 3.05}
    draft = projects.edit_crop(state, crop)
    state = projects.save_project(path, request(state, crop=crop, model_crop=state["model_crop"],
                                                 model_crop_stale=draft["model_crop_stale"]))
    result = projects.reconstruct_project(path, {"expected_revision": state["revision"],
        "confirm_z_up": True, "job_id": token(), "settings": {}})
    assert len(result["model"]["storeys"]) == 1
    assert result["model"]["metadata"]["crop"]["active"]
    assert result["model"]["metadata"]["crop"]["selected_points"] < result["model"]["metadata"]["crop"]["source_points"]
    assert result["model_crop"] == crop and not result["model_crop_stale"]
    assert source_path.read_bytes() == source_before
    generation = projects.assets_for(path) / "generations" / result["generations"][-1]
    assert not (generation / "crop-working").exists()


@pytest.mark.parametrize("changes", [{"thickness": -1}, {"height": float("nan")}, {"start": [0, 0, 0]}, {"review_state": "approved"}, {"thickness": True}])
def test_invalid_correction_cannot_change_saved_model(project, changes):
    path, state = project
    saved = path.read_bytes()
    model = deepcopy(state["model"])
    with pytest.raises((ValueError, TypeError)):
        projects.edit_model(state, model, model["walls"][0]["id"], changes)
    assert path.read_bytes() == saved and model == state["model"]


def test_stale_revision_and_failed_atomic_save_preserve_previous_project(project, monkeypatch):
    path, state = project
    state2 = projects.save_project(path, request(state))
    saved = path.read_bytes()
    with pytest.raises(ValueError, match="changed since"):
        projects.save_project(path, request(state))
    replace = projects.os.replace
    def fail(source, target):
        if Path(target) == path:
            raise OSError("Simulated full disk")
        return replace(source, target)
    monkeypatch.setattr(projects.os, "replace", fail)
    with pytest.raises(OSError, match="full disk"):
        projects.save_project(path, request(state2, name="Unsaved"))
    assert path.read_bytes() == saved
    assert projects.load_project(path)["revision"] == state2["revision"]


def test_project_rejects_path_escape_and_missing_preview(project, tmp_path):
    path, state = project
    with pytest.raises(ValueError, match="escapes"):
        projects.safe_path(projects.assets_for(path), "../outside")
    state["preview"]["path"] = "../../outside"
    projects.atomic_json(path, state)
    with pytest.raises(ValueError, match="escapes"):
        projects.load_project(path)


def test_large_cloud_preview_uses_gpu_friendly_display_budget(tmp_path):
    count = projects.PREVIEW_LIMIT + 17
    points = np.zeros((count, 3), dtype=np.float64)
    points[:, 0] = np.arange(count)
    manifest = projects.write_preview(CloudData(points), tmp_path, "generation")
    assert manifest["point_count"] == projects.PREVIEW_LIMIT == 500_000
    assert manifest["source_point_count"] == count
    assert manifest["sampling"].endswith("display only")
    assert "spatial-cell" in manifest["sampling"]
    assert (tmp_path / "preview.bin").stat().st_size == projects.PREVIEW_LIMIT * 24


def test_spatial_preview_prefers_occupied_cells_and_is_repeatable():
    cluster = np.zeros((900, 3), dtype=np.float64)
    distributed = np.column_stack((np.arange(100), np.arange(100) % 10,
                                   np.arange(100) // 10)).astype(np.float64)
    points = np.vstack((distributed, cluster))
    first = projects.spatial_preview_indices(points, limit=100)
    second = projects.spatial_preview_indices(points, limit=100)
    assert np.array_equal(first, second)
    assert len(first) == len(np.unique(first)) == 100
    # A 100-row source sample would retain only about ten distinct positions.
    # The wider candidate pass keeps spatial cells before filling duplicates.
    assert len(np.unique(points[first], axis=0)) >= 35


def test_storey_correction_shifts_dependents_and_rejects_overlap(project):
    path, state = project
    model = state["model"]
    upper = max(model["storeys"], key=lambda s: s["elevation"])
    changes = {"elevation": upper["elevation"] + .1, "ceiling": upper["ceiling"] + .1}
    draft = projects.edit_model(state, model, upper["id"], changes)
    for prior, after in zip(model["walls"], draft["walls"]):
        assert after["base"] == pytest.approx(prior["base"] + (.1 if prior["storey_id"] == upper["id"] else 0))
    with pytest.raises(ValueError, match="overlap"):
        projects.edit_model(state, model, upper["id"], {"elevation": 1})
    with pytest.raises(ValueError, match="name"):
        projects.edit_model(state, model, upper["id"], {"name": ""})


def test_rejected_wall_excluded_and_failed_export_preserves_existing_file(project, tmp_path):
    path, state = project
    corrected = projects.edit_model(state, state["model"], state["model"]["walls"][0]["id"], {"review_state": "rejected"})
    target = tmp_path / "review.ifc"
    report = projects.export_project(path, request(state, model=corrected, output=str(target)))
    assert report["excluded_rejected_walls"] == 1
    assert len(ifcopenshell.open(str(target)).by_type("IfcWall")) == len(state["model"]["walls"])-1
    saved = target.read_bytes()
    corrected["walls"][1]["height"] = 0
    with pytest.raises(ValueError):
        projects.export_project(path, request(state, model=corrected, output=str(target)))
    assert target.read_bytes() == saved


def test_e57_reconstruct_retains_coordinates_and_original_record_evidence(tmp_path):
    source, path = tmp_path / "source.e57", tmp_path / "scan.punctora"
    _write_building_e57(source)
    original = source.read_bytes()
    state = projects.create_project(path, token(), source=source)
    saved = path.read_bytes()
    with pytest.raises(ValueError, match="Confirm"):
        projects.reconstruct_project(path, request(state, job_id=token()))
    assert path.read_bytes() == saved
    state = projects.reconstruct_project(path, request(state, job_id=token(), confirm_z_up=True))
    cloud = projects.load_cloud(path, state)
    for wall in state["model"]["walls"]:
        refs = np.load(projects.assets_for(path) / wall["evidence"]["records"]["path"], allow_pickle=False)
        np.testing.assert_array_equal(refs[:, 1], cloud.scan_index[refs[:, 0]])
        np.testing.assert_array_equal(refs[:, 2], cloud.source_record_index[refs[:, 0]])
    assert state["model"]["metadata"]["coordinate_mapping"] == state["import_manifest"]["coordinate_mapping"]
    assert source.read_bytes() == original
    assert projects.load_project(path)["model"] == json.loads(json.dumps(state["model"]))


def test_worker_termination_releases_lock_and_preserves_saved_generation(project):
    path, state = project
    saved = path.read_bytes()
    job = token()
    child = subprocess.Popen([sys.executable, "-m", "punctora_core.worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        child.stdin.write(json.dumps(request(state, command="reconstruct", project=str(path), job_id=job, protocol_version=1, confirm_z_up=True))+"\n")
        child.stdin.flush()
        while True:
            line = child.stdout.readline()
            assert line, child.stderr.read()
            message = json.loads(line)
            if message["type"] == "progress" and message["percent"] == 20:
                break
        child.kill()
        child.communicate(timeout=20)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=20)
    assert path.read_bytes() == saved
    projects.save_project(path, request(state))  # Dead worker cannot retain the OS lock.
    removed = projects.cleanup_project(path)["removed"]
    assert f"staging/{job}" in removed
    assert projects.load_project(path)["generations"] == state["generations"]


def test_malformed_worker_protocol_is_structured_error(tmp_path):
    run = subprocess.run([sys.executable, "-m", "punctora_core.worker"], input=json.dumps({"job_id": token(), "protocol_version": 999})+"\n", text=True, capture_output=True, timeout=30)
    result = json.loads(run.stdout)
    assert run.returncode == 1 and result["type"] == "error"
    assert "protocol" in result["message"]


def test_copy_can_resume_owned_folder_left_by_cancelled_worker(project, tmp_path):
    path, state = project
    destination = tmp_path / "resumed.punctora"
    root = projects.ensure_assets(destination, state["project_id"])
    partial = root / "generations" / state["generations"][0]
    partial.mkdir(parents=True)
    (partial / "preview.bin").write_bytes(b"interrupted")
    copied = projects.save_copy(path, destination, request(state))
    assert projects.load_project(destination)["revision"] == copied["revision"]


def test_release_cached_array_views_before_publishing_directory(tmp_path):
    folder = tmp_path / "staging"
    folder.mkdir()
    np.save(folder / "points.npy", np.array([[1., 2., 3.]]))
    mapped = np.load(folder / "points.npy", mmap_mode="r", allow_pickle=False)
    cloud = CloudData(mapped)  # Cloud validation wraps memmap in ndarray views.
    projects.close_cloud(cloud)
    assert mapped._mmap.closed
    folder.rename(tmp_path / "published")
    np.testing.assert_array_equal(np.load(tmp_path / "published" / "points.npy"), [[1., 2., 3.]])
