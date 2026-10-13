"""Generated classical proposal smoke; no learned weights or external truth."""
import argparse
from pathlib import Path
import numpy as np

from punctora_core.annotation_io import content_digest
from punctora_core.fixtures import demo_cloud
from punctora_core.quality_benchmark import write_report
from punctora_core.recognition.classical_provider import ClassicalProvider
from punctora_core.recognition.io import export_semantic_samples
from punctora_core.recognition.job import run_recognition
from punctora_core.recognition.tiling import TileSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    cloud = demo_cloud()
    # Explicit generated namespace, never E57 IDs manufactured for real data.
    cloud.scan_index = np.zeros(len(cloud.points), dtype="<u8")
    cloud.source_record_index = np.arange(2**53 + 1, 2**53 + 1 + len(cloud.points), dtype="<u8")
    cloud.working_index = np.arange(len(cloud.points), dtype="<u8")
    case = {"case_id": "generated-classical-smoke", "source_sha256": content_digest({"fixture": "demo_cloud-v1"}),
            "coordinate_mapping": {"translation_m": [0., 0., 0.], "yaw_degrees": 0.}, "crop": None}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = lambda r: write_report(args.output_dir / "diagnostics.json", r)
    settings = TileSettings(maximum_context_points=100000)
    first, report, hit = run_recognition(cloud, case, ClassicalProvider(), args.output_dir / "cache",
                                       tile_settings=settings, diagnostics=diagnostics)
    second, repeated, second_hit = run_recognition(cloud, case, ClassicalProvider(), args.output_dir / "cache", tile_settings=settings)
    assert second_hit and first == second and report == repeated
    assert report["instances"] and report["provider"]["backend"] == "CPU"
    keys = [{"source_sha256": case["source_sha256"], "scan_index": 0, "source_record_index": int(r)}
            for r in cloud.source_record_index[::1000]]
    labels = export_semantic_samples(first, keys, args.output_dir / "semantic-prediction.json")
    assert labels["elements"] == []
    result = {"status": "passed", "scope": "generated internal conformance, not real-scan or learned-model quality",
              "source_points": len(cloud.points), "proposed_instances": len(report["instances"]),
              "labelled_points": int((np.load(first / "labels.npy") >= 0).sum()),
              "cache_replay_identical": True, "semantic_export": labels["export_diagnostics"]}
    write_report(args.output_dir / "smoke.json", result)
    print(result)


if __name__ == "__main__":
    main()
