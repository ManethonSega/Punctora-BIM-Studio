"""Atomic replacement and lossless numeric handling for point-cloud data."""
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
import numpy as np


def _all_finite(values: np.ndarray) -> bool:
    """Validate mapped arrays without allocating a cloud-sized boolean array."""
    return all(np.isfinite(values[begin:begin + 100_000]).all()
               for begin in range(0, len(values), 100_000))


@dataclass
class CloudData:
    points: np.ndarray
    colors: np.ndarray | None = None
    intensity: np.ndarray | None = None
    color_valid: np.ndarray | None = None
    intensity_valid: np.ndarray | None = None
    scan_index: np.ndarray | None = None
    metadata: dict = field(default_factory=dict)
    source_record_index: np.ndarray | None = None

    def __post_init__(self):
        self.points = np.asarray(self.points, dtype=np.float64)
        if self.points.ndim != 2 or self.points.shape[1] != 3 or len(self.points) == 0:
            raise ValueError("Cloud points must be a nonempty N x 3 array")
        if not _all_finite(self.points):
            raise ValueError("Cloud contains invalid/nonfinite coordinates")
        if self.colors is not None:
            self.colors = np.asarray(self.colors, dtype=np.float64)
            if self.colors.shape != self.points.shape or not _all_finite(self.colors):
                raise ValueError("Colors must be a finite N x 3 array")
        if self.intensity is not None:
            self.intensity = np.asarray(self.intensity, dtype=np.float64).reshape(-1, 1)
            if len(self.intensity) != len(self.points) or not _all_finite(self.intensity):
                raise ValueError("Intensity must have one finite value per point")
        for name, channel in [("color_valid", self.color_valid), ("intensity_valid", self.intensity_valid)]:
            if channel is not None:
                values = np.asarray(channel, dtype=bool).reshape(-1)
                if len(values) != len(self.points):
                    raise ValueError(f"{name} must have one value per point")
                setattr(self, name, values)
        if self.color_valid is not None and self.colors is None:
            raise ValueError("color_valid requires colors")
        if self.intensity_valid is not None and self.intensity is None:
            raise ValueError("intensity_valid requires intensity")
        if self.scan_index is not None:
            self.scan_index = np.asarray(self.scan_index)
            if self.scan_index.shape != (len(self.points),) or self.scan_index.dtype.kind not in "iu":
                raise ValueError("scan_index must contain one integer per point")
        if self.source_record_index is not None:
            self.source_record_index = np.asarray(self.source_record_index)
            if (self.source_record_index.shape != (len(self.points),)
                    or self.source_record_index.dtype.kind not in "iu"):
                raise ValueError("source_record_index must contain one integer per point")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dictionary")


def write_xyz(cloud: CloudData, path: str | Path, chunk_size: int = 10000) -> None:
    """Replace output atomically, retaining double precision and optional channels."""
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = [cloud.points]
    columns = ["X", "Y", "Z"]
    if cloud.colors is not None:
        arrays.append(cloud.colors)
        columns.extend(["R", "G", "B"])
    if cloud.intensity is not None:
        arrays.append(cloud.intensity)
        columns.append("Intensity")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write("\t".join(columns) + "\n")
            for begin in range(0, len(cloud.points), chunk_size):
                rows = np.column_stack([a[begin:begin + chunk_size] for a in arrays])
                np.savetxt(temp, rows, delimiter="\t", fmt="%.17g")
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def e57_data_to_xyz(data, path, chunk_size: int = 10000) -> None:
    """Compatibility adapter for upstream decoded E57 objects, not an E57 reader."""
    colors = getattr(data, "color", None)
    intensity = getattr(data, "intensity", None)
    write_xyz(CloudData(data.points, colors, intensity), path, chunk_size)


def read_xyz(path: str | Path, stride: int = 1) -> CloudData:
    """Read XYZ/XYZI/XYZRGB/XYZRGBI with an optional header; retain first sample."""
    if not isinstance(stride, int) or isinstance(stride, bool) or stride <= 0:
        raise ValueError("stride must be a positive integer")
    rows, data_index, column_count = [], 0, None
    with Path(path).open(encoding="utf-8-sig") as source:
        for line_no, line in enumerate(source, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            if text.startswith("//"):
                if data_index == 0:
                    continue
                raise ValueError(f"Unexpected header on line {line_no}")
            tokens = text.split()
            if data_index == 0 and tokens[:3] == ["X", "Y", "Z"]:
                continue
            try:
                row = [float(token) for token in tokens]
            except ValueError as exc:
                raise ValueError(f"Invalid numeric data on line {line_no}") from exc
            if len(row) not in {3, 4, 6, 7}:
                raise ValueError(f"Expected 3, 4, 6 or 7 columns on line {line_no}")
            if column_count is not None and len(row) != column_count:
                raise ValueError("Inconsistent XYZ columns")
            if not np.isfinite(row).all():
                raise ValueError(f"Nonfinite value on line {line_no}")
            column_count = len(row)
            if data_index % stride == 0:
                rows.append(row)
            data_index += 1
    if not rows:
        raise ValueError("XYZ contains no points")
    values = np.asarray(rows)
    intensity = values[:, 3:4] if values.shape[1] == 4 else values[:, 6:7] if values.shape[1] == 7 else None
    return CloudData(values[:, :3], values[:, 3:6] if values.shape[1] >= 6 else None, intensity)
