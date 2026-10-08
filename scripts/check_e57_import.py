"""Check Cartesian E57 imports against native records and separately read XML poses.

This developer check does not certify acquisition accuracy or building geometry.
Both read paths use pye57/libE57Format, so this is not an independent decoder.
Input scans and their cache arrays must not be committed to the repository.
"""
import argparse
import hashlib
import json
import platform
import struct
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np
import pye57
from scipy.spatial.transform import Rotation

from punctora_core.benchmark import peak_memory_bytes
from punctora_core.e57_io import read_e57

NS = {"e": "http://www.astm.org/COMMIT/E57/2010-e57-v1.0"}


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read_xml(path):
    """Read the paged XML without using the importer's pose/header helpers."""
    with path.open("rb") as file:
        signature, major, minor, size, offset, length, page = struct.unpack("<8sIIQQQQ", file.read(48))
        if signature != b"ASTM-E57" or (major, minor) != (1, 0) or size != path.stat().st_size:
            raise ValueError("Unsupported or inconsistent E57 file header")
        if page < 8 or offset >= size or length > size:
            raise ValueError("Invalid E57 XML range")
        file.seek(offset)
        chunks = []
        while length:
            remaining = page - 4 - file.tell() % page
            if remaining <= 0:
                file.seek(page - file.tell() % page, 1)
                continue
            block = file.read(min(length, remaining))
            if not block:
                raise ValueError("Truncated E57 XML")
            chunks.append(block)
            length -= len(block)
    # Page CRC checks are handled by libE57Format on the native read path.
    return ET.fromstring(b"".join(chunks))


def xml_pose(scan):
    translation = np.zeros(3)
    quaternion = np.array([0., 0., 0., 1.])  # scipy uses XYZW
    pose = scan.find("e:pose", NS)
    if pose is not None:
        rotation = pose.find("e:rotation", NS)
        shift = pose.find("e:translation", NS)
        if rotation is not None:
            # E57 Float nodes can omit the text when their value is zero.
            quaternion = np.array([float(rotation.find(f"e:{axis}", NS).text or "0") for axis in "xyzw"])
        if shift is not None:
            translation = np.array([float(shift.find(f"e:{axis}", NS).text or "0") for axis in "xyz"])
    return Rotation.from_quat(quaternion), translation


def check_reference(path, imported, capacity=65536):
    """Compare every retained record/channel; never allocate a whole native scan."""
    cloud, manifest = imported.cloud, imported.manifest
    xml_scans = list(read_xml(path).find("e:data3D", NS))
    if len(xml_scans) != manifest["scan_count"]:
        raise AssertionError("XML and manifest scan counts differ")
    origin = np.asarray(manifest["coordinate_mapping"]["working_to_source_translation_m"])
    maximum_error, output_offset = 0., 0
    with pye57.E57(str(path), "r") as native:
        for index, xml_scan in enumerate(xml_scans):
            header = native.get_header(index)
            xml_count = int(xml_scan.find("e:points", NS).attrib["recordCount"])
            if xml_count != header.point_count or xml_count != manifest["scans"][index]["raw_point_count"]:
                raise AssertionError("XML, decoder and manifest record counts differ")
            if not {"cartesianX", "cartesianY", "cartesianZ"}.issubset(header.point_fields):
                raise ValueError("This verification tool checks Cartesian examples only")
            rotation, translation = xml_pose(xml_scan)
            fields = [name for name in ["cartesianX", "cartesianY", "cartesianZ", "cartesianInvalidState",
                                       "intensity", "colorRed", "colorGreen", "colorBlue",
                                       "isColorInvalid", "isIntensityInvalid"] if name in header.point_fields]
            arrays, buffers = {}, pye57.libe57.VectorSourceDestBuffer()
            for name in fields:
                arrays[name] = np.empty(capacity, dtype=np.float64)
                buffers.append(pye57.libe57.SourceDestBuffer(native.image_file, name, arrays[name], capacity, True, True))
            reader = header.points.reader(buffers)
            raw_offset, scan_valid = 0, 0
            try:
                while count := reader.read():
                    local = np.column_stack([arrays[name][:count] for name in ["cartesianX", "cartesianY", "cartesianZ"]])
                    keep = np.isfinite(local).all(axis=1)
                    if "cartesianInvalidState" in arrays:
                        keep &= arrays["cartesianInvalidState"][:count] == 0
                    valid_count = int(keep.sum())
                    selected = slice(output_offset, output_offset + valid_count)
                    expected = rotation.apply(local[keep]) + translation
                    recovered = cloud.points[selected] + origin
                    if valid_count:
                        error = float(np.max(np.abs(recovered - expected)))
                        maximum_error = max(maximum_error, error)
                        np.testing.assert_allclose(recovered, expected, atol=1e-7, rtol=0)
                    np.testing.assert_array_equal(cloud.scan_index[selected], np.full(valid_count, index))
                    np.testing.assert_array_equal(cloud.source_record_index[selected], np.arange(raw_offset, raw_offset+count)[keep])
                    if {"colorRed", "colorGreen", "colorBlue"}.issubset(arrays):
                        colors = np.column_stack([arrays[name][:count][keep] for name in ["colorRed", "colorGreen", "colorBlue"]])
                        validity = np.isfinite(colors).all(axis=1)
                        if "isColorInvalid" in arrays:
                            validity &= arrays["isColorInvalid"][:count][keep] == 0
                        np.testing.assert_array_equal(cloud.color_valid[selected], validity)
                        np.testing.assert_array_equal(cloud.colors[selected], np.where(np.isfinite(colors), colors, 0))
                    if "intensity" in arrays:
                        intensity = arrays["intensity"][:count][keep]
                        validity = np.isfinite(intensity)
                        if "isIntensityInvalid" in arrays:
                            validity &= arrays["isIntensityInvalid"][:count][keep] == 0
                        np.testing.assert_array_equal(cloud.intensity_valid[selected], validity)
                        np.testing.assert_array_equal(cloud.intensity[selected, 0], np.where(np.isfinite(intensity), intensity, 0))
                    output_offset += valid_count
                    scan_valid += valid_count
                    raw_offset += count
            finally:
                reader.close()
            if raw_offset != xml_count or scan_valid != manifest["scans"][index]["valid_point_count"]:
                raise AssertionError("Decoded counts differ from the import manifest")
    if output_offset != len(cloud.points):
        raise AssertionError("Retained record count differs")
    return {"records_checked": output_offset, "coordinate_absolute_tolerance_m": 1e-7,
            "maximum_coordinate_component_difference_m": maximum_error,
            "scan_and_original_record_indices_equal": True,
            "available_rgb_intensity_and_validity_equal": True}


def check_repeat(first, second, chunk=100000):
    for name in ["points", "scan_index", "source_record_index", "colors", "color_valid", "intensity", "intensity_valid"]:
        a, b = getattr(first.cloud, name), getattr(second.cloud, name)
        if a is None or b is None:
            if a is not None or b is not None:
                raise AssertionError("Repeat import channel presence changed")
            continue
        if a.shape != b.shape:
            raise AssertionError("Repeat import shape changed")
        for begin in range(0, len(a), chunk):
            np.testing.assert_array_equal(a[begin:begin+chunk], b[begin:begin+chunk])
    np.testing.assert_array_equal(first.manifest["coordinate_mapping"]["working_to_source_matrix"],
                                  second.manifest["coordinate_mapping"]["working_to_source_matrix"])
    first_paths = {item["path"] for item in first.manifest["cache"]["files"].values()}
    second_paths = {item["path"] for item in second.manifest["cache"]["files"].values()}
    if first_paths & second_paths:
        raise AssertionError("Repeat import reused immutable cache generation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output_dir.resolve()
    if source == output / "verification.json":
        parser.error("Output overlaps source")
    output.mkdir(parents=True, exist_ok=True)
    before = fingerprint(source)
    start = perf_counter()
    first = read_e57(source, output / "working-cache", 200000)
    first_seconds = perf_counter() - start
    first_peak = peak_memory_bytes()
    reference = check_reference(source, first)
    start = perf_counter()
    second = read_e57(source, output / "working-cache", 75000)
    repeat_seconds = perf_counter() - start
    check_repeat(first, second)
    if before != fingerprint(source):
        raise AssertionError("Source file bytes changed")
    manifest = first.manifest
    report = {
        "schema_version": 1, "test_date": datetime.now(timezone.utc).date().isoformat(), "source": manifest["source"],
        "environment": {"python": platform.python_version(), "os": platform.system(), "machine": platform.machine(),
                        "punctora_version": manifest["importer"]["punctora_core_version"],
                        "pye57_version": manifest["importer"]["pye57_version"]},
        "scope": "Cartesian example file import integrity only; no survey or reconstruction accuracy claim",
        "reference": {"native_decoder": "pye57/libE57Format shared with importer",
                      "pose_reference": "Separately parsed E57 XML and scipy Rotation, not importer pose helpers",
                      "chunk_points": 65536, **reference},
        "scan_count": manifest["scan_count"], "raw_point_count": manifest["raw_point_count"],
        "valid_point_count": manifest["valid_point_count"],
        "scans": [{key: s[key] for key in ["index", "coordinate_system", "raw_point_count", "valid_point_count",
                   "invalid_coordinate_count", "nonfinite_coordinate_count", "has_pose", "has_color", "has_intensity",
                   "invalid_color_count", "invalid_intensity_count", "unsupported_fields"]} for s in manifest["scans"]],
        "extent_m": (np.asarray(manifest["source_bounds_m"]["maximum"])-manifest["source_bounds_m"]["minimum"]).tolist(),
        "coordinate_metadata_status": manifest["coordinate_metadata_status"],
        "warnings": manifest["warnings"], "source_bytes_unchanged": True,
        "first_import": {"chunk_points": 200000, "seconds": first_seconds, "process_peak_memory_bytes": first_peak,
                         "cache_size_bytes": sum((output/"working-cache"/s["path"]).stat().st_size for s in manifest["cache"]["files"].values())},
        "repeat_import": {"chunk_points": 75000, "seconds": repeat_seconds,
                          "all_arrays_equal": True, "first_generation_still_readable": True,
                          "new_generation_created": True},
        "complete_check_process_peak_memory_bytes": peak_memory_bytes(),
    }
    # No coordinates, scanner serials, GUIDs or cache paths are published in this report.
    temporary = output / "verification.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(output / "verification.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
