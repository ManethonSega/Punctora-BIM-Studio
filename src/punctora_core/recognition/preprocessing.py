"""Original-neighbour PCA and deterministic representative/inverse mapping.

    Explicit experiment version, not a claim of unpublished training parity.
    Geometry remains f64. Only the isolated model's features become float32.
    """
import numpy as np
from scipy.spatial import cKDTree

PREPROCESSING = {"version": "punctora-ptv3-original-normal-v1", "grid_m": .06,
                 "normal_radius_m": .30, "normal_max_nn": 30,
                 "normal_sign": "largest_absolute_component_positive",
                 "normal_source": "complete original context, not preview",
                 "normal_degenerate": "unknown, no fabricated normal",
                 "translation": "XY mean and Z minimum of voting points",
                 "representative": "first in immutable scan/record order",
                 "feature_channels": ["normal_x", "normal_y", "normal_z"]}


def original_normals(context, selected, radius=.3, max_nn=30, check=lambda: None, query_points=None, workers=1):
    context = np.asarray(context, dtype=np.float64)
    tree = cKDTree(context)
    queries = context[selected] if query_points is None else np.asarray(query_points, dtype=np.float64)
    normals = np.zeros((len(queries), 3), dtype=np.float64)
    valid = np.zeros(len(queries), dtype=bool)
    neighbours = min(max_nn, len(context))
    for begin in range(0, len(queries), 4096):
        check()
        query = queries[begin:begin + 4096]
        distance, indices = tree.query(query, k=neighbours, distance_upper_bound=radius, workers=workers)
        if neighbours == 1:
            distance, indices = distance[:, None], indices[:, None]
        keep = np.isfinite(distance)
        values = context[np.minimum(indices, len(context) - 1)] - query[:, None, :]
        values *= keep[..., None]
        count = keep.sum(axis=1)
        mean = values.sum(axis=1) / np.maximum(count, 1)[:, None]
        centred = (values - mean[:, None, :]) * keep[..., None]
        covariance = np.einsum("nki,nkj->nij", centred, centred) / np.maximum(count, 1)[:, None, None]
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        normal = eigenvectors[:, :, 0]
        major = np.abs(normal).argmax(axis=1)
        sign = np.where(normal[np.arange(len(normal)), major] < 0, -1., 1.)
        supported = (count >= 3) & (eigenvalues[:, 1] > 1e-12)
        normals[begin:begin + len(query)] = normal * sign[:, None] * supported[:, None]
        valid[begin:begin + len(query)] = supported
    return normals, valid


def prepare_model_input(points, vote_mask, check=lambda: None):
    selected = np.flatnonzero(vote_mask)
    normals, valid = original_normals(points, selected, check=check)
    selected, normals = selected[valid], normals[valid]
    if not len(selected):
        return None
    original = np.asarray(points[selected], dtype=np.float64)
    origin = np.array([original[:, 0].mean(), original[:, 1].mean(), original[:, 2].min()])
    shifted = original - origin
    grid = np.floor(shifted / PREPROCESSING["grid_m"])
    if np.any(grid < -(2**31)) or np.any(grid >= 2**31):
        raise ValueError("Model grid coordinates exceed int32 bounds")
    grid = grid.astype(np.int32)
    unique, representative, inverse = np.unique(grid, axis=0, return_index=True, return_inverse=True)
    return {"coord": shifted[representative].astype(np.float32), "grid_coord": unique,
            "feat": normals[representative].astype(np.float32), "selected": selected,
            "inverse": inverse, "origin_m": origin}
