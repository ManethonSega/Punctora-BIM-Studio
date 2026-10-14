from copy import deepcopy
from pathlib import Path
import hashlib
import sys
import time

import numpy as np
import pytest

from punctora_core.annotation_io import content_digest, read_json
from punctora_core.cloud_io import CloudData
from punctora_core.recognition.contracts import ProviderUnavailable, load_proposal_set, validate_proposal_set
from punctora_core.recognition.job import run_recognition
from punctora_core.recognition.provider import RecognitionProvider, TilePrediction
from punctora_core.recognition.specialist_decoders import decode_masks, decode_obb, decode_section
from punctora_core.recognition.specialist_frames import (plan_frame, plan_pixel_centres_world, plan_pixels,
    rasterize_section, section_frame, slab_section_windows)
from punctora_core.recognition.specialist_indices import (build_index_inputs, kernel_map,
    prepare_point_model_view, validate_index_inputs)
from punctora_core.recognition.specialist_pack import MODEL_PACK_MANIFEST, resolve_model_pack
from punctora_core.recognition.specialist_provider import (PunctoraSpecialistAssets,
    PunctoraSpecialistProvider, SpecialistSettings, foreground_consensus)
from punctora_core.recognition.specialist_worker import image_tensor
from punctora_core.recognition.tiling import TileSettings


def identity():
    return {"case_id": "generated-specialist", "source_sha256": "a" * 64,
            "coordinate_mapping": {"translation_m": [7_000_000., 5_000_000., 100.],
                                   "yaw_degrees": 0.}, "crop": None}


def cloud():
    x, y = np.meshgrid(np.arange(11) * .05, np.arange(11) * .05)
    points = np.column_stack((x.ravel() + 7_000_000.123456789,
                              y.ravel() + 5_000_000.123456789,
                              np.full(x.size, 100.25)))
    return CloudData(points, scan_index=np.arange(len(points), dtype="<u8") % 3,
                     source_record_index=np.arange(2**53 + 100, 2**53 + 100 + len(points), dtype="<u8"),
                     working_index=np.arange(900, 900 + len(points), dtype="<u8"))


def fixture_resolution(active="I"):
    status = {}
    for name in "ABCDEFGHIJ":
        available = name in active
        branch = MODEL_PACK_MANIFEST["branches"][name]
        status[name] = {"status": "available" if available else "missing",
                        "graph_sha256": branch["graph_sha256"] if available else None,
                        "companion_sha256": branch.get("companion_sha256") if available else None,
                        "graph_bytes": 1024 if available else 0, "companion_bytes": 0}
    return deepcopy(MODEL_PACK_MANIFEST), status, [name for name in "ABCDEFGHIJ" if name not in active]


FAKE_WORKER = r'''
import json, pathlib, sys, time
import numpy as np
request=json.loads(pathlib.Path(sys.argv[1]).read_text())
root=pathlib.Path(request["model_root"])
if request["mode"]=="preflight":
    if (root/"slow").exists(): time.sleep(30)
    response={"schema_version":1,"status":"complete","active_branches":request["active_branches"],
              "runtime":{"id":"onnxruntime","version":"1.23.2","requested_provider":"CPUExecutionProvider",
                         "actual_provider":"CPUExecutionProvider"},"contracts":{}}
elif request["mode"]=="point":
    feed=json.loads(pathlib.Path(request["feed_manifest"]).read_text())
    count=len(np.load(feed["feat"],allow_pickle=False))
    logits=np.zeros((count,12),dtype=np.float32);logits[:,0]=3;logits[:,1]=1
    if (root/"malformed").exists(): logits=logits[:,:11]
    np.save(request["output"],logits,allow_pickle=False)
    response={"schema_version":1,"status":"complete","branch":"I","output":request["output"]}
else:
    raise RuntimeError("fixture only supports point inference")
pathlib.Path(request["response"]).write_text(json.dumps(response),encoding="utf-8")
'''


class FixtureSpecialist(PunctoraSpecialistProvider):
    def __init__(self, worker, *args, **kwargs):
        self._fixture_worker = Path(worker)
        super().__init__(*args, **kwargs)

    @property
    def worker_path(self):
        return self._fixture_worker


class FixtureFallback(RecognitionProvider):
    def descriptor(self):
        value = {"id": "fixture_classical", "version": "1", "backend": "CPU",
                 "score_kind": "fixture_native"}
        return {**value, "fingerprint": content_digest(value)}

    def prepare(self, cloud, identity, directory, control):
        pass

    def infer_chunk(self, tile, directory, control):
        return TilePrediction(np.full(len(tile.points), 5, dtype="<i2"),
                              np.ones(len(tile.points), dtype="<f4"))


def make_provider(tmp_path, monkeypatch, marker=None):
    root = tmp_path / "models"; root.mkdir(parents=True)
    if marker:
        (root / marker).touch()
    worker = tmp_path / "fixture_specialist.py"; worker.write_text(FAKE_WORKER, encoding="utf-8")
    monkeypatch.setattr("punctora_core.recognition.specialist_provider.resolve_model_pack",
                        lambda *args, **kwargs: fixture_resolution())
    settings = SpecialistSettings(level_bounds=(
        {"name": "L1", "bottom_m": 100., "top_m": 103.,
         "evidence_state": "user_supplied_bound_not_measured_floor"},))
    return FixtureSpecialist(worker, PunctoraSpecialistAssets(sys.executable, str(root.resolve()), 10.), settings)


def test_model_pack_binds_content_and_rejects_wrong_companion(tmp_path, monkeypatch):
    import punctora_core.recognition.specialist_pack as pack
    manifest = deepcopy(MODEL_PACK_MANIFEST)
    graph, companion = b"graph-D", b"external-D"
    manifest["branches"]["D"]["graph_sha256"] = hashlib.sha256(graph).hexdigest()
    manifest["branches"]["D"]["companion_sha256"] = hashlib.sha256(companion).hexdigest()
    manifest["manifest_sha256"] = content_digest({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    monkeypatch.setattr(pack, "MODEL_PACK_MANIFEST", manifest)
    (tmp_path / "model_D.onnx").write_bytes(graph)
    (tmp_path / "model_D.onnx.data").write_bytes(companion)
    resolved, status, missing = resolve_model_pack(tmp_path)
    assert resolved["manifest_sha256"] == manifest["manifest_sha256"]
    assert status["D"]["status"] == "available" and "D" not in missing
    (tmp_path / "model_D.onnx.data").write_bytes(b"compatible-looking-wrong-content")
    with pytest.raises(ValueError, match="companion digest mismatch"):
        resolve_model_pack(tmp_path)


@pytest.mark.parametrize("count", [1, 31, 127, 128, 129, 255, 256, 257, 513])
def test_point_index_contract_all_stages_and_native_tail(count):
    rows = np.arange(count)
    grid = np.column_stack((rows % 17, (rows // 17) % 17, rows // 289))
    feed, stages = build_index_inputs(grid, np.ones((count, 3), dtype=np.float32))
    assert len(feed) == 40 and len(stages) == 5
    validate_index_inputs(feed)
    for stage, population in enumerate(stages):
        window = feed[f"s{stage}_o0_win"]
        inverse = feed[f"s{stage}_o0_inv"]
        assert np.array_equal(window.ravel()[inverse], np.arange(population))


def test_native_kernel_column_order_and_malformed_indices_fail():
    grid = np.asarray([(a, b, c) for a in range(5) for b in range(5) for c in range(5)], dtype=np.int64)
    values = kernel_map(grid, 3)
    centre = np.flatnonzero(np.all(grid == [2, 2, 2], axis=1))[0]
    expected = np.flatnonzero(np.all(grid == [1, 1, 2], axis=1))[0]
    assert values[centre, 1] == expected and values[centre, 13] == centre
    feed, _ = build_index_inputs(grid, np.ones((len(grid), 3), dtype=np.float32))
    broken = {name: value.copy() for name, value in feed.items()}
    broken["s0_k3"][0, 13] = -1
    with pytest.raises(ValueError, match="kernel"):
        validate_index_inputs(broken)
    with pytest.raises(MemoryError, match="working budget"):
        build_index_inputs(grid, np.ones((len(grid), 3), dtype=np.float32), memory_budget_bytes=100)


def test_source_key_order_precedes_survey_scale_centring():
    class Control:
        working_budget = 2**30
        @staticmethod
        def check(): pass
    class Tile: pass
    source = cloud(); order = np.arange(len(source.points))[::-1]
    def tile(indices):
        value = Tile(); value.points = source.points[indices]; value.scan_ids = source.scan_index[indices]
        value.record_ids = source.source_record_index[indices]; value.working_rows = source.working_index[indices]
        return value
    a, b = prepare_point_model_view(tile(np.arange(len(order))), Control()), prepare_point_model_view(tile(order), Control())
    assert np.array_equal(a.origin_m, b.origin_m)
    assert a.origin_m.dtype == np.float64 and a.feed.keys() == b.feed.keys()
    assert all(np.array_equal(a.feed[name], b.feed[name]) for name in a.feed)


@pytest.mark.parametrize("mirrored", [False, True])
def test_plan_frame_roundtrip_and_true_mirror_at_large_coordinates(mirrored):
    frame = plan_frame("p", [7_000_000.25, 5_000_000.75], 10.24, 1024, 30., mirrored, 100., 103.)
    rows = np.array([0, 117, 511, 1023]); columns = np.array([0, 311, 700, 1023])
    xy = plan_pixel_centres_world(frame, rows, columns)
    points = np.column_stack((xy, np.full(len(xy), 101.5)))
    recovered_rows, recovered_columns, inside = plan_pixels(frame, points)
    assert inside.all() and np.array_equal(rows, recovered_rows) and np.array_equal(columns, recovered_columns)
    determinant = np.linalg.det(np.stack((frame.basis_u_xy, frame.basis_v_xy)))
    assert determinant == pytest.approx(-1. if mirrored else 1.)


def test_slab_section_declared_transform_remains_reversible():
    points = np.array([[7_000_000. + x, 5_000_000., 100. + z]
                       for x in np.linspace(0, 8, 80) for z in np.linspace(0, 3, 31)])
    frame = section_frame("a", points, [1., 0.], base_m=100.)
    windows = slab_section_windows(frame, rasterize_section(frame, points))
    assert windows and all(image.shape[1] == 1024 and image.shape[0] <= 1024 for image, _, _ in windows)
    assert all(meta["lossless_inference_buffer"] and meta["cross_window_nms_iou"] == .3
               for _, _, meta in windows)
    assert windows[0][1].pixel_m == pytest.approx(frame.pixel_m / windows[0][2]["lanczos_scale"])


def test_native_decoders_keep_score_kinds_foreground_and_query_identity():
    points = np.array([[0., 0., 0.], [10., 0., 3.]])
    section = section_frame("s", points, [1., 0.], base_m=0.)
    boxes = np.zeros((1, 300, 4), dtype=np.float32); boxes[0, 0] = [.5, .5, .2, .4]
    logits = np.full((1, 300, 2), [-8., -7.], dtype=np.float32)
    decoded = decode_section("B", {"dets": boxes, "labels": logits}, section, .7)
    assert len(decoded) == 300 and decoded[0]["native_score"] == pytest.approx(.73105858)
    masks = np.zeros((1, 3, 5, 7), dtype=np.float32); masks[:, 2] = 1
    labels, winning, margin = decode_masks("D", {"logits": masks})
    assert labels.shape == (5, 7) and np.all(labels == 2) and np.all(winning == 1) and np.all(margin == 1)
    plan = plan_frame("j", [0., 0.], 10.24, 1024, 0., False, 0., 3.)
    jboxes = np.zeros((1, 300, 4), dtype=np.float32); jboxes[0, 0] = [.5, .5, .4, .05]
    jlogits = np.full((1, 300, 3), -20., dtype=np.float32); jlogits[0, 0] = [3., 2., 1.]
    angles = np.zeros((1, 300, 1), dtype=np.float32)
    candidates = decode_obb({"dets": jboxes, "labels": jlogits, "angles": angles}, plan)
    assert len(candidates) == 1 and candidates[0]["query_id"] == 0 and candidates[0]["native_class_id"] == 0
    assert len(candidates[0]["native_class_scores"]) == 3
    selected, subtype, foreground = foreground_consensus(np.array([[2, 2, 2], [3, 3, 0]], dtype=np.uint8), 4)
    assert selected.tolist() == [True, False] and foreground.tolist() == [4, 3]
    assert subtype.tolist() == [1, 1]  # Tie is explicit but cannot erase combined foreground consensus.


def test_branch_specific_image_preprocessing_shapes_polarity_and_bgr_order():
    gray = np.array([[0, 255], [255, 0]], dtype=np.uint8)
    assert image_tensor("A", gray).shape == (1, 3, 560, 560)
    mask = image_tensor("D", gray)
    assert mask.shape == (1, 1, 512, 512) and mask.min() == pytest.approx(-1) and mask.max() == pytest.approx(1)
    bgr = np.empty((2, 2, 3), dtype=np.uint8); bgr[:] = [10, 20, 30]
    tensor = image_tensor("J", bgr)
    assert tensor.shape == (1, 3, 576, 576)
    expected = (np.array([10, 20, 30]) / 255. - np.array([.485, .456, .406])) / np.array([.229, .224, .225])
    assert np.allclose(tensor[0, :, 0, 0], expected, atol=2e-6)


def test_isolated_specialist_provider_runs_point_graph_and_publishes_review_only(tmp_path, monkeypatch):
    provider = make_provider(tmp_path, monkeypatch)
    directory, report, hit = run_recognition(
        cloud(), identity(), provider, tmp_path / "cache",
        tile_settings=TileSettings(size_m=8., overlap_m=2., maximum_context_points=10000))
    assert not hit and report["requested_provider"]["id"] == "PunctoraSpecialistProvider"
    assert report["provider"]["backend"] == "CPUExecutionProvider"
    extension = report["extensions"]["specialist_v1"]
    assert extension["branches"]["I"]["status"] == "active"
    assert all(extension["branches"][name]["status"] == "missing" for name in "ABCDEFGHJ")
    assert extension["accepted_geometry_changes"] == extension["accepted_cuts"] == extension["ifc_objects_written"] == 0
    assert np.all(np.load(directory / "labels.npy") == 0)
    assert np.load(directory / "record_ids.npy")[0] > 2**53
    assert read_json(directory / extension["proposals_path"])["proposals"]
    support = np.load(directory / extension["support_rows"]["path"])
    assert support.dtype == np.dtype("<u8") and len(support)
    assert np.load(directory / "record_ids.npy")[support].min() > 2**53
    assert str(tmp_path) not in (directory / extension["views_path"]).read_text(encoding="utf-8")
    assert not list(directory.rglob("*.ifc"))
    assert load_proposal_set(directory) == report
    second = make_provider(tmp_path / "again", monkeypatch)
    _, cached, cache_hit = run_recognition(
        cloud(), identity(), second, tmp_path / "cache",
        tile_settings=TileSettings(size_m=8., overlap_m=2., maximum_context_points=10000))
    assert cache_hit and cached == report


def test_specialist_contract_rejects_geometry_promotion(tmp_path, monkeypatch):
    provider = make_provider(tmp_path, monkeypatch)
    directory, report, _ = run_recognition(cloud(), identity(), provider, tmp_path / "cache",
        tile_settings=TileSettings(size_m=8., overlap_m=2., maximum_context_points=10000))
    corrupt = deepcopy(report)
    corrupt["extensions"]["specialist_v1"]["accepted_geometry_changes"] = 1
    corrupt["proposal_sha256"] = content_digest({k: v for k, v in corrupt.items() if k != "proposal_sha256"})
    with pytest.raises(ValueError, match="cannot accept geometry"):
        validate_proposal_set(corrupt, directory, verify_arrays=False)


def test_missing_runtime_falls_back_truthfully_from_common_lifecycle(tmp_path):
    models = tmp_path / "models"; models.mkdir()
    provider = PunctoraSpecialistProvider(PunctoraSpecialistAssets(str(tmp_path / "missing-python"), str(models.resolve())))
    directory, report, _ = run_recognition(cloud(), identity(), provider, tmp_path / "cache",
        fallback=FixtureFallback(), tile_settings=TileSettings(maximum_context_points=10000))
    assert report["requested_provider"]["id"] == "PunctoraSpecialistProvider"
    assert report["provider"]["id"] == "fixture_classical"
    assert any("fallback" in warning for warning in report["warnings"])
    assert "specialist_v1" not in report.get("extensions", {})
    assert np.all(np.load(directory / "labels.npy") == 5)


def test_malformed_worker_output_never_falls_back(tmp_path, monkeypatch):
    provider = make_provider(tmp_path, monkeypatch, "malformed")
    fallback = FixtureFallback()
    with pytest.raises(ValueError, match="logits"):
        run_recognition(cloud(), identity(), provider, tmp_path / "cache", fallback=fallback,
                        tile_settings=TileSettings(maximum_context_points=10000))
    assert not list((tmp_path / "cache").glob("[0-9a-f]" * 64))


def test_cancellation_terminates_isolated_preflight_and_publishes_nothing(tmp_path, monkeypatch):
    provider = make_provider(tmp_path, monkeypatch, "slow")
    started = time.monotonic()
    with pytest.raises(InterruptedError):
        run_recognition(cloud(), identity(), provider, tmp_path / "cache",
                        tile_settings=TileSettings(maximum_context_points=10000),
                        cancelled=lambda: time.monotonic() - started > .2)
    assert time.monotonic() - started < 5 and provider.process is None
    assert not list((tmp_path / "cache").glob("[0-9a-f]" * 64))


def test_asset_and_settings_validation_is_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="timeout"):
        PunctoraSpecialistAssets(sys.executable, str(tmp_path.resolve()), "forever").validate()
    with pytest.raises(ValueError, match="overlap"):
        SpecialistSettings(level_bounds=(
            {"name": "a", "bottom_m": 0., "top_m": 3.},
            {"name": "b", "bottom_m": 2., "top_m": 4.})).validate()
