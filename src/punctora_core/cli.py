"""Developer CLI for direct E57/XYZ reconstruction and validated IFC output."""
import argparse
import hashlib
import json
import os
import tempfile
import uuid
import shutil
from pathlib import Path

from . import __version__
from .cloud_io import read_xyz, write_xyz
from .e57_io import read_e57
from .fixtures import demo_cloud
from .ifc_export import write_ifc
from .reconstruction import ReconstructionSettings, reconstruct
from .convergence import compare_budgets
from .evidence import write_model_evidence


def _json_write(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, indent=2, ensure_ascii=False, allow_nan=False)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Punctora experimental E57/XYZ-to-IFC core")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Generate and reconstruct a synthetic floor example")
    demo.add_argument("--two-storeys", action="store_true")
    demo.add_argument("--output-dir", type=Path, required=True)
    demo.add_argument("--settings", type=Path, help="JSON object containing ReconstructionSettings fields")
    demo.add_argument("--compare-budgets", action="store_true",
                      help="Compare 250k/500k/1M/2M/5M candidate budgets until geometry stabilises")
    convert = commands.add_parser("convert-xyz", help="Reconstruct local, registered XYZ data with declared units and Z up")
    convert.add_argument("input", type=Path)
    convert.add_argument("--units", choices=["m", "mm"], required=True)
    convert.add_argument("--settings", type=Path, help="JSON object containing ReconstructionSettings fields")
    convert.add_argument("--compare-budgets", action="store_true",
                         help="Compare candidate budgets until geometry stabilises")
    convert.add_argument("--output-dir", type=Path, required=True)
    e57 = commands.add_parser("convert-e57", help="Import registered E57 scans and reconstruct in a local metre frame")
    e57.add_argument("input", type=Path)
    e57.add_argument("--settings", type=Path, help="JSON object containing ReconstructionSettings fields")
    e57.add_argument("--compare-budgets", action="store_true",
                     help="Compare candidate budgets until geometry stabilises")
    e57.add_argument("--chunk-points", type=int, default=1_000_000,
                     help="Maximum E57 records decoded at once (default: 1000000)")
    e57.add_argument("--output-dir", type=Path, required=True)
    importer = commands.add_parser("import-e57", help="Import E57 into a local cache without reconstructing elements")
    importer.add_argument("input", type=Path)
    importer.add_argument("--chunk-points", type=int, default=1_000_000)
    importer.add_argument("--output-dir", type=Path, required=True)
    quality = commands.add_parser("quality-evaluate", help="Evaluate fingerprinted local truth; never reconstruct or tune")
    quality.add_argument("manifest", type=Path)
    quality.add_argument("--output", type=Path, required=True)
    quality.add_argument("--freeze", action="store_true", help="Write-once baseline, refuse changed content")
    quality.add_argument("--compare-baseline", type=Path, help="Compare against a frozen evaluator report")
    freeze = commands.add_parser("quality-freeze-artifacts", help="Freeze a27 IFC/telemetry facts, not independent accuracy")
    freeze.add_argument("--ifc", type=Path, required=True)
    freeze.add_argument("--performance", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    recognition = commands.add_parser("recognition-propose", help="Run review-only recognition on fingerprinted original arrays; never write IFC")
    recognition.add_argument("manifest", type=Path)
    recognition.add_argument("--cache-dir", type=Path, required=True)
    recognition.add_argument("--provider", choices=["classical", "cloud2bim_experimental"], default="classical")
    recognition.add_argument("--assets", type=Path, help="Explicit isolated runtime/checkpoint/config JSON; no downloads")
    recognition.add_argument("--settings", type=Path, help="Classical ReconstructionSettings JSON")
    recognition.add_argument("--tiles", type=Path, help="TileSettings JSON")
    recognition.add_argument("--ram-gb", type=float, default=0.)
    recognition.add_argument("--diagnostics", type=Path, help="Persistent diagnostics outside cache staging")
    semantic = commands.add_parser("recognition-export-samples", help="Export labels for ID-only semantic samples after inference")
    semantic.add_argument("proposal_directory", type=Path)
    semantic.add_argument("sample_keys", type=Path)
    semantic.add_argument("--output", type=Path, required=True)
    hybrid = commands.add_parser("recognition-fuse", help="Fuse review-only 3D labels, both-face projections and optional isolated 2D instances")
    hybrid.add_argument("manifest", type=Path)
    hybrid.add_argument("--proposal-dir", type=Path, required=True, help="Fingerprint-matched, unfused Run 2 generation")
    hybrid.add_argument("--cache-dir", type=Path, required=True)
    hybrid.add_argument("--vision-assets", type=Path, help="Explicit trusted local 2D worker/configuration, no downloads")
    hybrid.add_argument("--settings", type=Path, help="HybridSettings JSON")
    hybrid.add_argument("--tiles", type=Path, help="TileSettings JSON")
    hybrid.add_argument("--ram-gb", type=float, default=0.)
    hybrid.add_argument("--diagnostics", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "recognition-fuse":
            from .annotation_io import read_json
            from .quality_benchmark import write_report
            from .recognition.contracts import safe_artifact_path
            from .recognition.hybrid import HybridProvider, HybridSettings
            from .recognition.io import load_input
            from .recognition.job import run_recognition
            from .recognition.tiling import TileSettings
            from .recognition.vision_provider import IsolatedVisionProvider, VisionAssets
            if not __import__("math").isfinite(args.ram_gb) or args.ram_gb < 0:
                raise ValueError("Hybrid RAM cap must be finite and nonnegative")
            source = read_json(args.manifest)
            protected = [args.manifest, *[p for p in (args.settings, args.tiles, args.vision_assets) if p]]
            protected.extend(safe_artifact_path(args.manifest.parent, a["path"]) for a in source.get("arrays", {}).values())
            vision = None
            if args.vision_assets:
                assets = read_json(args.vision_assets)
                protected.extend(Path(assets[k]) for k in ("python", "worker", "configuration"))
                configuration = Path(assets["configuration"])
                if configuration.is_file():
                    protected.extend(Path(a["path"]) for a in read_json(configuration).get("model_assets", []))
                vision = IsolatedVisionProvider(VisionAssets(**assets))
            if args.diagnostics and (args.diagnostics.resolve() in {p.resolve() for p in protected}
                or args.diagnostics.resolve().is_relative_to(args.cache_dir.resolve())
                or args.diagnostics.resolve().is_relative_to(args.proposal_dir.resolve())):
                raise ValueError("Hybrid diagnostics must be outside inputs and both immutable caches")
            settings = HybridSettings(**read_json(args.settings)) if args.settings else HybridSettings()
            tiles = TileSettings(**read_json(args.tiles)) if args.tiles else TileSettings()
            provider = HybridProvider(args.proposal_dir, vision, settings)
            with load_input(args.manifest) as (cloud, identity):
                directory, report, hit = run_recognition(cloud, identity, provider, args.cache_dir,
                    tile_settings=tiles, memory_limit_bytes=int(args.ram_gb * 1024**3),
                    diagnostics=(lambda r: write_report(args.diagnostics, r)) if args.diagnostics else None)
            print(json.dumps({"status": report["status"], "directory": str(directory), "cache_hit": hit,
                "geometry_authority": report["geometry_authority"], "instances": len(report["instances"]),
                "hybrid": report["extensions"]["hybrid_v1"]["diagnostics"], "warnings": report["warnings"]}, indent=2))
            return 0
        if args.command == "recognition-export-samples":
            from .annotation_io import read_json
            from .recognition.io import export_semantic_samples
            if args.output.resolve() == args.sample_keys.resolve():
                raise ValueError("Semantic export cannot overwrite its source-key input")
            report = export_semantic_samples(args.proposal_directory, read_json(args.sample_keys), args.output)
            print(json.dumps({"output": str(args.output), **report["export_diagnostics"]}, indent=2))
            return 0
        if args.command == "recognition-propose":
            from .annotation_io import read_json
            from .quality_benchmark import write_report
            from .recognition.classical_provider import ClassicalProvider
            from .recognition.cloud2bim_provider import Cloud2BIMAssets, Cloud2BIMProvider
            from .recognition.io import load_input
            from .recognition.job import run_recognition
            from .recognition.tiling import TileSettings
            from .recognition.contracts import safe_artifact_path
            if not __import__("math").isfinite(args.ram_gb) or args.ram_gb < 0:
                raise ValueError("Recognition RAM cap must be finite and nonnegative")
            protected = [args.manifest, *[p for p in (args.assets, args.settings, args.tiles) if p]]
            input_manifest = read_json(args.manifest)
            protected.extend(safe_artifact_path(args.manifest.parent, descriptor["path"])
                             for descriptor in input_manifest.get("arrays", {}).values())
            if args.assets:
                asset_manifest = read_json(args.assets)
                protected.extend(Path(asset_manifest[key]) for key in ("python", "checkpoint", "model_config", "runtime_manifest"))
            if args.diagnostics and (args.diagnostics.resolve() in {p.resolve() for p in protected}
                                     or args.diagnostics.resolve().is_relative_to(args.cache_dir.resolve())):
                raise ValueError("Recognition diagnostics must be outside inputs and the immutable cache")
            settings = ReconstructionSettings(**read_json(args.settings)) if args.settings else ReconstructionSettings()
            classical = ClassicalProvider(settings)
            if args.provider == "cloud2bim_experimental":
                if args.assets is None:
                    raise ValueError("Experimental recognition requires explicit local --assets; no automatic download")
                provider = Cloud2BIMProvider(Cloud2BIMAssets(**asset_manifest))
                fallback = classical
            else:
                if args.assets:
                    raise ValueError("Model --assets only apply to cloud2bim_experimental")
                provider, fallback = classical, None
            tiles = TileSettings(**read_json(args.tiles)) if args.tiles else TileSettings()
            with load_input(args.manifest) as (cloud, identity):
                directory, report, hit = run_recognition(cloud, identity, provider, args.cache_dir,
                    tile_settings=tiles, fallback=fallback, memory_limit_bytes=int(args.ram_gb * 1024**3),
                    diagnostics=(lambda r: write_report(args.diagnostics, r)) if args.diagnostics else None)
            print(json.dumps({"status": report["status"], "requested_provider": args.provider,
                              "provider_used": report["provider"]["id"], "cache_hit": hit, "directory": str(directory),
                              "geometry_authority": report["geometry_authority"], "warnings": report["warnings"]}, indent=2))
            return 0
        if args.command == "quality-freeze-artifacts":
            from .quality_benchmark import freeze_artifact_baseline
            report = freeze_artifact_baseline(args.ifc, args.performance, args.output)
            print(json.dumps({"status": report["status"], "output": str(args.output)}, indent=2))
            return 0
        if args.command == "quality-evaluate":
            from .quality_benchmark import run_benchmark, write_report, compare_reports, load_manifest
            from .annotation_io import read_json, content_digest
            report = run_benchmark(args.manifest)
            if args.compare_baseline:
                report["baseline_comparison"] = compare_reports(read_json(args.compare_baseline), report)
            protected = [args.manifest]
            for case in load_manifest(args.manifest)["cases"]:
                for key in ("truth", "prediction", "semantic_prediction", "repeat_prediction", "performance", "source_path"):
                    if case.get(key):
                        value = Path(case[key])
                        protected.append(value if value.is_absolute() else args.manifest.parent / value)
            if args.compare_baseline:
                protected.append(args.compare_baseline)
            if args.output.resolve() in {p.resolve() for p in protected}:
                raise ValueError("Quality output cannot overwrite an input or frozen baseline")
            report["report_sha256"] = content_digest({k: v for k, v in report.items() if k != "report_sha256"})
            write_report(args.output, report, frozen=args.freeze)
            print(json.dumps({"passed": report["passed"], "decision": report["decision"],
                              "output": str(args.output)}, indent=2))
            return 0 if report["passed"] else 1
        settings = ReconstructionSettings()
        source = {"kind": "generated_fixture"}
        import_manifest = None
        if args.command == "demo":
            cloud = demo_cloud(args.two_storeys)
        elif args.command == "convert-xyz":
            cloud = read_xyz(args.input)
            cloud.points *= 0.001 if args.units == "mm" else 1.0
            source = {"kind": "XYZ", "filename": args.input.name, "units": args.units,
                      "sha256": hashlib.sha256(args.input.read_bytes()).hexdigest()}
        else:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            imported = read_e57(args.input, args.output_dir / "working-cache", args.chunk_points)
            cloud, import_manifest = imported.cloud, imported.manifest
            source = import_manifest["source"]
            if args.command == "import-e57":
                _json_write(args.output_dir/"import-manifest.json", import_manifest)
                print(json.dumps({"version": __version__, "source_points": len(cloud.points),
                                  "scan_count": import_manifest["scan_count"], "output": str(args.output_dir),
                                  "warnings": import_manifest["warnings"]}, indent=2))
                return 0
        if getattr(args, "settings", None):
            settings = ReconstructionSettings(**json.loads(args.settings.read_text(encoding="utf-8")))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        performance_path = args.output_dir / "performance.json"
        if getattr(args, "compare_budgets", False):
            model, budget_report = compare_budgets(
                cloud, settings,
                diagnostics=lambda report: _json_write(performance_path, report))
            _json_write(args.output_dir / "budget-comparison.json", budget_report)
        else:
            model = reconstruct(
                cloud, settings,
                name="Punctora core example" if args.command == "demo" else args.input.stem,
                diagnostics=lambda report: _json_write(performance_path, report))
        model.metadata["source"] = source
        if import_manifest is not None:
            model.warnings.extend(import_manifest["warnings"])
            model.metadata["coordinate_mapping"] = import_manifest["coordinate_mapping"]
            model.metadata["e57"] = {
                "coordinate_metadata": import_manifest["coordinate_metadata"],
                "coordinate_metadata_status": import_manifest["coordinate_metadata_status"],
                "scan_count": import_manifest["scan_count"],
                "raw_point_count": import_manifest["raw_point_count"],
                "valid_point_count": import_manifest["valid_point_count"],
            }
        # Protect the source even if output directory overlaps its directory.
        destinations = [args.output_dir/name for name in ["model.ifc", "elements.json", "validation.json", "source.xyz"]]
        if args.command == "convert-xyz" and any(p.resolve() == args.input.resolve() for p in destinations[:3]):
            raise ValueError("Output path overlaps the source input")
        evidence_directory = args.output_dir/"evidence"/uuid.uuid4().hex
        evidence_directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            write_model_evidence(cloud,model,evidence_directory,settings.processing_chunk_points)
        except Exception:
            shutil.rmtree(evidence_directory, ignore_errors=True)
            raise
        report = write_ifc(model, args.output_dir/"model.ifc")
        _json_write(args.output_dir/"elements.json", model.to_dict())
        _json_write(args.output_dir/"validation.json", report)
        if import_manifest is not None:
            _json_write(args.output_dir/"import-manifest.json", import_manifest)
        if args.command == "demo":
            write_xyz(cloud, args.output_dir/"source.xyz")
        print(json.dumps({"version": __version__, "storeys": len(model.storeys), "walls": len(model.walls),
                          "slabs": len(model.slabs), "spaces": len(model.spaces), "openings": len(model.openings),
                          "stairs": len(model.stairs), "landings": len(model.landings), "ifc_valid": report["valid"],
                          "output": str(args.output_dir), "warnings": model.warnings}, indent=2))
        return 0
    except (ValueError, TypeError, OSError, MemoryError, RuntimeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Punctora: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

