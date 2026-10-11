"""Fail CI if the desktop walkthrough produced incomplete evidence."""
import json
from pathlib import Path
import sys
import ifcopenshell
from punctora_core.ifc_export import validate_ifc

for argument in sys.argv[1:]:
    directory = Path(argument)
    report = json.loads((directory / "ui-verification.json").read_text())
    if directory.name == "m3-gl":
        assert "OpenGL" in report["viewport_backend"], "OpenGL CI must not silently pass through CPU fallback"
    assert report["edit_survived_reopen"] and report["ifc_exists"], report
    assert report["crop_undo_restored"] and report["crop_survived_reopen"], report
    assert report["feature_add_delete_passed"], report
    assert report["preview_failure_recovery_passed"], report
    assert report["small_window_scroll_passed"], report
    assert report["interactive_preview_passed"], report
    assert report["orbit"]["coalesced_mouse_moves"] >= 90, report
    assert report["orbit"]["pending_camera_frames"] <= 1, report
    if "OpenGL" in report["viewport_backend"]:
        assert 75_000 <= report["orbit"]["active_points"] <= 100_000, report
    assert report["graphics"]["preview_quality"] == "Adaptive", report
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
