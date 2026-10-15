"""Reversible, physical-scale specialist plan and vertical-section rasters."""
from dataclasses import dataclass, asdict
from math import cos, radians, sin
import numpy as np
import cv2


@dataclass(frozen=True)
class PlanFrame:
    frame_id: str
    centre_xy_m: tuple
    basis_u_xy: tuple
    basis_v_xy: tuple
    side_m: float
    native_pixels: int
    model_pixels: int
    rotation_degrees: float
    mirrored: bool
    z_min_m: float
    z_max_m: float
    row_direction: str = "row_zero_is_positive_v"
    cell_convention: str = "floor_quantized_pixel_centres"

    @property
    def pixel_m(self):
        return self.side_m / self.native_pixels

    def to_dict(self):
        return {**asdict(self), "effective_pixel_m": self.pixel_m,
                "model_resize": {"from": [self.native_pixels, self.native_pixels],
                                 "to": [self.model_pixels, self.model_pixels],
                                 "interpolation": "opencv_linear"}}


@dataclass(frozen=True)
class SectionFrame:
    frame_id: str
    origin_xy_m: tuple
    axis_xy: tuple
    u_min_m: float
    z_min_m: float
    pixel_m: float
    native_width: int
    native_height: int
    base_m: float
    extension_m: float
    row_direction: str = "row_zero_is_positive_z"
    cell_convention: str = "floor_quantized_pixel_centres"

    def to_dict(self):
        return {**asdict(self), "model_resize": {"from": [self.native_height, self.native_width],
                                                  "to": [560, 560],
                                                  "interpolation": "opencv_linear"}}


def plan_frame(identifier, centre_xy, side_m, native_pixels, angle_degrees, mirrored,
               z_min, z_max, model_pixels=512):
    if side_m <= 0 or native_pixels < 2 or model_pixels < 2 or z_max <= z_min:
        raise ValueError("Invalid specialist plan-frame dimensions")
    angle = radians(float(angle_degrees))
    base_u = np.array([cos(angle), sin(angle)], dtype=np.float64)
    v = np.array([-base_u[1], base_u[0]], dtype=np.float64)
    u = base_u.copy()
    if mirrored:
        u *= -1
    return PlanFrame(identifier, tuple(map(float, centre_xy)), tuple(u), tuple(v), float(side_m),
                     int(native_pixels), int(model_pixels), float(angle_degrees), bool(mirrored),
                     float(z_min), float(z_max))


def plan_pixels(frame, points, pixels=None):
    points = np.asarray(points, dtype=np.float64)
    size = frame.native_pixels if pixels is None else int(pixels)
    centre = np.asarray(frame.centre_xy_m)
    relative = points[:, :2] - centre
    u = relative @ np.asarray(frame.basis_u_xy)
    v = relative @ np.asarray(frame.basis_v_xy)
    scale = size / frame.side_m
    columns = np.floor((u + frame.side_m / 2) * scale).astype(np.int64)
    y = np.floor((v + frame.side_m / 2) * scale).astype(np.int64)
    rows = size - 1 - y
    inside = ((points[:, 2] >= frame.z_min_m) & (points[:, 2] <= frame.z_max_m)
              & (columns >= 0) & (columns < size) & (rows >= 0) & (rows < size))
    return rows, columns, inside


def plan_pixel_centres_world(frame, rows, columns, pixels=None):
    size = frame.native_pixels if pixels is None else int(pixels)
    pixel = frame.side_m / size
    u = (np.asarray(columns, dtype=np.float64) + .5) * pixel - frame.side_m / 2
    v = (size - 1 - np.asarray(rows, dtype=np.float64) + .5) * pixel - frame.side_m / 2
    return (np.asarray(frame.centre_xy_m) + u[:, None] * np.asarray(frame.basis_u_xy)
            + v[:, None] * np.asarray(frame.basis_v_xy))


def rasterize_plan(frame, points, *, dot_radius_pixels=2):
    rows, columns, inside = plan_pixels(frame, points)
    occupied = np.zeros((frame.native_pixels, frame.native_pixels), dtype=np.uint8)
    occupied[rows[inside], columns[inside]] = 255
    if dot_radius_pixels:
        size = dot_radius_pixels * 2 + 1
        occupied = cv2.dilate(occupied, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    return (255 - occupied), {"input_points": int(len(points)), "rasterized_points": int(inside.sum()),
                              "dot_radius_pixels": int(dot_radius_pixels),
                              "dot_radius_m": float(dot_radius_pixels * frame.pixel_m)}


def section_frame(identifier, points, axis_xy, *, base_m, extension_m=.15, pixel_m=.01,
                  maximum_pixels=4096):
    points = np.asarray(points, dtype=np.float64)
    axis = np.asarray(axis_xy, dtype=np.float64)
    length = np.linalg.norm(axis)
    if not len(points) or length <= 1e-12 or pixel_m <= 0:
        raise ValueError("Invalid specialist section source or axis")
    axis /= length
    origin = points[:, :2].mean(axis=0)
    along = (points[:, :2] - origin) @ axis
    u_min, u_max = float(along.min()), float(along.max())
    z_min, z_max = float(points[:, 2].min() - extension_m), float(points[:, 2].max() + extension_m)
    width = max(2, int(np.ceil((u_max - u_min) / pixel_m)) + 1)
    height = max(2, int(np.ceil((z_max - z_min) / pixel_m)) + 1)
    effective = max(pixel_m, (u_max - u_min) / max(1, maximum_pixels - 1),
                    (z_max - z_min) / max(1, maximum_pixels - 1))
    width = max(2, int(np.ceil((u_max - u_min) / effective)) + 1)
    height = max(2, int(np.ceil((z_max - z_min) / effective)) + 1)
    return SectionFrame(identifier, tuple(origin), tuple(axis), u_min, z_min, float(effective),
                        width, height, float(base_m), float(extension_m))


def section_pixels(frame, points):
    points = np.asarray(points, dtype=np.float64)
    along = (points[:, :2] - np.asarray(frame.origin_xy_m)) @ np.asarray(frame.axis_xy)
    columns = np.floor((along - frame.u_min_m) / frame.pixel_m).astype(np.int64)
    z = np.floor((points[:, 2] - frame.z_min_m) / frame.pixel_m).astype(np.int64)
    rows = frame.native_height - 1 - z
    inside = ((columns >= 0) & (columns < frame.native_width)
              & (rows >= 0) & (rows < frame.native_height))
    return rows, columns, inside


def rasterize_section(frame, points, *, dot_radius_pixels=1):
    rows, columns, inside = section_pixels(frame, points)
    occupied = np.zeros((frame.native_height, frame.native_width), dtype=np.uint8)
    occupied[rows[inside], columns[inside]] = 255
    if dot_radius_pixels:
        size = dot_radius_pixels * 2 + 1
        occupied = cv2.dilate(occupied, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    return 255 - occupied


def slab_section_windows(frame, image):
    """Apply the declared branch-A padding/crop/Lanczos/window transform.

    Each returned SectionFrame maps its detector pixels directly back to the
    same f64 world section.  Window overlap is limited to the final short tail;
    cross-window duplicate suppression remains a separate decoder step.
    """
    from PIL import Image
    image = np.asarray(image, dtype=np.uint8)
    if image.ndim != 2 or image.shape[0] < 2 or image.shape[1] < 2:
        raise ValueError("Branch A requires a nonempty grayscale section")
    raw_height, raw_width = image.shape
    crop = min((raw_width - 2) // 2, int(np.floor(raw_width * .05)))
    padded = np.pad(image, ((10, 10), (0, 0)), constant_values=255)
    cropped = padded[:, crop:raw_width - crop]
    scale = 1024. / cropped.shape[1]
    resized_height = max(2, int(round(cropped.shape[0] * scale)))
    resized = np.asarray(Image.fromarray(cropped).resize((1024, resized_height), Image.Resampling.LANCZOS),
                         dtype=np.uint8).copy()
    for fraction in (.04, .96):
        column = int(round((resized.shape[1] - 1) * fraction))
        cv2.line(resized, (column, 0), (column, resized.shape[0] - 1), 127, 9)
    if resized_height <= 1024:
        starts = [0]
    else:
        starts = list(range(0, resized_height - 1024 + 1, 1024))
        tail = resized_height - 1024
        if starts[-1] != tail:
            starts.append(tail)
    result = []
    effective = frame.pixel_m / scale
    for index, start in enumerate(starts):
        window = resized[start:min(start + 1024, resized_height)]
        height = len(window)
        z_top = frame.z_min_m + (raw_height + 10 - start / scale) * frame.pixel_m
        z_min = z_top - height * effective
        mapped = SectionFrame(f"{frame.frame_id}:window:{index}", frame.origin_xy_m, frame.axis_xy,
                              frame.u_min_m + crop * frame.pixel_m, float(z_min), float(effective),
                              1024, height, frame.base_m, frame.extension_m)
        result.append((window, mapped, {"padding_top_bottom_pixels": 10,
                                        "horizontal_crop_fraction": .05,
                                        "horizontal_crop_pixels": crop,
                                        "lanczos_width_pixels": 1024,
                                        "lanczos_scale": scale,
                                        "guide_lines": {"fractions": [.04, .96], "gray": 127, "width_pixels": 9},
                                        "window_start_row": start, "window_height": height,
                                        "cross_window_nms_iou": .3,
                                        "lossless_inference_buffer": True}))
    return result


def section_box_world(frame, box_xyxy):
    x1, y1, x2, y2 = map(float, box_xyxy)
    u1 = frame.u_min_m + x1 * frame.pixel_m
    u2 = frame.u_min_m + x2 * frame.pixel_m
    z_top = frame.z_min_m + (frame.native_height - y1) * frame.pixel_m
    z_bottom = frame.z_min_m + (frame.native_height - y2) * frame.pixel_m
    origin, axis = np.asarray(frame.origin_xy_m), np.asarray(frame.axis_xy)
    return {"start": (origin + axis * u1).tolist(), "end": (origin + axis * u2).tolist(),
            "z_min_m": float(min(z_bottom, z_top)), "z_max_m": float(max(z_bottom, z_top))}
