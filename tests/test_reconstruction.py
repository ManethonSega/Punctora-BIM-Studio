from dataclasses import replace
import math
import numpy as np
import pytest
from shapely.geometry import Polygon

from punctora_core.cloud_io import CloudData
from punctora_core.fixtures import demo_cloud, room_cloud
from punctora_core.reconstruction import ReconstructionSettings, reconstruct, spaces_for_storey


def test_one_floor_detects_walls_slabs_and_two_rooms():
    model = reconstruct(demo_cloud())
    assert len(model.storeys) == 1
    assert len(model.walls) == 5
    assert len(model.slabs) == 2
    assert len(model.spaces) == 2
    assert sorted(Polygon(s.footprint).area for s in model.spaces) == pytest.approx([11.6, 11.6], abs=0.01)
    paired = [w for w in model.walls if w.classification == "paired_faces"]
    assert len(paired) == 1
    assert paired[0].thickness == pytest.approx(0.2, abs=0.001)
    assert paired[0].provenance["thickness"] == "measured"
    assert max(w.fit_rmse_m for w in model.walls) < 1e-6


def test_two_floors_do_not_leak_rooms_from_previous_floor():
    model = reconstruct(demo_cloud(two_storeys=True))
    assert len(model.storeys) == 2
    assert len(model.slabs) == 3
    assert [s.elevation for s in model.storeys] == pytest.approx([0, 3.2])
    first_rooms = [s for s in model.spaces if s.storey_id == "storey-1"]
    second_rooms = [s for s in model.spaces if s.storey_id == "storey-2"]
    assert len(first_rooms) == 2
    assert len(second_rooms) == 1
    assert all(min(x for x, y in s.footprint) >= 10 for s in second_rooms)
    # Even an accidentally accumulated wall list is filtered in the helper.
    fresh = spaces_for_storey(model.storeys[1], model.walls)
    assert len(fresh) == 1
    assert Polygon(fresh[0].footprint).area == pytest.approx(12.0, abs=0.01)


def test_configured_exterior_thickness_is_used_and_marked_as_assumed():
    settings = ReconstructionSettings(exterior_wall_thickness_m=0.42)
    model = reconstruct(demo_cloud(), settings)
    exterior = [w for w in model.walls if w.classification == "exterior_candidate"]
    assert len(exterior) == 4
    assert all(w.thickness == 0.42 and w.provenance["thickness"] == "inferred" for w in exterior)
    assert all(w.provenance["material"] == "unknown" and w.provenance["load_bearing"] == "unknown" for w in model.walls)
    assert model.slabs[-1].kind == "NOTDEFINED"  # A scanned ceiling does not establish a roof.


def test_slab_between_two_observed_faces_has_measured_thickness():
    model = reconstruct(demo_cloud(two_storeys=True))
    intermediate = model.slabs[1]
    assert intermediate.base == pytest.approx(3.0)
    assert intermediate.thickness == pytest.approx(0.2)
    assert intermediate.provenance["thickness"] == "measured"


def test_rotated_floor_reconstructs_in_scan_coordinates():
    cloud = room_cloud(partition=False)
    angle = math.radians(27)
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    cloud.points[:, :2] = cloud.points[:, :2] @ rotation.T + [20, -7]
    model = reconstruct(cloud)
    assert len(model.walls) == 4
    assert len(model.spaces) == 1
    assert Polygon(model.spaces[0].footprint).area == pytest.approx(24.0, abs=0.1)


def test_explicit_floor_bounds_keep_user_supplied_provenance():
    automatic = reconstruct(demo_cloud())
    explicit = [replace(automatic.storeys[0], provenance={"elevation": "user_supplied", "ceiling": "user_supplied", "footprint": "user_supplied"})]
    model = reconstruct(demo_cloud(), storeys=explicit)
    assert all(w.provenance["height"] == "user_supplied" for w in model.walls)


def test_empty_wall_section_reports_failure_instead_of_crashing():
    cloud = demo_cloud()
    cloud = CloudData(cloud.points[np.isin(cloud.points[:, 2], [0.0, 3.0])])
    model = reconstruct(cloud)
    assert not model.walls
    assert any("no supported wall" in warning for warning in model.warnings)


@pytest.mark.parametrize("field,value", [("grid_size_m", 0), ("grid_size_m", float("nan")),
                                          ("exterior_wall_thickness_m", 0.7), ("level_density_fraction", 1.1)])
def test_invalid_settings_rejected(field, value):
    with pytest.raises(ValueError):
        reconstruct(demo_cloud(), replace(ReconstructionSettings(), **{field: value}))


def test_huge_contour_extent_is_rejected_before_allocating_grid():
    cloud = demo_cloud()
    cloud.points[cloud.points[:, 0] == 6, 0] = 1e8
    with pytest.raises(ValueError, match="contour-grid"):
        reconstruct(cloud)
