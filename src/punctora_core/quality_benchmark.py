"""Local quality evaluation and write-once baselines, independent of reconstruction."""
from copy import deepcopy
import json
from math import dist
import os
from pathlib import Path
import tempfile

import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .annotation_io import (CLASSES, MATCHING, canonical_json, content_digest, file_digest,
                            identity, load_annotations, read_json, record_key, sha256,
                            validate_annotations, validate_identity, number, identifier)
from .model import BuildingModel, slab_opening_footprint, slab_opening_is_validated
from .quality_metrics import evaluate_geometry, semantic_metrics
from .reproducibility import quality_snapshot_signature

BASELINE_COMMIT = "5327fdc172edec7849cbd30553591945b71aeb9b"


def write_report(path, report, frozen=False):
    """Atomic reports; frozen baselines cannot be silently overwritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if frozen:
        if path.exists():
            if path.read_bytes() == encoded:
                return
            raise ValueError("Frozen baseline differs; use a new explicitly versioned baseline path")
        # Publish the complete temporary file without replacing an existing
        # baseline. Hard-link creation is atomic on the local project volume.
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != encoded:
                raise ValueError("Frozen baseline differs; use a new explicitly versioned baseline path")
        finally:
            temporary.unlink(missing_ok=True)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def model_snapshot(model, case_identity):
    """Adapt schema 2 into the evaluator contract, without inventing future classes."""
    model.validate()
    data = {"schema_version": 1, "units": "metres", **deepcopy(case_identity),
            "elements": [], "semantic_samples": [], "cuts": [],
            "adapter": "punctora-schema-2", "limitations": [
                "Schema 2 has no explicit roof or ramp record; those classes can be evaluated as missing",
                "Semantic point labels require a separate prediction artifact",
                "Source-record retention requires complete evidence arrays, not evidence counts or examples"]}
    hosts = {w.id: w for w in model.walls}

    def append(obj, name, geometry, **extra):
        states = set(obj.provenance.values())
        support = "measured" if states == {"measured"} else "inferred" if "inferred" in states else "unknown"
        data["elements"].append({"id": obj.id, "class": name, "geometry": geometry,
                                 "support_state": support, "review_state": obj.review_state,
                                 "provenance": deepcopy(obj.provenance), **extra})

    for w in model.walls:
        if w.review_state == "rejected":
            continue
        append(w, "wall", {"type": "wall", "start": list(w.start), "end": list(w.end),
                            "base": w.base, "height": w.height, "thickness": w.thickness,
                            "profile_xz": deepcopy(w.profile_xz)}, observed_faces=deepcopy(w.observed_faces))
    for o in model.openings:
        if o.review_state == "rejected" or hosts[o.host_wall_id].review_state == "rejected":
            continue
        w = hosts[o.host_wall_id]
        direction = (np.asarray(w.end, dtype=np.float64) - w.start) / dist(w.start, w.end)
        start = np.asarray(w.start, dtype=np.float64) + direction * o.offset
        shape = Polygon(w.profile_xz) if w.profile_xz else box(0, 0, dist(w.start, w.end), w.height)
        append(o, o.kind if o.kind != "unknown" else "opening",
               {"type": "opening", "start": start.tolist(), "end": (start + direction * o.width).tolist(),
                "base": w.base + o.sill, "height": o.height}, host_id=w.id,
               containment_valid=bool(shape.buffer(1e-8).covers(box(o.offset, o.sill, o.offset + o.width, o.sill + o.height))))
    for s in [*model.slabs, *model.landings]:
        if s.review_state == "rejected":
            continue
        kind = (s.kind.lower() if hasattr(s, "kind") else "landing")
        kind = kind if kind in {"floor", "ceiling", "roof", "landing"} else "slab"
        holes = [slab_opening_footprint(o) for o in model.slab_openings if o.host_slab_id == s.id
                 and slab_opening_is_validated(o, model.stairs, model.landings)]
        # Boolean results, not unnormalised overlapping cut rings, are the
        # actual surface being evaluated. Retain every resulting component.
        shape = Polygon(s.footprint).difference(unary_union([Polygon(h) for h in holes]))
        pieces = [] if shape.is_empty else [shape] if isinstance(shape, Polygon) else list(shape.geoms)
        for index, piece in enumerate(sorted(pieces, key=lambda p: (p.bounds, p.area))):
            surface_level = s.base + s.thickness if kind == "floor" else s.base
            append(s, kind, {"type": "surface", "footprint": list(piece.exterior.coords)[:-1],
                            "holes": [list(r.coords)[:-1] for r in piece.interiors],
                            "base": surface_level, "solid_base": s.base, "thickness": s.thickness},
                   coverage_areas_m2={key: value.get("area_m2") for key, value in
                                      s.evidence.get("coverage_classes", {}).items()} or None,
                   connected_ids=list(getattr(s, "connected_stair_ids", [])))
            if len(pieces) > 1 and index > 0:
                data["elements"][-1]["id"] = f"{s.id}:component:{index}"
    for s in model.stairs:
        if s.review_state == "rejected":
            continue
        append(s, "stair", {"type": "stair", "start": list(s.start), "end": list(s.end), "base": s.base,
                             "width": s.width, "rise": s.rise, "going": s.going, "steps": s.steps,
                             "tread_thickness": s.tread_thickness},
               observed_treads=s.evidence.get("observed_step_indices", []),
               inferred_treads=s.evidence.get("inferred_missing_step_indices", []),
               connections={label: s.evidence.get(f"{label}_landing_id") or s.evidence.get(f"{label}_slab_id")
                            for label in ("lower", "upper")})
    for o in model.slab_openings:
        data["cuts"].append({"id": o.id, "host_id": o.host_slab_id, "footprint": slab_opening_footprint(o),
                             "applied": slab_opening_is_validated(o, model.stairs, model.landings)})
    return validate_annotations(data, truth=False)


def performance_summary(report):
    """Telemetry remains separate from quality and does not decide the Run 1 gate."""
    return {key: report.get(key) for key in (
        "status", "source_points", "elapsed_seconds", "logical_point_visits_total",
        "unique_points_visited_total", "point_cloud_passes_total", "peak_process_rss_bytes")}


def freeze_artifact_baseline(ifc_path, performance_path, output):
    """Freeze supplied artifacts and aggregate facts, not pretend they are truth."""
    import ifcopenshell
    import ifcopenshell.util.element
    file = ifcopenshell.open(str(ifc_path))
    props = [ifcopenshell.util.element.get_psets(e).get("Punctora_Reconstruction", {})
             for e in file.by_type("IfcElement")]
    versions = sorted({p["EngineVersion"] for p in props if p.get("EngineVersion")})
    if versions != ["0.3.0a27"]:
        raise ValueError("The a27 artifact baseline requires IFC EngineVersion 0.3.0a27")
    counts = {name: len(file.by_type(name)) for name in ("IfcWall", "IfcOpeningElement", "IfcWindow",
                                                       "IfcDoor", "IfcSlab", "IfcRoof", "IfcRamp",
                                                       "IfcStairFlight", "IfcBuildingStorey")}
    report = {"schema_version": 1, "baseline_id": "a27-supplied-facade-artifacts-v1",
              "planning_commit": BASELINE_COMMIT, "engine_versions": versions,
              "artifacts": {"ifc_sha256": file_digest(ifc_path),
                            "performance_sha256": file_digest(performance_path)},
              "ifc_counts": counts, "performance": performance_summary(read_json(performance_path)),
              "accuracy": None, "source_record_retention": None,
              "status": "artifact_baseline_only", "limitations": [
                  "Counts, file hashes and fitting residuals are not independent accuracy measurements",
                  "Complete source E57/cache, crop mapping, elements.json and independent truth are not supplied",
                  "Artifact facts alone do not establish external quality acceptance; internal implementation gates are separate"]}
    report["baseline_sha256"] = content_digest(report)
    write_report(output, report, frozen=True)
    return report


def _resolve(root, value):
    path = Path(value)
    return path if path.is_absolute() else root / path


def _model_identity_check(model, case):
    from .cropping import validate_crop, crop_active
    if model.metadata.get("source", {}).get("sha256") != case["source_sha256"]:
        raise ValueError("Model source identity disagrees with manifest")
    mapping = model.metadata.get("coordinate_mapping", {})
    actual = {"translation_m": mapping.get("working_to_source_translation_m", [0, 0, 0]),
              "yaw_degrees": mapping.get("yaw_degrees", 0)}
    if actual != case["coordinate_mapping"]:
        raise ValueError("Model coordinate mapping disagrees with benchmark")
    report = model.metadata.get("crop", {})
    value = report.get("crop") if isinstance(report, dict) else None
    crop = validate_crop(value)
    actual_crop = crop if crop_active(crop) else None
    if actual_crop != case["crop"]:
        raise ValueError("Model crop identity disagrees with benchmark")


def load_manifest(path):
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Benchmark manifest requires schema 1")
    identifier(data.get("benchmark_id"), "benchmark_id")
    identifier(data.get("revision"), "revision")
    if data.get("suite_kind") not in {"acceptance", "generated_regression"}:
        raise ValueError("suite_kind must be acceptance or generated_regression")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark requires at least one case")
    ids = set()
    for case in cases:
        identifier(case.get("case_id"), "case_id")
        if case["case_id"] in ids:
            raise ValueError("Duplicate benchmark case ID")
        ids.add(case["case_id"])
        if case.get("split") not in {"calibration", "held_out", "regression"}:
            raise ValueError("Case split must be calibration, held_out or regression")
        if case.get("availability", "ready") not in {"ready", "pending"}:
            raise ValueError("availability must be ready or pending")
        if not isinstance(case.get("required", True), bool):
            raise ValueError("required must be boolean")
        if case.get("availability", "ready") == "pending":
            identifier(case.get("reason"), "pending reason")
            continue
        validate_identity(case)
        if case.get("source_kind") not in {"E57", "generated_fixture"}:
            raise ValueError("Ready case requires source_kind E57 or generated_fixture")
        identifier(case.get("truth_revision"), "truth_revision")
        for field in ("truth", "prediction"):
            identifier(case.get(field), field)
            sha256(case.get(field + "_sha256"), field + "_sha256")
        if case.get("semantic_prediction"):
            identifier(case["semantic_prediction"], "semantic_prediction")
            sha256(case.get("semantic_prediction_sha256"), "semantic_prediction_sha256")
        for key, value in case.get("matching", {}).items():
            if key not in MATCHING:
                raise ValueError(f"Unknown matching threshold {key}")
            number(value, key, True)
            if key in {"minimum_iou", "duplicate_iou"} and value > 1:
                raise ValueError("IoU threshold cannot exceed one")
        gates = case.get("gates")
        if not isinstance(gates, list) or not gates:
            raise ValueError("Ready case requires explicit acceptance gates")
        for gate in gates:
            identifier(gate.get("metric"), "metric path")
            if gate.get("operator") not in {"<=", ">=", "=="}:
                raise ValueError("Gate operator must be <=, >= or ==")
            number(gate.get("value"), "gate value")
    return data


def _metric(report, path):
    current = report
    for name in path.split("."):
        if not isinstance(current, dict) or name not in current:
            return None
        current = current[name]
    return current


def _gates(report, gates):
    operations = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b, "==": lambda a, b: a == b}
    result = []
    for gate in gates:
        value = _metric(report, gate["metric"])
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            passed, reason = False, "Metric missing or not evaluated"
        else:
            passed, reason = bool(operations[gate["operator"]](value, gate["value"])), None
        result.append({**gate, "actual": value, "passed": passed, "reason": reason})
    return result


def evidence_retention(model, truth, root, matches=(), cancelled=lambda: False):
    """Check sampled identities against full mmap arrays; never load the source cloud."""
    wanted = {(e["id"], record_key(r)) for e in truth["elements"] for r in e.get("source_records", [])}
    if not wanted:
        return {"status": "not_evaluated", "retention": None, "reason": "No independent source-record references"}
    found, hashes, incomplete = set(), [], []
    matched = {r["prediction_id"]: r["truth_id"] for r in matches}
    for obj in [*model.walls, *model.slabs, *model.openings, *model.stairs, *model.landings]:
        descriptors = [(obj.evidence.get("records"), obj.evidence.get("source_context", {}).get("source", {}).get(
            "sha256", model.metadata.get("source", {}).get("sha256")))]
        descriptors.extend((s.get("evidence", {}).get("records"),
                            s.get("source_context", {}).get("source", {}).get("sha256"))
                           for s in obj.evidence.get("additional_sources", []))
        for descriptor, source in descriptors:
            if not descriptor:
                continue
            path = _resolve(root, descriptor["path"])
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Evidence array must stay inside its project asset root")
            if not path.is_file():
                incomplete.append(f"{obj.id}: missing evidence array")
                continue
            sha256(source, "evidence source SHA-256")
            array = np.load(path, mmap_mode="r", allow_pickle=False)
            if (array.ndim != 2 or array.shape[1] != 3 or array.dtype.kind not in "iu"
                    or array.dtype.itemsize != 8 or len(array) != descriptor["count"]
                    or descriptor.get("columns") != ["cloud_index", "scan_index", "source_record_index"]):
                raise ValueError("Evidence requires complete Nx3 int64/uint64 source-reference arrays")
            truth_id = matched.get(obj.id)
            targets = {key for owner, key in wanted if key[0] == source and owner == truth_id}
            records = np.array(sorted({key[2] for key in targets}), dtype=np.uint64)
            for begin in range(0, len(array), 65536):
                if cancelled():
                    raise InterruptedError("Quality evaluation cancelled")
                block = array[begin:begin + 65536]
                if array.dtype.kind == "i" and np.any(block < 0):
                    incomplete.append(f"{obj.id}: missing source identifier")
                selected = block[np.isin(block[:, 2], records)] if len(records) else []
                for row in selected:
                    key = source, int(row[1]), int(row[2])
                    if key in targets:
                        found.add((truth_id, key))
            hashes.append({"element_id": obj.id, "source_sha256": source, "count": len(array),
                           "records_sha256": file_digest(path, cancelled=cancelled)})
    complete = bool(hashes) and not incomplete
    return {"status": "evaluated" if complete else "incomplete",
            "scope": "Independent sampled records found in full arrays; not whole-cloud retention proof",
            "required_records": len(wanted), "retained_records": len(found),
            "retention": len(found) / len(wanted) if complete else None,
            "sample_retention": len(found) / len(wanted),
            "missing_records": [{"truth_id": owner, "record": list(key)} for owner, key in sorted(wanted - found)],
            "arrays": sorted(hashes, key=lambda r: (r["element_id"], r["source_sha256"], r["records_sha256"])),
            "warnings": sorted(set(incomplete))}


def evaluate_case(case, root, cancelled=lambda: False):
    paths = {field: _resolve(root, case[field]) for field in ("truth", "prediction")}
    for field, path in paths.items():
        if file_digest(path, cancelled=cancelled) != case[field + "_sha256"]:
            raise ValueError(f"{field} fingerprint changed; explicit manifest revision required")
    if case.get("source_path") and file_digest(_resolve(root, case["source_path"]), cancelled=cancelled) != case["source_sha256"]:
        raise ValueError("Source fingerprint mismatch")
    truth = load_annotations(paths["truth"])
    if identity(truth) != identity(case) or truth["truth_revision"] != case["truth_revision"]:
        raise ValueError("Truth source/crop/coordinate identity or revision disagrees with manifest")
    raw = read_json(paths["prediction"])
    model = None
    if raw.get("schema_version") == 2:
        model = BuildingModel.from_dict(raw)
        _model_identity_check(model, case)
        prediction = model_snapshot(model, identity(case))
    else:
        prediction = validate_annotations(raw, truth=False)
        if identity(prediction) != identity(case):
            raise ValueError("Prediction source/crop/coordinate identity disagrees with truth")
    semantic_sha = None
    if case.get("semantic_prediction"):
        semantic_path = _resolve(root, case["semantic_prediction"])
        semantic_sha = file_digest(semantic_path, cancelled=cancelled)
        if semantic_sha != case["semantic_prediction_sha256"]:
            raise ValueError("Semantic prediction fingerprint changed")
        semantic = load_annotations(semantic_path, truth=False)
        if identity(semantic) != identity(case) or semantic["elements"]:
            raise ValueError("Semantic sidecar must share identity and must not supply geometry")
        prediction["semantic_samples"] = semantic["semantic_samples"]
    report = {"case_id": case["case_id"], "split": case["split"], "identity": identity(case),
              "truth_revision": case["truth_revision"], "truth_sha256": case["truth_sha256"],
              "prediction_sha256": case["prediction_sha256"],
              "semantic_prediction_sha256": semantic_sha,
              "geometry": evaluate_geometry(truth, prediction, case.get("matching")),
              "semantics": semantic_metrics(truth, prediction),
              "signature": quality_snapshot_signature(prediction, case.get("matching", {}).get("signature_m", MATCHING["signature_m"]))}
    report["source_record_retention"] = (evidence_retention(model, truth, paths["prediction"].parent,
                                                          report["geometry"]["matches"], cancelled)
        if model is not None else {"status": "not_evaluated", "retention": None,
                                  "reason": "Standalone predictions do not prove evidence-array retention"})
    repeat_path = case.get("repeat_prediction")
    report["repeatability"] = {"status": "not_evaluated", "geometry_equal": None, "evidence_arrays_equal": None}
    if repeat_path:
        repeated_path = _resolve(root, repeat_path)
        repeat_raw = read_json(repeated_path)
        if repeat_raw.get("schema_version") == 2:
            if model is None:
                raise ValueError("Repeat prediction format must match the primary prediction")
            repeat_model = BuildingModel.from_dict(repeat_raw)
            _model_identity_check(repeat_model, case)
            repeated = model_snapshot(repeat_model, identity(case))
        else:
            repeated = validate_annotations(repeat_raw, truth=False)
            if identity(repeated) != identity(case):
                raise ValueError("Repeated prediction has different source/crop/mapping")
        difference = evaluate_geometry({**truth, "elements": prediction["elements"],
                                       "class_states": {c: "present" if any(e["class"] == c for e in prediction["elements"])
                                                        else "absent" for c in CLASSES}}, repeated, case.get("matching"))
        report["repeatability"] = {"status": "evaluated", "geometry_equal": int(
            quality_snapshot_signature(repeated, report["signature"]["comparison_tolerance_m"]) == report["signature"]),
            "differences": difference, "evidence_arrays_equal": None,
            "prediction_sha256": file_digest(repeated_path, cancelled=cancelled)}
        if model is not None and repeat_raw.get("schema_version") == 2:
            repeated_geometry = evaluate_geometry(truth, repeated, case.get("matching"))
            repeated_evidence = evidence_retention(repeat_model, truth, _resolve(root, repeat_path).parent,
                                                   repeated_geometry["matches"], cancelled)
            report["repeatability"]["source_record_retention"] = repeated_evidence
            current_evidence = report["source_record_retention"]
            if current_evidence["status"] == repeated_evidence["status"] == "evaluated":
                def signatures(evidence):
                    return sorted((r["source_sha256"], r["count"], r["records_sha256"]) for r in evidence["arrays"])
                report["repeatability"]["evidence_arrays_equal"] = int(signatures(current_evidence) == signatures(repeated_evidence))
    if case.get("performance"):
        report["performance"] = performance_summary(read_json(_resolve(root, case["performance"])))
    report["gates"] = _gates(report, case["gates"])
    report["numerical_passed"] = all(g["passed"] for g in report["gates"])
    review = case.get("visual_review", {})
    report["visual_review"] = {"status": "not_required_generated_fixture" if case["source_kind"] == "generated_fixture"
                               else "passed" if (review.get("status") == "passed" and review.get("reviewer")
                                   and review.get("truth_sha256") == case["truth_sha256"]
                                   and review.get("prediction_sha256") == case["prediction_sha256"]) else "pending"}
    report["passed"] = report["numerical_passed"] and report["visual_review"]["status"] != "pending"
    return report


def run_benchmark(manifest_path, cancelled=lambda: False):
    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    reports = []
    for case in sorted(manifest["cases"], key=lambda c: c["case_id"]):
        if cancelled():
            raise InterruptedError("Quality evaluation cancelled")
        if case.get("availability") == "pending":
            reports.append({"case_id": case["case_id"], "split": case["split"], "passed": False,
                            "status": "not_evaluated", "reason": case["reason"]})
            continue
        try:
            result = evaluate_case(case, manifest_path.parent, cancelled)
            result["status"] = "passed" if result["passed"] else "failed"
            reports.append(result)
        except InterruptedError:
            raise
        except (ValueError, OSError, KeyError, TypeError) as exc:
            reports.append({"case_id": case["case_id"], "split": case["split"], "passed": False,
                            "status": "invalid_or_missing_input", "reason": str(exc)})
    required = {c["case_id"] for c in manifest["cases"] if c.get("required", True)}
    held_out = [c for c in manifest["cases"] if c["split"] == "held_out" and c.get("required", True)]
    passed = bool(held_out) and all(r["passed"] for r in reports if r["case_id"] in required)
    report = {"schema_version": 1, "benchmark_id": manifest["benchmark_id"], "revision": manifest["revision"],
              "suite_kind": manifest["suite_kind"],
              "manifest_sha256": content_digest(manifest), "passed": passed, "cases": reports,
              "decision": {"disposition": None,
                           "scope": "External responsibility checkpoint after the internal implementation gate",
                           "future_run_action": None, "affected_future_runs": [],
                           "reason": "Internal checks run first. This report informs the applicable external checkpoint disposition; unavailable external inputs leave it awaiting checkpoint, while a reproduced defect can request targeted repair or redesign."},
              "limitations": ["Numerical gates do not substitute for independent visual overlay review",
                              "This evaluator never tunes thresholds or changes the reconstruction model"]}
    report["report_sha256"] = content_digest(report)
    return report


def compare_reports(baseline, candidate):
    """Refuse moving truth/thresholds; retain explicit missing/failed cases."""
    if baseline.get("benchmark_id") != candidate.get("benchmark_id"):
        raise ValueError("Baseline belongs to a different benchmark")
    if baseline.get("suite_kind") != candidate.get("suite_kind"):
        raise ValueError("Baseline benchmark scope changed")
    expected = content_digest({k: v for k, v in baseline.items() if k != "report_sha256"})
    if baseline.get("report_sha256") != expected:
        raise ValueError("Frozen baseline report digest disagrees with its contents")
    before = {r["case_id"]: r for r in baseline["cases"]}
    after = {r["case_id"]: r for r in candidate["cases"]}
    if set(before) != set(after):
        raise ValueError("Baseline case set changed; explicit new baseline required")
    changes = []
    for case_id in sorted(before):
        a, b = before[case_id], after[case_id]
        for key in ("identity", "truth_revision", "truth_sha256", "split"):
            if a.get(key) != b.get(key):
                raise ValueError("Independent truth/source identity changed; not an algorithm comparison")
        if a.get("geometry", {}).get("matching") != b.get("geometry", {}).get("matching"):
            raise ValueError("Matching tolerances changed; explicit new baseline required")
        gates_a = [(g["metric"], g["operator"], g["value"]) for g in a.get("gates", [])]
        gates_b = [(g["metric"], g["operator"], g["value"]) for g in b.get("gates", [])]
        if gates_a != gates_b:
            raise ValueError("Acceptance thresholds changed; explicit new baseline required")
        changes.append({"case_id": case_id, "before_status": a["status"], "after_status": b["status"],
                        "geometry_equal": (a["signature"] == b["signature"] if "signature" in a and "signature" in b else None),
                        "before_instances": a.get("geometry", {}).get("instances"),
                        "after_instances": b.get("geometry", {}).get("instances")})
    return {"baseline_report_sha256": baseline["report_sha256"], "changes": changes}
