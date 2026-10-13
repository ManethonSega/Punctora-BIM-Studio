from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from punctora_core.annotation_io import (CLASSES, file_digest,
                                         read_json, validate_annotations)
from punctora_core.model import BuildingModel, Storey, Wall, Opening, Slab, SlabOpening
from punctora_core.quality_benchmark import (compare_reports, evidence_retention, model_snapshot, run_benchmark, write_report)
from punctora_core.quality_metrics import evaluate_geometry, semantic_metrics
from punctora_core.reproducibility import quality_snapshot_signature


SOURCE = "a" * 64


def annotations(elements=(), truth=True, samples=()):
    result = {"schema_version": 1, "units": "metres", "case_id": "fixture",
              "source_sha256": SOURCE, "coordinate_mapping": {"translation_m": [0, 0, 0], "yaw_degrees": 0},
              "crop": None, "elements": list(deepcopy(elements)), "semantic_samples": list(deepcopy(samples))}
    if truth:
        result.update(truth_revision="truth-v1", class_states={c: "present" if any(e["class"] == c for e in elements)
                      else "absent" for c in CLASSES}, exclusions=[])
    return result


def wall(identifier="w", start=(0, 0), end=(5, 0), base=0):
    return {"id": identifier, "class": "wall", "geometry": {"type": "wall", "start": list(start),
            "end": list(end), "base": base, "height": 3., "thickness": .2}}


def opening(identifier="o", kind="window", host="w", start=(1, 0), end=(2, 0)):
    return {"id": identifier, "class": kind, "host_id": host, "containment_valid": True,
            "geometry": {"type": "opening", "start": list(start), "end": list(end), "base": 1., "height": 1.}}


def surface(identifier="f", name="floor", footprint=None, holes=()):
    return {"id": identifier, "class": name, "geometry": {"type": "surface", "base": 0.,
            "footprint": footprint or [[0, 0], [5, 0], [5, 4], [0, 4]], "holes": list(holes), "thickness": .2}}


def case_files(tmp_path, truth, prediction, split="held_out", gates=None):
    t, p = tmp_path / "truth.json", tmp_path / "prediction.json"
    write_report(t, truth)
    write_report(p, prediction)
    case = {**{k: truth[k] for k in ("case_id", "source_sha256", "coordinate_mapping", "crop")},
            "source_kind": "generated_fixture", "split": split, "truth_revision": truth["truth_revision"],
            "truth": t.name, "truth_sha256": file_digest(t), "prediction": p.name, "prediction_sha256": file_digest(p),
            "gates": gates or [{"metric": "geometry.instances.wall.recall", "operator": ">=", "value": 1}]}
    path = tmp_path / "benchmark.json"
    write_report(path, {"schema_version": 1, "suite_kind": "generated_regression", "benchmark_id": "generated",
                        "revision": "v1", "cases": [case]})
    return path, case


def test_truth_states_all_classes_and_float64_coordinates():
    element = wall(start=(600000.00000001, 5600000), end=(600005.00000001, 5600000))
    data = validate_annotations(annotations([element]))
    assert data["elements"][0]["geometry"]["start"][0] == 600000.00000001
    assert set(data["class_states"]) == set(CLASSES)
    data["class_states"]["roof"] = "uncertain"
    data["class_states"]["ramp"] = "out_of_scope"
    assert validate_annotations(data)["class_states"]["ramp"] == "out_of_scope"


@pytest.mark.parametrize("mutate", [
    lambda d: d["class_states"].pop("roof"),
    lambda d: d["class_states"].update(wall="absent"),
    lambda d: d["class_states"].update(roof="present"),
    lambda d: d["elements"].append(deepcopy(d["elements"][0])),
    lambda d: d["elements"][0]["geometry"].update(height=float("nan")),
    lambda d: d["elements"][0]["geometry"].update(height=True),
    lambda d: d.update(coordinate_mapping={"translation_m": [0, 0, 0], "scale": 1}),
])
def test_malformed_truth_fails_closed(mutate):
    data = annotations([wall()])
    mutate(data)
    with pytest.raises(ValueError):
        validate_annotations(data)


def test_duplicate_keys_and_nonfinite_json_rejected(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError, match="Duplicate"):
        read_json(path)
    path.write_text('{"a":NaN}')
    with pytest.raises(ValueError, match="Non-finite"):
        read_json(path)


def test_original_record_identity_above_float_exact_range():
    sample = {"source_sha256": SOURCE, "scan_index": 1, "source_record_index": 2**53 + 1, "label": "wall"}
    data = annotations([wall()], samples=[sample])
    assert validate_annotations(data)["semantic_samples"][0]["source_record_index"] == 2**53 + 1
    sample["source_record_index"] = float(2**53 + 1)
    with pytest.raises(ValueError, match="integer"):
        validate_annotations(annotations([wall()], samples=[sample]))


def test_one_to_one_matching_does_not_hide_duplicates():
    truth = annotations([wall()])
    prediction = annotations([wall("a"), wall("b")], False)
    report = evaluate_geometry(truth, prediction)
    assert report["instances"]["wall"]["tp"] == 1
    assert report["instances"]["wall"]["fp"] == 1
    assert report["duplicate_pairs"] == [["a", "b"]]
    assert report["walls"][0]["overlap_length_m"] == 5
    assert report == evaluate_geometry(truth, {**prediction, "elements": prediction["elements"][::-1]})


def test_missing_and_overextended_walls_and_vertical_separation():
    truth = annotations([wall(), wall("missing", (0, 4), (5, 4))])
    prediction = annotations([wall("p", (-.4, 0), (5.3, 0))], False)
    report = evaluate_geometry(truth, prediction)
    assert report["instances"]["wall"]["recall"] == .5
    assert report["matches"][0]["unsupported_extension_m"] == pytest.approx(.7)
    assert report["missed_truth_ids"] == ["missing"]
    assert next(w for w in report["walls"] if w["truth_id"] == "missing")["largest_missing_region_m"] == 5
    prediction["elements"][0]["geometry"]["base"] = 4
    assert evaluate_geometry(truth, prediction)["instances"]["wall"]["tp"] == 0


def test_fragment_union_keeps_missing_interval():
    report = evaluate_geometry(annotations([wall()]), annotations([
        wall("a", (0, 0), (2, 0)), wall("b", (2.48, 0), (5, 0))], False))
    assert report["walls"][0]["coverage"] == pytest.approx(.904)
    assert report["walls"][0]["largest_missing_region_m"] == pytest.approx(.48)


def test_opening_class_host_and_containment_errors():
    truth = annotations([wall(), wall("other", (0, 3), (5, 3)), opening()])
    prediction = annotations([wall("p"), wall("p2", (0, 3), (5, 3)),
                              opening("po", "door", "p2")], False)
    prediction["elements"][-1]["containment_valid"] = False
    report = evaluate_geometry(truth, prediction)
    match = next(r for r in report["matches"] if r["truth_id"] == "o")
    assert not match["class_correct"] and not match["host_correct"]
    assert report["instances"]["window"]["fn"] == 1
    assert report["instances"]["door"]["fp"] == 1
    assert report["safety"]["openings_outside_hosts"] == 1


def test_rare_unknown_class_is_not_false_certainty():
    truth = annotations([wall()])
    truth["class_states"]["roof"] = "uncertain"
    prediction = annotations([wall(), surface("r", "roof")], False)
    report = evaluate_geometry(truth, prediction)
    assert report["instances"]["roof"]["status"] == "not_evaluated"
    assert report["not_evaluated_prediction_ids"] == ["r"]


def test_surface_concavity_holes_and_boundary_metrics():
    ring = [[0, 0], [5, 0], [5, 2], [3, 2], [3, 4], [0, 4]]
    hole = [[1, 1], [2, 1], [2, 2], [1, 2]]
    a = surface(footprint=ring, holes=[hole])
    b = surface("p")
    report = evaluate_geometry(annotations([a]), annotations([b], False))
    match = report["matches"][0]
    assert match["symmetric_difference_m2"] == 5
    assert match["boundary_distance_m"] > 0
    assert match["boundary_f1"] < 1
    exact = evaluate_geometry(annotations([a]), annotations([deepcopy(a)], False))["matches"][0]
    assert exact["area_iou"] == 1 and exact["boundary_f1"] == 1


def test_sloped_roof_surface_matches_respect_plane():
    a = surface(name="roof")
    a["geometry"]["plane"] = [.2, 0, 0]
    b = deepcopy(a)
    b["id"] = "p"
    b["geometry"]["plane"] = [.25, 0, 0]
    assert evaluate_geometry(annotations([a]), annotations([b], False))["instances"]["roof"]["tp"] == 0


def test_unsafe_and_unevaluated_surface_cuts():
    truth = annotations([surface()])
    prediction = annotations([surface("p")], False)
    prediction["cuts"] = [{"id": "bad", "host_id": "p", "applied": True,
                            "footprint": [[1, 1], [2, 1], [2, 2], [1, 2]]}]
    assert evaluate_geometry(truth, prediction)["safety"]["unsafe_surface_cuts"] == 1
    prediction["cuts"][0]["host_id"] = "missing"
    assert evaluate_geometry(truth, prediction)["safety"]["unsafe_surface_cuts"] is None


def test_semantic_missing_predictions_are_false_negatives_not_dropped():
    records = [{"source_sha256": SOURCE, "scan_index": 1, "source_record_index": i,
                "label": "wall", "boundary": bool(i % 2)} for i in range(3)]
    truth = annotations([wall()], samples=records)
    prediction = annotations([wall()], False, records[:1])
    report = semantic_metrics(truth, prediction)
    assert report["missing_predictions"] == 2
    assert report["classes"]["wall"]["recall"] == pytest.approx(1 / 3)
    assert report["classes"]["wall"]["boundary"]["fn"] == 1
    assert semantic_metrics(annotations([wall()]), prediction)["status"] == "not_evaluated"


def test_excluded_or_unobservable_regions_are_explicit():
    truth = annotations([wall(), wall("hidden", (0, 4), (5, 4))])
    truth["exclusions"] = [{"reason": "occluded", "footprint": [[-1, 3], [6, 3], [6, 5], [-1, 5]],
                            "z_min": 0, "z_max": 3}]
    report = evaluate_geometry(truth, annotations([wall()], False))
    assert report["excluded_truth_ids"] == ["hidden"]
    assert report["instances"]["wall"]["recall"] == 1


def test_signature_profiles_axis_reversal_and_holes():
    a = wall()
    a["geometry"]["profile_xz"] = [[0, 0], [5, 0], [5, 2], [2, 2], [2, 3], [0, 3]]
    original = annotations([a, surface()], False)
    same = deepcopy(original)
    same["elements"][0]["id"] = "renamed"
    g = same["elements"][0]["geometry"]
    g["start"], g["end"] = g["end"], g["start"]
    g["profile_xz"] = [[5 - x, z] for x, z in g["profile_xz"]][::-1]
    same["elements"].reverse()
    assert quality_snapshot_signature(original) == quality_snapshot_signature(same)
    same["elements"][0]["geometry"]["holes"] = [[[1, 1], [2, 1], [2, 2], [1, 2]]]
    assert quality_snapshot_signature(original) != quality_snapshot_signature(same)


def test_stair_landing_and_ramp_endpoint_metrics_and_signature():
    stair = {"id": "s", "class": "stair", "geometry": {"type": "stair", "start": [0, 1], "end": [1.5, 1],
             "base": 0, "width": 1, "rise": .17, "going": .25, "steps": 6},
             "connections": {"lower": "l", "upper": "u"}, "observed_treads": [0, 1, 2], "inferred_treads": [3, 4, 5]}
    lower, upper = surface("l", "landing"), surface("u", "landing")
    upper["geometry"]["base"] = 1.02
    lower["connected_ids"] = ["s"]
    ramp = {"id": "r", "class": "ramp", "geometry": {"type": "ramp", "start": [0, 3], "end": [5, 3],
            "base": 0, "width": 1, "rise": 1}, "connections": {"lower": "l", "upper": "u"}}
    truth = validate_annotations(annotations([stair, lower, upper, ramp]))
    prediction = annotations(truth["elements"], False)
    report = evaluate_geometry(truth, prediction)
    matched_stair = next(r for r in report["matches"] if r["class"] == "stair")
    assert matched_stair["endpoint_associations"] == {"lower": True, "upper": True}
    assert matched_stair["observed_tread_count"] == 3 and matched_stair["inferred_tread_count"] == 3
    previous = quality_snapshot_signature(prediction)
    prediction["elements"][0]["connections"]["upper"] = None
    assert quality_snapshot_signature(prediction) != previous


def test_repeatable_evaluator_and_baseline_lock(tmp_path):
    path, case = case_files(tmp_path, annotations([wall()]), annotations([wall()], False))
    first, second = run_benchmark(path), run_benchmark(path)
    assert first == second
    assert first["passed"]
    assert first["decision"]["disposition"] == "Repeat current run"  # generated is not survey acceptance
    baseline = tmp_path / "baseline.json"
    write_report(baseline, first, frozen=True)
    write_report(baseline, second, frozen=True)
    with pytest.raises(ValueError, match="Frozen baseline"):
        write_report(baseline, {**first, "passed": False}, frozen=True)
    assert compare_reports(first, second)["changes"][0]["geometry_equal"]
    changed = deepcopy(second)
    changed["cases"][0]["truth_revision"] = "moved-goalposts"
    with pytest.raises(ValueError, match="truth"):
        compare_reports(first, changed)


def test_fingerprint_gate_and_missing_metric_fail_closed(tmp_path):
    path, case = case_files(tmp_path, annotations([wall()]), annotations([wall()], False))
    (tmp_path / "truth.json").write_text('{}')
    assert run_benchmark(path)["cases"][0]["status"] == "invalid_or_missing_input"
    path, case = case_files(tmp_path, annotations([wall()]), annotations([wall()], False),
        gates=[{"metric": "source_record_retention.retention", "operator": ">=", "value": 1}])
    report = run_benchmark(path)
    assert not report["passed"]
    assert report["cases"][0]["gates"][0]["actual"] is None


def test_no_held_out_case_and_pending_case_prevent_proceed(tmp_path):
    path, case = case_files(tmp_path, annotations([wall()]), annotations([wall()], False), split="regression")
    assert not run_benchmark(path)["passed"]
    manifest = read_json(path)
    manifest["cases"].append({"case_id": "facade", "split": "held_out", "availability": "pending",
                              "reason": "Independent truth not supplied"})
    write_report(path, manifest)
    report = run_benchmark(path)
    assert not report["passed"] and report["decision"]["disposition"] == "Repeat current run"


def test_real_case_requires_digest_bound_visual_review(tmp_path):
    path, case = case_files(tmp_path, annotations([wall()]), annotations([wall()], False))
    case["source_kind"] = "E57"
    manifest = read_json(path)
    manifest["suite_kind"] = "acceptance"
    manifest["cases"] = [case]
    write_report(path, manifest)
    assert not run_benchmark(path)["passed"]
    case["visual_review"] = {"status": "passed", "reviewer": "tester", "truth_sha256": case["truth_sha256"],
                            "prediction_sha256": case["prediction_sha256"]}
    write_report(path, manifest)
    assert run_benchmark(path)["passed"]
    case["visual_review"]["prediction_sha256"] = "b" * 64
    write_report(path, manifest)
    assert not run_benchmark(path)["passed"]


def test_model_adapter_excludes_rejected_and_preserves_surface_holes():
    model = BuildingModel("fixture", [Storey("level", "L", 0, 3, [(0, 0), (5, 0), (5, 4), (0, 4)])],
        walls=[Wall("w", "level", (0, 0), (5, 0), 0, 3, .2),
               Wall("rejected", "level", (0, 4), (5, 4), 0, 3, .2, review_state="rejected")],
        openings=[Opening("o", "w", "window", 1, 1, 1, 1)],
        slabs=[Slab("floor", "level", [(0, 0), (5, 0), (5, 4), (0, 4)], 0, .2)],
        slab_openings=[SlabOpening("cut", "floor", (1, 1), (2, 1), 1, ifc_cut_approved=True)])
    snapshot = model_snapshot(model, {k: annotations()[k] for k in
                                     ("case_id", "source_sha256", "coordinate_mapping", "crop")})
    assert "rejected" not in {e["id"] for e in snapshot["elements"]}
    assert next(e for e in snapshot["elements"] if e["class"] == "floor")["geometry"]["holes"]
    assert snapshot["cuts"][0]["applied"]


def test_evidence_retention_is_element_scoped_not_global(tmp_path):
    model = BuildingModel("fixture", [Storey("level", "L", 0, 3, [(0, 0), (5, 0), (5, 4), (0, 4)])],
                          walls=[Wall("p", "level", (0, 0), (5, 0), 0, 3, .2)],
                          metadata={"source": {"sha256": SOURCE}})
    records = np.array([[0, 1, 2**53 + 1], [1, 1, 7]], dtype=np.int64)
    np.save(tmp_path / "records.npy", records, allow_pickle=False)
    model.walls[0].evidence["records"] = {"path": "records.npy", "count": 2,
        "columns": ["cloud_index", "scan_index", "source_record_index"]}
    element = wall()
    element["source_records"] = [{"source_sha256": SOURCE, "scan_index": 1, "source_record_index": 2**53 + 1}]
    truth = annotations([element])
    matches = [{"prediction_id": "p", "truth_id": "w"}]
    assert evidence_retention(model, truth, tmp_path, matches)["retention"] == 1
    assert evidence_retention(model, truth, tmp_path, [])["retention"] == 0
    with pytest.raises(InterruptedError):
        evidence_retention(model, truth, tmp_path, matches, cancelled=lambda: True)
    (tmp_path / "records.npy").unlink()
    assert evidence_retention(model, truth, tmp_path, matches)["status"] == "incomplete"


def test_cancellation_never_returns_success(tmp_path):
    path, _ = case_files(tmp_path, annotations([wall()]), annotations([wall()], False))
    with pytest.raises(InterruptedError):
        run_benchmark(path, cancelled=lambda: True)


def test_cli_cannot_overwrite_truth_or_prediction(tmp_path):
    from punctora_core.cli import main
    path, _ = case_files(tmp_path, annotations([wall()]), annotations([wall()], False))
    for name in ("truth.json", "prediction.json", "benchmark.json"):
        target = tmp_path / name
        original = target.read_bytes()
        with pytest.raises(SystemExit) as exc:
            main(["quality-evaluate", str(path), "--output", str(target)])
        assert exc.value.code == 2 and target.read_bytes() == original


def test_changed_acceptance_thresholds_or_corrupt_baseline_rejected(tmp_path):
    path, _ = case_files(tmp_path, annotations([wall()]), annotations([wall()], False))
    baseline = run_benchmark(path)
    changed = deepcopy(baseline)
    changed["cases"][0]["gates"][0]["value"] = .5
    with pytest.raises(ValueError, match="thresholds"):
        compare_reports(baseline, changed)
    changed = deepcopy(baseline)
    changed["passed"] = False
    with pytest.raises(ValueError, match="digest"):
        compare_reports(changed, baseline)


def test_visible_face_coverage_is_distinct_from_inferred_axis():
    reference = wall()
    reference["observed_faces"] = [{"start": [0, 0], "end": [5, 0], "z_min": 0, "z_max": 3}]
    candidate = wall("p", (0, -.15), (5, -.15))
    candidate["observed_faces"] = deepcopy(reference["observed_faces"])
    report = evaluate_geometry(annotations([reference]), annotations([candidate], False))
    assert report["instances"]["wall"]["tp"] == 0
    assert report["observed_faces"]["faces"][0]["area_coverage"] == 1


def test_wall_profile_coverage_does_not_certify_height_from_axis_only():
    candidate = wall("p")
    candidate["geometry"]["height"] = .3
    report = evaluate_geometry(annotations([wall()]), annotations([candidate], False))
    assert report["walls"][0]["coverage"] == 1
    assert report["walls"][0]["profile_area_coverage"] == pytest.approx(.1)


def test_schema2_crop_identity_cannot_be_relabelled(tmp_path):
    from punctora_core.quality_benchmark import _model_identity_check
    model = BuildingModel("fixture", metadata={"source": {"sha256": SOURCE},
        "crop": {"active": True, "crop": {"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "z_min": 0, "z_max": 3}}})
    with pytest.raises(ValueError, match="crop"):
        _model_identity_check(model, annotations())


def test_malformed_profile_and_stair_observed_inferred_overlap_rejected():
    bad = surface(footprint=[[0, 0], [5, 4], [0, 4], [5, 0]])
    with pytest.raises(ValueError, match="valid"):
        validate_annotations(annotations([bad]))
    stair = {"id": "s", "class": "stair", "geometry": {"type": "stair", "start": [0, 1], "end": [1.5, 1],
             "base": 0, "width": 1, "rise": .17, "going": .25, "steps": 6},
             "observed_treads": [1], "inferred_treads": [1]}
    with pytest.raises(ValueError, match="both"):
        validate_annotations(annotations([stair]))


def test_cancellation_inside_case_hash_is_not_swallowed(tmp_path):
    path, _ = case_files(tmp_path, annotations([wall()]), annotations([wall()], False))
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 2

    with pytest.raises(InterruptedError):
        run_benchmark(path, cancelled)


def test_duplicate_rate_is_excess_elements_not_pair_count():
    report = evaluate_geometry(annotations([wall()]), annotations([wall("a"), wall("b"), wall("c")], False))
    assert len(report["duplicate_pairs"]) == 3
    assert report["duplicate_elements"] == 2
    assert report["duplicate_rate"] == pytest.approx(2 / 3)


def test_floor_face_level_is_not_assumed_solid_underside():
    model = BuildingModel("fixture", [Storey("s", "L", 0, 3, [(0, 0), (5, 0), (5, 4), (0, 4)])],
                          slabs=[Slab("f", "s", [(0, 0), (5, 0), (5, 4), (0, 4)], -.2, .2)])
    snapshot = model_snapshot(model, {k: annotations()[k] for k in
                                     ("case_id", "source_sha256", "coordinate_mapping", "crop")})
    g = snapshot["elements"][0]["geometry"]
    assert g["base"] == 0 and g["solid_base"] == -.2
    report = evaluate_geometry(annotations([surface()]), snapshot)
    assert report["instances"]["floor"]["recall"] == 1


def test_semantic_sidecar_can_label_samples_but_cannot_author_geometry(tmp_path):
    sample = {"source_sha256": SOURCE, "scan_index": 1, "source_record_index": 7, "label": "wall"}
    truth = annotations([wall()], samples=[sample])
    path, case = case_files(tmp_path, truth, annotations([wall()], False), gates=[
        {"metric": "semantics.classes.wall.recall", "operator": "==", "value": 1}])
    sidecar = tmp_path / "semantic.json"
    write_report(sidecar, annotations([], False, samples=[sample]))
    case.update(semantic_prediction=sidecar.name, semantic_prediction_sha256=file_digest(sidecar))
    manifest = read_json(path)
    manifest["cases"] = [case]
    write_report(path, manifest)
    assert run_benchmark(path)["passed"]
    write_report(sidecar, annotations([wall("injected")], False, samples=[sample]))
    case["semantic_prediction_sha256"] = file_digest(sidecar)
    write_report(path, manifest)
    report = run_benchmark(path)
    assert not report["passed"]
    assert "must not supply geometry" in report["cases"][0]["reason"]
