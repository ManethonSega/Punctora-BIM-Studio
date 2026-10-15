"""Deterministic 40-input PTv3 ONNX index construction for branch I."""
from dataclasses import dataclass
import itertools
import numpy as np

from .preprocessing import original_normals


GRID_M = .06
PATCH = 128
BLOCK_COUNTS = (2, 2, 2, 6, 2)
CURVE_NAMES = ("morton", "morton_transposed", "hilbert", "hilbert_transposed")


@dataclass(frozen=True)
class PointModelView:
    feed: dict
    tile_rows: np.ndarray
    voxel_inverse: np.ndarray
    origin_m: np.ndarray
    diagnostics: dict


def morton(grid, depth):
    grid = np.asarray(grid, dtype=np.int64)
    result = np.zeros(len(grid), dtype=np.int64)
    for bit in range(depth):
        for dimension in range(3):
            result |= ((grid[:, dimension] >> bit) & 1) << (3 * bit + 2 - dimension)
    return result


def hilbert(grid, depth):
    """Reviewed Pointcept bit-array Hilbert encoding, vectorised and stable."""
    grid = np.asarray(grid, dtype=np.int64)
    shifts = np.arange(depth - 1, -1, -1, dtype=np.int64)
    gray = ((grid[:, :, None] >> shifts) & 1).astype(bool)
    for bit in range(depth):
        for dimension in range(3):
            active = gray[:, dimension, bit].copy()
            gray[:, 0, bit + 1:] ^= active[:, None]
            flip = (~active[:, None]) & (gray[:, 0, bit + 1:] ^ gray[:, dimension, bit + 1:])
            gray[:, dimension, bit + 1:] ^= flip
            gray[:, 0, bit + 1:] ^= flip
    bits = np.logical_xor.accumulate(gray.swapaxes(1, 2).reshape(len(grid), -1), axis=1)
    weights = np.int64(1) << np.arange(bits.shape[1] - 1, -1, -1, dtype=np.int64)
    return (bits.astype(np.int64) * weights).sum(axis=1)


def serialized_orders(grid, depth):
    transposed = grid[:, [1, 0, 2]]
    return np.stack((morton(grid, depth), morton(transposed, depth),
                     hilbert(grid, depth), hilbert(transposed, depth)))


def padded_rows(count, patch=PATCH):
    if count < 1:
        raise ValueError("PTv3 stages cannot be empty")
    width = min(count, patch)
    padded_count = (count + width - 1) // width * width
    rows = np.arange(padded_count, dtype=np.int64)
    remainder = count % width
    if remainder:
        # Native tail convention repeats the matching rows of the preceding
        # complete window.  It neither wraps to zero nor fabricates a row.
        rows[padded_count - width + remainder:padded_count] = rows[
            padded_count - 2 * width + remainder:padded_count - width]
    if np.any(rows < 0) or np.any(rows >= count):
        raise ValueError("Invalid PTv3 tail padding")
    return width, rows


def kernel_map(grid, side, check=lambda: None):
    """Native column order: grid column 0 slowest, column 2 fastest."""
    grid = np.asarray(grid, dtype=np.int64)
    count, radius = len(grid), side // 2
    offsets = np.asarray(list(itertools.product(range(-radius, radius + 1), repeat=3)), dtype=np.int64)
    # Sorted structured coordinates preserve exact integer equality without
    # Python's N x 125 tuple/hash loop. No float or packed-key overflow.
    dtype = np.dtype([('x','<i8'),('y','<i8'),('z','<i8')])
    keys = np.ascontiguousarray(grid).view(dtype).ravel()
    order = np.argsort(keys, kind='stable'); sorted_keys = keys[order]
    result = np.full((count, side ** 3), count, dtype=np.int64)
    for column, offset in enumerate(offsets):
        check()
        wanted = np.ascontiguousarray(grid+offset).view(dtype).ravel()
        positions = np.searchsorted(sorted_keys, wanted)
        valid = positions < count
        valid &= sorted_keys[np.minimum(positions,count-1)] == wanted
        result[valid,column] = order[positions[valid]]
    if not np.array_equal(result[:, side ** 3 // 2], np.arange(count, dtype=np.int64)):
        raise ValueError("PTv3 kernel centre does not map every voxel to itself")
    return result


def _validate_windows(window, inverse, count):
    if (window.dtype != np.int64 or inverse.dtype != np.int64 or inverse.shape != (count,)
            or np.any(window < 0) or np.any(window >= count)
            or np.any(inverse < 0) or np.any(inverse >= window.size)):
        raise ValueError("Malformed PTv3 attention window")
    if not np.array_equal(window.ravel()[inverse], np.arange(count, dtype=np.int64)):
        raise ValueError("PTv3 attention inverse does not restore every stage row")


def build_index_inputs(grid, features, *, memory_budget_bytes=None, check=lambda: None):
    grid = np.ascontiguousarray(grid, dtype=np.int64)
    features = np.ascontiguousarray(features, dtype=np.float32)
    if (grid.ndim != 2 or grid.shape[1] != 3 or features.shape != grid.shape
            or not np.isfinite(features).all() or len(grid) < 1):
        raise ValueError("PTv3 requires finite N x 3 features and voxel coordinates")
    grid = grid - grid.min(axis=0)
    if np.any(grid < 0) or len(np.unique(grid, axis=0)) != len(grid):
        raise ValueError("PTv3 canonical coordinates must be unique and nonnegative")
    depth = max(1, (int(grid.max()) + 1).bit_length())
    if depth > 16:
        raise ValueError("PTv3 serialization depth exceeds the reviewed 16-bit bound")
    # Stage-zero maps dominate.  Refuse before allocating when their lower
    # bound alone would consume more than half the owned working budget.
    lower_bound = len(grid) * (3 + 27 + 125 + 8) * 8 + features.nbytes
    if memory_budget_bytes is not None and lower_bound > memory_budget_bytes // 2:
        raise MemoryError("PTv3 index lower bound exceeds half the recognition working budget; subdivide the tile")
    codes = serialized_orders(grid, depth)
    feed = {"feat": features}
    stage_sizes = []
    for stage in range(5):
        check()
        count = len(grid)
        stage_sizes.append(count)
        feed[f"s{stage}_gc"] = np.ascontiguousarray(grid, dtype=np.int64)
        feed[f"s{stage}_k3"] = kernel_map(grid, 3,check)
        if stage == 0:
            feed["s0_k5"] = kernel_map(grid, 5,check)
        order = np.argsort(codes, axis=1, kind="stable")
        width, padding = padded_rows(count)
        order_count = min(4, BLOCK_COUNTS[stage])
        for order_index in range(order_count):
            ordered = order[order_index]
            rank = np.empty(count, dtype=np.int64)
            rank[ordered] = np.arange(count, dtype=np.int64)
            window = ordered[padding].reshape(-1, width)
            inverse = rank.copy()
            _validate_windows(window, inverse, count)
            feed[f"s{stage}_o{order_index}_win"] = np.ascontiguousarray(window)
            feed[f"s{stage}_o{order_index}_inv"] = np.ascontiguousarray(inverse)
        if stage == 4:
            continue
        pooling_depth = 1 if depth >= 1 else 0
        down_codes = codes >> (3 * pooling_depth)
        _, cluster, counts = np.unique(down_codes[0], return_inverse=True, return_counts=True)
        cluster = cluster.astype(np.int64)
        ordered_clusters = np.argsort(cluster, kind="stable")
        heads = ordered_clusters[np.r_[0, np.cumsum(counts)[:-1]]]
        parent = grid[heads] >> pooling_depth
        if not np.array_equal(parent[cluster], grid >> pooling_depth):
            raise ValueError("PTv3 pool clusters disagree with parent coordinates")
        feed[f"p{stage}_cluster"] = np.ascontiguousarray(cluster)
        grid, codes, depth = parent, down_codes[:, heads], depth - pooling_depth
    validate_index_inputs(feed)
    return feed, stage_sizes


def validate_index_inputs(feed):
    expected = {"feat"}
    for stage in range(5):
        expected.update({f"s{stage}_gc", f"s{stage}_k3"})
        if stage == 0:
            expected.add("s0_k5")
        for order_index in range(min(4, BLOCK_COUNTS[stage])):
            expected.update({f"s{stage}_o{order_index}_win", f"s{stage}_o{order_index}_inv"})
        if stage < 4:
            expected.add(f"p{stage}_cluster")
    if set(feed) != expected or len(feed) != 40:
        raise ValueError("Branch I requires exactly one feature and 39 index arrays")
    if feed["feat"].dtype != np.float32 or feed["feat"].ndim != 2 or feed["feat"].shape[1] != 3:
        raise ValueError("Branch I feature tensor must be contiguous float32 N x 3")
    for name, value in feed.items():
        if not value.flags.c_contiguous:
            raise ValueError("Branch I arrays must be contiguous")
        if name != "feat" and value.dtype != np.int64:
            raise ValueError("Branch I index arrays must be int64")
    for stage in range(5):
        count = len(feed[f"s{stage}_gc"])
        grid = feed[f"s{stage}_gc"]
        if grid.shape != (count, 3) or np.any(grid < 0) or len(np.unique(grid, axis=0)) != count:
            raise ValueError("Branch I stage grids must be unique nonnegative N x 3 arrays")
        for side in (3, 5) if stage == 0 else (3,):
            values = feed[f"s{stage}_k{side}"]
            if values.shape != (count, side ** 3) or np.any(values < 0) or np.any(values > count):
                raise ValueError("Branch I kernel indices must use the stage-size sentinel")
            if not np.array_equal(values[:, side ** 3 // 2], np.arange(count)):
                raise ValueError("Branch I kernel centre is invalid")
        for order_index in range(min(4, BLOCK_COUNTS[stage])):
            _validate_windows(feed[f"s{stage}_o{order_index}_win"],
                              feed[f"s{stage}_o{order_index}_inv"], count)
        if stage < 4:
            parent_count = len(feed[f"s{stage + 1}_gc"])
            clusters = feed[f"p{stage}_cluster"]
            if clusters.shape != (count,) or np.any(clusters < 0) or np.any(clusters >= parent_count):
                raise ValueError("Branch I pool cluster is out of range")
    return feed


def prepare_point_model_view(tile, control):
    """Stable source-key centring and representative selection.

    Geometry remains f64.  Only the branch-I model view is float32; tile rows
    map every model result back to the immutable tile/source arrays.
    """
    count = len(tile.points)
    order = np.lexsort((tile.working_rows, tile.record_ids, tile.scan_ids))
    scan, record = tile.scan_ids[order], tile.record_ids[order]
    if len(order) > 1 and np.any((scan[1:] == scan[:-1]) & (record[1:] == record[:-1])):
        raise ValueError("Duplicate source identity before specialist centring")
    points = np.asarray(tile.points[order], dtype=np.float64)
    # Adapter v2 computes exactly the feature normals consumed by the graph,
    # once per source-key-stable voxel representative, not once per dense row.
    origin = np.array([points[:,0].mean(),points[:,1].mean(),points[:,2].min()],dtype=np.float64)
    shifted = points - origin
    grid = np.floor(shifted / GRID_M).astype(np.int64)
    grid -= grid.min(axis=0)
    _, representative, inverse = np.unique(grid, axis=0, return_index=True, return_inverse=True)
    context = getattr(tile,'normal_points',None)
    context = points if context is None else context
    normals, valid = original_normals(context, np.empty(0,dtype=int), query_points=points[representative],
                                      radius=.30,max_nn=30,check=control.check,
                                      workers=getattr(control, 'cpu_workers', 1))
    if not valid.any():
        return None
    selected = np.flatnonzero(valid[inverse])
    voxel_grid = grid[representative][valid]
    remap = np.full(len(representative),-1,dtype=np.int64); remap[valid]=np.arange(valid.sum())
    inverse = remap[inverse[selected]]
    voxel_features = normals[valid].astype(np.float32)
    feed, stages = build_index_inputs(voxel_grid, voxel_features,
                                      memory_budget_bytes=control.working_budget, check=control.check)
    tile_rows = order[selected].astype(np.int64)
    return PointModelView(feed, tile_rows, inverse.astype(np.int64), origin,
                          {"model_view_points": int(len(selected)), "model_voxels": int(len(voxel_grid)),
                           "original_context_points": int(count), "normal_context_points": int(len(context)),
                           "normal_queries": int(len(representative)), "degenerate_normals": int(count - len(selected)),
                           "stage_populations": stages, "grid_m": GRID_M,
                           "normal_recipe": "v2 source-key voxel representative, original-neighbour PCA, largest-absolute-component positive",
                           "source_order": "scan_id, record_id, working_row before centring and representatives"})
