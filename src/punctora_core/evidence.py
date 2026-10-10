"""Original-record wall fitting and recomputable, bounded evidence selectors."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from .sampling import point_batches


def _working_rows(cloud, indices):
    return cloud.working_index[indices] if cloud.working_index is not None else indices


def face_selection(points, face, radius, endpoint_margin):
    a, b = np.asarray(face["start"]), np.asarray(face["end"])
    length = np.linalg.norm(b-a)
    direction = (b-a)/length
    normal = np.array([-direction[1], direction[0]])
    mask = (points[:, 2] >= face["z_min"]) & (points[:, 2] <= face["z_max"])
    rows = np.flatnonzero(mask)
    xy = points[rows, :2]-a
    along, local_residual = xy@direction, xy@normal
    residual = np.zeros(len(points),float)
    residual[rows] = local_residual
    mask[rows] = ((np.abs(local_residual) <= radius)&(along >= -endpoint_margin)&(along <= length+endpoint_margin))
    return mask, residual


def _refine_face(points, face, radius, margin, chunk_points):
    """Fit XY covariance on original records without collecting all support."""
    anchor = np.asarray(face["start"])
    histogram = np.zeros(257, dtype=np.int64)
    edges = np.linspace(-radius, radius, len(histogram)+1)
    for batch, _ in point_batches(points, chunk_points):
        mask, residual = face_selection(batch, face, radius, margin)
        histogram += np.histogram(residual[mask], bins=edges)[0]
    if histogram.sum() < 6:
        return face
    centres = (edges[:-1]+edges[1:])/2
    median_index = np.searchsorted(np.cumsum(histogram), (histogram.sum()+1)//2)
    median = centres[median_index]
    deviations = np.abs(centres-median)
    order = np.argsort(deviations, kind="stable")
    mad_index = np.searchsorted(np.cumsum(histogram[order]), (histogram.sum()+1)//2)
    trim = max(radius/5, 3*deviations[order[mad_index]])
    count, sums, products = 0, np.zeros(2), np.zeros((2, 2))
    for batch, _ in point_batches(points, chunk_points):
        mask, residual = face_selection(batch, face, radius, margin)
        mask &= np.abs(residual-median) <= trim
        xy = batch[mask, :2]-anchor
        count += len(xy)
        sums += xy.sum(axis=0)
        products += xy.T @ xy
    if count < 6:
        return face
    centre = sums/count
    values, vectors = np.linalg.eigh(products/count - np.outer(centre, centre))
    if values[-1] <= 1e-12:
        return face
    direction = vectors[:, -1]
    original_direction = np.asarray(face["end"])-anchor
    if direction @ original_direction < 0:
        direction *= -1
    centre += anchor
    result = {**face, "start": centre.tolist(), "end": (centre+direction*np.linalg.norm(original_direction)).tolist(),
              "original_inlier_fit_points":count, "original_plane_fit_rmse_m":float(np.sqrt(max(0.,values[0])))}
    # Use the original proposal's finite interval for refinement, so unrelated
    # collinear walls elsewhere cannot extend this candidate.
    low, high = np.inf, -np.inf
    for batch, _ in point_batches(points, chunk_points):
        original, residual = face_selection(batch, face, radius, margin)
        normal = np.array([-direction[1], direction[0]])
        # Apply the robust gate to the refitted plane, not the slightly skewed
        # raster proposal, so a clean observed endpoint is not trimmed away.
        keep = original & (np.abs((batch[:, :2]-centre) @ normal) <= trim)
        if keep.any():
            along = (batch[keep, :2]-centre) @ direction
            low, high = min(low, float(along.min())), max(high, float(along.max()))
    if np.isfinite(low) and high > low:
        result["start"], result["end"] = (centre+low*direction).tolist(), (centre+high*direction).tolist()
        return result
    return face


def wall_batches(cloud, wall, chunk_points):
    selector = wall.evidence["selector"]
    for points, indices in point_batches(cloud.points, chunk_points):
        selected = np.zeros(len(points), dtype=bool)
        distances = np.full(len(points), np.inf)
        for face in wall.observed_faces:
            mask, residual = face_selection(points, face, selector["radius_m"], selector["endpoint_margin_m"])
            selected |= mask
            distances[mask] = np.minimum(distances[mask], np.abs(residual[mask]))
        if selected.any():
            yield indices[selected], distances[selected]


def _attach_evidence_serial(cloud, walls, chunk_points=100_000, endpoint_margin=0.04, radius=0.01):
    for wall in walls:
        previous_evidence = dict(wall.evidence)
        wall.observed_faces = [_refine_face(cloud.points, f, radius, endpoint_margin, chunk_points)
                               for f in wall.observed_faces]
        if not wall.observed_faces:
            continue
        first = wall.observed_faces[0]
        a, b = np.asarray(first["start"]), np.asarray(first["end"])
        if wall.detection_method == "multi_slice":
            previous_evidence["refined_slices"] = [dict(f) for f in wall.observed_faces]
            slices=previous_evidence.get('slices',[])
            if len(slices)==len(wall.observed_faces):
                previous_evidence['slices']=[{**r,'proposal_start':r['start'],'proposal_end':r['end'],**f}
                                             for r,f in zip(slices,wall.observed_faces)]
        elif len(wall.observed_faces) == 2 and wall.classification == "paired_faces":
            from .reconstruction import _paired_axis
            second = wall.observed_faces[1]
            axis, thickness = _paired_axis([a, b], [second["start"], second["end"]])
            # A pair that no longer overlaps after refinement is left for review.
            if np.linalg.norm(axis[1]-axis[0]) > 1e-8:
                wall.start, wall.end = tuple(axis[0]), tuple(axis[1])
                wall.thickness = thickness
        elif wall.classification == "exterior_candidate":
            old_midpoint = (np.asarray(wall.start)+np.asarray(wall.end))/2
            normal = np.array([-(b-a)[1], (b-a)[0]]) / np.linalg.norm(b-a)
            if normal @ (old_midpoint-(a+b)/2) < 0:
                normal *= -1
            wall.start, wall.end = tuple(a+normal*wall.thickness/2), tuple(b+normal*wall.thickness/2)
        elif wall.classification != "consolidated_candidate":
            wall.start, wall.end = tuple(a), tuple(b)
        wall.evidence = {**previous_evidence, "schema_version": 2, "scope": "observed face support, excludes unseen geometry",
                         "selector": {"radius_m": radius, "endpoint_margin_m": endpoint_margin,
                                      "frame": "working metres", "faces_field": "observed_faces"},
                         "index_semantics": "working cloud row; E57 scan index and original scan record when available",
                         "record_examples": [], "scan_counts": []}
        count, squared, maximum, scan_counts = 0, 0.0, 0.0, {}
        for ids, distances in wall_batches(cloud, wall, chunk_points):
            count += len(ids)
            squared += float(distances @ distances)
            maximum = max(maximum, float(distances.max()))
            scans = cloud.scan_index[ids] if cloud.scan_index is not None else np.full(len(ids), -1)
            unique, counts = np.unique(scans, return_counts=True)
            for scan, amount in zip(unique, counts):
                scan_counts[int(scan)] = scan_counts.get(int(scan), 0)+int(amount)
            remaining = 32-len(wall.evidence["record_examples"])
            for row, scan in zip(ids[:remaining], scans[:remaining]):
                wall.evidence["record_examples"].append({
                    "cloud_index": int(_working_rows(cloud, np.asarray([row]))[0]),
                    "scan_index": int(scan) if scan >= 0 else None,
                    "source_record_index": int(cloud.source_record_index[row]) if cloud.source_record_index is not None else None})
        wall.evidence_count = count
        wall.fit_rmse_m = float(np.sqrt(squared/count)) if count else None
        wall.evidence["scan_counts"] = [{"scan_index": s if s >= 0 else None, "count": n}
                                        for s, n in sorted(scan_counts.items())]
        wall.evidence["maximum_distance_m"] = maximum if count else None


def attach_evidence(cloud, walls, chunk_points=100_000, endpoint_margin=0.04,
                    radius=0.01, workers=1):
    """Fit independent wall regions in parallel without duplicating the cloud."""
    if workers <= 1 or len(walls) <= 1:
        return _attach_evidence_serial(cloud, walls, chunk_points, endpoint_margin, radius)
    with ThreadPoolExecutor(max_workers=min(workers, len(walls))) as executor:
        list(executor.map(lambda wall: _attach_evidence_serial(
            cloud, [wall], chunk_points, endpoint_margin, radius), walls))


def write_wall_evidence(cloud, walls, directory, chunk_points=100_000, surface_proposals=None):
    """Write complete source references as mapped N x 3 int64 arrays.

    Columns: working-cloud row, E57 scan, original scan record. -1 means the
    source does not supply that identifier. directory is a fresh generation.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for index, wall in enumerate(walls):
        path = directory/f"wall-{index+1}.npy"
        records = np.lib.format.open_memmap(path, mode="w+", dtype="<i8", shape=(wall.evidence_count, 3))
        cursor = 0
        for ids, _ in wall_batches(cloud, wall, chunk_points):
            end = cursor+len(ids)
            records[cursor:end, 0] = _working_rows(cloud, ids)
            records[cursor:end, 1] = cloud.scan_index[ids] if cloud.scan_index is not None else -1
            records[cursor:end, 2] = cloud.source_record_index[ids] if cloud.source_record_index is not None else -1
            cursor = end
        records.flush()
        del records
        if cursor != wall.evidence_count:
            raise ValueError("Evidence selector changed while exporting source references")
        wall.evidence["records"] = {"path": f"evidence/{directory.name}/{path.name}",
                                    "columns": ["cloud_index", "scan_index", "source_record_index"],
                                    "count": cursor, "dtype": "int64", "missing_identifier": -1}
    for index, proposal in enumerate(surface_proposals or []):
        local_ids = np.asarray(proposal["representative_cloud_indices"], dtype="<i8")
        ids = np.asarray(_working_rows(cloud, local_ids), dtype="<i8")
        path = directory/f"patch-{index+1}.npy"
        np.save(path, ids, allow_pickle=False)
        proposal["representative_cloud_index_examples"] = ids[:32].tolist()
        proposal["representative_cloud_records"] = {"path": f"evidence/{directory.name}/{path.name}",
                                                     "count": len(ids), "dtype": "int64"}
        del proposal["representative_cloud_indices"]

