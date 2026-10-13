"""Generated end-to-end CLI/evaluator smoke test, not real-scan acceptance."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from punctora_core.annotation_io import CLASSES, file_digest, read_json
from punctora_core.cli import main as core_main
from punctora_core.fixtures import demo_cloud
from punctora_core.quality_benchmark import run_benchmark, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir
    # Analytic truth is declared before the reconstruction is invoked. No
    # candidate result is copied into or used to tune this reference.
    elements = []
    for index, (start, end) in enumerate([([0, 0], [6, 0]), ([6, 0], [6, 4]),
                                        ([6, 4], [0, 4]), ([0, 4], [0, 0]), ([3, 0], [3, 4])]):
        elements.append({"id": f"wall-{index}", "class": "wall", "geometry": {
            "type": "wall", "start": start, "end": end, "base": 0., "height": 3., "thickness": .2}})
    identity = {"case_id": "generated-room", "source_sha256": hashlib.sha256(demo_cloud().points.astype("<f8").tobytes()).hexdigest(),
                "coordinate_mapping": {"translation_m": [0, 0, 0], "yaw_degrees": 0}, "crop": None}
    truth = {"schema_version": 1, "units": "metres", **identity, "truth_revision": "analytic-room-v1",
             "elements": elements, "semantic_samples": [], "exclusions": [],
             "class_states": {c: "present" if c == "wall" else "out_of_scope" if c in {"floor", "slab", "ceiling"}
                              else "absent" for c in CLASSES}}
    truth_path = output / "analytic-room.truth.json"
    write_report(truth_path, truth, frozen=True)
    reconstruction = output / "reconstruction"
    core_main(["demo", "--output-dir", str(reconstruction)])
    prediction = read_json(reconstruction / "elements.json")
    prediction["metadata"]["source"] = {"kind": "generated_fixture", "sha256": identity["source_sha256"]}
    prediction_path = output / "prediction.json"
    write_report(prediction_path, prediction)
    repeated = deepcopy(prediction)
    repeated["walls"].reverse()
    repeat_path = output / "reordered-prediction.json"
    write_report(repeat_path, repeated)
    case = {**identity, "source_kind": "generated_fixture", "split": "held_out", "required": True,
            "truth_revision": truth["truth_revision"], "truth": truth_path.name, "truth_sha256": file_digest(truth_path),
            "prediction": prediction_path.name, "prediction_sha256": file_digest(prediction_path),
            "repeat_prediction": repeat_path.name, "gates": [
                {"metric": "geometry.instances.wall.recall", "operator": "==", "value": 1},
                {"metric": "geometry.instances.stair.fp", "operator": "==", "value": 0},
                {"metric": "geometry.safety.duplicate_openings", "operator": "==", "value": 0},
                {"metric": "repeatability.geometry_equal", "operator": "==", "value": 1}]}
    manifest_path = output / "benchmark.json"
    write_report(manifest_path, {"schema_version": 1, "suite_kind": "generated_regression", "benchmark_id": "generated-cli-smoke",
                               "revision": "v1", "cases": [case]})
    baseline = output / "baseline-v1.json"
    outcome = core_main(["quality-evaluate", str(manifest_path), "--output", str(baseline), "--freeze"])
    # The unchanged a27 detector can fail an independent numerical gate.
    # That is a measured baseline defect, not an evaluator malfunction. The
    # harness tests transport, deterministic replay and non-moving truth.
    if outcome not in {0, 1}:
        return 1
    first = baseline.read_bytes()
    if core_main(["quality-evaluate", str(manifest_path), "--output", str(baseline), "--freeze"]) != outcome:
        return 1
    if first != baseline.read_bytes() or run_benchmark(manifest_path) != run_benchmark(manifest_path):
        raise ValueError("Generated evaluator report is not deterministic")
    if core_main(["quality-evaluate", str(manifest_path), "--output", str(output / "comparison.json"),
                  "--compare-baseline", str(baseline)]) != outcome:
        return 1
    report = read_json(baseline)
    if report["cases"][0].get("repeatability", {}).get("geometry_equal") != 1:
        raise ValueError("Reordering changed the geometry signature")
    print("Evaluator smoke passed; reconstruction acceptance is reported separately and is not overridden")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
