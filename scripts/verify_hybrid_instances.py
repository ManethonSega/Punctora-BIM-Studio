"""Run 3 generated classical -> projection/fusion/graph -> cache smoke."""
import argparse
from pathlib import Path
import numpy as np

from punctora_core.annotation_io import content_digest, read_json
from punctora_core.fixtures import demo_cloud
from punctora_core.quality_benchmark import write_report
from punctora_core.recognition.classical_provider import ClassicalProvider
from punctora_core.recognition.element_graph import validate_graph
from punctora_core.recognition.hybrid import HybridProvider, HybridSettings
from punctora_core.recognition.job import run_recognition
from punctora_core.recognition.tiling import TileSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cloud = demo_cloud()
    cloud.scan_index = np.zeros(len(cloud.points), dtype="<u8")
    cloud.source_record_index = np.arange(2**53 + 1, 2**53 + 1 + len(cloud.points), dtype="<u8")
    cloud.working_index = np.arange(len(cloud.points), dtype="<u8")
    identity = {"case_id": "generated-hybrid-chain", "source_sha256": content_digest({"fixture": "demo_cloud-v1"}),
                "coordinate_mapping": {"translation_m": [0., 0., 0.], "yaw_degrees": 0.}, "crop": None}
    tile_settings = TileSettings(maximum_context_points=100000)
    upstream, _, _ = run_recognition(cloud, identity, ClassicalProvider(), args.output_dir / "upstream", tile_settings=tile_settings)
    provider = HybridProvider(upstream, settings=HybridSettings(maximum_wall_context_points=100000, maximum_column_points=100000))
    directory, report, _ = run_recognition(cloud, identity, provider, args.output_dir / "fused", tile_settings=tile_settings,
        diagnostics=lambda r: write_report(args.output_dir / "diagnostics.json", r))
    replay, repeated, hit = run_recognition(cloud, identity, HybridProvider(upstream, settings=provider.settings),
                                          args.output_dir / "fused", tile_settings=tile_settings)
    assert hit and replay == directory and repeated == report
    graph = validate_graph(read_json(directory / "hybrid/element-graph-v1.json"))
    assert graph["nodes"] and all(n["cut_applied"] is False for n in graph["nodes"])
    assert np.array_equal(np.load(upstream / "labels.npy"), np.load(directory / "labels.npy"))
    assert np.array_equal(np.load(upstream / "scores.npy"), np.load(directory / "scores.npy"))
    assert not list(directory.glob("*.ifc"))
    result = {"status": "passed", "scope": "generated internal conformance, real-building quality after Run 9",
              "source_points": len(cloud.points), "wall_views": report["extensions"]["hybrid_v1"]["diagnostics"]["wall_views"],
              "graph_nodes": len(graph["nodes"]), "graph_relations": len(graph["edges"]),
              "applied_cuts": 0, "point_labels_scores_unchanged": True, "cache_replay_identical": True}
    write_report(args.output_dir / "smoke.json", result)
    print(result)


if __name__ == "__main__":
    main()
