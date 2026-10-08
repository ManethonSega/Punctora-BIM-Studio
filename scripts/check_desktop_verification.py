"""Fail CI if the desktop walkthrough produced incomplete evidence."""
import json
from pathlib import Path
import sys
import ifcopenshell
from punctora_core.ifc_export import validate_ifc

for argument in sys.argv[1:]:
    directory = Path(argument)
    report = json.loads((directory / "ui-verification.json").read_text())
    assert report["edit_survived_reopen"] and report["ifc_exists"], report
    assert report["graphics"]["render_callbacks"] > 0, report
    assert (directory / "desktop.png").stat().st_size > 1000
    assert validate_ifc(ifcopenshell.open(str(directory / "edited.ifc")))["valid"]
    if "OpenGL" in report["viewport_backend"]:
        assert (directory / "viewport-gl.png").stat().st_size > 1000
    print(directory, report["viewport_backend"])
