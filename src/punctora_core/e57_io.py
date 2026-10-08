"""Bounded-memory E57 import with reversible source-coordinate mapping."""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pye57

from . import __version__
from .cloud_io import CloudData


_CARTESIAN = ("cartesianX", "cartesianY", "cartesianZ")
_SPHERICAL = ("sphericalRange", "sphericalAzimuth", "sphericalElevation")
_COLOR = ("colorRed", "colorGreen", "colorBlue")
_FLAGS = {"cartesianInvalidState", "sphericalInvalidState", "isColorInvalid", "isIntensityInvalid"}


@dataclass
class E57ImportResult:
    cloud: CloudData
    manifest: dict


def _sha256(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def _node_text(node, field: str, default: str = "") -> str:
    return str(node[field].value()) if node.isDefined(field) else default


def _pose(node, index):
    """Read named pose components; reject malformed poses instead of guessing."""
    quaternion, translation = np.array([1., 0., 0., 0.]), np.zeros(3)
    if node.isDefined("pose"):
        pose = node["pose"]
        if pose.isDefined("rotation"):
            quaternion = np.array([pose["rotation"][name].value() for name in ["w", "x", "y", "z"]])
        if pose.isDefined("translation"):
            translation = np.array([pose["translation"][name].value() for name in ["x", "y", "z"]])
    if not np.isfinite(quaternion).all() or not np.isfinite(translation).all():
        raise ValueError(f"E57 scan {index} has a nonfinite pose")
    if not np.isclose(np.linalg.norm(quaternion), 1., atol=1e-6, rtol=0):
        raise ValueError(f"E57 scan {index} rotation quaternion must have unit length")
    w, x, y, z = quaternion / np.linalg.norm(quaternion)
    rotation = np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
    ])
    return quaternion, translation, rotation


def _buffers(reader: pye57.E57, fields: list[str], capacity: int):
    """Use double channels, retaining precision and RGB values above 255."""
    arrays, buffers = {}, pye57.libe57.VectorSourceDestBuffer()
    for field in fields:
        array = np.empty(capacity, dtype=np.int8 if field in _FLAGS else np.float64)
        buffer = pye57.libe57.SourceDestBuffer(reader.image_file, field, array, capacity, True, True)
        arrays[field] = array
        buffers.append(buffer)
    return arrays, buffers


def _cartesian(data: dict[str, np.ndarray], count: int, coordinate_system: str) -> np.ndarray:
    if coordinate_system == "cartesian":
        return np.column_stack([data[name][:count] for name in _CARTESIAN])
    distance = data["sphericalRange"][:count]
    azimuth = data["sphericalAzimuth"][:count]
    elevation = data["sphericalElevation"][:count]
    horizontal = distance * np.cos(elevation)
    return np.column_stack([
        horizontal * np.cos(azimuth),
        horizontal * np.sin(azimuth),
        distance * np.sin(elevation),
    ])


def _temporary(cache_dir: Path, suffix: str):
    return tempfile.NamedTemporaryFile(dir=cache_dir, prefix=".e57-import-", suffix=suffix, delete=False)


def read_e57(path: str | Path, cache_dir: str | Path, chunk_points: int = 1_000_000) -> E57ImportResult:
    """Import registered E57 scans into a disk-backed local metre frame.

    Coordinate-invalid and nonfinite points are excluded. Optional values and
    their validity masks are retained. ``source = working + origin`` reverses
    the project-frame shift; scan pose matrices map scan-local to source.
    """
    if not isinstance(chunk_points, int) or isinstance(chunk_points, bool) or chunk_points <= 0:
        raise ValueError("chunk_points must be a positive integer")
    path, cache_dir = Path(path), Path(cache_dir)
    if path.suffix.lower() != ".e57":
        raise ValueError("Direct import requires an .e57 file")
    if not path.is_file():
        raise ValueError(f"E57 source does not exist: {path}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    source_sha = _sha256(path)
    token = source_sha[:16]
    temporary_paths: list[Path] = []
    handles = {}
    publication = None
    try:
        with pye57.E57(str(path), "r") as source:
            if source.scan_count == 0:
                raise ValueError("E57 contains no 3D scans")
            specs, any_color, any_intensity = [], False, False
            for index in range(source.scan_count):
                header = source.get_header(index)
                fields = set(header.point_fields)
                if set(_CARTESIAN).issubset(fields):
                    coordinate_system, coordinate_fields, invalid_field = "cartesian", _CARTESIAN, "cartesianInvalidState"
                elif set(_SPHERICAL).issubset(fields):
                    coordinate_system, coordinate_fields, invalid_field = "spherical", _SPHERICAL, "sphericalInvalidState"
                else:
                    raise ValueError(f"E57 scan {index} has no complete Cartesian or spherical coordinates")
                color = set(_COLOR).issubset(fields)
                intensity = "intensity" in fields
                any_color, any_intensity = any_color or color, any_intensity or intensity
                rotation, translation, rotation_matrix = _pose(header.node, index)
                matrix = np.eye(4, dtype=np.float64)
                matrix[:3, :3] = rotation_matrix
                matrix[:3, 3] = translation
                read_fields = list(coordinate_fields)
                read_fields += [name for name in [invalid_field, "intensity", *_COLOR,
                                                   "isIntensityInvalid", "isColorInvalid"] if name in fields]
                supported_for_import = set(coordinate_fields) | {invalid_field, "intensity", *_COLOR,
                                                                  "isIntensityInvalid", "isColorInvalid"}
                specs.append({
                    "index": index,
                    "name": _node_text(header.node, "name", f"Scan {index}"),
                    "guid": _node_text(header.node, "guid"),
                    "metadata": {name: header.node[name].value() for name in [
                        "description", "sensorVendor", "sensorModel", "sensorSerialNumber",
                        "sensorHardwareVersion", "sensorSoftwareVersion", "sensorFirmwareVersion",
                        "temperature", "relativeHumidity", "atmosphericPressure",
                    ] if header.node.isDefined(name)},
                    "acquisition": {
                        name: {field: header.node[name][field].value()
                               for field in ["dateTimeValue", "isAtomicClockReferenced"]
                               if header.node[name].isDefined(field)}
                        for name in ["acquisitionStart", "acquisitionEnd"] if header.node.isDefined(name)
                    },
                    "raw_point_count": int(header.point_count),
                    "coordinate_system": coordinate_system,
                    "coordinate_fields": coordinate_fields,
                    "invalid_field": invalid_field,
                    "fields": sorted(fields),
                    "read_fields": read_fields,
                    "unsupported_fields": sorted(fields - supported_for_import),
                    "has_pose": bool(header.has_pose()),
                    "rotation_quaternion_wxyz": rotation.tolist(),
                    "translation_m": translation.tolist(),
                    "scan_to_source_matrix": matrix.tolist(),
                    "rotation_matrix": matrix[:3, :3],
                    "translation": translation,
                    "has_color": color,
                    "has_intensity": intensity,
                    "valid_point_count": 0,
                    "invalid_coordinate_count": 0,
                    "nonfinite_coordinate_count": 0,
                    "invalid_color_count": 0,
                    "invalid_intensity_count": 0,
                })

            channel_names = ["points", "scan_index", "source_record_index"]
            if any_color:
                channel_names += ["colors", "color_valid"]
            if any_intensity:
                channel_names += ["intensity", "intensity_valid"]
            for name in channel_names:
                handle = _temporary(cache_dir, f"-{name}.tmp")
                handles[name] = handle
                temporary_paths.append(Path(handle.name))

            minimum = np.full(3, np.inf)
            maximum = np.full(3, -np.inf)
            total_valid = 0
            for spec in specs:
                header = source.get_header(spec["index"])
                arrays, buffers = _buffers(source, spec["read_fields"], chunk_points)
                compressed = header.points.reader(buffers)
                record_offset = 0
                try:
                    while count := compressed.read():
                        record_indices = np.arange(record_offset, record_offset + count, dtype="<u8")
                        record_offset += count
                        local = _cartesian(arrays, count, spec["coordinate_system"])
                        finite = np.isfinite(local).all(axis=1)
                        invalid = np.zeros(count, dtype=bool)
                        if spec["invalid_field"] in arrays:
                            invalid = arrays[spec["invalid_field"]][:count] != 0
                        spec["invalid_coordinate_count"] += int(invalid.sum())
                        spec["nonfinite_coordinate_count"] += int((~finite & ~invalid).sum())
                        keep = finite & ~invalid
                        local = local[keep]
                        if not len(local):
                            continue
                        global_points = local @ spec["rotation_matrix"].T + spec["translation"]
                        if not np.isfinite(global_points).all():
                            raise ValueError(f"E57 scan {spec['index']} pose produced nonfinite coordinates")
                        global_points.astype("<f8", copy=False).tofile(handles["points"])
                        np.full(len(local), spec["index"], dtype="<u4").tofile(handles["scan_index"])
                        record_indices[keep].tofile(handles["source_record_index"])
                        minimum = np.minimum(minimum, global_points.min(axis=0))
                        maximum = np.maximum(maximum, global_points.max(axis=0))
                        valid_count = int(len(local))
                        spec["valid_point_count"] += valid_count
                        total_valid += valid_count

                        if any_color:
                            if spec["has_color"]:
                                colors = np.column_stack([arrays[name][:count] for name in _COLOR])[keep]
                                color_valid = np.isfinite(colors).all(axis=1)
                                if "isColorInvalid" in arrays:
                                    color_valid &= arrays["isColorInvalid"][:count][keep] == 0
                                colors[~np.isfinite(colors)] = 0
                            else:
                                colors = np.zeros((valid_count, 3), dtype=np.float64)
                                color_valid = np.zeros(valid_count, dtype=bool)
                            spec["invalid_color_count"] += int((~color_valid).sum())
                            colors.astype("<f8", copy=False).tofile(handles["colors"])
                            color_valid.astype("u1", copy=False).tofile(handles["color_valid"])

                        if any_intensity:
                            if spec["has_intensity"]:
                                intensity = np.asarray(arrays["intensity"][:count][keep], dtype=np.float64)
                                intensity_valid = np.isfinite(intensity)
                                if "isIntensityInvalid" in arrays:
                                    intensity_valid &= arrays["isIntensityInvalid"][:count][keep] == 0
                                intensity[~np.isfinite(intensity)] = 0
                            else:
                                intensity = np.zeros(valid_count, dtype=np.float64)
                                intensity_valid = np.zeros(valid_count, dtype=bool)
                            spec["invalid_intensity_count"] += int((~intensity_valid).sum())
                            intensity.astype("<f8", copy=False).tofile(handles["intensity"])
                            intensity_valid.astype("u1", copy=False).tofile(handles["intensity_valid"])
                finally:
                    compressed.close()
                if record_offset != spec["raw_point_count"]:
                    raise ValueError(f"E57 scan {spec['index']} record count differs from its header")

            if total_valid == 0:
                raise ValueError("E57 contains no valid finite 3D points")
            for handle in handles.values():
                handle.flush()
                os.fsync(handle.fileno())
                handle.close()

            # Keep Z near the lowest observed point for readable storey levels.
            origin = np.array([(minimum[0] + maximum[0]) / 2,
                               (minimum[1] + maximum[1]) / 2, minimum[2]], dtype=np.float64)
            staged_points = np.memmap(temporary_paths[channel_names.index("points")], dtype="<f8", mode="r+",
                                      shape=(total_valid, 3))
            for begin in range(0, total_valid, chunk_points):
                staged_points[begin:begin + chunk_points] -= origin
            staged_points.flush()
            del staged_points

            # Publish a complete immutable generation. Previously mapped files
            # remain usable on Windows and a failed import cannot alter them.
            publication = tempfile.TemporaryDirectory(dir=cache_dir, prefix=".e57-publish-")
            generation_name = f"import-{token}-{uuid.uuid4().hex}"
            staging = Path(publication.name)
            final_directory = cache_dir / generation_name
            final_paths = {}
            extensions = {"points": "f64", "scan_index": "u32", "colors": "f64",
                          "color_valid": "bool", "intensity": "f64", "intensity_valid": "bool",
                          "source_record_index": "u64"}
            for name in channel_names:
                filename = f"{name}.{extensions[name]}"
                os.replace(Path(handles[name].name), staging / filename)
                temporary_paths.remove(Path(handles[name].name))
                final_paths[name] = final_directory / filename
            os.replace(staging, final_directory)

            points = np.memmap(final_paths["points"], dtype="<f8", mode="r", shape=(total_valid, 3))
            scan_index = np.memmap(final_paths["scan_index"], dtype="<u4", mode="r", shape=(total_valid,))
            source_record_index = np.memmap(final_paths["source_record_index"], dtype="<u8", mode="r", shape=(total_valid,))
            colors = (np.memmap(final_paths["colors"], dtype="<f8", mode="r", shape=(total_valid, 3))
                      if any_color else None)
            color_valid = (np.memmap(final_paths["color_valid"], dtype="?", mode="r", shape=(total_valid,))
                           if any_color else None)
            intensity = (np.memmap(final_paths["intensity"], dtype="<f8", mode="r", shape=(total_valid, 1))
                         if any_intensity else None)
            intensity_valid = (np.memmap(final_paths["intensity_valid"], dtype="?", mode="r", shape=(total_valid,))
                               if any_intensity else None)

            coordinate_metadata = _node_text(source.root, "coordinateMetadata").strip()
            warnings = ["Confirm source Z-up orientation, CRS and vertical datum before survey use."]
            if not coordinate_metadata:
                warnings.append("E57 coordinateMetadata is absent; no coordinate reference system was inferred.")
            for spec in specs:
                if not spec["has_pose"]:
                    warnings.append(f"Scan {spec['index']}: pose absent; identity transform used.")
                if spec["unsupported_fields"]:
                    warnings.append(f"Scan {spec['index']}: ignored point fields: {', '.join(spec['unsupported_fields'])}.")
                dropped = spec["invalid_coordinate_count"] + spec["nonfinite_coordinate_count"]
                if dropped:
                    warnings.append(f"Scan {spec['index']}: excluded {dropped} invalid or nonfinite coordinate records.")
            cache_files = {}
            shapes = {"points": [total_valid, 3], "scan_index": [total_valid], "colors": [total_valid, 3],
                      "color_valid": [total_valid], "intensity": [total_valid, 1], "intensity_valid": [total_valid],
                      "source_record_index": [total_valid]}
            dtypes = {"points": "<f8", "scan_index": "<u4", "colors": "<f8", "color_valid": "|b1",
                      "intensity": "<f8", "intensity_valid": "|b1", "source_record_index": "<u8"}
            for name, stored_path in final_paths.items():
                cache_files[name] = {"path": f"{generation_name}/{stored_path.name}",
                                     "dtype": dtypes[name], "shape": shapes[name]}
            scan_manifest = []
            for spec in specs:
                scan_manifest.append({key: value for key, value in spec.items()
                                      if key not in {"coordinate_fields", "invalid_field", "read_fields",
                                                     "rotation_matrix", "translation"}})
            matrix = np.eye(4)
            matrix[:3, 3] = origin
            inverse = np.eye(4)
            inverse[:3, 3] = -origin
            manifest = {
                "schema_version": 1,
                "importer": {"punctora_core_version": __version__, "pye57_version": version("pye57"),
                             "chunk_points": chunk_points},
                "source": {"kind": "E57", "filename": path.name, "sha256": source_sha,
                           "size_bytes": path.stat().st_size, "units": "metres"},
                "coordinate_metadata": coordinate_metadata or None,
                "coordinate_metadata_status": "present_unverified" if coordinate_metadata else "absent",
                "coordinate_mapping": {
                    "working_frame": "local metres, Z up as encoded by source",
                    "source_frame": "E57 source coordinates; CRS requires confirmation",
                    "working_to_source_matrix": matrix.tolist(),
                    "source_to_working_matrix": inverse.tolist(),
                    "working_to_source_translation_m": origin.tolist(),
                    "formula": "source_xyz_m = working_xyz_m + working_to_source_translation_m",
                },
                "source_bounds_m": {"minimum": minimum.tolist(), "maximum": maximum.tolist()},
                "working_bounds_m": {"minimum": (minimum - origin).tolist(), "maximum": (maximum - origin).tolist()},
                "raw_point_count": int(sum(spec["raw_point_count"] for spec in specs)),
                "valid_point_count": total_valid,
                "scan_count": len(specs),
                "warnings": warnings,
                "scans": scan_manifest,
                "cache": {"format": "little-endian flat binary", "directory": cache_dir.name,
                          "files": cache_files},
            }
            cloud = CloudData(points, colors, intensity, color_valid, intensity_valid, scan_index,
                              {"coordinate_frame": "E57-derived local metres", "coordinate_mapping": manifest["coordinate_mapping"]},
                              source_record_index=source_record_index)
            return E57ImportResult(cloud, manifest)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Unable to import E57 {path.name}: {exc}") from exc
    finally:
        if publication is not None:
            publication.cleanup()
        for handle in handles.values():
            try:
                handle.close()
            except Exception:
                pass
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)
