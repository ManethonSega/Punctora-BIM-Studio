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
from .evidence import write_wall_evidence


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
    args = parser.parse_args(argv)
    try:
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
            write_wall_evidence(cloud, model.walls, evidence_directory, settings.processing_chunk_points,
                                model.metadata.get("surface_proposals"))
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
    except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Punctora: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

