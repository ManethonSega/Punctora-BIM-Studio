import json
from math import sqrt

import ifcopenshell
import numpy as np
import pye57
import pytest

from punctora_core.cli import main
from punctora_core.e57_io import read_e57
from punctora_core.fixtures import demo_cloud


def test_region_e57_export_retains_source_records_after_pose_and_invalid_filtering(tmp_path):
    source = tmp_path/"building.e57"
    _write_building_e57(source)
    original = source.read_bytes()
    settings = tmp_path/"region.json"
    settings.write_text(json.dumps({"surface_method": "region_growing"}))
    output = tmp_path/"result"
    assert main(["convert-e57", str(source), "--settings", str(settings), "--chunk-points", "1000",
                 "--output-dir", str(output)]) == 0
    model = json.loads((output/"elements.json").read_text())
    manifest = json.loads((output/"import-manifest.json").read_text())
    files = manifest["cache"]["files"]
    scans = np.fromfile(output/"working-cache"/files["scan_index"]["path"], dtype=files["scan_index"]["dtype"])
    records = np.fromfile(output/"working-cache"/files["source_record_index"]["path"], dtype=files["source_record_index"]["dtype"])
    assert len(model["walls"]) == 5
    for wall in model["walls"]:
        refs = np.load(output/wall["evidence"]["records"]["path"])
        np.testing.assert_array_equal(refs[:, 1], scans[refs[:, 0]])
        np.testing.assert_array_equal(refs[:, 2], records[refs[:, 0]])
    for patch in model["metadata"]["surface_proposals"]:
        assert "representative_cloud_indices" not in patch
        assert len(np.load(output/patch["representative_cloud_records"]["path"])) == patch["sample_count"]
    assert json.loads((output/"validation.json").read_text())["valid"]
    assert source.read_bytes() == original


def _write_small_e57(path):
    expected = np.array([
        [4_000_000.0, 5_000_000.0, 100.0],
        [4_000_001.0, 5_000_002.0, 103.0],
        [4_000_002.0, 5_000_004.0, 101.0],
    ])
    with pye57.E57(str(path), "w") as target:
        translation = np.array([4_000_000.0, 5_000_000.0, 100.0])
        local = expected[:2] - translation
        target.write_scan_raw({
            "cartesianX": local[:, 0], "cartesianY": local[:, 1], "cartesianZ": local[:, 2],
            "intensity": np.array([0.2, 0.3]),
            "colorRed": np.array([1, 2], dtype=np.uint8),
            "colorGreen": np.array([3, 4], dtype=np.uint8),
            "colorBlue": np.array([5, 6], dtype=np.uint8),
        }, name="coloured", translation=translation)
        translation = np.array([4_000_002.0, 5_000_004.0, 101.0])
        local = np.vstack([expected[2] - translation, [9.0, 9.0, 9.0]])
        target.write_scan_raw({
            "cartesianX": local[:, 0], "cartesianY": local[:, 1], "cartesianZ": local[:, 2],
            "cartesianInvalidState": np.array([0, 1], dtype=np.int8),
        }, name="invalid-point", translation=translation)
    return expected


def _write_building_e57(path):
    points = demo_cloud().points + np.array([4_000_000.0, 5_000_000.0, 100.0])
    split = len(points) // 2
    rotation = np.array([sqrt(0.5), 0.0, 0.0, sqrt(0.5)])
    rotation_matrix = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    with pye57.E57(str(path), "w") as target:
        first_translation = np.array([4_000_000.0, 5_000_000.0, 100.0])
        first = points[:split] - first_translation
        target.write_scan_raw({"cartesianX": first[:, 0], "cartesianY": first[:, 1],
                               "cartesianZ": first[:, 2]}, name="first", translation=first_translation)
        second_translation = np.array([4_000_006.0, 5_000_004.0, 100.0])
        second = (points[split:] - second_translation) @ rotation_matrix
        second = np.vstack([second, [20.0, 20.0, 20.0]])
        target.write_scan_raw({"cartesianX": second[:, 0], "cartesianY": second[:, 1],
                               "cartesianZ": second[:, 2],
                               "cartesianInvalidState": np.r_[np.zeros(len(second) - 1, dtype=np.int8), 1]},
                              name="rotated", rotation=rotation, translation=second_translation)


def test_e57_import_applies_each_pose_once_and_keeps_reversible_mapping(tmp_path):
    source = tmp_path / "survey.e57"
    expected = _write_small_e57(source)
    imported = read_e57(source, tmp_path / "cache", chunk_points=1)
    origin = np.asarray(imported.manifest["coordinate_mapping"]["working_to_source_translation_m"])
    np.testing.assert_allclose(imported.cloud.points + origin, expected, atol=1e-8)
    np.testing.assert_array_equal(imported.cloud.scan_index, [0, 0, 1])
    np.testing.assert_array_equal(imported.cloud.color_valid, [True, True, False])
    np.testing.assert_array_equal(imported.cloud.intensity_valid, [True, True, False])
    assert imported.manifest["raw_point_count"] == 4
    assert imported.manifest["valid_point_count"] == 3
    assert imported.manifest["scans"][1]["invalid_coordinate_count"] == 1
    assert imported.manifest["coordinate_metadata_status"] == "absent"
    assert all((tmp_path / "cache" / item["path"]).is_file()
               for item in imported.manifest["cache"]["files"].values())


def _write_raw_fixture(path, data, quaternion=None):
    """Write double precision fields/flags not supported by pye57's writer."""
    lib = pye57.libe57
    class FixtureE57(pye57.E57):
        def write_default_header(self):
            self.image_file.extensionsAdd("", lib.E57_V1_0_URI)
            self.root.set("formatName", lib.StringNode(self.image_file, "ASTM E57 3D Imaging Data File"))
            self.root.set("guid", lib.StringNode(self.image_file, "fixture-root"))
            self.root.set("versionMajor", lib.IntegerNode(self.image_file, 1))
            self.root.set("versionMinor", lib.IntegerNode(self.image_file, 0))
            self.root.set("coordinateMetadata", lib.StringNode(self.image_file, 'LOCAL_CS["test survey"]'))
            self.root.set("data3D", lib.VectorNode(self.image_file, True))
            self.root.set("images2D", lib.VectorNode(self.image_file, True))
    with FixtureE57(str(path), "w") as target:
        scan = lib.StructureNode(target.image_file)
        scan.set("guid", lib.StringNode(target.image_file, "generated-fixture"))
        scan.set("sensorVendor", lib.StringNode(target.image_file, "Generated test sensor"))
        if quaternion is not None:
            pose, rotation = lib.StructureNode(target.image_file), lib.StructureNode(target.image_file)
            for name, value in zip(["w", "x", "y", "z"], quaternion):
                rotation.set(name, lib.FloatNode(target.image_file, float(value)))
            pose.set("rotation", rotation)
            scan.set("pose", pose)
        prototype = lib.StructureNode(target.image_file)
        arrays, buffers = {}, lib.VectorSourceDestBuffer()
        for name, values in data.items():
            is_flag = name.endswith("InvalidState") or name.startswith("is")
            values = np.asarray(values, dtype=np.int8 if is_flag else np.float64)
            arrays[name] = values
            node = (lib.IntegerNode(target.image_file, 0, 0, 2) if is_flag else
                    lib.FloatNode(target.image_file, float(values[0]), lib.E57_DOUBLE))
            prototype.set(name, node)
            buffers.append(lib.SourceDestBuffer(target.image_file, name, values, len(values), True, True))
        points = lib.CompressedVectorNode(target.image_file, prototype, lib.VectorNode(target.image_file, True))
        scan.set("points", points)
        target.data3d.append(scan)
        writer = points.writer(buffers)
        writer.write(len(next(iter(arrays.values()))))
        writer.close()


def test_spherical_e57_import_filters_invalid_directions_and_preserves_metadata(tmp_path):
    data = {
        "sphericalRange": [2., 100., 3.], "sphericalAzimuth": [0., 0., np.pi / 2],
        "sphericalElevation": [0., 0., np.pi / 2], "sphericalInvalidState": [0, 1, 0],
    }
    source = tmp_path / "spherical.e57"
    _write_raw_fixture(source, data)
    result = read_e57(source, tmp_path / "cache", chunk_points=1)
    origin = result.manifest["coordinate_mapping"]["working_to_source_translation_m"]
    np.testing.assert_allclose(result.cloud.points + origin, [[2, 0, 0], [0, 0, 3]], atol=1e-12)
    np.testing.assert_array_equal(result.cloud.source_record_index, [0, 2])
    assert not result.manifest["scans"][0]["has_pose"]
    assert result.manifest["coordinate_metadata_status"] == "present_unverified"
    assert result.manifest["scans"][0]["metadata"]["sensorVendor"] == "Generated test sensor"


def test_e57_retains_double_intensity_large_rgb_and_flagged_channel_values(tmp_path):
    source = tmp_path / "attributes.e57"
    data = {"cartesianX": [0., 1.], "cartesianY": [0., 2.], "cartesianZ": [0., 3.],
            "intensity": [0.123456789012345, 0.987654321098765], "isIntensityInvalid": [0, 1],
            "colorRed": [65535., 32000.], "colorGreen": [10., 20.], "colorBlue": [30., 40.],
            "isColorInvalid": [1, 0]}
    _write_raw_fixture(source, data)
    result = read_e57(source, tmp_path / "cache", chunk_points=1)
    np.testing.assert_array_equal(result.cloud.intensity[:, 0], data["intensity"])
    np.testing.assert_array_equal(result.cloud.colors[:, 0], data["colorRed"])
    np.testing.assert_array_equal(result.cloud.color_valid, [False, True])
    np.testing.assert_array_equal(result.cloud.intensity_valid, [True, False])


def test_repeat_import_keeps_live_previous_cache_and_does_not_duplicate_points(tmp_path):
    source = tmp_path / "survey.e57"
    _write_small_e57(source)
    first = read_e57(source, tmp_path / "cache", chunk_points=1)
    original_points = first.cloud.points.copy()
    first_paths = [tmp_path / "cache" / item["path"] for item in first.manifest["cache"]["files"].values()]
    second = read_e57(source, tmp_path / "cache", chunk_points=2)
    assert second.manifest["valid_point_count"] == first.manifest["valid_point_count"] == 3
    np.testing.assert_array_equal(first.cloud.points, original_points)
    np.testing.assert_array_equal(second.cloud.points, original_points)
    assert all(p.exists() for p in first_paths)


@pytest.mark.parametrize("bad_pose", [[0., 0., 0., 0.], [2., 0., 0., 0.]])
def test_invalid_pose_rejected_and_no_incomplete_cache_left(tmp_path, bad_pose):
    source = tmp_path / "bad-pose.e57"
    _write_raw_fixture(source, {"cartesianX": [0.], "cartesianY": [0.], "cartesianZ": [0.]}, bad_pose)
    with pytest.raises(ValueError, match="unit length"):
        read_e57(source, tmp_path / "cache", chunk_points=1)
    assert list((tmp_path / "cache").iterdir()) == []


def test_failed_decode_preserves_previous_cache_and_cleans_partial_outputs(tmp_path, monkeypatch):
    from punctora_core import e57_io
    source = tmp_path / "survey.e57"
    _write_small_e57(source)
    first = read_e57(source, tmp_path / "cache", chunk_points=1)
    snapshot = {p.relative_to(tmp_path / "cache"): p.read_bytes()
                for p in (tmp_path / "cache").rglob("*") if p.is_file()}
    def fail(*args, **kwargs):
        raise RuntimeError("simulated corrupt compressed data")
    monkeypatch.setattr(e57_io, "_cartesian", fail)
    with pytest.raises(ValueError, match="corrupt compressed data"):
        read_e57(source, tmp_path / "cache", chunk_points=1)
    assert snapshot == {p.relative_to(tmp_path / "cache"): p.read_bytes()
                        for p in (tmp_path / "cache").rglob("*") if p.is_file()}
    assert len(first.cloud.points) == 3
    assert not list((tmp_path / "cache").glob(".e57-*"))


def test_all_invalid_e57_rejected_and_staging_cleaned(tmp_path):
    source = tmp_path / "invalid.e57"
    _write_raw_fixture(source, {"cartesianX": [0.], "cartesianY": [0.], "cartesianZ": [0.],
                                "cartesianInvalidState": [1]})
    with pytest.raises(ValueError, match="no valid"):
        read_e57(source, tmp_path / "cache", chunk_points=1)
    assert list((tmp_path / "cache").iterdir()) == []


def test_import_only_cli_accepts_nonbuilding_cloud_and_reports_missing_pose(tmp_path, capsys):
    source = tmp_path / "single.e57"
    _write_raw_fixture(source, {"cartesianX": [1.], "cartesianY": [2.], "cartesianZ": [3.]})
    output = tmp_path / "result"
    assert main(["import-e57", str(source), "--output-dir", str(output)]) == 0
    summary = json.loads(capsys.readouterr().out)
    manifest = json.loads((output / "import-manifest.json").read_text())
    assert summary["source_points"] == 1
    assert any("pose absent" in warning for warning in summary["warnings"])
    assert manifest["coordinate_metadata_status"] == "present_unverified"
    assert not (output / "model.ifc").exists()


def test_e57_cli_reconstructs_large_offset_rotated_scans_and_georeferences_ifc(tmp_path, capsys):
    source = tmp_path / "building.e57"
    _write_building_e57(source)
    original = source.read_bytes()
    output = tmp_path / "result"
    assert main(["convert-e57", str(source), "--chunk-points", "257", "--output-dir", str(output)]) == 0
    summary = json.loads(capsys.readouterr().out)
    manifest = json.loads((output / "import-manifest.json").read_text())
    elements = json.loads((output / "elements.json").read_text())
    assert summary["ifc_valid"]
    assert manifest["scan_count"] == 2
    assert manifest["scans"][1]["invalid_coordinate_count"] == 1
    assert manifest["valid_point_count"] == len(demo_cloud().points)
    assert elements["metadata"]["source"]["sha256"] == manifest["source"]["sha256"]
    assert elements["metadata"]["coordinate_mapping"] == manifest["coordinate_mapping"]
    ifc = ifcopenshell.open(str(output / "model.ifc"))
    conversion = ifc.by_type("IfcMapConversion")
    assert len(conversion) == 1
    origin = manifest["coordinate_mapping"]["working_to_source_translation_m"]
    assert conversion[0].Eastings == pytest.approx(origin[0])
    assert conversion[0].Northings == pytest.approx(origin[1])
    assert conversion[0].OrthogonalHeight == pytest.approx(origin[2])
    assert source.read_bytes() == original


@pytest.mark.parametrize("chunk_points", [0, -1, True, 1.5])
def test_e57_import_rejects_invalid_chunk_size(tmp_path, chunk_points):
    with pytest.raises(ValueError, match="chunk_points"):
        read_e57(tmp_path / "scan.e57", tmp_path / "cache", chunk_points)
