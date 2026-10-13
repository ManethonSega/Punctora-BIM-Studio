"""Reversible f64 wall views with exact original-row pixel associations."""
from dataclasses import dataclass
import numpy as np

from ..annotation_io import content_digest, validate_geometry
from ..cropping import crop_mask
from .contracts import ProviderUnavailable


@dataclass(frozen=True)
class WallFrame:
    host_id: str
    origin_xy: tuple
    along_xy: tuple
    length_m: float
    base_m: float
    height_m: float
    offset_m: float
    side: int
    cell_m: float
    plane_basis: str

    @property
    def shape(self):
        def cells(length):
            ratio = length / self.cell_m
            # Rigid transforms at survey-size coordinates can perturb an
            # integral ratio by a few ulps. Such a microscopic sliver is not
            # a usable pixel and cannot survive a f64 world round trip.
            nearest = round(ratio)
            if abs(ratio - nearest) <= 1e-7:
                ratio = nearest
            return max(1, int(np.ceil(ratio)))
        return cells(self.height_m), cells(self.length_m)

    @property
    def normal_xy(self):
        return np.array([-self.along_xy[1], self.along_xy[0]], dtype=np.float64)

    @property
    def id(self):
        return "view:" + content_digest(self.to_dict())[:24]

    def to_dict(self):
        return {"host_id": self.host_id, "origin_xy": list(self.origin_xy), "along_xy": list(self.along_xy),
                "length_m": self.length_m, "base_m": self.base_m, "height_m": self.height_m,
                "offset_m": self.offset_m, "side": self.side, "cell_m": self.cell_m,
                "plane_basis": self.plane_basis, "shape": list(self.shape), "pixel_origin": "lower_left",
                "coordinate_dtype": "float64", "depth_convention": "side * (axis_normal_distance - offset)"}

    def local(self, points):
        points = np.asarray(points, dtype=np.float64)
        relative = points[:, :2] - self.origin_xy
        along = relative @ np.asarray(self.along_xy)
        x = along if self.side == 1 else self.length_m - along
        return np.column_stack((x, points[:, 2] - self.base_m, (relative @ self.normal_xy - self.offset_m) * self.side))

    def world(self, local):
        local = np.asarray(local, dtype=np.float64)
        along = local[:, 0] if self.side == 1 else self.length_m - local[:, 0]
        xy = (np.asarray(self.origin_xy) + along[:, None] * self.along_xy
              + (self.offset_m + local[:, 2] * self.side)[:, None] * self.normal_xy)
        return np.column_stack((xy, local[:, 1] + self.base_m))

    def pixels(self, local):
        local = np.asarray(local, dtype=np.float64)
        within = ((local[:, 0] >= 0) & (local[:, 0] <= self.length_m)
                  & (local[:, 1] >= 0) & (local[:, 1] <= self.height_m))
        # Coordinate noise at rigid-transform boundaries is numerical only.
        # Floor is used without biased epsilon so genuine neighbouring pixels
        # are never pulled across the cell boundary.
        xy = np.floor(local[:, :2] / self.cell_m).astype(np.int64)
        nz, nx = self.shape
        xy[:, 0] = np.clip(xy[:, 0], 0, nx - 1)
        xy[:, 1] = np.clip(xy[:, 1], 0, nz - 1)
        return xy, within

    def pixel_centres(self, pixels, depth=0.):
        pixels = np.asarray(pixels, dtype=np.int64)
        if pixels.ndim != 2 or pixels.shape[1] != 2 or np.any(pixels < 0) or np.any(pixels >= np.array(self.shape[::-1])):
            raise ValueError("Pixels must lie inside the exact wall image")
        lower = pixels * self.cell_m
        upper = np.minimum(lower + self.cell_m, [self.length_m, self.height_m])
        local = np.column_stack(((lower + upper) / 2, np.broadcast_to(depth, len(pixels))))
        return self.world(local)

    def local_bounds(self, box):
        x0, z0, x1, z1 = box
        x0, x1 = x0 * self.cell_m, min(x1 * self.cell_m, self.length_m)
        low, high = (x0, x1) if self.side == 1 else (self.length_m - x1, self.length_m - x0)
        return [float(low), float(z0 * self.cell_m), float(high), float(min(z1 * self.cell_m, self.height_m))]


def wall_frames(instance, cell_m=.05):
    geometry = instance["geometry"]
    validate_geometry(geometry)
    if geometry["type"] != "wall" or not np.isfinite(cell_m) or cell_m <= 0:
        raise ValueError("Projection needs a valid wall and positive metre cell")
    a, b = np.asarray(geometry["start"], dtype=np.float64), np.asarray(geometry["end"], dtype=np.float64)
    # A canonical axis keeps instance IDs and both views independent of the
    # preliminary wall's endpoint order.
    if tuple(b) < tuple(a):
        a, b = b, a
    length = float(np.linalg.norm(b - a))
    along = (b - a) / length
    normal = np.array([-along[1], along[0]])
    offsets = []
    for face in instance.get("observed_faces", []):
        middle = np.mean(np.asarray([face["start"], face["end"]], dtype=np.float64), axis=0)
        offsets.append(float((middle - a) @ normal))
    if offsets:
        front, back = max(offsets), min(offsets)
        basis = "measured_plane" if abs(front - back) > 1e-6 else "opposite_views_of_one_measured_plane"
    else:
        front, back, basis = geometry["thickness"] / 2, -geometry["thickness"] / 2, "inferred_envelope_plane"
    return [WallFrame(instance["id"], tuple(a), tuple(along), length, float(geometry["base"]),
                      float(geometry["height"]), offset, side, float(cell_m), basis)
            for side, offset in ((1, front), (-1, back))]


@dataclass
class WallProjection:
    frame: WallFrame
    face_counts: np.ndarray
    return_counts: np.ndarray
    signed_depth_m: np.ndarray
    rgb: np.ndarray
    rgb_valid: np.ndarray
    source_rows: np.ndarray
    pixel_ids: np.ndarray
    face_distances_m: np.ndarray

    def rows_for_mask(self, mask, near_face=False, face_band_m=.025):
        if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.shape != self.frame.shape:
            raise ValueError("Back-projection requires an exact boolean image mask")
        selected = mask.ravel()[self.pixel_ids]
        if near_face:
            selected &= self.face_distances_m <= face_band_m
        return self.source_rows[selected]


def project_wall(cloud, candidate_rows, frame, crop=None, *, face_band_m=.025, depth_radius_m=.35,
                 maximum_cells=250000, maximum_context_points=250000, chunk_points=65536, check=lambda: None):
    nz, nx = frame.shape
    if nz * nx > maximum_cells or len(candidate_rows) > maximum_context_points:
        raise ProviderUnavailable("Wall projection exceeds an explicit cell/original-point limit; partition the crop, never decimate")
    if frame.plane_basis == "inferred_envelope_plane":
        # Such an image remains an inferred view; no occupancy here certifies
        # that the guessed plane is a measured wall face.
        pass
    face = np.zeros(nz * nx, dtype=np.uint32)
    returns = np.zeros_like(face)
    signed = np.full(nz * nx, np.nan, dtype=np.float64)
    nearest = np.full(nz * nx, np.inf, dtype=np.float64)
    rgb = np.zeros((nz * nx, 3), dtype=np.float64)
    rgb_valid = np.zeros(nz * nx, dtype=bool)
    # A representative RGB sample is selected by depth then exact source IDs,
    # not a point-order-dependent floating sum or an assumed color scale.
    winner = np.empty(nz * nx, dtype=[("depth", "<f8"), ("scan", "<u8"), ("record", "<u8")])
    winner["depth"], winner["scan"], winner["record"] = np.inf, np.iinfo(np.uint64).max, np.iinfo(np.uint64).max
    source, pixels, distances = [], [], []
    for begin in range(0, len(candidate_rows), chunk_points):
        check()
        rows = np.asarray(candidate_rows[begin:begin + chunk_points], dtype=np.uint64)
        points = cloud.points[rows]
        local = frame.local(points)
        xy, keep = frame.pixels(local)
        keep &= (np.abs(local[:, 2]) <= depth_radius_m) & crop_mask(points, crop)
        rows, xy, depth = rows[keep], xy[keep], local[keep, 2]
        pixel = (xy[:, 1] * nx + xy[:, 0]).astype(np.uint32)
        absolute = np.abs(depth)
        source.append(rows)
        pixels.append(pixel)
        distances.append(absolute)
        np.add.at(returns, pixel, 1)
        np.add.at(face, pixel[absolute <= face_band_m], 1)
        unique = np.unique(pixel)
        old = nearest[unique].copy()
        np.minimum.at(nearest, pixel, absolute)
        signed[unique[nearest[unique] < old]] = np.inf
        closest = absolute == nearest[pixel]
        np.minimum.at(signed, pixel[closest], depth[closest])
        if cloud.colors is not None:
            valid = np.ones(len(rows), dtype=bool) if cloud.color_valid is None else cloud.color_valid[rows]
            ids = np.flatnonzero(valid)
            order = np.lexsort((cloud.source_record_index[rows[ids]], cloud.scan_index[rows[ids]], absolute[ids], pixel[ids]))
            ids = ids[order]
            if len(ids):
                ids = ids[np.r_[True, pixel[ids][1:] != pixel[ids][:-1]]]
            for i in ids:
                p = pixel[i]
                key = (float(absolute[i]), int(cloud.scan_index[rows[i]]), int(cloud.source_record_index[rows[i]]))
                old = (float(winner[p]["depth"]), int(winner[p]["scan"]), int(winner[p]["record"]))
                if key < old:
                    winner[p] = key
                    rgb[p], rgb_valid[p] = cloud.colors[rows[i]], True
    arrays = [np.concatenate(parts) if parts else np.empty(0, dtype=dtype)
              for parts, dtype in ((source, "<u8"), (pixels, "<u4"), (distances, "<f8"))]
    return WallProjection(frame, face.reshape(nz, nx), returns.reshape(nz, nx), signed.reshape(nz, nx),
                          rgb.reshape(nz, nx, 3), rgb_valid.reshape(nz, nx), *arrays)
