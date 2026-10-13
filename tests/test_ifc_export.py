import numpy as np
import pytest
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.shape

from punctora_core.fixtures import demo_cloud
from punctora_core.ifc_export import create_ifc, validate_ifc, write_ifc
from punctora_core.model import (BuildingModel, Landing, Opening, Slab, SlabOpening, Space,
                                 Stair, Storey, Wall)
from punctora_core.reconstruction import reconstruct


def shape(product):
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    return ifcopenshell.geom.create_shape(settings, product)


def bounds(product):
    tessellation = shape(product)  # Retain native shape ownership while reading geometry.
    vertices = np.asarray(tessellation.geometry.verts).reshape(-1, 3)
    return vertices.min(axis=0), vertices.max(axis=0)


def opening_model():
    model = BuildingModel("Opening regression", [Storey("upper", "Upper floor", 3.2, 6.2, [(0, 0), (10, 0), (10, 10), (0, 10)])])
    model.walls = [Wall("host", "upper", (1, 2), (1, 8), 3.2, 3, 0.3,
                        provenance={"thickness": "user_supplied", "material": "unknown", "load_bearing": "unknown"})]
    model.openings = [Opening("door", "host", "door", 0.5, 0.0, 0.9, 2.1, {"dimensions": "user_supplied"}),
                      Opening("window", "host", "window", 2.5, 1.0, 1.2, 1.1, {"dimensions": "user_supplied"})]
    model.spaces = [Space("space", "upper", [(1.2, 2), (5, 2), (5, 8), (1.2, 8)], 3.2, 3,
                          {"footprint": "user_supplied"})]
    return model


def test_roundtrip_ifc_has_valid_rules_geometry_and_floor_placements(tmp_path):
    model = reconstruct(demo_cloud(two_storeys=True))
    report = write_ifc(model, tmp_path/"model.ifc")
    assert report["valid"] and not report["express_findings"] and not report["geometry_errors"]
    file = ifcopenshell.open(tmp_path/"model.ifc")
    assert len(file.by_type("IfcBuildingStorey")) == 2
    for space in file.by_type("IfcSpace"):
        assert space.Decomposes[0].RelatingObject.is_a("IfcBuildingStorey")
        assert not any(space in relation.RelatedElements for relation in file.by_type("IfcRelContainedInSpatialStructure"))
    upper_walls = [wall for wall in file.by_type("IfcWall") if wall.ContainedInStructure[0].RelatingStructure.Elevation > 0]
    assert upper_walls
    for wall in upper_walls:
        low, high = bounds(wall)
        assert low[2] == pytest.approx(3.2)
        assert high[2] == pytest.approx(6.2)
    assert not file.by_type("IfcMaterial")
    for wall in file.by_type("IfcWall"):
        properties = ifcopenshell.util.element.get_psets(wall)["Punctora_Reconstruction"]
        assert properties["material_provenance"] == "unknown"
        assert properties["load_bearing_provenance"] == "unknown"


def test_door_window_voids_types_positions_and_cut_volume(tmp_path):
    model = opening_model()
    report = write_ifc(model, tmp_path/"openings.ifc")
    assert report["valid"]
    file = ifcopenshell.open(tmp_path/"openings.ifc")
    host = file.by_type("IfcWall")[0]
    assert len(host.HasOpenings) == 2
    assert len(file.by_type("IfcRelFillsElement")) == 2
    window_type = file.by_type("IfcWindowType")[0]
    assert window_type.PartitioningType == "NOTDEFINED"
    assert file.by_type("IfcDoorType")[0].OperationType == "NOTDEFINED"
    window = file.by_type("IfcWindow")[0]
    low, high = bounds(window)
    assert low[1:] == pytest.approx([4.5, 4.2])
    assert high[1:] == pytest.approx([5.7, 5.3])
    expected_volume = 6*3*0.3 - (0.9*2.1+1.2*1.1)*0.3
    tessellation = shape(host)
    assert ifcopenshell.util.shape.get_volume(tessellation.geometry) == pytest.approx(expected_volume, abs=1e-6)


def test_uncertain_opening_cuts_wall_without_inventing_a_door_or_window(tmp_path):
    model = opening_model()
    model.openings.append(Opening("uncertain", "host", "unknown", 4.4, .3, .8, 1.5,
                                  {"dimensions": "measured", "kind": "inferred"}))
    report = write_ifc(model, tmp_path/"uncertain-opening.ifc")
    assert report["valid"]
    file = ifcopenshell.open(tmp_path/"uncertain-opening.ifc")
    assert len(file.by_type("IfcOpeningElement")) == 3
    assert len(file.by_type("IfcRelFillsElement")) == 2


def test_multiflight_stair_and_landing_export_as_one_ifc_assembly(tmp_path):
    storey = Storey("lower", "Lower", 0, 3.2, [(-1, -1), (5, -1), (5, 5), (-1, 5)])
    first = Stair("f1", "lower", (0, 0), (2.24, 0), 0, .9, .175, .28, 8,
                  system_id="system", flight_index=1)
    second = Stair("f2", "lower", (2.24, 0), (2.24, 2.8), 1.4, .9, .18, .28, 10,
                   system_id="system", flight_index=2)
    landing = Landing("landing", "lower", [(1.79, -.45), (2.69, -.45),
                      (2.69, .45), (1.79, .45)], 1.34, .12, "system", ["f1", "f2"])
    model = BuildingModel("Stair system", [storey], stairs=[first, second], landings=[landing])
    report = write_ifc(model, tmp_path/"stair-system.ifc")
    assert report["valid"]
    file = ifcopenshell.open(tmp_path/"stair-system.ifc")
    assert len(file.by_type("IfcStair")) == 1
    assert len(file.by_type("IfcStairFlight")) == 2
    ifc_landing = next(item for item in file.by_type("IfcSlab") if item.PredefinedType == "LANDING")
    assert ifc_landing.Decomposes[0].RelatingObject.is_a("IfcStair")


def test_reviewed_stair_slab_opening_cuts_its_host_floor(tmp_path):
    lower = Storey("lower", "Lower", 0, 3, [(0, 0), (10, 0), (10, 10), (0, 10)])
    upper = Storey("upper", "Upper", 3.2, 6.2, [(0, 0), (10, 0), (10, 10), (0, 10)])
    slab = Slab("upper-floor", "upper", upper.footprint, 3.0, .2, "FLOOR",
                {"thickness": "measured"})
    stair = Stair("stair", "lower", (2, 2), (6, 2), 0, 1, .2, .25, 16,
                  provenance={"treads": "measured"})
    opening = SlabOpening("stair-opening", slab.id, (1.9, 2), (6.1, 2), 1.2,
                          stair.id, {"footprint": "inferred"}, "reviewed", .8,
                          {"scope": "test candidate"}, ifc_cut_approved=True)
    model = BuildingModel("Slab void", [lower, upper], slabs=[slab], stairs=[stair],
                          slab_openings=[opening])
    report = write_ifc(model, tmp_path/"slab-opening.ifc")
    assert report["valid"]
    file = ifcopenshell.open(tmp_path/"slab-opening.ifc")
    host = file.by_type("IfcSlab")[0]
    assert len(host.HasOpenings) == 1
    assert host.HasOpenings[0].RelatedOpeningElement.Name == opening.id
    expected = 10*10*.2 - 4.2*1.2*.2
    assert ifcopenshell.util.shape.get_volume(shape(host).geometry) == pytest.approx(expected, abs=1e-5)
    properties = ifcopenshell.util.element.get_psets(host.HasOpenings[0].RelatedOpeningElement)
    assert properties["Punctora_Reconstruction"]["ReviewState"] == "reviewed"


def test_validation_detects_original_window_type_defect():
    file = create_ifc(opening_model())
    entity = file.by_type("IfcWindowType")[0]
    text = file.to_string()
    line = next(line for line in text.splitlines() if line.startswith(f"#{entity.id()}="))
    broken = line.replace(",.NOTDEFINED.,.NOTDEFINED.,", ",.NOTDEFINED.,$,")
    assert broken != line
    file = ifcopenshell.file.from_string(text.replace(line, broken))
    report = validate_ifc(file)
    assert not report["valid"]
    assert report["express_findings"]


def test_validation_detects_original_space_containment_defect():
    file = create_ifc(opening_model())
    file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                       RelatedElements=[file.by_type("IfcSpace")[0]],
                       RelatingStructure=file.by_type("IfcBuildingStorey")[0])
    assert not validate_ifc(file)["valid"]


def test_stable_product_ids_across_reconstruction_exports():
    model = reconstruct(demo_cloud())
    a, b = create_ifc(model), create_ifc(model)
    assert [p.GlobalId for p in a.by_type("IfcProduct")] == [p.GlobalId for p in b.by_type("IfcProduct")]


def test_element_id_matching_spatial_root_does_not_duplicate_guid():
    model = opening_model()
    model.walls[0].id = "project"
    for opening in model.openings:
        opening.host_wall_id = "project"
    file = create_ifc(model)
    identifiers = [entity.GlobalId for entity in file.by_type("IfcRoot")]
    assert len(identifiers) == len(set(identifiers))
    assert validate_ifc(file)["valid"]


@pytest.mark.parametrize("change", ["outside_opening", "zero_thickness", "duplicate_id", "self_crossing_polygon"])
def test_invalid_input_preserves_previous_ifc(tmp_path, change):
    model = opening_model()
    if change == "outside_opening":
        model.openings[0].offset = 5.9
    elif change == "zero_thickness":
        model.walls[0].thickness = 0
    elif change == "duplicate_id":
        model.openings[0].id = "host"
    else:
        model.spaces[0].footprint = [(0, 0), (1, 1), (0, 1), (1, 0)]
    path = tmp_path/"model.ifc"
    path.write_text("previous IFC")
    with pytest.raises(ValueError):
        write_ifc(model, path)
    assert path.read_text() == "previous IFC"
