"""Repeatable provider comparisons. Generated measurements are not survey acceptance."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from time import perf_counter
import numpy as np
from shapely.geometry import Polygon
from shapely import contains_xy
from shapely.ops import unary_union

from . import __version__
from .cloud_io import CloudData
from .fixtures import demo_cloud, room_cloud
from .model import slab_opening_footprint
from .reconstruction import ReconstructionSettings, reconstruct

CASES = ["clean", "rotated", "noisy", "sparse", "low_clutter", "thin_partition", "two_storeys", "concave", "void", "wall_gap"]
PROVIDERS = ["contour", "region_fixed", "region_adaptive"]


def _room_reference(width=6., depth=4., floor=0., offset=(0., 0.), partition=True, thickness=.2):
    vertices = np.array([[0, 0], [width, 0], [width, depth], [0, depth]])+offset
    faces = [{"start": vertices[i].tolist(), "end": vertices[(i+1)%4].tolist(), "floor": floor} for i in range(4)]
    if partition:
        for x in [width/2-thickness/2, width/2+thickness/2]:
            faces.append({"start": [x+offset[0], offset[1]], "end": [x+offset[0], depth+offset[1]], "floor": floor})
    return faces, Polygon(vertices)


def _polygon_cloud(polygon):
    step = .05
    lo, hi = np.asarray(polygon.bounds[:2]), np.asarray(polygon.bounds[2:])
    xx, yy = np.meshgrid(np.arange(lo[0], hi[0]+step/2, step), np.arange(lo[1], hi[1]+step/2, step))
    # Include edges as well as interiors in the generated floor samples.
    selected = contains_xy(polygon.buffer(1e-8), xx.ravel(), yy.ravel())
    xy = np.column_stack([xx.ravel()[selected], yy.ravel()[selected]])
    points = [np.column_stack([xy, np.full(len(xy), z)]) for z in [0., 3.]]
    reference = []
    for ring in [polygon.exterior, *polygon.interiors]:
        coords = np.asarray(ring.coords)
        for a, b in zip(coords, coords[1:]):
            t = np.linspace(0, 1, int(np.ceil(np.linalg.norm(b-a)/step))+1)
            edge = a+t[:, None]*(b-a)
            for z in np.arange(0, 3.025, step):
                points.append(np.column_stack([edge, np.full(len(edge), z)]))
            reference.append({"start": a.tolist(), "end": b.tolist(), "floor": 0.})
    return CloudData(np.unique(np.concatenate(points), axis=0)), reference


def benchmark_fixture(case):
    rng = np.random.default_rng(20261008)
    cloud = demo_cloud(case == "two_storeys")
    reference, footprint = _room_reference()
    footprints = [footprint]
    if case == "two_storeys":
        upper, area = _room_reference(4, 3, 3.2, (10, 0), False)
        reference.extend(upper)
        footprints.append(area)
    elif case == "rotated":
        angle = np.radians(27)
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        cloud.points[:, :2] = cloud.points[:, :2] @ rotation.T+[20, -7]
        for face in reference:
            for key in ["start", "end"]:
                face[key] = (np.asarray(face[key]) @ rotation.T+[20, -7]).tolist()
        footprints = [Polygon(np.asarray(footprint.exterior.coords) @ rotation.T+[20, -7])]
    elif case == "noisy":
        cloud.points += rng.normal(0, .003, cloud.points.shape)
    elif case == "sparse":
        cloud = CloudData(cloud.points[rng.random(len(cloud.points)) > .6])
    elif case == "low_clutter":
        clutter = room_cloud(1.2, .8, ceiling=1.2, offset=(1, 1), partition=False)
        cloud = CloudData(np.concatenate([cloud.points, clutter.points]))
    elif case == "thin_partition":
        cloud.points[cloud.points[:, 0] == 2.9, 0] = 2.94
        cloud.points[cloud.points[:, 0] == 3.1, 0] = 3.06
        reference, _ = _room_reference(thickness=.12)
    elif case in {"concave", "void"}:
        polygon = (Polygon([(0, 0), (6, 0), (6, 2), (3, 2), (3, 4), (0, 4)]) if case == "concave"
                   else Polygon([(0, 0), (6, 0), (6, 4), (0, 4)], [[(2, 1), (2, 3), (4, 3), (4, 1)]]))
        cloud, reference = _polygon_cloud(polygon)
        footprints = [polygon]
    elif case == "wall_gap":
        p = cloud.points
        gap = (p[:, 1] == 0) & (p[:, 0] > 2.5) & (p[:, 0] < 3.5) & (p[:, 2] > 0) & (p[:, 2] < 3)
        cloud = CloudData(p[~gap])
    elif case != "clean":
        raise ValueError(f"Unknown benchmark case: {case}")
    return cloud, reference, footprints


def accuracy_metrics(model, reference, footprints, plane_tolerance_m=.03, angle_tolerance_deg=3., minimum_coverage=.95):
    """Match finite observed faces on the same storey, not inferred centrelines.

    Union coverage avoids double-counting overlapping proposal fragments.
    Metrics use independent fixture geometry, not the fitting residual itself.
    """
    proposals = [(wall, face) for wall in model.walls for face in wall.observed_faces]
    matched_proposals, found, offsets, coverages, overlap = set(), 0, [], [], 0.
    storeys = {s.id: s for s in model.storeys}
    for truth in reference:
        a, b = np.asarray(truth["start"]), np.asarray(truth["end"])
        length = float(np.linalg.norm(b-a))
        direction = (b-a)/length
        normal = np.array([-direction[1], direction[0]])
        intervals, errors, wall_intervals = [], [], {}
        for index, (wall, face) in enumerate(proposals):
            if abs(storeys[wall.storey_id].elevation-truth["floor"]) > .05:
                continue
            c, d = np.asarray(face["start"]), np.asarray(face["end"])
            axis = (d-c)/np.linalg.norm(d-c)
            angle = np.degrees(np.arccos(np.clip(abs(axis @ direction), 0, 1)))
            error = float(max(abs((c-a) @ normal), abs((d-a) @ normal)))
            low, high = sorted([float((c-a) @ direction), float((d-a) @ direction)])
            low, high = max(0., low), min(length, high)
            if angle <= angle_tolerance_deg and error <= plane_tolerance_m and high > low:
                intervals.append((low, high))
                wall_intervals.setdefault(wall.id, []).append((low, high))
                errors.append(error)
                matched_proposals.add(index)
        end, covered = 0., 0.
        for low, high in sorted(intervals):
            covered += max(0., high-max(low, end))
            end = max(end, high)
        coverage = covered/length
        proposed_length = 0.
        for local in wall_intervals.values():
            boundary = 0.
            for low, high in sorted(local):
                proposed_length += max(0., high-max(low,boundary))
                boundary = max(boundary,high)
        overlap += proposed_length-covered
        coverages.append(coverage)
        if coverage >= minimum_coverage:
            found += 1
        if errors:
            offsets.append(max(errors))
    area_error = sum(abs(Polygon(s.footprint).area-p.area) for s, p in zip(sorted(model.storeys, key=lambda s:s.elevation), footprints))
    slab_error = 0.
    for storey, truth in zip(sorted(model.storeys, key=lambda s:s.elevation), footprints):
        local = [s for s in model.slabs if s.storey_id == storey.id and s.kind == "FLOOR"]
        shapes = []
        for slab in local:
            holes = [Polygon(slab_opening_footprint(o)) for o in model.slab_openings if o.host_slab_id == slab.id]
            shapes.append(Polygon(slab.footprint).difference(unary_union(holes)))
        slab_error += unary_union(shapes).symmetric_difference(truth).area
    return {"reference_faces": len(reference), "detected_reference_faces": found,
            "face_recall": found/len(reference), "unmatched_proposed_faces": len(proposals)-len(matched_proposals),
            "mean_reference_coverage": float(np.mean(coverages)),
            "overlapping_proposal_length_m": overlap,
            "maximum_matched_plane_error_m": max(offsets) if offsets else None,
            "footprint_area_error_m2": area_error,
            "footprint_area_scope": "storey search envelope, not exported slab geometry",
            "slab_footprint_symmetric_difference_m2": slab_error,
            "storey_count_error": abs(len(model.storeys)-len(footprints)),
            "matching": {"plane_tolerance_m": plane_tolerance_m, "angle_tolerance_deg": angle_tolerance_deg,
                         "minimum_reference_coverage": minimum_coverage}}


def peak_memory_bytes():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        info = Counters()
        info.cb = ctypes.sizeof(info)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(info), info.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return int(info.PeakWorkingSetSize)
    import resource
    amount = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(amount if sys.platform == "darwin" else amount*1024)


def measure(case, provider, repeated_points=0, e57_path=None, output_dir=None):
    settings = ReconstructionSettings(surface_method="contour" if provider == "contour" else "region_growing",
                                      region_adaptive=provider == "region_adaptive")
    import_seconds = None
    if e57_path:
        from .e57_io import read_e57
        start = perf_counter()
        imported = read_e57(e57_path, Path(output_dir)/f"{provider}-cache")
        import_seconds = perf_counter()-start
        cloud, reference, footprints = imported.cloud, None, None
        source = imported.manifest["source"]
    else:
        cloud, reference, footprints = benchmark_fixture(case)
        source = {"kind": "generated_fixture", "case": case, "seed": 20261008}
    temporary = tempfile.TemporaryDirectory() if repeated_points else None
    try:
        if repeated_points:
            path = Path(temporary.name)/"repeated.npy"
            points = np.lib.format.open_memmap(path, mode="w+", dtype="float64", shape=(repeated_points, 3))
            for begin in range(0, repeated_points, 100_000):
                ids = np.arange(begin, min(begin+100_000, repeated_points)) % len(cloud.points)
                points[begin:begin+len(ids)] = cloud.points[ids]
            points.flush()
            cloud = CloudData(points)
            source.update(repeated_points=repeated_points, note="Repeated generated records exercise size, not scanner diversity")
        start = perf_counter()
        model = reconstruct(cloud, settings)
        seconds = perf_counter()-start
        result = {"case": "real_e57" if e57_path else case, "provider": provider,
                  "source": source, "source_points": len(cloud.points), "reconstruction_seconds": seconds,
                  "import_seconds": import_seconds, "process_peak_memory_bytes": peak_memory_bytes(),
                  "walls": len(model.walls), "storeys": len(model.storeys), "slabs": len(model.slabs),
                  "settings": model.metadata["settings"], "detection": model.metadata["detection"],
                  "level_detection": model.metadata["level_detection"],
                  "accuracy": accuracy_metrics(model, reference, footprints) if reference is not None else None,
                  "measured_thicknesses_m": [w.thickness for w in model.walls if w.provenance["thickness"] == "measured"],
                  "warnings": model.warnings}
        del model, cloud
        if repeated_points:
            del points
        return result
    finally:
        if temporary:
            temporary.cleanup()


def run_benchmark(output_dir, cases=None, repeated_points=0, e57_path=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    # One fresh process per case/provider keeps peak RSS comparisons independent.
    environment = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    for case in (["real_e57"] if e57_path else cases or CASES):
        for provider in PROVIDERS:
            command = [sys.executable, "-m", "punctora_core.benchmark", "--worker", "--case", case,
                       "--provider", provider, "--output-dir", str(output_dir), "--repeated-points", str(repeated_points)]
            if e57_path:
                command.extend(["--e57", str(Path(e57_path).resolve())])
            completed = subprocess.run(command, text=True, capture_output=True, env=environment)
            if completed.returncode:
                results.append({"case": case, "provider": provider, "error": completed.stderr.strip()})
            else:
                results.append(json.loads(completed.stdout))
    report = {"schema_version": 1, "punctora_version": __version__,
              "environment": {"os": platform.platform(), "python": platform.python_version(),
                              "machine": platform.machine(), "processor": platform.processor(), "cpu_count": os.cpu_count(),
                              "numerical_threads": 1},
              "scope": "real E57 performance only, no reference accuracy" if e57_path else "generated geometry and process-size experiments; no survey accuracy claim",
              "peak_memory_scope": "whole isolated worker, including interpreter, libraries, input creation/import and mapped pages",
              "results": results}
    # Publish the report atomically without deleting earlier measured results.
    temporary = output_dir/"benchmark.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(output_dir/"benchmark.json")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=CASES)
    parser.add_argument("--repeated-points", type=int, default=0)
    parser.add_argument("--e57", type=Path)
    parser.add_argument("--check", action="store_true", help="Fail if fixture faces, duplication or footprint checks fail")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--case", help=argparse.SUPPRESS)
    parser.add_argument("--provider", choices=PROVIDERS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.repeated_points < 0 or args.e57 and args.repeated_points:
        parser.error("Repeated generated points must be nonnegative and cannot be combined with E57")
    if args.e57 and args.e57.resolve() == (args.output_dir/"benchmark.json").resolve():
        parser.error("Benchmark report overlaps source input")
    if args.worker:
        print(json.dumps(measure(args.case, args.provider, args.repeated_points, args.e57, args.output_dir), allow_nan=False))
        return 0
    report = run_benchmark(args.output_dir, args.cases, args.repeated_points, args.e57)
    failures = []
    if args.check:
        if args.e57:
            parser.error("Reference accuracy checks require generated fixtures, not an unannotated E57")
        for result in report["results"]:
            metrics = result.get("accuracy")
            if metrics is None or (metrics["face_recall"] < 1 or metrics["unmatched_proposed_faces"]
                                  or metrics["overlapping_proposal_length_m"] > .02
                                  or metrics["footprint_area_error_m2"] > .2 or metrics["storey_count_error"]):
                failures.append({"case": result["case"], "provider": result["provider"]})
    print(json.dumps({"report": str(args.output_dir/"benchmark.json"), "runs": len(report["results"]),
                      "failed_runs": sum("error" in r for r in report["results"]), "reference_check_failures": failures}))
    return 1 if failures or any("error" in r for r in report["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
