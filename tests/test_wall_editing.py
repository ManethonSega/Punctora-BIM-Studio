from copy import deepcopy
import uuid

import ifcopenshell
import pytest

from punctora_core import projects
from punctora_core.model import BuildingModel, Opening, Storey, Wall
from punctora_core.wall_editing import consolidate_walls, merge_walls, split_wall


def model_with_fragments():
    model = BuildingModel("Wall corrections", [Storey("s", "Ground", 0, 3, [(-1, -1), (8, -1), (8, 3), (-1, 3)])])
    model.walls = [
        Wall("w1", "s", (0, 0), (2, 0), 0, 3, .2, evidence_count=20, fit_rmse_m=.01),
        Wall("w2", "s", (2.15, .01), (4, .01), 0, 3, .2, evidence_count=30, fit_rmse_m=.02),
        Wall("parallel", "s", (0, .5), (4, .5), 0, 3, .2),
    ]
    model.openings = [Opening("door", "w2", "door", .35, 0, .8, 2.1)]
    return model


def test_automatic_consolidation_joins_fragments_but_not_nearby_parallel_wall():
    model = model_with_fragments()
    walls, report = consolidate_walls(model.walls)
    assert [wall.id for wall in walls] == ["w1", "parallel"]
    assert report == {"input_walls": 3, "output_walls": 2, "groups": [["w1", "w2"]]}
    merged = walls[0]
    assert merged.evidence_count == 50
    assert merged.fit_rmse_m == pytest.approx((20*.01**2+30*.02**2)**.5/50**.5)
    assert merged.start[0] == pytest.approx(0, abs=.02)
    assert merged.end[0] == pytest.approx(4, abs=.02)


def test_manual_merge_reassigns_opening_and_retains_stable_wall_id():
    model = model_with_fragments()
    model.walls.pop()  # The separate parallel wall is not selected.
    result = merge_walls(model, ["w1", "w2"])
    assert [wall.id for wall in result.walls] == ["w1"]
    assert result.openings[0].host_wall_id == "w1"
    assert result.openings[0].offset == pytest.approx(2.5, abs=.03)
    assert result.openings[0].width == pytest.approx(.8, abs=.01)
    assert result.metadata["geometry_edited"]
    assert result.metadata["edit_history"][-1]["operation"] == "merge_walls"


def test_split_reassigns_openings_and_rejects_a_cut_through_an_opening():
    model = model_with_fragments();model.walls = [Wall("w", "s", (0, 0), (6, 0), 0, 3, .2)]
    model.openings = [Opening("first", "w", "door", .5, 0, .8, 2.1), Opening("second", "w", "window", 4, 1, 1, 1)]
    result = split_wall(model, "w", 3)
    assert [wall.id for wall in result.walls] == ["w", "w-split-2"]
    assert result.openings[0].host_wall_id == "w"
    assert result.openings[1].host_wall_id == "w-split-2"
    assert result.openings[1].offset == pytest.approx(1)
    crossing = deepcopy(result)
    with pytest.raises(ValueError, match="crosses opening"):
        split_wall(crossing, "w-split-2", 1.5)


def test_wall_topology_edits_survive_save_and_export_valid_ifc(tmp_path):
    path = tmp_path/"walls.punctora"
    state = projects.create_project(path, uuid.uuid4().hex)
    model = model_with_fragments();model.walls.pop();model.metadata["project_id"] = state["project_id"]
    draft = projects.merge_model_walls(state, model.to_dict(), ["w1", "w2"])
    state = projects.save_project(path, {"expected_revision": state["revision"], "model": draft})
    reopened = projects.load_project(path)
    assert len(reopened["model"]["walls"]) == 1
    assert reopened["model"]["openings"][0]["host_wall_id"] == "w1"
    target = tmp_path/"walls.ifc"
    report = projects.export_project(path, {"expected_revision": state["revision"], "model": reopened["model"], "output": str(target)})
    assert report["validation"]["valid"]
    file = ifcopenshell.open(str(target))
    assert len(file.by_type("IfcWall")) == 1
    assert len(file.by_type("IfcOpeningElement")) == 1
