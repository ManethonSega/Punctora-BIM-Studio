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

    def validate(self):
        values = (self.size_m, self.overlap_m, self.normal_radius_m, self.index_cell_m)
        if not np.isfinite(values).all() or self.size_m <= 0 or self.index_cell_m <= 0:
            raise ValueError("Tile lengths must be finite and positive")
        if self.overlap_m < 0 or self.normal_radius_m <= 0 or 2 * self.overlap_m >= self.size_m:
            raise ValueError("Invalid overlap or normal radius")
        if abs(self.size_m / self.index_cell_m - round(self.size_m / self.index_cell_m)) > 1e-8:
            raise ValueError("Tile size must be an integral number of index cells")
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 1
               for v in (self.maximum_context_points, self.maximum_tiles)):
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


class TileIndex:
    """Reuse the exact sorted point index, no cloud-sized coordinate copies."""
    def __init__(self, cloud, settings, budget, chunk_points, directory, check=lambda: None):
        self.cloud, self.settings, self.check = cloud, settings.validate(), check
        self.index = SpatialPointIndex.build(cloud, settings.index_cell_m, budget, chunk_points,
                                             progress=lambda *_: check(), scratch_directory=directory)
        cells_per_tile = int(round(settings.size_m / settings.index_cell_m))
        occupied = set()
        try:
            for cells, _, _ in self.index.runs:
                for begin in range(0, len(cells), chunk_points):
                    check()
                    block = cells[begin:begin + chunk_points]
                    xy = np.unique(np.column_stack((block["x"] // cells_per_tile, block["y"] // cells_per_tile)), axis=0)
                    occupied.update(map(tuple, xy.tolist()))
                    if len(occupied) > settings.maximum_tiles:
                        raise ProviderUnavailable("Recognition crop exceeds the explicit tile limit; partition it")
            self.tiles = sorted(occupied)
        except BaseException:
            self.close()
            raise

    def get(self, cell_xy, crop):
        self.check()
        settings, cell = self.settings, self.settings.index_cell_m
        low = np.asarray(cell_xy, dtype=np.float64) * settings.size_m
        high = low + settings.size_m
        halo = settings.overlap_m + settings.normal_radius_m
        minimum, maximum = np.floor((low - halo) / cell), np.floor((high + halo) / cell)
        pieces, count = [], 0
        for cells, starts, rows in self.index.runs:
            self.check()
            left, right = np.searchsorted(cells["x"], minimum[0]), np.searchsorted(cells["x"], maximum[0], side="right")
            block = cells[left:right]
            positions = np.flatnonzero((block["y"] >= minimum[1]) & (block["y"] <= maximum[1])) + left
            for position in positions:
                end = starts[position + 1] if position + 1 < len(starts) else len(rows)
                piece = rows[starts[position]:end]
                count += len(piece)
                if count > settings.maximum_context_points:
                    raise ProviderUnavailable("Tile original-point halo exceeds the declared budget; never silently decimate")
                pieces.append(piece)
        if not pieces:
            return None
        rows = np.concatenate(pieces)
        p = self.cloud.points[rows]
        keep = np.all((p[:, :2] >= low - halo) & (p[:, :2] <= high + halo), axis=1)
        rows, p = rows[keep], p[keep]
        scan = self.cloud.scan_index[rows].astype("<u8", copy=False)
        records = self.cloud.source_record_index[rows].astype("<u8", copy=False)
        working = (self.cloud.working_index[rows] if self.cloud.working_index is not None else rows).astype("<u8", copy=False)
        order = np.lexsort((working, records, scan))
        rows, p, scan, records, working = rows[order], p[order], scan[order], records[order], working[order]
        if len(rows) > 1 and np.any((scan[1:] == scan[:-1]) & (records[1:] == records[:-1])):
            raise ValueError("Duplicate original scan/record identity inside a tile")
        vote = np.all((p[:, :2] >= low - settings.overlap_m) & (p[:, :2] <= high + settings.overlap_m), axis=1)
        vote &= crop_mask(p, crop)
        if not vote.any():
            return None
        for array in (p, working, scan, records):
            array.flags.writeable = False
        return Tile(f"{cell_xy[0]}:{cell_xy[1]}", cell_xy, rows.astype("<u8"), vote, p, working, scan, records,
                    low.tolist(), high.tolist())

    def close(self):
        self.index.close()
