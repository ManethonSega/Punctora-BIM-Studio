from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pytest

from punctora_core.annotation_io import content_digest, file_digest, read_json
from punctora_core.cli import main
from punctora_core.cloud_io import CloudData
from punctora_core.model import BuildingModel, Storey, Wall
from punctora_core.planar_index import cluster_original_points
from punctora_core.quality_benchmark import write_report
from punctora_core.recognition.classical_provider import ClassicalProvider
from punctora_core.recognition.contracts import ProviderUnavailable, load_proposal_set, validate_proposal_set
from punctora_core.recognition.element_graph import build_graph, validate_graph
from punctora_core.recognition.hybrid import HybridProvider, HybridSettings
from punctora_core.recognition.job import run_recognition
from punctora_core.recognition.provider import RecognitionProvider, TilePrediction
from punctora_core.recognition.tiling import TileSettings
from punctora_core.recognition.vision_provider import (IsolatedVisionProvider, ProjectedEvidenceProvider,
    VisionAssets, VisionProvider, validate_detections)
from punctora_core.recognition.wall_projection import project_wall, wall_frames


def case(crop=None):
    return {"case_id": "generated-hybrid", "source_sha256": "a" * 64,
            "coordinate_mapping": {"translation_m": [0., 0., 0.], "yaw_degrees": 0.}, "crop": crop}


def fixture(filling=False, sparse=False, angle=.31, shift=(600000.123456789, 5600000.123456789), door=False):
    x, z = np.meshgrid(np.arange(.025, 8., .05), np.arange(.025, 3.2, .05))
    base = np.column_stack((x.ravel(), np.zeros(x.size), z.ravel()))
    holes = np.zeros(len(base), dtype=bool)
    for low in (1., 2.4, 3.8):
        holes |= (base[:, 0] >= low) & (base[:, 0] < low + 1.) & (base[:, 2] >= 1.) & (base[:, 2] < 2.2)
    if door:
        holes |= (base[:, 0] >= 5.5) & (base[:, 0] < 6.5) & (base[:, 2] < 2.1)
    a, b = base[~holes].copy(), base[~holes].copy()
    a[:, 1], b[:, 1] = .1, -.1
    points, labels = np.r_[a, b], np.zeros(len(a) + len(b), dtype="<i2")
    if filling:
        glass = base[holes].copy()
        kinds = np.where(glass[:, 0] > 5., 1, 2).astype("<i2")
        if sparse: glass, kinds = glass[::20], kinds[::20]
        points, labels = np.r_[points, glass], np.r_[labels, kinds]
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    origin = np.array(shift)
    points[:, :2] = points[:, :2] @ rotation.T + origin
    points[:, 2] += 10.
    faces = [{"start": (np.array([0., offset]) @ rotation.T + origin).tolist(),
              "end": (np.array([8., offset]) @ rotation.T + origin).tolist(), "z_min": 10., "z_max": 13.2} for offset in (.1, -.1)]
    wall = Wall("w", "l", tuple(origin), tuple(np.array([8., 0.]) @ rotation.T + origin), 10., 3.2, .2,
                observed_faces=faces, provenance={"dimensions": "measured"})
    model = BuildingModel("generated", storeys=[Storey("l", "l", 10., 13.2, [[0., 0.], [10., 0.], [10., 10.], [0., 10.]])], walls=[wall])
    cloud = CloudData(points, scan_index=np.arange(len(points), dtype="<u8") % 3,
        source_record_index=np.arange(2**53 + 1, 2**53 + 1 + len(points), dtype="<u8"),
        working_index=np.arange(100000, 100000 + len(points), dtype="<u8"),
        colors=np.tile([1200., 255., 32768.], (len(points), 1)), color_valid=np.ones(len(points), dtype=bool))
    return cloud, model, labels


class LabelFixtureProvider(ClassicalProvider):
    def __init__(self, model, labels):
        super().__init__(model=model)
        self.labels = labels

    def descriptor(self):
        value = super().descriptor()
        value.pop("fingerprint")
        value["id"], value["score_kind"] = "generated_labels_with_classical_geometry", "fixture_native_margin"
        value["fixture_labels_sha256"] = __import__("hashlib").sha256(self.labels.tobytes()).hexdigest()
        return {**value, "fingerprint": content_digest(value)}

    def infer_chunk(self, tile, directory, control):
        return TilePrediction(self.labels[tile.context_rows], np.full(len(tile.points), -.8, dtype="<f4"))


def make_upstream(tmp_path, cloud, model, labels, identity=None):
    return run_recognition(cloud, identity or case(), LabelFixtureProvider(model, labels), tmp_path / "source",
                           tile_settings=TileSettings(maximum_context_points=50000))[0]


def fuse(tmp_path, *, filling=False, sparse=False, door=False, vision=None, crop=None):
    cloud, model, labels = fixture(filling, sparse, door=door)
    identity = case(crop)
    original = make_upstream(tmp_path, cloud, model, labels, identity)
    provider = HybridProvider(original, vision, HybridSettings(cell_m=.1, maximum_projection_cells=5000,
                                                               maximum_wall_context_points=50000, maximum_column_points=50000))
    result = run_recognition(cloud, identity, provider, tmp_path / "hybrid", tile_settings=TileSettings(maximum_context_points=50000))
    return cloud, model, original, result


def openings(report):
    return [i for i in report["instances"] if i["class"] in {"opening", "door", "window"}]


def test_exact_both_view_pixel_identity_local_roundtrip_and_f64_rgb():
    cloud, model, _ = fixture()
    wall = {"id": "wall", "geometry": {"type": "wall", "start": list(model.walls[0].start), "end": list(model.walls[0].end),
            "base": 10., "height": 3.2, "thickness": .2}, "observed_faces": model.walls[0].observed_faces}
    for frame in wall_frames(wall, .1):
        pixels = np.array([[0, 0], [3, 7], [frame.shape[1] - 1, frame.shape[0] - 1]])
        world = frame.pixel_centres(pixels, .07)
        recovered, valid = frame.pixels(frame.local(world))
        assert valid.all() and np.array_equal(recovered, pixels)
        assert np.allclose(frame.world(frame.local(cloud.points[:200])), cloud.points[:200], rtol=0, atol=2e-9)
        projection = project_wall(cloud, np.arange(len(cloud.points)), frame, maximum_context_points=50000)
        mask = projection.return_counts > 0
        rows = projection.rows_for_mask(mask)
        assert np.array_equal(rows, projection.source_rows)
        assert cloud.source_record_index[rows].min() > 2**53
        assert projection.rgb.dtype == np.float64 and projection.rgb[projection.rgb_valid, 2].max() == 32768.


def test_void_only_both_faces_fuse_three_bays_plus_floor_portal_without_fillings(tmp_path):
    cloud, model, original, (directory, report, hit) = fuse(tmp_path, door=True)
    values = openings(report)
    assert not hit and len(values) == 4
    assert all(i["class"] == "opening" and i["classification_state"] == "unknown" and i["filling"] == "unknown" for i in values)
    assert all(i["cut_applied"] is False and i["host_validation_state"] == "pending_run4" for i in values)
    assert all(i["void_only"] and i["candidate_count"] == 2 for i in values)
    assert not model.openings  # Neither accepted model nor IFC writer touched.
    graph = read_json(directory / "hybrid/element-graph-v1.json")
    assert graph["bay_groups"] and len(graph["bay_groups"][0]["member_ids"]) == 3
    assert sum(e["relation"] == "hosted_by" for e in graph["edges"]) == 4
    assert report["extensions"]["hybrid_v1"]["diagnostics"]["both_face_duplicates_removed"] == 4
    for item in values:
        for evidence_id in item["evidence_ids"]:
            proof = next(e for e in graph["evidence"] if e["id"] == evidence_id)
            rows = np.load(directory / proof["source_rows_path"])
            assert len(rows) > 0 and rows.dtype == np.dtype("<u8")
            assert cloud.source_record_index[rows].min() > 2**53
    assert np.array_equal(np.load(original / "labels.npy"), np.load(directory / "labels.npy"))
    assert load_proposal_set(directory) == report


@pytest.mark.parametrize("sparse", [False, True])
def test_filling_labels_support_suggested_window_door_classes_sparse_and_reflective(tmp_path, sparse):
    _, _, _, (_, report, _) = fuse(tmp_path, filling=True, sparse=sparse, door=True)
    values = openings(report)
    assert len(values) == 4
    assert sum(i["class"] == "window" for i in values) == 3
    assert sum(i["class"] == "door" for i in values) == 1
    assert all(i["classification_state"] == "suggested" and i["filling"] == "unknown" and not i["void_only"] for i in values)
    assert all(i["native_score"] is None and i["cut_applied"] is False for i in values)


class FixtureVision(VisionProvider):
    def __init__(self, classification="window", score=1e9, unavailable=False, malformed=False):
        self.classification, self.score, self.unavailable, self.malformed = classification, score, unavailable, malformed

    def descriptor(self):
        value = {"id": "generated_2d", "version": "1", "backend": "CPU_fixture", "score_kind": "fixture_margin",
                 "class": self.classification, "score": self.score, "unavailable": self.unavailable, "malformed": self.malformed}
        return {**value, "fingerprint": content_digest(value)}

    def prepare(self, directory, control):
        if self.unavailable: raise ProviderUnavailable("fixture runtime unavailable")

    def infer(self, projection, directory, control):
        result = ProjectedEvidenceProvider().infer(projection, directory, control)
        for region in result:
            region["class"], region["native_score"], region["score_kind"] = self.classification, self.score, "fixture_margin"
            region["evidence"] = {"method": "controlled_2d"}
        if self.malformed and result: result[0]["box"][2] = projection.frame.shape[1] + 10
        return result


def test_native_score_scales_never_override_contradicting_class_evidence(tmp_path):
    _, _, _, (_, report, _) = fuse(tmp_path, filling=True, door=True, vision=FixtureVision())
    values = openings(report)
    assert len(values) == 4  # both views and two providers do not add duplicates
    conflict = next(i for i in values if i["classification_state"] == "conflicting")
    assert conflict["class"] == "opening"
    assert {c["class"] for c in conflict["class_claims"]} == {"door", "window"}
    assert any(c["native_score"] == 1e9 for c in conflict["class_claims"])
    assert any(c["native_score"] == float(np.float32(-.8)) for c in conflict["class_claims"])
    assert conflict["native_score"] is None and conflict["cut_applied"] is False


def test_empty_void_not_classified_by_an_unsupported_2d_assertion(tmp_path):
    _, _, _, (_, report, _) = fuse(tmp_path, vision=FixtureVision())
    assert len(openings(report)) == 3 and all(i["class"] == "opening" for i in openings(report))


def test_unavailable_vision_and_unsupported_classes_keep_classical_path(tmp_path):
    _, _, _, (_, report, _) = fuse(tmp_path / "missing", vision=FixtureVision(unavailable=True))
    assert len(openings(report)) == 3 and any("classical" in w and "unavailable" in w for w in report["warnings"])
    _, _, _, (_, unsupported, _) = fuse(tmp_path / "beam", filling=True, vision=FixtureVision(classification="beam"))
    assert len(openings(unsupported)) == 3 and all(i["class"] != "beam" for i in unsupported["instances"])
    assert unsupported["extensions"]["hybrid_v1"]["diagnostics"]["unsupported_2d_classes"]["beam"] == 6


def test_bad_2d_regions_fail_instead_of_silently_falling_back(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        fuse(tmp_path, vision=FixtureVision(malformed=True))
    assert not list((tmp_path / "hybrid").glob(".proposal-stage-*"))
    assert not list((tmp_path / "hybrid").glob("[0-9a-f]" * 64))


def test_same_class_scores_and_missing_labels_not_used_as_probability(tmp_path):
    _, _, _, (directory, report, _) = fuse(tmp_path, filling=True, vision=FixtureVision(score=-150.))
    assert len(openings(report)) == 3 and all(i["class"] == "window" for i in openings(report))
    graph = read_json(directory / "hybrid/element-graph-v1.json")
    kinds = {e["score_kind"] for e in graph["evidence"] if "score_kind" in e}
    assert "fixture_margin" in kinds and "minimum_frame_occupancy_fraction" in kinds
    assert all(i["native_score"] is None for i in openings(report))


def test_projection_and_clustering_order_independence_and_no_colour_scale_assumption(tmp_path):
    cloud, model, labels = fixture(filling=True)
    first = make_upstream(tmp_path / "first", cloud, model, labels)
    settings = HybridSettings(cell_m=.1, maximum_projection_cells=5000, maximum_wall_context_points=50000, maximum_column_points=50000)
    a, report_a, _ = run_recognition(cloud, case(), HybridProvider(first, settings=settings), tmp_path / "a", tile_settings=TileSettings(maximum_context_points=50000), chunk_points=127)
    order = np.arange(len(cloud.points))[::-1]
    permuted = CloudData(cloud.points[order], colors=cloud.colors[order], color_valid=cloud.color_valid[order], scan_index=cloud.scan_index[order],
                        source_record_index=cloud.source_record_index[order], working_index=cloud.working_index[order])
    second = make_upstream(tmp_path / "second", permuted, model, labels[order])
    b, report_b, _ = run_recognition(permuted, case(), HybridProvider(second, settings=settings), tmp_path / "b", tile_settings=TileSettings(maximum_context_points=50000), chunk_points=4096)
    signature = lambda report: sorted((i["id"], i["class"], i["geometry"]) for i in openings(report))
    assert signature(report_a) == signature(report_b)
    view_a = read_json(a / "hybrid/projections-v1.json")["views"][0]
    view_b = read_json(b / "hybrid/projections-v1.json")["views"][0]
    for key in ("face_counts", "return_counts", "signed_depth_m", "rgb", "rgb_valid"):
        assert np.array_equal(np.load(a / view_a["arrays"][key]), np.load(b / view_b["arrays"][key]), equal_nan=True)


def test_cluster_core_border_order_and_original_key_precision():
    points = np.array([[x, y, z] for x in (0., .05) for y in (0., .05) for z in (0., .1, .2)])
    points = np.r_[points, points + [2., 0., 0.], [[10., 10., 10.]]]
    scan = np.zeros(len(points), dtype=np.int64)
    record = np.arange(2**53 + 1, 2**53 + 1 + len(points), dtype="<u8")
    a = cluster_original_points(points, scan, record, .2, 4)
    order = np.arange(len(points))[::-1]
    b = cluster_original_points(points[order], scan[order], record[order], .2, 4)
    assert len(a) == len(b) == 2
    assert [set(record[c].tolist()) for c in a] == [set(record[order[c]].tolist()) for c in b]
    assert all(record[c].min() > 2**53 for c in a)


def test_sparse_planar_column_retains_unknown_thickness_no_fabricated_geometry(tmp_path):
    cloud, model, labels = fixture()
    column = np.array([[20., 20., 10. + z] for z in np.arange(0., .9, .1)])
    # Three nearly collocated source returns per level keep a rare thin/occluded
    # component clustered without inventing a back face or missing top/base.
    column = np.repeat(column, 3, axis=0)
    cloud = CloudData(np.r_[cloud.points, column], scan_index=np.r_[cloud.scan_index, np.zeros(len(column), dtype="<u8")],
        source_record_index=np.r_[cloud.source_record_index, np.arange(2**53 + 100000, 2**53 + 100000 + len(column), dtype="<u8")],
        working_index=np.arange(len(cloud.points) + len(column), dtype="<u8"))
    labels = np.r_[labels, np.full(len(column), 11, dtype="<i2")]
    source = make_upstream(tmp_path, cloud, model, labels)
    directory, report, _ = run_recognition(cloud, case(), HybridProvider(source, settings=HybridSettings(cell_m=.1)), tmp_path / "fused")
    columns = [i for i in report["instances"] if i["class"] == "column"]
    assert len(columns) == 1 and columns[0]["geometry"] is None
    assert columns[0]["geometry_state"] == "insufficient_for_parametric_geometry" and columns[0]["completion"] == "none"
    assert columns[0]["bounds_m"][1][2] - columns[0]["bounds_m"][0][2] < 1.
    assert load_proposal_set(directory) == report


def test_changed_points_mapping_and_crop_rejected_against_upstream(tmp_path):
    cloud, model, labels = fixture()
    original = make_upstream(tmp_path, cloud, model, labels)
    cloud.points[0, 0] += 1e-8
    with pytest.raises(ValueError, match="upstream original"):
        run_recognition(cloud, case(), HybridProvider(original), tmp_path / "changed")
    different = case()
    different["coordinate_mapping"]["yaw_degrees"] = .1
    with pytest.raises(ValueError, match="upstream original"):
        run_recognition(cloud, different, HybridProvider(original), tmp_path / "mapping")


def test_rgb_validity_cache_invalidation_and_replay(tmp_path):
    cloud, _, source, (directory, report, _) = fuse(tmp_path)
    settings = HybridSettings(cell_m=.1, maximum_projection_cells=5000, maximum_wall_context_points=50000, maximum_column_points=50000)
    provider = HybridProvider(source, settings=settings)
    again = run_recognition(cloud, case(), provider, tmp_path / "hybrid", tile_settings=TileSettings(maximum_context_points=50000))
    assert again[2] and again[0] == directory and again[1] == report
    cloud.colors[0, 0] += 1.
    changed = run_recognition(cloud, case(), HybridProvider(source, settings=settings), tmp_path / "hybrid", tile_settings=TileSettings(maximum_context_points=50000))
    assert not changed[2] and changed[0] != directory
    cloud.color_valid[0] = False
    changed_valid = run_recognition(cloud, case(), HybridProvider(source, settings=settings), tmp_path / "hybrid", tile_settings=TileSettings(maximum_context_points=50000))
    assert changed_valid[0] != changed[0]


@pytest.mark.parametrize("mutate", [
    lambda g: g["edges"][0].update(target="missing"),
    lambda g: g["edges"][0].update(evidence_ids=[]),
    lambda g: g["nodes"][0].update(status="user_confirmed"),
    lambda g: g["nodes"][0].update(cut_applied=True),
    lambda g: g["nodes"].append(deepcopy(g["nodes"][0])),
])
def test_graph_bad_references_duplicate_ids_and_promotion_rejected(tmp_path, mutate):
    _, _, _, (directory, _, _) = fuse(tmp_path)
    graph = read_json(directory / "hybrid/element-graph-v1.json")
    mutate(graph)
    graph["graph_sha256"] = content_digest({k: v for k, v in graph.items() if k != "graph_sha256"})
    with pytest.raises(ValueError): validate_graph(graph)


def test_graph_containment_cycle_rejected():
    proof = [{"id": "p", "kind": "fixture"}]
    nodes = [{"id": name, "class": "column", "status": "proposed", "evidence_ids": ["p"], "cut_applied": False} for name in ("a", "b")]
    edges = [{"id": name, "source": a, "target": b, "relation": "part_of", "status": "proposed", "evidence_ids": ["p"]} for name, a, b in (("1", "a", "b"), ("2", "b", "a"))]
    graph = {"schema_version": 1, "identity": case(), "geometry_authority": "review_only", "upstream_proposal_sha256": "b" * 64,
             "nodes": nodes, "edges": edges, "evidence": proof}
    graph["graph_sha256"] = content_digest(graph)
    with pytest.raises(ValueError, match="Cyclic"): validate_graph(graph)


def test_artifact_tampering_and_repeat_fusion_rejected(tmp_path):
    cloud, _, _, (directory, report, _) = fuse(tmp_path)
    with pytest.raises(ValueError, match="unfused Run 2"):
        run_recognition(cloud, case(), HybridProvider(directory), tmp_path / "repeat")
    descriptor = next(a for a in report["extensions"]["hybrid_v1"]["artifacts"] if a.get("role") == "source_rows")
    with (directory / descriptor["path"]).open("ab") as stream: stream.write(b"tampered")
    with pytest.raises(ValueError, match="Hybrid artifact digest"): load_proposal_set(directory)


def test_cancellation_retains_diagnostics_and_saved_source_generation(tmp_path):
    cloud, model, labels = fixture()
    source = make_upstream(tmp_path, cloud, model, labels)
    before = (source / "proposals-v1.json").read_bytes()
    provider = HybridProvider(source)
    diagnostics = []
    with pytest.raises(InterruptedError):
        run_recognition(cloud, case(), provider, tmp_path / "cancel", cancelled=lambda: bool(getattr(provider, "frames", [])), diagnostics=diagnostics.append)
    assert (source / "proposals-v1.json").read_bytes() == before
    assert not list((tmp_path / "cancel").glob(".proposal-stage-*")) and diagnostics[-1]["status"] == "cancelled"


def test_partial_crop_does_not_certify_unscanned_frames(tmp_path):
    crop = {"polygon": None, "z_min": 10., "z_max": 11.7}
    _, _, _, (_, report, _) = fuse(tmp_path, crop=crop)
    assert not openings(report)  # Head evidence is outside the crop.


def test_projection_and_cluster_explicit_limits_never_silent_decimation():
    cloud, model, _ = fixture()
    wall = {"id": "w", "geometry": {"type": "wall", "start": list(model.walls[0].start), "end": list(model.walls[0].end), "base": 10., "height": 3.2, "thickness": .2}}
    with pytest.raises(ProviderUnavailable, match="never decimate"):
        project_wall(cloud, np.arange(len(cloud.points)), wall_frames(wall)[0], maximum_cells=1)
    with pytest.raises(ValueError, match="neighbour limit"):
        cluster_original_points(np.zeros((10, 3)), np.zeros(10, dtype="<u8"), np.arange(10, dtype="<u8"), maximum_neighbours=2)


def test_isolated_vision_protocol_missing_asset_and_malformed_regions(tmp_path):
    cloud, model, labels = fixture(filling=True)
    source = make_upstream(tmp_path, cloud, model, labels)
    worker = tmp_path / "owned-vision-fixture.py"
    worker.write_text("import json,sys\nfrom pathlib import Path\nr=json.loads(Path(sys.argv[1]).read_text())\nPath(r['output']).write_text(json.dumps({'schema_version':1,'frame_id':'view:'+__import__('hashlib').sha256(json.dumps(r['frame'],sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24],'image_sha256':r['image_sha256'],'runtime_fingerprint':r['runtime_fingerprint'],'detections':[]}))\n")
    config = tmp_path / "config.json"
    write_report(config, {"schema_version": 1, "trusted_local_worker": True, "runtime_fingerprint": "c" * 64})
    assets = VisionAssets(str(Path(sys.executable).resolve()), str(worker), file_digest(worker), str(config), file_digest(config), "c" * 64)
    _, report, _ = run_recognition(cloud, case(), HybridProvider(source, IsolatedVisionProvider(assets), HybridSettings(cell_m=.1)), tmp_path / "isolated")
    assert report["extensions"]["hybrid_v1"]["diagnostics"]["vision_used"]
    missing = replace(assets, worker=str(tmp_path / "not-present.py"))
    _, fallback, _ = run_recognition(cloud, case(), HybridProvider(source, IsolatedVisionProvider(missing), HybridSettings(cell_m=.1)), tmp_path / "missing")
    assert len(openings(fallback)) == 3 and any("unavailable" in w for w in fallback["warnings"])


def test_cli_typed_rgb_inputs_and_guards(tmp_path):
    cloud, model, labels = fixture()
    source = make_upstream(tmp_path, cloud, model, labels)
    arrays = {}
    for name, values in (("points", cloud.points), ("scan_ids", cloud.scan_index), ("record_ids", cloud.source_record_index),
                         ("working_rows", cloud.working_index), ("colors", cloud.colors), ("color_valid", cloud.color_valid)):
        path = tmp_path / (name + ".npy")
        np.save(path, values)
        arrays[name] = {"path": path.name, "dtype": values.dtype.str, "shape": list(values.shape), "sha256": file_digest(path)}
    manifest = tmp_path / "input.json"
    write_report(manifest, {"schema_version": 1, "identity": case(), "source_scope": "complete_original_registered_cloud", "arrays": arrays})
    with pytest.raises(SystemExit):
        main(["recognition-fuse", str(manifest), "--proposal-dir", str(source), "--cache-dir", str(tmp_path / "out"), "--diagnostics", str(tmp_path / "colors.npy")])
    assert file_digest(tmp_path / "colors.npy") == arrays["colors"]["sha256"]
    settings = tmp_path / "settings.json"
    write_report(settings, {"cell_m": .1})
    assert main(["recognition-fuse", str(manifest), "--proposal-dir", str(source), "--cache-dir", str(tmp_path / "out"), "--settings", str(settings)]) == 0


def test_unsupported_3d_labels_remain_unchanged_not_forced_into_windows(tmp_path):
    cloud, model, labels = fixture(filling=True)
    labels[labels == 2] = 12  # Native beam evidence, not a wall/window class.
    source = make_upstream(tmp_path, cloud, model, labels)
    directory, report, _ = run_recognition(cloud, case(), HybridProvider(source, settings=HybridSettings(cell_m=.1)), tmp_path / "fused")
    assert len(openings(report)) == 3 and all(i["class"] == "opening" for i in openings(report))
    assert report["extensions"]["hybrid_v1"]["diagnostics"]["unsupported_3d_classes"]["beam"] > 0
    assert np.array_equal(np.load(source / "labels.npy"), np.load(directory / "labels.npy"))


def test_observed_volume_column_retains_only_supported_extent(tmp_path):
    cloud, model, labels = fixture()
    column = np.array([[20. + x, 20. + y, 10. + z] for x in (0., .1, .2) for y in (0., .1, .2) for z in np.arange(.2, 1.3, .1)])
    total = len(cloud.points) + len(column)
    cloud = CloudData(np.r_[cloud.points, column], scan_index=np.zeros(total, dtype=np.int64),
                     source_record_index=np.arange(2**53 + 1, 2**53 + 1 + total, dtype="<u8"), working_index=np.arange(total, dtype="<u8"))
    labels = np.r_[labels, np.full(len(column), 11, dtype="<i2")]
    source = make_upstream(tmp_path, cloud, model, labels)
    _, report, _ = run_recognition(cloud, case(), HybridProvider(source, settings=HybridSettings(cell_m=.1)), tmp_path / "fused")
    values = [i for i in report["instances"] if i["class"] == "column"]
    assert len(values) == 1 and values[0]["geometry"] is not None
    assert values[0]["completion"] == "none" and values[0]["structural_role"] == "unknown"
    assert np.allclose(values[0]["bounds_m"], [column.min(axis=0), column.max(axis=0)])
    assert abs(values[0]["geometry"]["height"] - np.ptp(column[:, 2])) < 1e-10


def test_closed_flush_fillings_recovered_from_projected_3d_labels_without_voids(tmp_path):
    cloud, model, labels = fixture(filling=True, door=True)
    filling = labels > 0
    normal = np.array([-np.sin(.31), np.cos(.31)])
    backs = cloud.points[filling].copy()
    backs[:, :2] -= normal * .1
    cloud.points[filling, :2] += normal * .1
    points = np.r_[cloud.points, backs]
    labels = np.r_[labels, labels[filling]]
    cloud = CloudData(points, scan_index=np.zeros(len(points), dtype="<u8"),
                      source_record_index=np.arange(2**53 + 1, 2**53 + 1 + len(points), dtype="<u8"), working_index=np.arange(len(points), dtype="<u8"))
    source = make_upstream(tmp_path, cloud, model, labels)
    directory, report, _ = run_recognition(cloud, case(), HybridProvider(source, settings=HybridSettings(cell_m=.1)), tmp_path / "fused")
    values = openings(report)
    assert len(values) == 4 and sum(i["class"] == "window" for i in values) == 3 and sum(i["class"] == "door" for i in values) == 1
    graph = read_json(directory / "hybrid/element-graph-v1.json")
    methods = [e.get("provider_evidence", {}).get("method") for e in graph["evidence"]]
    assert "projected_semantic_component" in methods and "projected_observed_face_void" not in methods
    assert all(i["host_validation_state"] == "pending_run4" and i["cut_applied"] is False for i in values)


def test_closed_input_maps_can_be_represented_safely_in_error_reports(tmp_path):
    from punctora_core.recognition.io import load_input
    cloud, _, _ = fixture()
    arrays = {}
    for name, value in (("points", cloud.points), ("scan_ids", cloud.scan_index), ("record_ids", cloud.source_record_index), ("working_rows", cloud.working_index)):
        path = tmp_path / (name + ".npy")
        np.save(path, value)
        arrays[name] = {"path": path.name, "dtype": value.dtype.str, "shape": list(value.shape), "sha256": file_digest(path)}
    manifest = tmp_path / "input.json"
    write_report(manifest, {"schema_version": 1, "identity": case(), "source_scope": "complete_original_registered_cloud", "arrays": arrays})
    with load_input(manifest) as (loaded, _):
        assert "points_shape=" in repr(loaded)
    assert "original_ids=True" in repr(loaded)


def test_corrupt_pixel_map_rejected_even_if_its_artifact_digest_is_recomputed(tmp_path):
    _, _, _, (directory, report, _) = fuse(tmp_path)
    bad = deepcopy(report)
    descriptor = next(d for d in bad["extensions"]["hybrid_v1"]["artifacts"] if d["path"].endswith("pixel_ids.npy"))
    pixels = np.load(directory / descriptor["path"])
    pixels[0] = 2**32 - 1
    np.save(directory / descriptor["path"], pixels)
    descriptor["sha256"] = file_digest(directory / descriptor["path"])
    bad["proposal_sha256"] = content_digest({k: v for k, v in bad.items() if k != "proposal_sha256"})
    with pytest.raises(ValueError, match="pixel map"):
        validate_proposal_set(bad, directory)


def test_owned_2d_process_is_stopped_and_generation_discarded_on_cancel(tmp_path):
    cloud, model, labels = fixture()
    source = make_upstream(tmp_path, cloud, model, labels)
    worker = tmp_path / "owned-waiting-worker.py"
    worker.write_text("import time\ntime.sleep(60)\n")
    configuration = tmp_path / "configuration.json"
    write_report(configuration, {"schema_version": 1, "trusted_local_worker": True, "runtime_fingerprint": "c" * 64})
    assets = VisionAssets(str(Path(sys.executable).resolve()), str(worker), file_digest(worker), str(configuration), file_digest(configuration), "c" * 64)
    vision = IsolatedVisionProvider(assets)
    before = (source / "proposals-v1.json").read_bytes()
    with pytest.raises(InterruptedError):
        run_recognition(cloud, case(), HybridProvider(source, vision, HybridSettings(cell_m=.1)), tmp_path / "cancel",
                        cancelled=lambda: vision.process is not None)
    assert vision.process is None and not list((tmp_path / "cancel").glob(".proposal-stage-*"))
    assert (source / "proposals-v1.json").read_bytes() == before
