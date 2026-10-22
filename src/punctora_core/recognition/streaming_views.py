"""Bounded original-point blocks, complete physical rasters and core ownership.

A model sees the complete declared physical field, not a randomly thinned or
independently resized fragment. Only source materialization is subdivided.
"""
import cv2
import numpy as np
import time

from .specialist_frames import plan_pixels, section_pixels, SectionFrame


class SourceBox:
    def __init__(self, cloud, index, minimum, maximum, control, point_limit, polygon=None):
        self.cloud, self.index, self.control = cloud, index, control
        self.minimum, self.maximum = np.asarray(minimum), np.asarray(maximum)
        self.polygon = polygon
        self.block_size = min(control.chunk_points, point_limit)
        if self.block_size < 1:
            raise ValueError("Raster source blocks require a positive point limit")

    def _row_blocks(self):
        """Coalesce tiny spatial cells without sorting or dropping any row.

        Per-cell NumPy reads and RSS syscalls otherwise repeat for every plan,
        vote and component pass. The materialization cap still bounds every
        block, including a single cell larger than that cap.
        """
        from .specialist_provider import PunctoraSpecialistProvider
        buffer = np.empty(self.block_size, dtype=np.int64)
        used = 0
        for candidate in PunctoraSpecialistProvider._iter_box_rows(
                self.index, self.minimum, self.maximum):
            if hasattr(self.control, 'source_read_stats'):
                self.control.source_read_stats['cells'] += 1
            begin = 0
            while begin < len(candidate):
                size = min(self.block_size-used, len(candidate)-begin)
                buffer[used:used+size] = candidate[begin:begin+size]
                used += size; begin += size
                if used == self.block_size:
                    yield buffer.copy()
                    used = 0
        if used:
            yield buffer[:used].copy()

    def blocks(self):
        self.control.check()
        for rows in self._row_blocks():
            started = time.monotonic()
            self.control.check()
            points = np.asarray(self.cloud.points[rows], dtype=np.float64)
            keep = np.all((points >= self.minimum) & (points <= self.maximum), axis=1)
            if self.polygon is not None:
                from shapely import contains_xy
                keep &= contains_xy(self.polygon,points[:,0],points[:,1])
            if hasattr(self.control, 'source_read_stats'):
                stats = self.control.source_read_stats
                stats['blocks'] += 1; stats['candidate_points'] += len(rows)
                stats['selected_points'] += int(keep.sum())
                stats['seconds'] += time.monotonic()-started
            if keep.any():
                yield rows[keep], points[keep]


def owned(points, minimum, maximum):
    """Half-open XY cores give every point one owner, including split planes."""
    return np.all((points[:, :2] >= minimum) & (points[:, :2] < maximum), axis=1)


def plan_image(source, frame, radius=2):
    return plan_images(source, [frame], radius)[0]


def plan_images(source, frames, radius=2):
    """Rasterize all physical TTA fields in one lossless source pass."""
    occupied = [np.zeros((frame.native_pixels, frame.native_pixels), dtype=np.uint8) for frame in frames]
    rasterized = [0] * len(frames)
    count = maximum = 0
    for _, points in source.blocks():
        count += len(points); maximum = max(maximum, len(points))
        for i, frame in enumerate(frames):
            rows, columns, inside = plan_pixels(frame, points)
            occupied[i][rows[inside], columns[inside]] = 255
            rasterized[i] += int(inside.sum())
    result = []
    for image, frame, population in zip(occupied, frames, rasterized):
        if radius:
            image = cv2.dilate(image, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1)))
        result.append((255-image, {"input_points": count, "rasterized_points": population,
            "maximum_materialized_points": maximum, "source_partition": "exact_bounded_blocks",
            "dot_radius_pixels": radius, "dot_radius_m": radius * frame.pixel_m}))
    return result


def section_image(source, identifier, axis, origin, base, extension=0., pixel=.01):
    axis = np.asarray(axis, dtype=np.float64)
    axis /= np.linalg.norm(axis)
    origin = np.asarray(origin, dtype=np.float64)
    low, high = np.full(2, np.inf), np.full(2, -np.inf)
    for _, points in source.blocks():
        values = np.column_stack(((points[:, :2] - origin) @ axis, points[:, 2]))
        low = np.minimum(low, values.min(axis=0)); high = np.maximum(high, values.max(axis=0))
    if not np.isfinite(low).all():
        return None, None
    low[1] -= extension; high[1] += extension
    effective = max(pixel, float((high-low).max()) / 4095)
    width, height = np.maximum(2, np.ceil((high-low)/effective).astype(int)+1)
    frame = SectionFrame(identifier, tuple(origin), tuple(axis), float(low[0]), float(low[1]),
                         effective, int(width), int(height), base, extension)
    occupied = np.zeros((height, width), dtype=np.uint8)
    for _, points in source.blocks():
        rows, columns, inside = section_pixels(frame, points)
        occupied[rows[inside], columns[inside]] = 255
    occupied = cv2.dilate(occupied, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return frame, 255 - occupied


def components(source, selector, core_min, core_max, level, branch, tile_id, class_name,
               support_limit=4096):
    """Connected masks from all original points; bounded, explicitly sampled IDs.

    Dense point labels remain lossless in ProposalSet. Component references are
    reproducible evidence examples, not a second copy of every labelled row.
    """
    pixel = .05
    origin = np.floor(np.asarray(core_min) / pixel) * pixel
    size = np.ceil((np.asarray(core_max) - origin) / pixel).astype(int) + 1
    if np.prod(size) > 4_000_000:
        raise ValueError("Component raster exceeds bounded grid allocation")
    occupied = np.zeros(tuple(size[::-1]), dtype=np.uint8)
    def chosen():
        for rows, points in source.blocks():
            keep = selector(rows, points) & owned(points, core_min, core_max)
            if keep.any():
                yield rows[keep], points[keep]
    for _, points in chosen():
        grid = np.floor((points[:, :2]-origin)/pixel + 1e-7).astype(int)
        occupied[grid[:, 1], grid[:, 0]] = 1
    count, labels, stats, _ = cv2.connectedComponentsWithStats(occupied, 8)
    eligible = {i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 6}
    support, populations, z_bounds = {}, {}, {}
    for rows, points in chosen():
        grid = np.floor((points[:, :2]-origin)/pixel + 1e-7).astype(int)
        ids = labels[grid[:, 1], grid[:, 0]]
        for component in sorted(set(ids.tolist()) & eligible):
            keep = ids == component
            values = rows[keep].astype(np.uint64)
            # Fixed-size lowest immutable source-row examples, independent of block order.
            support[component] = np.sort(np.r_[support.get(component, np.empty(0, dtype=np.uint64)), values])[:support_limit]
            populations[component] = populations.get(component, 0) + len(values)
            z = points[keep, 2]
            previous = z_bounds.get(component, (np.inf, -np.inf))
            z_bounds[component] = (min(previous[0], float(z.min())), max(previous[1], float(z.max())))
    result = []
    for component in sorted(eligible):
        y, x = np.nonzero(labels == component)
        centre, size_m, angle = cv2.minAreaRect(np.column_stack((x+.5, y+.5)).astype(np.float32)*pixel)
        rectangle = cv2.boxPoints((centre, tuple(max(float(s)+pixel, pixel) for s in size_m), angle)).astype(np.float64)+origin
        result.append({"id": f"{branch}:{tile_id}:{component}", "branch": branch, "class": class_name,
            "status": "proposed", "polygon_xy_m": rectangle.tolist(),
            "z_min_m": level["bottom_m"], "z_max_m": level["top_m"],
            "observed_z_bounds_m": list(z_bounds.get(component, (level["bottom_m"], level["top_m"]))),
            "support_points": populations.get(component, 0), "support_state": "point_gated_model_view_candidate",
            "source_support_scope": "up_to_4096_source_row_examples; dense_labels_remain_lossless",
            "display_scope": "minimum one-cell envelope; refit original points before geometry",
            "geometry_authority": "review_only", "core_min_xy_m": list(core_min), "core_max_xy_m": list(core_max),
            "_source_rows": support.get(component, np.empty(0, dtype=np.uint64))})
    return result


def stitch_proposals(items, support, check=lambda: None):
    """Stable same-branch seam joins, never bridge a pier or a perpendicular wall."""
    from copy import deepcopy
    from shapely.geometry import Polygon
    from ..annotation_io import content_digest
    groups = []
    for original in sorted(items, key=lambda v: v['id']):
        check()
        item = deepcopy(original)
        shape = Polygon(item['polygon_xy_m'])
        if not shape.is_valid or shape.area <= 0:
            raise ValueError('Invalid specialist proposal polygon before stitching')
        matches, ids = [], [item['id']]
        for i, (previous, other, members) in enumerate(groups):
            if (item.get('branch') != previous.get('branch') or item['class'] != previous['class']
                    or abs(item['z_min_m']-previous['z_min_m']) > .08
                    or abs(item['z_max_m']-previous['z_max_m']) > .08
                    or shape.distance(other) > .055):
                continue
            if item['class'] in {'window','door','opening'} and not shape.buffer(1e-8).intersects(other):
                continue  # A narrow opaque pier is not a seam to be stitched.
            observed = item.get('observed_z_bounds_m')
            prior = previous.get('observed_z_bounds_m')
            if (observed is None) != (prior is None):
                continue  # Partial bounds cannot describe the unknown member.
            if (observed is not None and prior is not None
                    and max(observed[0], prior[0]) > min(observed[1], prior[1]) + .08):
                continue  # Shared level bounds do not establish shared measured height.
            combined = shape.union(other)
            # A rotated rectangle may describe a straight seam only. Do not
            # turn touching L-shaped components into an invented diagonal wall.
            # Check the growing aggregate, not each pair against the input.
            if combined.minimum_rotated_rectangle.area > combined.area*1.15 + .005:
                continue
            matches.append(i)
            shape = combined
            ids.extend(members)
            item['z_min_m'] = min(item['z_min_m'], previous['z_min_m'])
            item['z_max_m'] = max(item['z_max_m'], previous['z_max_m'])
            item['support_points'] = item.get('support_points',0)+previous.get('support_points',0)
            if observed is not None and prior is not None:
                item['observed_z_bounds_m'] = [min(observed[0], prior[0]), max(observed[1], prior[1])]
        for i in reversed(matches):
            groups.pop(i)
        groups.append((item, shape, sorted(ids)))
    result, references = [], {}
    for item, shape, ids in groups:
        if len(ids)>1:
            rectangle = shape.minimum_rotated_rectangle
            item['polygon_xy_m'] = [list(p) for p in list(rectangle.exterior.coords)[:-1]]
            item['id'] = 'specialist:stitched:'+content_digest(ids)[:24]
            item['stitched_from'] = ids
        item['source_support'] = {'kind':'specialist_support_index','key':item['id']}
        references[item['id']] = np.unique(np.concatenate([support.get(i,np.empty(0,dtype='<u8')) for i in ids]))[:4096]
        result.append(item)
    return sorted(result,key=lambda v:v['id']), references
