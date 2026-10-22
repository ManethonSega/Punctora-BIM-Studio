"""Runtime prerequisites must fail before touching the user's scan or model."""
import json
import os
import sys
import uuid
import venv

import pytest

from punctora_core import projects, worker
from punctora_core.recognition import job, specialist_pack
from punctora_core.recognition.contracts import ProviderUnavailable


@pytest.fixture
def missing_ort_python(tmp_path):
    environment = tmp_path / "isolated-python"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(environment)
    site_packages = (environment / "Lib/site-packages" if os.name == "nt" else
                     next(environment.glob("lib/python*/site-packages")))
    # The marker distinguishes executing this venv from merely reporting its path.
    marker = environment / "interpreter-used"
    (site_packages / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('isolated-venv')\n",
        encoding="utf-8")
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _forbid_scan_work(monkeypatch):
    calls = []

    def forbidden(name):
        def fail(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"Unavailable specialist started {name}")
        return fail

    for name in ("generation_stage", "load_cloud", "materialize_crop", "reconstruct", "compare_budgets",
                 "write_model_evidence", "write_ifc"):
        monkeypatch.setattr(projects, name, forbidden(name))
    monkeypatch.setattr(job, "_input_digests", forbidden("source hashing and identity sorting"))
    return calls


@pytest.mark.parametrize("mode", ["specialist", "hybrid"])
def test_unavailable_specialist_blocks_scan_work_and_preserves_saved_project(
        tmp_path, monkeypatch, missing_ort_python, mode):
    path = tmp_path / "saved.punctora"
    state = projects.create_project(path, uuid.uuid4().hex)
    state = projects.save_project(path, {
        "expected_revision": state["revision"], "model": state["model"],
        "crop": {"polygon": [[0, 0], [4, 0], [4, 3], [0, 3]],
                 "z_min": .2, "z_max": 2.8}, "model_crop_stale": True})
    saved = path.read_bytes()
    generations = projects.assets_for(path) / "generations"
    before = sorted(p.name for p in generations.iterdir())
    calls = _forbid_scan_work(monkeypatch)
    models = tmp_path / "models"
    models.mkdir()
    job_id = uuid.uuid4().hex

    with pytest.raises(ProviderUnavailable, match="(?i)onnxruntime"):
        projects.reconstruct_project(path, {
            "expected_revision": state["revision"], "confirm_z_up": True,
            "job_id": job_id, "settings": {}, "recognition_mode": mode,
            "specialist_python": str(missing_ort_python),
            "specialist_model_directory": str(models)})

    assert calls == []
    assert path.read_bytes() == saved
    assert sorted(p.name for p in generations.iterdir()) == before
    assert not list((projects.assets_for(path) / "staging").iterdir())
    diagnostic = projects.read_json(projects.assets_for(path) / "last-performance.json")
    assert diagnostic["status"] == "failed" and diagnostic["job_id"] == job_id
    assert "onnxruntime" in diagnostic["error"].lower()
    assert projects.load_project(path)["revision"] == state["revision"]


def test_scan_free_preflight_reports_missing_ort_before_hashing_models(
        tmp_path, monkeypatch, missing_ort_python):
    calls = _forbid_scan_work(monkeypatch)
    models = tmp_path / "models"
    models.mkdir()
    # A corrupt present graph would fail its content check if hashing ran first.
    graph = models / specialist_pack.MODEL_PACK_MANIFEST["branches"]["A"]["graph"]
    graph.write_bytes(b"not an ONNX graph")
    hashed = []

    def forbidden_hash(*args, **kwargs):
        hashed.append(True)
        raise AssertionError("Model hashing preceded runtime admission")

    monkeypatch.setattr(specialist_pack, "file_digest", forbidden_hash)
    report = projects.preflight_recognition({
        "recognition_mode": "specialist", "specialist_python": str(missing_ort_python),
        "specialist_model_directory": str(models)})

    assert report["status"] == "unavailable"
    assert report["actual_provider"] == "unavailable"
    assert report["requested_mode"] == "specialist"
    assert "onnxruntime" in report["reason"].lower()
    # Resolving a venv's executable symlink would silently select its base Python.
    assert report["specialist_python"] == str(missing_ort_python.absolute())
    assert (missing_ort_python.parent.parent / "interpreter-used").read_text() == "isolated-venv"
    assert calls == [] and hashed == []
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("selection", ["explicit", "environment", "current"])
def test_preflight_interpreter_precedence_is_explicit_then_environment_then_current(
        tmp_path, monkeypatch, selection):
    explicit = tmp_path / "explicit-python"
    environment = tmp_path / "environment-python"
    current = tmp_path / "current-python"
    monkeypatch.setattr(sys, "executable", str(current))
    monkeypatch.delenv("PUNCTORA_SPECIALIST_PYTHON", raising=False)
    request = {"recognition_mode": "specialist",
               "specialist_model_directory": str(tmp_path / "models")}
    if selection in {"explicit", "environment"}:
        monkeypatch.setenv("PUNCTORA_SPECIALIST_PYTHON", str(environment))
    if selection == "explicit":
        request["specialist_python"] = str(explicit)

    report = projects.preflight_recognition(request)

    expected = {"explicit": explicit, "environment": environment, "current": current}[selection]
    assert report["specialist_python"] == str(expected.absolute())
    assert report["status"] == "unavailable" and report["reason"]


def test_worker_preflight_command_requires_no_project_or_scan(tmp_path, monkeypatch):
    calls = _forbid_scan_work(monkeypatch)

    def forbidden_project(*args, **kwargs):
        raise AssertionError("Scan-free preflight attempted to open a project")

    monkeypatch.setattr(projects, "load_project", forbidden_project)
    report = worker.dispatch({
        "command": "preflight_recognition", "recognition_mode": "specialist",
        "specialist_python": str(tmp_path / "missing-python"),
        "specialist_model_directory": str(tmp_path / "models")}, lambda *_: None)

    assert report["status"] == "unavailable"
    assert report["requested_mode"] == "specialist" and report["reason"]
    assert calls == []
