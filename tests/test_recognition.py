from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np
import pytest

from punctora_core.annotation_io import content_digest, file_digest, read_json
from punctora_core.cli import main
from punctora_core.cloud_io import CloudData
from punctora_core.model import BuildingModel, Storey, Wall, Opening
from punctora_core.quality_benchmark import write_report
from punctora_core.recognition.cache import ProposalCache
from punctora_core.recognition.classical_provider import ClassicalProvider
from punctora_core.recognition.cloud2bim_provider import (Cloud2BIMAssets, Cloud2BIMProvider,
    NATIVE_TO_TAXONOMY, POINTCEPT_REFERENCE)
from punctora_core.recognition.contracts import (TAXONOMY, ProviderUnavailable,
    load_proposal_set, validate_proposal_set)
from punctora_core.recognition.io import export_semantic_samples, load_input
from punctora_core.recognition.job import RecognitionControl, run_recognition
from punctora_core.recognition.preprocessing import PREPROCESSING, original_normals, prepare_model_input
from punctora_core.recognition.provider import RecognitionProvider, TilePrediction, combine_tiles, write_vote_shard
from punctora_core.recognition.tiling import TileIndex, TileSettings


def source():
    points = np.array([[.2, 0., 1.], [.8, 0., 1.], [1.9, 0., 1.], [2.05, 0., 1.],
                       [2.2, 0., 1.], [3.7, 0., 1.], [1.9, .2, 1.], [2.05, .2, 1.]], dtype=np.float64)
    return CloudData(points, scan_index=np.array([0, 1, 0, 1, 0, 1, 0, 1], dtype="<u8"),
        source_record_index=np.arange(2**53 + 1, 2**53 + 9, dtype="<u8"), working_index=np.arange(100, 108, dtype="<u8"))


def identity(crop=None):
    return {"case_id": "generated-recognition", "source_sha256": "a" * 64,
            "coordinate_mapping": {"translation_m": [600000., 5600000., 0.], "yaw_degrees": 0.}, "crop": crop}


def tiles():
    return TileSettings(size_m=2., overlap_m=.2, maximum_context_points=100, maximum_tiles=20)


class FixtureProvider(RecognitionProvider):
    def __init__(self, label=0, score=-.75, failure=None, backend="fixture CPU"):
        self.label, self.score, self.failure, self.backend = label, score, failure, backend
        self.prepared, self.closed, self.visits = 0, 0, []

    def descriptor(self):
        value = {"id": "generated_fixture", "version": "v1", "backend": self.backend,
                 "score_kind": "native_fixture_logit", "label": self.label, "score": self.score}
        return {**value, "fingerprint": content_digest(value)}

    def prepare(self, cloud, case, directory, control):
        self.prepared += 1
        if self.failure == "prepare":
            raise ProviderUnavailable("no explicit fixture assets")

    def infer_chunk(self, tile, directory, control):
        self.visits.append(tile.id)
        if self.failure == "infer":
            raise ProviderUnavailable("device unsupported")
        score = np.nan if self.failure == "malformed" else self.score
        return TilePrediction(np.full(len(tile.points), self.label, dtype="<i2"), np.full(len(tile.points), score, dtype="<f4"))

    def close(self):
        self.closed += 1


def run(tmp_path, provider=None, **kwargs):
    return run_recognition(source(), identity(), provider or FixtureProvider(), tmp_path / "cache", tile_settings=tiles(), **kwargs)


def test_f64_and_large_original_ids_roundtrip_without_geometry_authority(tmp_path):
    cloud = source()
    before = cloud.points.copy()
    directory, report, hit = run_recognition(cloud, identity(), FixtureProvider(), tmp_path / "cache", tile_settings=tiles())
    assert not hit and report["geometry_authority"] == "review_only"
    assert np.array_equal(before, cloud.points)
    for name, original in (("scan_ids", cloud.scan_index), ("record_ids", cloud.source_record_index), ("working_rows", cloud.working_index)):
        assert np.array_equal(np.load(directory / (name + ".npy")), original)
    assert np.all(np.load(directory / "labels.npy") == 0)
    assert np.all(np.load(directory / "scores.npy") == np.float32(-.75))
    assert np.load(directory / "record_ids.npy")[0] == 2**53 + 1
    assert load_proposal_set(directory) == report
    assert not list(directory.glob("attempt*")) and not list(directory.glob("*.ifc"))


def test_cache_hit_and_exact_point_provider_settings_invalidation(tmp_path):
    p = FixtureProvider()
    first = run(tmp_path, p)
    second = run(tmp_path, p)
    assert first[0] == second[0] and second[2] and p.prepared == 1
    third = run(tmp_path, FixtureProvider(label=2))
    assert third[0] != first[0]
    cloud = source()
    cloud.points[0, 0] += 1e-10
    changed = run_recognition(cloud, identity(), FixtureProvider(), tmp_path / "cache", tile_settings=tiles())
    assert changed[0] != first[0]
    changed_settings = run_recognition(source(), identity(), FixtureProvider(), tmp_path / "cache",
        tile_settings=TileSettings(size_m=2., overlap_m=.1, maximum_context_points=100, maximum_tiles=20))
    assert changed_settings[0] != first[0]


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(status="incomplete"),
    lambda d: d.update(geometry_authority="final"),
    lambda d: d.update(selected_point_count=-1),
    lambda d: d["provider"].update(score_kind="probability"),
    lambda d: d["identity"]["coordinate_mapping"].update(yaw_degrees=1),
    lambda d: d["arrays"]["record_ids"].update(path="../record_ids.npy"),
    lambda d: d["arrays"]["record_ids"].update(dtype="<f8"),
    lambda d: d["taxonomy"].append("fabricated"),
    lambda d: d["settings"].update(overlap_m=.99),
])
def test_manifest_corruption_fails_closed(tmp_path, mutation):
    directory, report, _ = run(tmp_path)
    bad = deepcopy(report)
    mutation(bad)
    with pytest.raises(ValueError):
        validate_proposal_set(bad, directory)


def test_array_corruption_and_malformed_existing_cache_never_replaced(tmp_path):
    directory, report, _ = run(tmp_path)
    np.save(directory / "labels.npy", np.full(8, 2, dtype="<i2"))
    with pytest.raises(ValueError, match="digest"):
        run(tmp_path)
    np.save(directory / "labels.npy", np.zeros(8, dtype="<i2"))
    cache = ProposalCache(tmp_path / "empty-existing")
    destination = cache.root / report["cache_key"]
    destination.mkdir()
    with cache.stage() as stage:
        # Only testing publication refusal; an incomplete existing directory
        # must not be treated as permission to overwrite it.
        import shutil
        for path in directory.glob("*.npy"):
            shutil.copyfile(path, stage / path.name)
        with pytest.raises((ValueError, FileNotFoundError)):
            cache.publish(stage, report)
    assert destination.exists() and not list(destination.iterdir())


def test_tile_halo_original_points_and_immutable_identity(tmp_path):
    cloud = source()
    crop = {"polygon": [[0., -.1], [2., -.1], [2., .1], [0., .1]], "z_min": 0., "z_max": 2.}
    index = TileIndex(cloud, tiles(), 32 * 1024**2, 3, tmp_path)
    try:
        tile = index.get((0, 0), crop)
        assert np.any(tile.points[:, 0] > 2.)  # original normal halo outside crop
        assert np.all(tile.points[tile.vote_mask, 0] <= 2.)
        with pytest.raises(ValueError):
            tile.points[0, 0] = 999
        assert np.array_equal(tile.record_ids, cloud.source_record_index[tile.context_rows])
    finally:
        index.close()


def test_overlap_tie_native_score_and_shard_order_independence(tmp_path):
    index = TileIndex(source(), tiles(), 32 * 1024**2, 4, tmp_path)
    class Control:
        chunk_points = 3
        def check(self): pass
    try:
        tile = index.get((0, 0), None)
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        first = write_vote_shard(tile, TilePrediction(np.zeros(len(tile.points), dtype="<i2"), np.full(len(tile.points), -5., dtype="<f4")), a)
        second = write_vote_shard(tile, TilePrediction(np.full(len(tile.points), 2, dtype="<i2"), np.full(len(tile.points), 100., dtype="<f4")), b)
        combine_tiles([first, second], 8, a, Control())
        combine_tiles([second, first], 8, b, Control())
        assert np.array_equal(np.load(a / "labels.npy"), np.load(b / "labels.npy"))
        assert np.array_equal(np.load(a / "scores.npy"), np.load(b / "scores.npy"))
        labels = np.load(a / "labels.npy")
        assert np.all(labels[tile.context_rows[tile.vote_mask]] == 0)  # counts, not score
        assert np.all(np.load(a / "scores.npy")[labels == 0] == -5.)
    finally:
        index.close()


@pytest.mark.parametrize("field", ["scan_index", "source_record_index", "working_index"])
def test_negative_exact_source_id_rejected(tmp_path, field):
    cloud = source()
    setattr(cloud, field, getattr(cloud, field).astype(np.int64))
    getattr(cloud, field)[0] = -1
    with pytest.raises(ValueError, match="nonnegative"):
        run_recognition(cloud, identity(), FixtureProvider(), tmp_path / "cache", tile_settings=tiles())
    assert not list((tmp_path / "cache").iterdir())


def test_global_duplicate_source_ids_even_in_separate_tiles_rejected(tmp_path):
    cloud = source()
    cloud.scan_index[5] = cloud.scan_index[0]
    cloud.source_record_index[5] = cloud.source_record_index[0]
    with pytest.raises(ValueError, match="Duplicate original"):
        run_recognition(cloud, identity(), FixtureProvider(), tmp_path / "cache", tile_settings=tiles())


def test_duplicate_working_id_and_missing_original_ids_rejected(tmp_path):
    cloud = source()
    cloud.working_index[4] = cloud.working_index[0]
    with pytest.raises(ValueError, match="Duplicate working"):
        run_recognition(cloud, identity(), FixtureProvider(), tmp_path / "cache", tile_settings=tiles())
    cloud.scan_index = None
    with pytest.raises(ValueError, match="original scan"):
        run_recognition(cloud, identity(), FixtureProvider(), tmp_path / "cache", tile_settings=tiles())


@pytest.mark.parametrize("failure", ["prepare", "infer"])
def test_explicit_fallback_retains_requested_and_used_provider(tmp_path, failure):
    p = FixtureProvider(failure=failure)
    fallback = FixtureProvider(label=2, backend="classical fixture CPU")
    directory, report, _ = run(tmp_path, p, fallback=fallback)
    assert report["requested_provider"]["backend"] == "fixture CPU"
    assert report["provider"]["backend"] == "classical fixture CPU"
    assert any("fallback" in text for text in report["warnings"])
    assert np.all(np.load(directory / "labels.npy") == 2)
    assert p.closed and fallback.closed


def test_malformed_predictions_do_not_fallback_or_publish(tmp_path):
    fallback = FixtureProvider()
    with pytest.raises(ValueError, match="nonfinite"):
        run(tmp_path, FixtureProvider(failure="malformed"), fallback=fallback)
    assert fallback.prepared == 0 and not list((tmp_path / "cache").iterdir())


def test_cancellation_discards_generation_preserves_diagnostics(tmp_path):
    p = FixtureProvider()
    diagnostics = []
    with pytest.raises(InterruptedError):
        run(tmp_path, p, cancelled=lambda: bool(p.visits), diagnostics=diagnostics.append)
    assert not list((tmp_path / "cache").iterdir())
    assert diagnostics[-1]["status"] == "cancelled"
    assert diagnostics[-1]["fraction_limit"] == .70


def test_empty_crop_and_context_overflow_fail_without_silent_decimation(tmp_path):
    crop = {"polygon": [[100., 100.], [101., 100.], [101., 101.], [100., 101.]], "z_min": None, "z_max": None}
    with pytest.raises(ValueError, match="no original points"):
        run_recognition(source(), identity(crop), FixtureProvider(), tmp_path / "cache", tile_settings=tiles())
    tiny = TileSettings(size_m=2., overlap_m=.2, maximum_context_points=1)
    with pytest.raises(ProviderUnavailable, match="never silently decimate"):
        run_recognition(source(), identity(), FixtureProvider(), tmp_path / "cache", tile_settings=tiny)


def test_normals_use_original_neighbours_and_deterministic_voxel_inverse():
    points = np.array([[x, y, 1.] for x in (0., .04, .08) for y in (0., .04, .08)])
    normals, valid = original_normals(points, np.array([4]))
    assert valid[0] and np.allclose(normals[0], [0., 0., 1.])
    inputs = prepare_model_input(points, np.ones(len(points), dtype=bool))
    assert inputs["feat"].shape[1] == 3 and inputs["coord"].dtype == np.float32
    assert len(inputs["inverse"]) == len(points)
    assert len(inputs["coord"]) < len(points)
    assert inputs["origin_m"].dtype == np.float64
    assert prepare_model_input(np.array([[0., 0., 0.], [1., 0., 0.]]), np.ones(2, dtype=bool)) is None


def test_classical_adapter_preserves_host_and_does_not_label_inferred_axis(tmp_path):
    wall = Wall("w", "l", (0., 0.), (4., 0.), 0., 3., .2,
        observed_faces=[{"start": [0., 0.], "end": [4., 0.], "z_min": 0., "z_max": 3.}],
        provenance={"axis": "inferred", "observed_face": "measured"})
    model = BuildingModel("fixture", storeys=[Storey("l", "l", 0., 3., [[0., -1.], [4., -1.], [4., 1.], [0., 1.]])],
                          walls=[wall], openings=[Opening("o", "w", "window", 1., 1., .5, .5)])
    original = model.to_dict()
    directory, report, _ = run(tmp_path, ClassicalProvider(model=model))
    assert report["provider"]["backend"] == "CPU"
    instances = {item["class"]: item for item in report["instances"]}
    assert instances["window"]["host_id"] == instances["wall"]["id"]
    assert model.to_dict() == original
    assert np.array_equal(np.load(directory / "labels.npy"), [0, 0, 0, 0, 0, 0, -1, -1])


def test_semantic_sidecar_exact_ids_empty_geometry_and_label_blinding(tmp_path):
    directory, _, _ = run(tmp_path)
    cloud = source()
    keys = [{"source_sha256": "a" * 64, "scan_index": int(cloud.scan_index[0]), "source_record_index": int(cloud.source_record_index[0])}]
    report = export_semantic_samples(directory, keys, tmp_path / "semantic.json")
    assert report["elements"] == [] and report["semantic_samples"][0]["source_record_index"] == 2**53 + 1
    assert report["semantic_samples"][0]["label"] == "wall"
    with pytest.raises(ValueError, match="no labels"):
        export_semantic_samples(directory, [{**keys[0], "label": "wall"}])
    with pytest.raises(ValueError, match="immutable"):
        export_semantic_samples(directory, keys, directory / "proposals-v1.json")


def test_unsupported_native_classes_remain_visible_not_remapped(tmp_path):
    assert len(NATIVE_TO_TAXONOMY) == 12
    assert TAXONOMY[NATIVE_TO_TAXONOMY[5]] == "beam"
    directory, _, _ = run(tmp_path, FixtureProvider(label=TAXONOMY.index("beam")))
    key = {"source_sha256": "a" * 64, "scan_index": 0, "source_record_index": 2**53 + 1}
    report = export_semantic_samples(directory, [key])
    assert not report["semantic_samples"] and report["export_diagnostics"]["unknown_or_unsupported_labels"] == 1


def make_assets(tmp_path, device="cpu"):
    checkpoint = tmp_path / "checkpoint.pth"
    checkpoint.write_bytes(b"fixture-not-real-model" * 100)
    config = tmp_path / "model-config.json"
    write_report(config, {"schema_version": 1, "preprocessing": PREPROCESSING,
                         "model": {"type": "DefaultSegmentorV2", "num_classes": 12, "backbone": {"in_channels": 3}}})
    runtime = tmp_path / "runtime.json"
    write_report(runtime, {"schema_version": 1, "python_version": platform.python_version(),
        "pointcept_commit": POINTCEPT_REFERENCE, "pointcept_python_tree_sha256": "b" * 64,
        "packages": {name: "fixture-version" for name in ("numpy", "scipy", "torch", "spconv", "torch-scatter", "torch-cluster")}})
    return Cloud2BIMAssets(str(Path(sys.executable).resolve()), str(checkpoint), file_digest(checkpoint),
                          str(config), file_digest(config), str(runtime), file_digest(runtime), device=device)


def test_missing_checkpoint_unsupported_device_and_asset_tamper(tmp_path):
    assets = make_assets(tmp_path)
    Path(assets.checkpoint).unlink()
    provider = Cloud2BIMProvider(assets)
    _, report, _ = run(tmp_path, provider, fallback=FixtureProvider())
    assert report["requested_provider"]["id"] == "cloud2bim_experimental"
    assert any("automatic downloads are disabled" in w for w in report["warnings"])
    bad_device = Cloud2BIMProvider(make_assets(tmp_path, device="opencl"))
    _, report, _ = run(tmp_path, bad_device, fallback=FixtureProvider())
    assert any("no AMD/OpenCL claim" in w for w in report["warnings"])
    assets = make_assets(tmp_path)
    Path(assets.model_config).write_text("{}")
    with pytest.raises(ValueError, match="digest mismatch"):
        run(tmp_path, Cloud2BIMProvider(assets), fallback=FixtureProvider())


def test_isolated_worker_transport_and_cancellation(tmp_path, monkeypatch):
    from punctora_core.recognition import cloud2bim_provider as module
    assets = make_assets(tmp_path)
    owned_worker = tmp_path / "owned-fixture-worker.py"
    owned_worker.write_text("import json,sys,numpy as np\nfrom pathlib import Path\nr=json.loads(Path(sys.argv[1]).read_text())\np=np.load(r['points'])\no=Path(r['output_directory'])\nnp.save(o/'labels.npy',np.zeros(len(p),dtype='<i2'))\nnp.save(o/'scores.npy',np.full(len(p),-.25,dtype='<f4'))\n")
    popen = subprocess.Popen
    spawned = []
    def fixture_process(command, **kwargs):
        assert command[1] == "-I" and not kwargs.get("shell", False)
        assert "PYTHONPATH" not in kwargs["env"]
        command[2] = str(owned_worker)
        process = popen(command, **kwargs)
        spawned.append(process)
        return process
    monkeypatch.setattr(module.subprocess, "Popen", fixture_process)
    directory, report, _ = run(tmp_path, Cloud2BIMProvider(assets))
    assert report["provider"]["backend"] == "cpu"
    assert np.all(np.load(directory / "scores.npy") == np.float32(-.25))
    assert spawned and all(p.poll() == 0 for p in spawned)
    owned_worker.write_text("import time\ntime.sleep(60)\n")
    p = Cloud2BIMProvider(assets)
    start = time.monotonic()
    with pytest.raises(InterruptedError):
        run(tmp_path / "cancel", p, cancelled=lambda: p.process is not None)
    assert time.monotonic() - start < 10.
    assert spawned[-1].poll() is not None
    assert not list((tmp_path / "cancel" / "cache").iterdir())


def test_core_does_not_import_model_stack():
    output = subprocess.check_output([sys.executable, "-c", "from punctora_core.recognition.job import run_recognition; from punctora_core.recognition.cloud2bim_provider import Cloud2BIMProvider; import sys; assert not any(n in sys.modules for n in ('torch','pointcept','open3d','spconv'))"], text=True)
    assert output == ""


def test_typed_input_readonly_cli_guards_and_semantic_cli(tmp_path):
    cloud = source()
    arrays = {}
    for name, value in (("points", cloud.points), ("scan_ids", cloud.scan_index), ("record_ids", cloud.source_record_index), ("working_rows", cloud.working_index)):
        path = tmp_path / (name + ".npy")
        np.save(path, value)
        arrays[name] = {"path": path.name, "shape": list(value.shape), "dtype": value.dtype.str, "sha256": file_digest(path)}
    manifest = tmp_path / "input.json"
    write_report(manifest, {"schema_version": 1, "identity": identity(), "arrays": arrays,
                            "source_scope": "complete_original_registered_cloud"})
    with load_input(manifest) as (loaded, case):
        assert loaded.points.dtype == np.float64 and not loaded.points.flags.writeable and case == identity()
    with pytest.raises(SystemExit):
        main(["recognition-propose", str(manifest), "--cache-dir", str(tmp_path / "cache"), "--diagnostics", str(tmp_path / "points.npy")])
    assert file_digest(tmp_path / "points.npy") == arrays["points"]["sha256"]
    directory, _, _ = run(tmp_path)
    keys = tmp_path / "keys.json"
    write_report(keys, [{"source_sha256": "a" * 64, "scan_index": 0, "source_record_index": 2**53 + 1}])
    assert main(["recognition-export-samples", str(directory), str(keys), "--output", str(tmp_path / "semantic.json")]) == 0


def test_resource_plan_obeys_70_percent_and_lower_user_cap():
    control = RecognitionControl()
    assert control.memory_limit_bytes <= int(control.available_at_start * .70)
    assert control.chunk_points <= 65536
    with pytest.raises(ValueError, match="Insufficient available RAM"):
        RecognitionControl(memory_limit_bytes=1024)


def test_cancellation_at_publication_preserves_existing_generation(tmp_path):
    directory, report, _ = run(tmp_path)
    cache = ProposalCache(tmp_path / "cache")
    before = (directory / "proposals-v1.json").read_bytes()
    with cache.stage() as stage:
        import shutil
        for artifact in directory.glob("*.npy"):
            shutil.copyfile(artifact, stage / artifact.name)
        with pytest.raises(InterruptedError):
            cache.publish(stage, deepcopy(report), cancelled=lambda: True)
    assert (directory / "proposals-v1.json").read_bytes() == before
    assert not list(cache.root.glob(".proposal-stage-*"))


def test_chunk_size_and_source_order_independence(tmp_path):
    cloud = source()
    directory, _, _ = run_recognition(cloud, identity(), FixtureProvider(), tmp_path / "small", tile_settings=tiles(), chunk_points=1)
    permuted = CloudData(cloud.points[::-1], scan_index=cloud.scan_index[::-1], source_record_index=cloud.source_record_index[::-1],
                         working_index=cloud.working_index[::-1])
    other, _, _ = run_recognition(permuted, identity(), FixtureProvider(), tmp_path / "large", tile_settings=tiles(), chunk_points=65536)
    assert np.array_equal(np.load(directory / "labels.npy"), np.load(other / "labels.npy")[::-1])
    assert np.array_equal(np.load(directory / "record_ids.npy"), np.load(other / "record_ids.npy")[::-1])


def test_crop_fusion_and_export_counts_outside_and_missing_ids(tmp_path):
    crop = {"polygon": None, "z_min": None, "z_max": 2.}
    cloud = source()
    cloud.points[0, 2] = 3.
    directory, _, _ = run_recognition(cloud, identity(crop), FixtureProvider(), tmp_path / "cache", tile_settings=tiles())
    assert np.load(directory / "labels.npy")[0] == -1
    keys = [{"source_sha256": "a" * 64, "scan_index": 0, "source_record_index": 2**53 + 1},
            {"source_sha256": "a" * 64, "scan_index": 99, "source_record_index": 0}]
    report = export_semantic_samples(directory, keys)
    assert report["export_diagnostics"]["outside_crop"] == 1
    assert report["export_diagnostics"]["missing_original_ids"] == 1


def test_completed_array_labels_cannot_escape_crop_even_with_new_file_digest(tmp_path):
    directory, report, _ = run(tmp_path)
    # Alter a selected bit and forge only the artifact digest, not the source
    # mask invariant. Validation must still catch labels outside the crop.
    selected = np.ones(8, dtype=bool)
    selected[0] = False
    np.save(directory / "selected.npy", selected)
    bad = deepcopy(report)
    bad["arrays"]["selected"]["sha256"] = file_digest(directory / "selected.npy")
    bad["selected_point_count"] = 7
    bad["proposal_sha256"] = content_digest({k: v for k, v in bad.items() if k != "proposal_sha256"})
    with pytest.raises(ValueError, match="Unselected"):
        validate_proposal_set(bad, directory)
