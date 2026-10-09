import numpy as np
import pytest

from punctora_core.cloud_io import CloudData
from punctora_core.cropping import crop_mask, materialize_crop, validate_crop
from punctora_core.projects import close_cloud


def test_polygon_and_height_crop_is_boundary_inclusive():
    points = np.array([[0, 0, 0.5], [1, 1, 1], [2, 1, 1.5],
                       [1, 3, 1], [1, 1, 2]], dtype=float)
    crop = {"polygon": [[0, 0], [2, 0], [2, 2], [0, 2]],
            "z_min": .5, "z_max": 1.5}
    np.testing.assert_array_equal(crop_mask(points, crop), [True, True, True, False, False])


@pytest.mark.parametrize("crop", [
    {"polygon": [[0, 0], [1, 1]], "z_min": None, "z_max": None},
    {"polygon": [[0, 0], [1, 1], [0, 1], [1, 0]], "z_min": None, "z_max": None},
    {"polygon": None, "z_min": 2, "z_max": 1},
    {"polygon": None, "z_min": float("nan"), "z_max": None},
])
def test_invalid_crop_is_rejected(crop):
    with pytest.raises(ValueError, match="Crop"):
        validate_crop(crop)


def test_materialized_crop_preserves_source_rows_and_channels(tmp_path):
    points = np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2], [3, 3, 3]], dtype=float)
    cloud = CloudData(points.copy(), colors=points+10, intensity=np.arange(4),
                      scan_index=np.array([4, 4, 5, 5]), source_record_index=np.arange(20, 24))
    crop = {"polygon": [[.5, .5], [2.5, .5], [2.5, 2.5], [.5, 2.5]],
            "z_min": .5, "z_max": 2.5}
    selected, report = materialize_crop(cloud, crop, tmp_path / "crop", chunk_points=2)
    try:
        np.testing.assert_array_equal(selected.points, points[1:3])
        np.testing.assert_array_equal(selected.colors, points[1:3]+10)
        np.testing.assert_array_equal(selected.working_index, [1, 2])
        np.testing.assert_array_equal(selected.source_record_index, [21, 22])
        assert report == {"active": True, "source_points": 4, "selected_points": 2,
                          "crop": validate_crop(crop)}
        np.testing.assert_array_equal(cloud.points, points)
    finally:
        close_cloud(selected)

