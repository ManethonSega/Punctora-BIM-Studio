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
    assert report["crop_undo_restored"] and report["crop_survived_reopen"], report
    assert report["feature_add_delete_passed"], report
    assert report["preview_failure_recovery_passed"], report
    assert report["small_window_scroll_passed"], report
    assert (directory / "small-window.png").stat().st_size > 1000
    assert report["graphics"]["render_callbacks"] > 0, report
    assert report["graphics"]["cloud_color_mode"] == "Monochrome", report
    assert report["graphics"]["point_size_px"] == 5, report
    assert (directory / "desktop.png").stat().st_size > 1000
    model = ifcopenshell.open(str(directory / "edited.ifc"))
    assert validate_ifc(model)["valid"]
    assert len(model.by_type("IfcWindow")) == 1
    assert len(model.by_type("IfcStairFlight")) == 1
    assert model.by_type("IfcStairFlight")[0].TreadLength == .28
    if "OpenGL" in report["viewport_backend"]:
        assert (directory / "viewport-gl.png").stat().st_size > 1000
    print(directory, report["viewport_backend"])
