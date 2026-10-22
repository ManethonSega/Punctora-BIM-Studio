"""Deterministic XY tiles with original-point normal halos and exact source IDs."""
from dataclasses import dataclass
import numpy as np

from ..cropping import crop_mask
from ..spatial_index import SpatialPointIndex
from .contracts import ProviderUnavailable


@dataclass(frozen=True)
class TileSettings:
    size_m: float = 8.
    overlap_m: float = .3
    normal_radius_m: float = .3
    index_cell_m: float = .25
    maximum_context_points: int = 250_000
    maximum_tiles: int = 4096
    adaptive_partition: bool = False
    vertical_overlap_m: float = .3
    minimum_core_m: float = .25
    maximum_subdivision_depth: int = 16
    separate_normal_context: bool = False

    def validate(self):
        values = (self.size_m, self.overlap_m, self.normal_radius_m, self.index_cell_m,
                  self.vertical_overlap_m, self.minimum_core_m)
        if not np.isfinite(values).all() or self.size_m <= 0 or self.index_cell_m <= 0:
            raise ValueError("Tile lengths must be finite and positive")
        if (self.overlap_m < 0 or self.vertical_overlap_m < 0 or self.normal_radius_m <= 0
                or self.minimum_core_m <= 0 or 2 * self.overlap_m >= self.size_m):
            raise ValueError("Invalid overlap or normal radius")
        if abs(self.size_m / self.index_cell_m - round(self.size_m / self.index_cell_m)) > 1e-8:
            raise ValueError("Tile size must be an integral number of index cells")
        if (not isinstance(self.adaptive_partition, bool) or not isinstance(self.separate_normal_context, bool)
                or any(isinstance(v, bool) or not isinstance(v, int) or v < 1
                       for v in (self.maximum_context_points, self.maximum_tiles,
                                 self.maximum_subdivision_depth))):
            raise ValueError("Tile limits must be positive integers")
        return self


@dataclass
class Tile:
    id: str
    cell_xy: tuple
    context_rows: np.ndarray
    vote_mask: np.ndarray
    points: np.ndarray
    working_rows: np.ndarray
    scan_ids: np.ndarray
    record_ids: np.ndarray
    core_min_xy: list
    core_max_xy: list
    core_min_z: float
    core_max_z: float
    partition_depth: int
    context_overlap_xyz: list
    vote_overlap_xyz: list
    normal_points: np.ndarray | None = None


@dataclass(frozen=True)
class TileRegion:
    id: str
    root_cell_xy: tuple
    minimum: tuple
    maximum: tuple
    depth: int = 0


class TileOverflow(Exception):
    """Internal signal requesting exact spatial subdivision, never thinning."""
    def __init__(self, region, children, context_points):
        super().__init__(f"Tile {region.id} has more than {context_points:,} context points")
        self.region, self.children, self.context_points = region, children, context_points


class TileIndex:
    """Reuse the exact sorted point index, no cloud-sized coordinate copies."""
    def __init__(self, cloud, settings, budget, chunk_points, directory, check=lambda: None):
        self.cloud, self.settings, self.check = cloud, settings.validate(), check
        self.chunk_points = chunk_points
        self.budget = budget
        self.index = SpatialPointIndex.build(cloud, settings.index_cell_m, budget, chunk_points,
                                             progress=lambda *_: check(), scratch_directory=directory)
        cells_per_tile = int(round(settings.size_m / settings.index_cell_m))
        occupied, z_min, z_max = set(), None, None
        try:
            for cells, _, _ in self.index.runs:
                if len(cells):
                    local_min, local_max = int(cells["z"].min()), int(cells["z"].max())
                    z_min = local_min if z_min is None else min(z_min, local_min)
                    z_max = local_max if z_max is None else max(z_max, local_max)
                for begin in range(0, len(cells), chunk_points):
                    check()
                    block = cells[begin:begin + chunk_points]
                    xy = np.unique(np.column_stack((block["x"] // cells_per_tile, block["y"] // cells_per_tile)), axis=0)
                    occupied.update(map(tuple, xy.tolist()))
                    if len(occupied) > settings.maximum_tiles:
                        raise ProviderUnavailable("Recognition crop exceeds the explicit tile limit; partition it")
            self.tiles = sorted(occupied)
            self.z_bounds = ((z_min or 0) * settings.index_cell_m,
                             ((z_max or 0) + 1) * settings.index_cell_m)
        except BaseException:
            self.close()
            raise

    def _region(self, value):
        if isinstance(value, TileRegion):
            return value
        cell_xy = tuple(map(int, value))
        low = np.asarray(cell_xy, dtype=np.float64) * self.settings.size_m
        return TileRegion(f"{cell_xy[0]}:{cell_xy[1]}", cell_xy,
                          (float(low[0]), float(low[1]), float(self.z_bounds[0])),
                          (float(low[0] + self.settings.size_m),
                           float(low[1] + self.settings.size_m), float(self.z_bounds[1])))

    def _split(self, region):
        settings = self.settings
        low, high = np.asarray(region.minimum), np.asarray(region.maximum)
        spans = high - low
        eligible = spans / 2 >= settings.minimum_core_m - 1e-12
        if region.depth >= settings.maximum_subdivision_depth or not eligible.any():
            return []
        context = np.asarray([settings.overlap_m + settings.normal_radius_m,
                              settings.overlap_m + settings.normal_radius_m,
                              settings.vertical_overlap_m + settings.normal_radius_m])
        priority = np.where(eligible, spans / np.maximum(context, settings.minimum_core_m), -np.inf)
        axis = int(np.argmax(priority))
        middle = (low[axis] + high[axis]) / 2
        children = []
        for side in range(2):
            child_low, child_high = low.copy(), high.copy()
            if side == 0:
                child_high[axis] = middle
            else:
                child_low[axis] = middle
            children.append(TileRegion(f"{region.id}~{axis}{side}", region.root_cell_xy,
                                       tuple(map(float, child_low)), tuple(map(float, child_high)),
                                       region.depth + 1))
        return children

    def get(self, cell_xy, crop):
        self.check()
        settings, cell = self.settings, self.settings.index_cell_m
        region = self._region(cell_xy)
        low, high = np.asarray(region.minimum), np.asarray(region.maximum)
        configured_overlap = np.asarray([settings.overlap_m, settings.overlap_m,
                                         settings.vertical_overlap_m])
        context_overlap = (np.minimum(configured_overlap, (high - low) / 4)
                           if region.depth else configured_overlap)
        # Exact child cores partition an overflowing root. They retain bounded
        # context for normals/model receptive fields but do not multiply votes
        # across every internal split boundary.
        vote_overlap = np.zeros(3) if region.depth else configured_overlap
        halo = context_overlap if settings.separate_normal_context else context_overlap + settings.normal_radius_m
        minimum, maximum = np.floor((low - halo) / cell), np.floor((high + halo) / cell)
        pieces, count = [], 0
        for cells, starts, rows in self.index.runs:
            self.check()
            left, right = np.searchsorted(cells["x"], minimum[0]), np.searchsorted(cells["x"], maximum[0], side="right")
            block = cells[left:right]
            positions = np.flatnonzero((block["y"] >= minimum[1]) & (block["y"] <= maximum[1])
                                       & (block["z"] >= minimum[2]) & (block["z"] <= maximum[2])) + left
            for position in positions:
                end = starts[position + 1] if position + 1 < len(starts) else len(rows)
                candidate = rows[starts[position]:end]
                for begin in range(0, len(candidate), self.chunk_points):
                    self.check()
                    block_rows = candidate[begin:begin + self.chunk_points]
                    candidate_points = self.cloud.points[block_rows]
                    piece = block_rows[np.all((candidate_points >= low - halo)
                                              & (candidate_points <= high + halo), axis=1)]
                    if not len(piece):
                        continue
                    count += len(piece)
                    if count > settings.maximum_context_points:
                        children = self._split(region) if settings.adaptive_partition else []
                        if children:
                            raise TileOverflow(region, children, count)
                        spans = np.asarray(region.maximum) - np.asarray(region.minimum)
                        raise ProviderUnavailable(
                            "Tile original-point halo exceeds the declared budget after exact adaptive partition "
                            f"(tile {region.id}, depth {region.depth}, core spans {spans.tolist()} m, "
                            f"more than {settings.maximum_context_points:,} points); never silently decimate")
                    pieces.append(piece)
        if not pieces:
            return None
        rows = np.concatenate(pieces)
        p = self.cloud.points[rows]
        scan = self.cloud.scan_index[rows].astype("<u8", copy=False)
        records = self.cloud.source_record_index[rows].astype("<u8", copy=False)
        working = (self.cloud.working_index[rows] if self.cloud.working_index is not None else rows).astype("<u8", copy=False)
        order = np.lexsort((working, records, scan))
        rows, p, scan, records, working = rows[order], p[order], scan[order], records[order], working[order]
        if len(rows) > 1 and np.any((scan[1:] == scan[:-1]) & (records[1:] == records[:-1])):
            raise ValueError("Duplicate original scan/record identity inside a tile")
        vote = np.all((p >= low - vote_overlap) & (p < high + vote_overlap), axis=1)
        vote &= crop_mask(p, crop)
        if not vote.any():
            return None
        for array in (p, working, scan, records):
            array.flags.writeable = False
        normal_points = None
        if settings.separate_normal_context:
            # Normals query original neighbours, but these neighbours never
            # become PTv3 voxels or duplicate votes. Budgeted independently.
            from .streaming_views import SourceBox
            class Control:
                chunk_points = self.chunk_points
                check = staticmethod(self.check)
            source = SourceBox(self.cloud, self.index, low-halo-settings.normal_radius_m,
                               high+halo+settings.normal_radius_m, Control(), self.chunk_points)
            parts, total = [], 0
            for _, block in source.blocks():
                total += len(block)
                if total*128 > self.budget:
                    raise ProviderUnavailable('Original-neighbour normal context exceeds its RAM budget')
                parts.append(block)
            normal_points = np.concatenate(parts) if parts else p
        return Tile(region.id, region.root_cell_xy, rows.astype("<u8"), vote, p, working, scan, records,
                    low[:2].tolist(), high[:2].tolist(), float(low[2]), float(high[2]), region.depth,
                    context_overlap.tolist(), vote_overlap.tolist(), normal_points)

    def close(self):
        self.index.close()
