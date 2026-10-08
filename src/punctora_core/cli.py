"""Developer CLI for the M1 core; desktop and direct E57 input follow later."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from . import __version__
from .cloud_io import read_xyz, write_xyz
from .fixtures import demo_cloud
from .ifc_export import write_ifc
from .reconstruction import ReconstructionSettings, reconstruct


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
    parser = argparse.ArgumentParser(description="Punctora experimental XYZ-to-IFC core (E57 reader not implemented)")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Generate and reconstruct a synthetic floor example")
    demo.add_argument("--two-storeys", action="store_true")
    demo.add_argument("--output-dir", type=Path, required=True)
    convert = commands.add_parser("convert-xyz", help="Reconstruct local, registered XYZ data with declared units and Z up")
    convert.add_argument("input", type=Path)
    convert.add_argument("--units", choices=["m", "mm"], required=True)
    convert.add_argument("--settings", type=Path, help="JSON object containing ReconstructionSettings fields")
    convert.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        settings = ReconstructionSettings()
        source = {"kind": "generated_fixture"}
        if args.command == "demo":
            cloud = demo_cloud(args.two_storeys)
        else:
            cloud = read_xyz(args.input)
            cloud.points *= 0.001 if args.units == "mm" else 1.0
            source = {"kind": "XYZ", "filename": args.input.name, "units": args.units,
                      "sha256": hashlib.sha256(args.input.read_bytes()).hexdigest()}
            if args.settings:
                settings = ReconstructionSettings(**json.loads(args.settings.read_text(encoding="utf-8")))
        model = reconstruct(cloud, settings, name="Punctora core example" if args.command == "demo" else args.input.stem)
        model.metadata["source"] = source
        args.output_dir.mkdir(parents=True, exist_ok=True)
        # Protect the source even if output directory overlaps its directory.
        destinations = [args.output_dir/name for name in ["model.ifc", "elements.json", "validation.json", "source.xyz"]]
        if args.command == "convert-xyz" and any(p.resolve() == args.input.resolve() for p in destinations[:3]):
            raise ValueError("Output path overlaps the source input")
        report = write_ifc(model, args.output_dir/"model.ifc")
        _json_write(args.output_dir/"elements.json", model.to_dict())
        _json_write(args.output_dir/"validation.json", report)
        if args.command == "demo":
            write_xyz(cloud, args.output_dir/"source.xyz")
        print(json.dumps({"version": __version__, "storeys": len(model.storeys), "walls": len(model.walls),
                          "slabs": len(model.slabs), "spaces": len(model.spaces), "ifc_valid": report["valid"],
                          "output": str(args.output_dir), "warnings": model.warnings}, indent=2))
        return 0
    except (ValueError, TypeError, OSError) as exc:
        parser.exit(2, f"Punctora: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
