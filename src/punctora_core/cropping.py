"""Validated, non-destructive project crops for preview and reconstruction."""
from pathlib import Path
import shutil

import numpy as np
from shapely.geometry import Polygon

from .cloud_io import CloudData


EMPTY_CROP = {"polygon": None, "z_min": None, "z_max": None}


def validate_crop(value):
    if value is None:
        return dict(EMPTY_CROP)
    if not isinstance(value, dict) or set(value) - set(EMPTY_CROP):
        raise ValueError("Crop must contain only polygon, z_min and z_max")
    result = dict(EMPTY_CROP)
    polygon = value.get("polygon")
    if polygon is not None:
        try:
            vertices = np.asarray(polygon, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError("Crop polygon coordinates must be finite numbers") from exc
        if (vertices.ndim != 2 or vertices.shape[1] != 2
                or not 3 <= len(vertices) <= 64 or not np.isfinite(vertices).all()):
            raise ValueError("Crop polygon requires 3 to 64 finite XY vertices")
        shape = Polygon(vertices)
        if not shape.is_valid or shape.area <= 1e-8:
            raise ValueError("Crop polygon must be simple and have a nonzero area")
        result["polygon"] = vertices.tolist()
    for name in ("z_min", "z_max"):
        number = value.get(name)
        if number is not None:
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not np.isfinite(number):
                raise ValueError("Crop heights must be finite numbers in metres")
            result[name] = float(number)
    if result["z_min"] is not None and result["z_max"] is not None and result["z_min"] >= result["z_max"]:
        raise ValueError("Crop bottom must be below crop top")
    return result


def crop_active(crop):
    crop = validate_crop(crop)
    return crop["polygon"] is not None or crop["z_min"] is not None or crop["z_max"] is not None


def points_in_polygon(points, polygon):
    """Boundary-inclusive, vectorised XY point-in-polygon test."""
    points = np.asarray(points, dtype=np.float64)
    vertices = np.asarray(polygon, dtype=np.float64)
    x, y = points[:, 0], points[:, 1]
    inside = np.zeros(len(points), dtype=bool)
    boundary = np.zeros(len(points), dtype=bool)
    scale = max(1.0, float(np.ptp(vertices, axis=0).max()))
    tolerance = scale * 1e-10
    previous = vertices[-1]
    for current in vertices:
        ax, ay = previous
        bx, by = current
        cross = (x-ax)*(by-ay) - (y-ay)*(bx-ax)
        within = ((x >= min(ax, bx)-tolerance) & (x <= max(ax, bx)+tolerance)
                  & (y >= min(ay, by)-tolerance) & (y <= max(ay, by)+tolerance))
        boundary |= (np.abs(cross) <= tolerance) & within
        crossing = ((ay > y) != (by > y)) & (x < (bx-ax)*(y-ay)/(by-ay+1e-300)+ax)
        inside ^= crossing
        previous = current
    return inside | boundary


def crop_mask(points, crop):
    crop = validate_crop(crop)
    selected = np.ones(len(points), dtype=bool)
    if crop["z_min"] is not None:
        selected &= points[:, 2] >= crop["z_min"]
    if crop["z_max"] is not None:
        selected &= points[:, 2] <= crop["z_max"]
    if crop["polygon"] is not None:
        selected &= points_in_polygon(points, crop["polygon"])
    return selected


def materialize_crop(cloud, crop, directory, chunk_points=1_000_000):
    """Stream a crop into temporary mapped arrays without changing its source."""
    crop = validate_crop(crop)
    if not crop_active(crop):
        return cloud, {"active": False, "source_points": len(cloud.points),
                       "selected_points": len(cloud.points), "crop": crop}
    if not isinstance(chunk_points, int) or isinstance(chunk_points, bool) or chunk_points <= 0:
        raise ValueError("Crop chunk size must be a positive integer")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    channels = {name: getattr(cloud, name) for name in (
        "points", "colors", "intensity", "color_valid", "intensity_valid",
        "scan_index", "source_record_index") if getattr(cloud, name) is not None}
    handles = {}
    count = 0
    try:
        for name in [*channels, "working_index"]:
            handles[name] = (directory / f"{name}.bin").open("wb")
        for begin in range(0, len(cloud.points), chunk_points):
            end = min(begin+chunk_points, len(cloud.points))
            points = cloud.points[begin:end]
            selected = crop_mask(points, crop)
            if not selected.any():
                continue
            for name, values in channels.items():
                np.asarray(values[begin:end][selected]).tofile(handles[name])
            np.arange(begin, end, dtype="<i8")[selected].tofile(handles["working_index"])
            count += int(selected.sum())
        for handle in handles.values():
            handle.close()
        handles.clear()
        if count == 0:
            raise ValueError("The crop contains no point-cloud records")
        mapped = {}
        for name, values in channels.items():
            shape = (count, *values.shape[1:])
            mapped[name] = np.memmap(directory / f"{name}.bin", mode="r", dtype=values.dtype, shape=shape)
        working_index = np.memmap(directory / "working_index.bin", mode="r", dtype="<i8", shape=(count,))
        result = CloudData(**mapped, working_index=working_index, metadata={**cloud.metadata,
                           "crop": crop, "uncropped_point_count": len(cloud.points)})
        return result, {"active": True, "source_points": len(cloud.points),
                        "selected_points": count, "crop": crop}
    except Exception:
        for handle in handles.values():
            handle.close()
        shutil.rmtree(directory, ignore_errors=True)
        raise
