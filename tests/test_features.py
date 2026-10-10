import numpy as np
import pytest
import ifcopenshell
import ifcopenshell.util.element

from punctora_core.cloud_io import CloudData
from punctora_core.features import detect_openings, detect_stairs, derive_stair_slab_openings
from punctora_core.ifc_export import write_ifc
from punctora_core.model import BuildingModel, Landing, Slab, Stair, Storey, Wall
from punctora_core.projects import edit_model
from punctora_core import projects
from punctora_core.reconstruction import ReconstructionSettings, reconstruct


def level():
    return Storey("s", "Ground", 0, 3, [(-1, -1), (6, -1), (6, 4), (-1, 4)])


def wall_cloud(gaps=True):
    x, z = np.meshgrid(np.arange(0, 5, .025), np.arange(0, 3, .025))
    points = np.column_stack([x.ravel(), np.zeros(x.size), z.ravel()])
    if gaps:
        door = (points[:, 0] >= .8) & (points[:, 0] < 1.7) & (points[:, 2] < 2.1)
        window = (points[:, 0] >= 2.8) & (points[:, 0] < 4) & (points[:, 2] >= 1) & (points[:, 2] < 2.1)
        points = points[~(door | window)]
    return CloudData(points)


def recessed_filling_cloud():
    x, z = np.meshgrid(np.arange(0, 5, .025), np.arange(0, 3, .025))
    points = np.column_stack([x.ravel(), np.full(x.size, .1), z.ravel()])
    door = (points[:, 0] >= .8) & (points[:, 0] < 1.7) & (points[:, 2] < 2.1)
    window = ((points[:, 0] >= 2.8) & (points[:, 0] < 4)
              & (points[:, 2] >= 1) & (points[:, 2] < 2.1))
    points[door | window, 1] = .03
    return CloudData(points)


def stairs_cloud(angle=0, shift=(0, 0)):
    treads = []
    for i in range(8):
        x, y = np.meshgrid(np.arange(i*.28, (i+1)*.28, .02), np.arange(0, 1.1, .02))
        treads.append(np.column_stack([x.ravel(), y.ravel(), np.full(x.size, (i+1)*.17)]))
    points = np.vstack(treads)
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    points[:, :2] = points[:, :2]@rotation.T+shift
    return CloudData(points)


def test_openings_require_bounded_edge_evidence_and_classify_height():
    wall = Wall("w", "s", (0, 0), (5, 0), 0, 3, .2)
    openings = detect_openings(wall_cloud(), [wall], ReconstructionSettings())
    assert len(openings) == 2
    door, window = sorted(openings, key=lambda o: o.offset)
    assert door.kind == "door" and door.sill == 0
    assert door.width == pytest.approx(.9, abs=.06)
    assert window.kind == "window" and window.sill == pytest.approx(1, abs=.06)
    assert all(min(o.evidence["edge_support_fractions"]) >= .65 for o in openings)
    assert not detect_openings(wall_cloud(False), [wall], ReconstructionSettings())
    sparse = wall_cloud(); sparse.points = sparse.points[::40]
    assert not detect_openings(sparse, [wall], ReconstructionSettings())


def test_recessed_closed_door_and_glazing_planes_are_detected_without_empty_gaps():
    wall = Wall("w", "s", (0, 0), (5, 0), 0, 3, .2)
    openings = detect_openings(recessed_filling_cloud(), [wall], ReconstructionSettings())
    assert [opening.kind for opening in openings] == ["door", "window"]
    assert [opening.offset for opening in openings] == pytest.approx([.8, 2.8])
    assert all(opening.evidence["method"] == "recessed_filling_plane" for opening in openings)
    assert all(opening.evidence["interior_depth_contrast_m"] > .06 for opening in openings)


@pytest.mark.parametrize("angle", [0, .63, 1.57])
def test_straight_stair_detection_retains_rotation_and_tread_measurements(angle):
    stairs = detect_stairs(stairs_cloud(angle, (1, 1)), [level()], ReconstructionSettings())
    assert len(stairs) == 1
    stair = stairs[0]
    assert stair.steps == 8
    assert stair.rise == pytest.approx(.17, abs=.01)
    assert stair.going == pytest.approx(.28, abs=.015)
    assert stair.width == pytest.approx(1.1, abs=.12)
    assert len(stair.evidence["tread_support_counts"]) == 8


def test_landing_at_flight_endpoint_is_detected_and_assigned_to_system():
    cloud = stairs_cloud()
    x, y = np.meshgrid(np.arange(2.24, 3.34, .02), np.arange(0, 1.1, .02))
    landing = np.column_stack([x.ravel(), y.ravel(), np.full(x.size, 1.44)])
    cloud.points = np.vstack([cloud.points, landing])
    landings = []
    stairs = detect_stairs(cloud, [level()], ReconstructionSettings(), landing_output=landings)
    assert len(stairs) == len(landings) == 1
    assert stairs[0].system_id == landings[0].system_id
    assert landings[0].connected_stair_ids == [stairs[0].id]
    assert landings[0].evidence["support_points"] > 100


def test_vertical_wall_and_flat_floor_do_not_propose_stairs():
    assert not detect_stairs(wall_cloud(False), [level()], ReconstructionSettings())
    x, y = np.meshgrid(np.arange(0, 3, .04), np.arange(0, 3, .04))
    cloud = CloudData(np.column_stack([x.ravel(), y.ravel(), np.full(x.size, .5)]))
    assert not detect_stairs(cloud, [level()], ReconstructionSettings())


def test_feature_roundtrip_review_edit_and_validated_ifc(tmp_path):
    model = BuildingModel("Features", [level()])
    model.walls = [Wall("w", "s", (0, 0), (5, 0), 0, 3, .2)]
    model.openings = detect_openings(wall_cloud(), model.walls, ReconstructionSettings())
    model.stairs = detect_stairs(stairs_cloud(), model.storeys, ReconstructionSettings())
    copy = BuildingModel.from_dict(model.to_dict())
    assert copy.to_dict() == model.to_dict()
    # Use the same project binding enforced by desktop edits.
    state = {"project_id": "test", "model": model.to_dict(), "coordinate_confirmation": {"z_up": True}}
    model.metadata["project_id"] = "test"
    state["model"] = model.to_dict()
    data = edit_model(state, model.to_dict(), model.openings[0].id, {"review_state": "reviewed", "width": .8})
    data = edit_model(state, data, model.stairs[0].id, {"going": .3, "review_state": "reviewed"})
    changed = BuildingModel.from_dict(data)
    assert np.linalg.norm(np.array(changed.stairs[0].end)-changed.stairs[0].start) == pytest.approx(2.4)
    report = write_ifc(changed, tmp_path/"features.ifc")
    assert report["valid"]
    file = ifcopenshell.open(tmp_path/"features.ifc")
    assert len(file.by_type("IfcRelVoidsElement")) == 2
    assert len(file.by_type("IfcRelFillsElement")) == 2
    flight = file.by_type("IfcStairFlight")[0]
    assert flight.NumberOfTreads == 8
    assert flight.Decomposes[0].RelatingObject.is_a("IfcStair")
    assert ifcopenshell.util.element.get_psets(flight)["Punctora_Reconstruction"]["ReviewState"] == "reviewed"


def test_rejected_features_survive_save_but_are_excluded_from_ifc(tmp_path):
    import uuid
    path = tmp_path/"features.punctora"
    state = projects.create_project(path, uuid.uuid4().hex)
    model = BuildingModel("Features", [level()], metadata={"project_id": state["project_id"]})
    model.walls = [Wall("w", "s", (0, 0), (5, 0), 0, 3, .2)]
    model.openings = detect_openings(wall_cloud(), model.walls, ReconstructionSettings())
    model.stairs = detect_stairs(stairs_cloud(), model.storeys, ReconstructionSettings())
    model.openings[0].review_state = "rejected"
    model.stairs[0].review_state = "rejected"
    state = projects.save_project(path, {"expected_revision": state["revision"], "model": model.to_dict()})
    reopened = projects.load_project(path)
    assert reopened["model"]["stairs"][0]["review_state"] == "rejected"
    target = tmp_path/"filtered.ifc"
    projects.export_project(path, {"expected_revision": state["revision"], "model": state["model"], "output": str(target)})
    file = ifcopenshell.open(str(target))
    assert len(file.by_type("IfcOpeningElement")) == 1
    assert not file.by_type("IfcStairFlight")


def test_old_schema_two_and_invalid_new_feature_values():
    model = BuildingModel("Old", [level()])
    data = model.to_dict(); data.pop("stairs"); data.pop("landings"); data.pop("slab_openings")
    old = BuildingModel.from_dict(data)
    assert old.stairs == [] and old.landings == [] and old.slab_openings == []
    model.stairs = detect_stairs(stairs_cloud(), model.storeys, ReconstructionSettings())
    data = model.to_dict(); data["stairs"][0]["steps"] = 8.5
    with pytest.raises(ValueError, match="steps"):
        BuildingModel.from_dict(data)
    data = model.to_dict(); end = data["stairs"][0]["end"]; data["stairs"][0]["end"] = [end[0]+1, end[1]]
    with pytest.raises(ValueError, match="run"):
        BuildingModel.from_dict(data)


def test_reconstruction_connects_both_detectors_and_can_disable_them():
    x, y = np.meshgrid(np.arange(0, 5, .05), np.arange(0, 3, .05))
    horizontal = np.column_stack([x.ravel(), y.ravel(), np.zeros(x.size)])
    ceiling = horizontal.copy(); ceiling[:, 2] = 3
    cloud = CloudData(np.vstack([wall_cloud().points, horizontal, ceiling, stairs_cloud(0, (.5, 1.2)).points]))
    model = reconstruct(cloud, storeys=[level()])
    assert model.openings and model.stairs
    disabled = reconstruct(cloud, ReconstructionSettings(detect_openings_enabled=False, detect_stairs_enabled=False), storeys=[level()])
    assert not disabled.openings and not disabled.stairs


def stair_and_upper_slab():
    stair = Stair("stair", "lower", (2, 2), (6, 2), 0, 1, .2, .25, 16,
                  provenance={"treads": "measured"}, confidence=.8)
    slab = Slab("upper-floor", "upper", [(0, 0), (10, 0), (10, 10), (0, 10)],
                3.0, .2, provenance={"thickness": "measured"})
    return stair, slab


def test_stair_slab_opening_is_reviewable_model_geometry_and_roundtrips():
    stair, slab = stair_and_upper_slab()
    openings, diagnostics = derive_stair_slab_openings([stair], [slab])
    assert len(openings) == 1
    opening = openings[0]
    assert opening.host_slab_id == slab.id and opening.source_stair_id == stair.id
    assert opening.start == pytest.approx((3.25, 2))
    assert opening.end == pytest.approx((6, 2))
    assert opening.width == pytest.approx(1.2)
    assert opening.evidence["headroom_m"] == 2
    assert opening.footprint is not None
    assert diagnostics[0]["status"] == "candidate_created"
    model = BuildingModel("Slab opening", [
        Storey("lower", "Lower", 0, 3, [(0, 0), (10, 0), (10, 10), (0, 10)]),
        Storey("upper", "Upper", 3.2, 6.2, [(0, 0), (10, 0), (10, 10), (0, 10)]),
    ], slabs=[slab], stairs=[stair], slab_openings=openings)
    assert BuildingModel.from_dict(model.to_dict()).to_dict() == model.to_dict()


def test_stair_slab_opening_requires_headroom_intersection_and_host_clipping():
    stair, slab = stair_and_upper_slab()
    low_stair = Stair(**{**stair.__dict__, "id": "low", "rise": .05})
    openings, diagnostics = derive_stair_slab_openings([low_stair], [slab])
    assert not openings and diagnostics[0]["status"] == "no_intersected_slab"
    edge_stair = Stair(**{**stair.__dict__, "id": "edge", "start": (7, 9.7), "end": (11, 9.7)})
    openings, diagnostics = derive_stair_slab_openings([edge_stair], [slab])
    assert openings and diagnostics[0]["status"] == "candidate_created"
    assert openings[0].evidence["clipped_to_host"]


def test_multiflight_system_and_landing_produce_polygonal_headroom_void():
    first = Stair("f1", "lower", (0, 0), (2.24, 0), 0, .9, .175, .28, 8,
                  system_id="system", flight_index=1)
    second = Stair("f2", "lower", (2.24, 0), (2.24, 2.8), 1.4, .9, .18, .28, 10,
                   system_id="system", flight_index=2)
    landing = Landing("landing", "lower", [(1.79, -.45), (2.69, -.45),
                      (2.69, .45), (1.79, .45)], 1.34, .12, "system", ["f1", "f2"])
    slab = Slab("upper", "upper", [(-1, -1), (5, -1), (5, 5), (-1, 5)], 3.2, .2)
    openings, diagnostics = derive_stair_slab_openings([first, second], [slab], [landing])
    assert len(openings) == 1 and len(openings[0].footprint) > 4
    assert openings[0].source_system_id == "system"
    assert openings[0].evidence["source_stair_ids"] == ["f1", "f2"]
    assert openings[0].evidence["source_landing_ids"] == ["landing"]
    assert diagnostics[0]["status"] == "candidate_created"


def test_slab_opening_edit_persists_and_rejected_candidate_is_not_exported(tmp_path):
    import uuid
    path = tmp_path/"slab-opening.punctora"
    state = projects.create_project(path, uuid.uuid4().hex)
    stair, slab = stair_and_upper_slab()
    openings, _ = derive_stair_slab_openings([stair], [slab])
    model = BuildingModel("Slab opening", [
        Storey("lower", "Lower", 0, 3, [(0, 0), (10, 0), (10, 10), (0, 10)]),
        Storey("upper", "Upper", 3.2, 6.2, [(0, 0), (10, 0), (10, 10), (0, 10)]),
    ], slabs=[slab], stairs=[stair], slab_openings=openings,
       metadata={"project_id": state["project_id"]})
    draft = edit_model(state, model.to_dict(), openings[0].id,
                       {"width": 1.1, "review_state": "reviewed"})
    state = projects.save_project(path, {"expected_revision": state["revision"], "model": draft})
    reopened = projects.load_project(path)
    assert reopened["model"]["slab_openings"][0]["width"] == pytest.approx(1.1)
    assert reopened["model"]["slab_openings"][0]["review_state"] == "reviewed"
    rejected = edit_model(reopened, reopened["model"], openings[0].id,
                          {"review_state": "rejected"})
    target = tmp_path/"without-slab-opening.ifc"
    report = projects.export_project(path, {"expected_revision": state["revision"],
                                            "model": rejected, "output": str(target)})
    assert report["excluded_slab_openings"] == 1
    assert not ifcopenshell.open(target).by_type("IfcOpeningElement")
