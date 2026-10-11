from copy import deepcopy
import uuid

import ifcopenshell
import pytest

from punctora_core import projects
from punctora_core.model import BuildingModel, Opening, Storey, Wall
from punctora_core.wall_editing import (consolidate_walls, merge_walls, snap_wall_topology,
                                       merge_reconciled_openings,
                                       reconcile_opening_supported_faces,
                                       rehost_reconciled_openings, split_wall,
                                       wall_connectivity_report)


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


def test_matching_openings_reconcile_partial_parallel_faces_and_keep_tails():
    faces=lambda y:[dict(start=[0,y],end=[6,y],z_min=0,z_max=3),
                    dict(start=[0,y],end=[6,y],z_min=0,z_max=3)]
    first=Wall('a','s',(0,0),(6,0),0,3,.2,'single_face_candidate',
               observed_faces=faces(0),evidence_count=100)
    second=Wall('b','s',(2,.2),(8,.2),0,3,.2,'single_face_candidate',
                observed_faces=[dict(start=[2,.2],end=[8,.2],z_min=0,z_max=3)]*2,
                evidence_count=120)
    openings=[Opening('a1','a','window',2.5,1.,1.,1.),
              Opening('a2','a','window',4.,1.,1.,1.),
              Opening('b1','b','window',.5,1.,1.,1.),
              Opening('b2','b','window',2.,1.,1.,1.)]
    walls,affected,replaced,report=reconcile_opening_supported_faces([first,second],openings)
    paired=[wall for wall in walls if wall.classification=='paired_faces']
    assert len(paired)==1 and paired[0].thickness==pytest.approx(.2)
    assert abs(paired[0].end[0]-paired[0].start[0])==pytest.approx(4.)
    assert len(walls)==3 and len(affected)==3 and replaced=={'a','b'}
    assert report[0]['action']=='pair' and report[0]['matching_opening_count']==2


def test_opening_reconciliation_converts_intervals_for_reversed_wall_axis():
    observed=lambda a,b,y:[dict(start=[a,y],end=[b,y],z_min=0,z_max=3)]*2
    paired=Wall('paired','s',(2,.1),(6,.1),0,3,.2,'paired_faces',
                observed_faces=observed(2,6,0)+observed(2,6,.2))
    reverse=Wall('reverse','s',(8,.3),(2,.3),0,3,.2,'single_face_candidate',
                 observed_faces=observed(8,2,.3),evidence={'vertical_continuity':.5})
    openings=[Opening('p','paired','window',1,1,1,1),
              Opening('r','reverse','window',4,1,1,1)]
    walls,affected,replaced,report=reconcile_opening_supported_faces([paired,reverse],openings)
    assert report[0]['action']=='trim_existing_pair' and replaced=={'reverse'}
    remainder=next(wall for wall in walls if wall.id.startswith('reverse-remainder'))
    assert sorted((remainder.start[0],remainder.end[0]))==pytest.approx([6,8])


def test_one_matching_opening_does_not_reconcile_two_long_independent_walls():
    faces=lambda y:[dict(start=[0,y],end=[8,y],z_min=0,z_max=3),
                    dict(start=[0,y],end=[8,y],z_min=0,z_max=3)]
    first=Wall('a','s',(0,0),(8,0),0,3,.2,observed_faces=faces(0))
    second=Wall('b','s',(0,.3),(8,.3),0,3,.2,observed_faces=faces(.3))
    openings=[Opening('a1','a','door',2,0,.8,2.1),Opening('b1','b','door',2,0,.8,2.1)]
    walls,affected,replaced,report=reconcile_opening_supported_faces([first,second],openings)
    assert walls==[first,second] and not affected and not replaced and not report


def test_supported_opening_survives_face_reconciliation_at_final_host_boundary():
    faces=lambda a,b,y:[dict(start=[a,y],end=[b,y],z_min=0,z_max=3)]*2
    paired=Wall('paired','s',(0,.1),(4,.1),0,3,.2,'paired_faces',
                observed_faces=faces(0,4,0)+faces(0,4,.2))
    source=Wall('source','s',(-1,.3),(5,.3),0,3,.2,'single_face_candidate',
                observed_faces=faces(-1,5,.3))
    old=[Opening('paired-window','paired','window',2,1,1,1,confidence=.8),
         Opening('same-window','source','window',3,1,1,1,confidence=.8),
         Opening('edge-window','source','window',1.5,1,.6,1,confidence=.9)]
    final,affected,replaced,report=reconcile_opening_supported_faces([paired,source],old)
    assert report and replaced=={'source'}
    carried=rehost_reconciled_openings(old,[paired,source],final,replaced)
    merged=merge_reconciled_openings([old[0]],carried,[],final)
    assert len(merged)==2
    edge=next(opening for opening in merged if opening.width==pytest.approx(.6))
    assert edge.host_wall_id=='paired'
    assert edge.evidence['reconciled_host']['source_wall_id']=='source'


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


def test_corner_clustering_converges_four_wall_ends_to_one_shared_point():
    walls = [
        Wall("west", "s", (-2, .02), (-.08, .02), 0, 3, .2),
        Wall("east", "s", (.09, -.01), (2, -.01), 0, 3, .2),
        Wall("south", "s", (.01, -2), (.01, -.07), 0, 3, .2),
        Wall("north", "s", (-.02, .08), (-.02, 2), 0, 3, .2),
    ]
    topology = snap_wall_topology(walls)
    joined = [walls[0].end, walls[1].start, walls[2].end, walls[3].start]
    assert all(point == pytest.approx(joined[0]) for point in joined[1:])
    assert len(topology["corner_clusters"]) == 1
    assert topology["corner_clusters"][0]["maximum_displacement_m"] < .2


def test_perpendicular_t_junction_snaps_but_nearby_parallel_wall_does_not_move():
    host = Wall("host", "s", (0, 0), (4, 0), 0, 3, .2)
    partition = Wall("partition", "s", (2, .08), (2, 2), 0, 3, .2)
    parallel = Wall("parallel", "s", (0, .08), (1.5, .08), 0, 3, .2)
    parallel_before = (parallel.start, parallel.end)
    topology = snap_wall_topology([host, partition, parallel], corner_tolerance_m=.05,
                                  t_tolerance_m=.1, t_minimum_angle_deg=25)
    assert partition.start == pytest.approx((2, 0))
    assert (parallel.start, parallel.end) == parallel_before
    assert len(topology["t_junctions"]) == 1
    junction = topology["t_junctions"][0]
    assert (junction["wall_id"], junction["end"], junction["host_wall_id"]) == (
        "partition", "start", "host")
    assert junction["distance_m"] == pytest.approx(.08)
    assert junction["host_offset_m"] == pytest.approx(2)
    assert junction["host_length_m"] == pytest.approx(4)
    assert junction["angle_deg"] == pytest.approx(90)


def test_both_ends_near_one_host_are_rejected_instead_of_collapsing_wall():
    host = Wall("host", "s", (-1, 0), (1, 0), 0, 3, .2)
    crossing = Wall("crossing", "s", (0, -.05), (0, .05), 0, 3, .2)
    topology = snap_wall_topology([host, crossing], corner_tolerance_m=.02,
                                  t_tolerance_m=.1, t_minimum_angle_deg=25)
    assert crossing.start == (0, -.05) and crossing.end == (0, .05)
    assert topology["t_junctions"] == []
    assert topology["rejected"] == [{"kind": "both_ends_near_same_host",
                                      "wall_id": "crossing", "host_wall_id": "host"}]


def test_connectivity_report_distinguishes_small_gaps_from_open_ends():
    walls = [Wall("host", "s", (0, 0), (4, 0), 0, 3, .2),
             Wall("near", "s", (2, .03), (2, 2), 0, 3, .2),
             Wall("far", "s", (8, 1), (8, 2), 0, 3, .2)]
    report = wall_connectivity_report(walls, {"endpoint_relations": []}, gap_tolerance_m=.05)
    statuses = {(item["wall_id"], item["end"]): item["status"] for item in report["endpoints"]}
    assert statuses[("near", "start")] == "unresolved_gap"
    assert statuses[("near", "end")] == "open_or_missing"
    assert report["counts"]["unresolved_gap"] == 1
