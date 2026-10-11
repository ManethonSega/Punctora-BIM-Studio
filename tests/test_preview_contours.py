"""Detailed clipped polygons remain concave and survive preview regeneration."""
import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from punctora_core.model import BuildingModel, Landing, SlabOpening, Storey, Slab


def contour_model():
    contours = json.loads((Path(__file__).parent / "fixtures/preview_contours.json").read_text())
    boundary = [(-5, -5), (5, -5), (5, 5), (-5, 5)]
    return BuildingModel("Preview contours", storeys=[Storey("level", "Level", 0, 3, boundary)],
        slabs=[Slab("floor", "level", boundary, -.2, .2)],
        landings=[Landing(f"landing-{i}", "level", polygon, 1.5)
                  for i, polygon in enumerate(contours["landings"])],
        slab_openings=[SlabOpening(f"void-{i}", "floor", (0, 0), (1, 0), .1, footprint=polygon)
                       for i, polygon in enumerate(contours["slab_openings"])])


def test_constrained_preview_matches_real_clipped_contours_after_edit():
    model = contour_model()
    for snapshot in [model.to_dict(), BuildingModel.from_dict(model.to_dict()).to_dict()]:
        for kind in ["landings", "slab_openings"]:
            for element in snapshot[kind]:
                source = Polygon(element["footprint"])
                cap = unary_union([Polygon(t) for t in element["preview_geometry"]["surface_triangles_xy"]])
                assert source.symmetric_difference(cap).area < 1e-9
    model.landings[0].footprint = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    changed = model.to_dict()["landings"][0]
    assert sum(Polygon(t).area for t in changed["preview_geometry"]["surface_triangles_xy"]) == pytest.approx(3)


def test_legacy_project_preview_is_rebuilt_without_changing_revision(tmp_path):
    from punctora_core import projects
    from uuid import uuid4
    path = tmp_path / "legacy.punctora"
    state = projects.create_project(path, uuid4().hex)
    model = contour_model()
    model.metadata["project_id"] = state["project_id"]
    state = projects.save_project(path, {"expected_revision": state["revision"], "model": model.to_dict()})
    old = json.loads(path.read_text())
    for kind in ["landings", "slab_openings"]:
        for element in old["model"][kind]:
            element.pop("preview_geometry")
    path.write_text(json.dumps(old))
    before = path.read_bytes()
    reopened = projects.load_project(path)
    assert reopened["revision"] == old["revision"]
    assert path.read_bytes() == before
    assert all(e["preview_geometry"]["surface_triangles_xy"] for kind in ["landings", "slab_openings"] for e in reopened["model"][kind])


def test_render_simplification_preserves_voids_and_exact_ifc_geometry():
    from copy import deepcopy
    import numpy as np
    import ifcopenshell.geom
    from punctora_core.ifc_export import create_ifc
    # Dense survey contour with submillimetre detail that has no screen value.
    boundary = [(i / 20, .0004 * (i % 2)) for i in range(201)] + [(10, 10), (0, 10)]
    model = BuildingModel("Render only", storeys=[Storey("level", "Level", 0, 3, boundary)],
        slabs=[Slab("floor", "level", boundary, -.2, .2)],
        slab_openings=[SlabOpening("hole", "floor", (4, 4), (5, 4), 1)])
    original = deepcopy(model.slabs[0].footprint)
    snapshot = model.to_dict()
    mesh = snapshot["slabs"][0]["preview_geometry"]
    exact = unary_union([Polygon(t) for t in mesh["surface_triangles_xy"]])
    render = unary_union([Polygon(t) for t in mesh["render_surface_triangles_xy"]])
    assert len(mesh["render_surface_triangles_xy"]) < len(mesh["surface_triangles_xy"]) / 2
    assert len(render.interiors) == len(exact.interiors) == 1
    assert render.hausdorff_distance(exact) <= .002 + 1e-9
    assert render.symmetric_difference(exact).area <= exact.area * .001
    assert model.slabs[0].footprint == snapshot["slabs"][0]["footprint"] == original

    def vertices(source):
        file = create_ifc(source)
        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)
        shape = ifcopenshell.geom.create_shape(settings, file.by_type("IfcSlab")[0])
        return np.asarray(shape.geometry.verts).reshape(-1, 3).copy()

    before = vertices(model)
    # Reopening a serialized preview must not substitute the render contours.
    after = vertices(BuildingModel.from_dict(snapshot))
    assert np.array_equal(before, after)
