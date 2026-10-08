from types import SimpleNamespace
import numpy as np
import pytest

from punctora_core.cloud_io import CloudData, e57_data_to_xyz, read_xyz, write_xyz


def test_repeated_decoded_e57_conversion_replaces_instead_of_appending(tmp_path):
    points = np.array([[0.1234567890123456, 2, 3], [4, 5, 6], [7, 8, 9]])
    data = SimpleNamespace(points=points, color=np.array([[1, 2, 3]]*3), intensity=np.arange(3).reshape(-1, 1))
    path = tmp_path/"cloud.xyz"
    e57_data_to_xyz(data, path, chunk_size=2)
    first = path.read_bytes()
    e57_data_to_xyz(data, path, chunk_size=1)
    assert path.read_bytes() == first
    result = read_xyz(path)
    np.testing.assert_array_equal(result.points, points)
    np.testing.assert_array_equal(result.colors, data.color)
    np.testing.assert_array_equal(result.intensity, data.intensity)


@pytest.mark.parametrize("header", ["", "X Y Z\n", "//X Y Z\n"])
def test_subsampling_keeps_first_numeric_point_with_or_without_header(tmp_path, header):
    path = tmp_path/"cloud.xyz"
    path.write_text(header + "\n".join(f"{i} {i+1} {i+2}" for i in range(7)))
    np.testing.assert_array_equal(read_xyz(path, stride=3).points[:, 0], [0, 3, 6])


def test_decoded_cloud_without_optional_channels_is_supported(tmp_path):
    path = tmp_path/"cloud.xyz"
    e57_data_to_xyz(SimpleNamespace(points=np.array([[1, 2, 3]])), path)
    assert read_xyz(path).colors is None


def test_intensity_without_color_is_preserved(tmp_path):
    path = tmp_path/"cloud.xyz"
    e57_data_to_xyz(SimpleNamespace(points=np.array([[1, 2, 3]]), intensity=np.array([[0.75]])), path)
    result = read_xyz(path)
    assert result.colors is None
    assert result.intensity[0, 0] == 0.75


def test_atomic_writer_preserves_existing_file_on_failure(tmp_path, monkeypatch):
    path = tmp_path/"cloud.xyz"
    path.write_text("previous content")
    def fail(*args, **kwargs):
        raise OSError("simulated write failure")
    monkeypatch.setattr(np, "savetxt", fail)
    with pytest.raises(OSError):
        write_xyz(CloudData(np.array([[1, 2, 3]])), path)
    assert path.read_text() == "previous content"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("stride", [0, -1, 1.5, True])
def test_invalid_subsampling_rejected(tmp_path, stride):
    with pytest.raises(ValueError):
        read_xyz(tmp_path/"irrelevant.xyz", stride)


def test_invalid_skipped_row_is_not_hidden_by_subsampling(tmp_path):
    path = tmp_path/"cloud.xyz"
    path.write_text("0 0 0\n1 nan 2\n3 4 5\n")
    with pytest.raises(ValueError, match="Nonfinite"):
        read_xyz(path, stride=2)


def test_optional_validity_masks_and_scan_membership_are_checked():
    points = np.array([[0, 0, 0], [1, 1, 1]], dtype=float)
    cloud = CloudData(points, colors=np.zeros((2, 3)), color_valid=[True, False], scan_index=[0, 1])
    np.testing.assert_array_equal(cloud.color_valid, [True, False])
    with pytest.raises(ValueError, match="scan_index"):
        CloudData(points, scan_index=[0])
