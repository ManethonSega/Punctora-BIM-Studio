"""Conservative geometric opening and straight-flight proposals, in metres.

Scores describe geometric support, not calibrated probabilities or scan accuracy.
Missing returns alone never establish an opening. No pretrained models are used.
"""
import cv2
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy.spatial import cKDTree

from .model import Opening, Stair
from .sampling import adaptive_point_limit, resolved_cpu_workers, voxel_sample


def detect_openings(cloud, walls, settings, workers=None):
    workers = resolved_cpu_workers(settings.cpu_workers) if workers is None else workers
    if workers > 1 and len(walls) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(walls))) as executor:
            groups = executor.map(lambda wall: detect_openings(cloud, [wall], settings, 1), walls)
            return [opening for group in groups for opening in group]
    result = []
    cell = max(0.05, settings.grid_size_m)
    for wall in walls:
        start = np.asarray(wall.start, dtype=float)
        direction = np.asarray(wall.end, dtype=float)-start
        length = float(np.linalg.norm(direction))
        direction /= length
        normal = np.array([-direction[1], direction[0]])
        nx, nz = int(np.ceil(length/cell)), int(np.ceil(wall.height/cell))
        if nx < 10 or nz < 20 or nx*nz > settings.maximum_grid_cells:
            continue
        occupancy = np.zeros((nz, nx), np.uint8)
        support = 0
        for begin in range(0, len(cloud.points), settings.processing_chunk_points):
            points = cloud.points[begin:begin+settings.processing_chunk_points]
            relative = points[:, :2]-start
            along, across, z = relative@direction, relative@normal, points[:, 2]-wall.base
            # Restrict evidence to the host's face envelope; furniture farther
            # into the room must not fill a genuine void.
            keep = ((along >= 0) & (along < length) & (z >= 0) & (z < wall.height)
                    & (np.abs(across) <= wall.thickness/2+0.04))
            x, h = (along[keep]/cell).astype(int), (z[keep]/cell).astype(int)
            occupancy[h, x] = 1
            support += len(x)
        if support < 100:
            continue
        filled = cv2.morphologyEx(occupancy, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(1-filled, 8)
        for index in range(1, count):
            x, z, width, height, area = map(int, stats[index])
            w, h = width*cell, height*cell
            # Allow floor-touching doors, but never candidates at a wall end or
            # open ceiling boundary. Require a mostly rectangular empty region.
            if x < 2 or x+width > nx-2 or z+height > nz-2 or area/(width*height) < 0.8:
                continue
            if not 0.55 <= w <= 3.0 or not 0.6 <= h <= 2.7:
                continue
            sill = z*cell
            door = sill <= 0.15 and h >= 1.7
            if not door and not 0.35 <= sill <= 1.8:
                continue
            strips = [filled[z:z+height, x-2:x], filled[z:z+height, x+width:x+width+2],
                      filled[z+height:z+height+2, x:x+width]]
            if not door:
                strips.append(filled[max(0, z-2):z, x:x+width])
            edge = [float(s.mean()) if s.size else 0.0 for s in strips]
            if min(edge) < 0.65:
                continue
            # Interior observed returns may be glazing, a closed leaf or noise.
            # This detector only handles visibly empty openings.
            interior = float(occupancy[z:z+height, x:x+width].mean())
            if interior > 0.15:
                continue
            result.append(Opening(f"{wall.id}-opening-{index}", wall.id, "door" if door else "window",
                                  x*cell, 0.0 if door else sill, min(w, length-x*cell),
                                  min(h+sill if door else h, wall.height-(0.0 if door else sill)),
                                  {"dimensions": "measured", "kind": "inferred", "filling": "unknown"},
                                  confidence=min(edge)*(1-interior), evidence={
                                      "method": "wall_occupancy_gap", "cell_size_m": cell,
                                      "edge_support_fractions": edge, "interior_occupancy": interior,
                                      "host_support_points": support,
                                      "scope": "bounded host-wall returns; occlusion can imitate an opening"}))
    return result


def detect_stairs(cloud, storeys, settings, backend=None, statistics=None):
    flights = []
    workers = resolved_cpu_workers(settings.cpu_workers)
    point_limit = adaptive_point_limit(settings.maximum_detection_points,
                                       settings.maximum_working_memory_gb, bytes_per_point=256)
    for storey in storeys:
        sample = voxel_sample(cloud.points, max(0.035, settings.detection_voxel_size_m),
                              point_limit, settings.processing_chunk_points,
                              (storey.elevation+0.08, storey.ceiling-0.05), workers, backend)
        if statistics is not None:
            statistics.append({"storey_id": storey.id, "sample_points": len(sample.points),
                               "source_point_count": sample.source_point_count,
                               "voxel_size_m": sample.voxel_size_m})
        points = sample.points
        if len(points) < 60:
            continue
        # Estimate local horizontal support with bounded batches. A vertical
        # riser or wall section is not accepted as a tread just for sharing Z.
        tree = cKDTree(points)
        horizontal = np.zeros(len(points), bool)
        for begin in range(0, len(points), 2048):
            distances, indices = tree.query(points[begin:begin+2048], k=min(12, len(points)), workers=workers)
            neighbours = points[indices]
            centre = neighbours.mean(axis=1, keepdims=True)
            covariance = np.einsum("nki,nkj->nij", neighbours-centre, neighbours-centre)
            values, vectors = np.linalg.eigh(covariance)
            horizontal[begin:begin+len(indices)] = ((np.abs(vectors[:, 2, 0]) > 0.96)
                & (values[:, 0]/np.maximum(values.sum(axis=1), 1e-12) < 0.025)
                & (distances[:, -1] < 0.22))
        points = points[horizontal]
        if len(points) < 40:
            continue
        zcells = np.floor((points[:, 2]-storey.elevation)/0.03).astype(int)
        levels = np.unique(zcells)
        groups = np.split(levels, np.where(np.diff(levels) > 1)[0]+1)
        patches = []
        for group in groups:
            plane = points[np.isin(zcells, group)]
            if len(plane) < 20 or np.ptp(plane[:, 2]) > 0.07:
                continue
            origin = plane[:, :2].min(axis=0)-0.06
            cells = np.floor((plane[:, :2]-origin)/0.06).astype(int)
            shape = cells.max(axis=0)+3
            if int(shape[0])*int(shape[1]) > settings.maximum_grid_cells:
                continue
            mask = np.zeros((int(shape[1]), int(shape[0])), np.uint8)
            mask[cells[:, 1], cells[:, 0]] = 1
            connected = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            count, labels = cv2.connectedComponents(connected, 8)
            ids = labels[cells[:, 1], cells[:, 0]]
            for index in range(1, count):
                patch = plane[ids == index]
                if len(patch) < 20:
                    continue
                centre = patch[:, :2].mean(axis=0)
                _, _, axes = np.linalg.svd(patch[:, :2]-centre, full_matrices=False)
                xy = (patch[:, :2]-centre)@axes.T
                low, high = xy.min(axis=0), xy.max(axis=0)
                width, depth = high-low
                if not 0.6 <= width <= 3.0 or not 0.16 <= depth <= 0.5:
                    continue
                # Require broad support, avoiding a line mistaken for a tread.
                coverage = len(np.unique(np.floor(xy/0.06).astype(int), axis=0))*0.06**2/(width*depth)
                if coverage < 0.5:
                    continue
                patches.append({"xy": centre+((low+high)/2)@axes,
                                "z": float(np.median(patch[:, 2])), "width": float(width),
                                "axis": axes[0], "count": len(patch)})
        patches.sort(key=lambda p: (p["z"], *p["xy"]))
        used = set()
        for first in range(len(patches)):
            if first in used:
                continue
            chain, direction = [first], None
            while len(chain) < 100:
                a = patches[chain[-1]]
                choices = []
                for j, b in enumerate(patches):
                    if j in used or j in chain:
                        continue
                    rise = b["z"]-a["z"]
                    delta = b["xy"]-a["xy"]
                    going = float(np.linalg.norm(delta))
                    if not 0.10 <= rise <= 0.24 or not 0.18 <= going <= 0.45:
                        continue
                    d = delta/going
                    if abs(d@a["axis"]) > 0.2 or abs(d@b["axis"]) > 0.2:
                        continue
                    if abs(b["width"]-a["width"]) > 0.2 or (direction is not None and d@direction < 0.98):
                        continue
                    choices.append((going, j, d))
                if not choices:
                    break
                _, j, d = min(choices, key=lambda c: (c[0], c[1]))
                direction = d if direction is None else direction
                chain.append(j)
            if len(chain) < 4:
                continue
            selected = [patches[i] for i in chain]
            rises = np.diff([p["z"] for p in selected])
            goings = np.linalg.norm(np.diff([p["xy"] for p in selected], axis=0), axis=1)
            if np.ptp(rises) > 0.035 or np.ptp(goings) > 0.045:
                continue
            rise, going = float(np.median(rises)), float(np.median(goings))
            start = selected[0]["xy"]-direction*going/2
            end = start+direction*going*len(chain)
            flights.append(Stair(f"{storey.id}-stair-{len(flights)+1}", storey.id, tuple(start), tuple(end),
                                 selected[0]["z"]-rise, float(np.median([p["width"] for p in selected])),
                                 rise, going, len(chain), provenance={"treads": "measured", "run": "inferred",
                                     "tread_thickness": "inferred", "structure": "unknown"},
                                 confidence=0.75, evidence={"method": "repeated_horizontal_treads",
                                     "tread_support_counts": [p["count"] for p in selected],
                                     "observed_tread_elevations_m": [p["z"] for p in selected],
                                     "rise_spread_m": float(np.ptp(rises)), "going_spread_m": float(np.ptp(goings)),
                                     "sample_voxel_size_m": sample.voxel_size_m,
                                     "scope": "straight flight proposal; support structure and landings not inferred"}))
            used.update(chain)
    return flights

