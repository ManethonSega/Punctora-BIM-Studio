"""Reproducible CPU-only Run 1 reference comparison. No real-survey claim.

Run: PYTHONPATH=src python scripts/benchmark_spatial_index.py --walls 144
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import numpy as np
from threadpoolctl import threadpool_limits
from punctora_core.cloud_io import CloudData
from punctora_core.evidence import attach_evidence, write_wall_evidence
from punctora_core.features import detect_openings
from punctora_core.model import Wall
from punctora_core.reconstruction import ReconstructionSettings
from punctora_core.spatial_index import SpatialPointIndex


def benchmark(count):
    x,z = np.meshgrid(np.linspace(0,6,61),np.linspace(0,3,61))
    face_points = np.column_stack((x.ravel(),np.zeros(x.size),z.ravel()))
    points,walls = [],[]
    for i in range(count):
        anchor = np.array([i%12*10.,i//12*10.])
        p = face_points.copy()
        p[:,:2] += anchor
        points.append(p)
        a,b = anchor.tolist(),(anchor+[6,0]).tolist()
        faces = [dict(start=a,end=b,z_min=j*.4,z_max=min(3.,j*.4+.6)) for j in range(7)]
        walls.append(Wall(f"w{i}","s",tuple(a),tuple(b),0,3,.2,observed_faces=faces,
                          classification="consolidated_candidate"))
    p = np.concatenate(points)
    ids = np.arange(len(p),dtype=np.int64)
    cloud = CloudData(p,scan_index=(ids%17).astype(np.int32),source_record_index=ids+111_111,
                      working_index=ids+777_777)
    reference,indexed = deepcopy(walls),deepcopy(walls)
    settings = ReconstructionSettings(cpu_workers=1,compute_backend="cpu")
    with threadpool_limits(limits=1), TemporaryDirectory(prefix="punctora-benchmark-") as directory:
        started = time.perf_counter()
        attach_evidence(cloud,reference,100_000,.08,.02,1)
        reference_fit = time.perf_counter()-started
        print(f"Reference fitting finished in {reference_fit:.3f}s",flush=True)
        started = time.perf_counter()
        index = SpatialPointIndex.build(cloud,.2,memory_budget_bytes=512*1024**2)
        index_seconds = time.perf_counter()-started
        try:
            started = time.perf_counter()
            attach_evidence(cloud,indexed,100_000,.08,.02,1,index)
            indexed_fit = time.perf_counter()-started
            for old,new in zip(reference,indexed):
                for a,b in zip(old.observed_faces,new.observed_faces):
                    assert np.allclose(a["start"],b["start"],rtol=0,atol=1e-10)
                    assert np.allclose(a["end"],b["end"],rtol=0,atol=1e-10)
                assert old.evidence_count==new.evidence_count
                assert old.evidence["scan_counts"]==new.evidence["scan_counts"]
            started = time.perf_counter()
            old_openings = detect_openings(cloud,reference,settings,1)
            reference_opening = time.perf_counter()-started
            started = time.perf_counter()
            new_openings = detect_openings(cloud,indexed,settings,1,index)
            indexed_opening = time.perf_counter()-started
            assert [o.__dict__ for o in old_openings]==[o.__dict__ for o in new_openings]
            started = time.perf_counter()
            write_wall_evidence(cloud,reference,Path(directory)/"reference")
            reference_export = time.perf_counter()-started
            started = time.perf_counter()
            write_wall_evidence(cloud,indexed,Path(directory)/"indexed",spatial_index=index)
            indexed_export = time.perf_counter()-started
            for i in range(count):
                assert np.array_equal(np.load(Path(directory)/f"reference/wall-{i+1}.npy"),
                                      np.load(Path(directory)/f"indexed/wall-{i+1}.npy"))
            visits = 1+sum(index.report(s)["point_cloud_passes"] for s in
                           ("original_wall_fitting","openings","evidence_export"))
            result = dict(walls=count,source_points=len(p),slices_per_wall=7,
                          reference_fitting_full_cloud_equivalents=count*22,
                          indexed_full_cloud_equivalents_including_build_fit_openings_export=visits,
                          index_seconds=index_seconds,reference_fit_seconds=reference_fit,
                          indexed_fit_seconds=indexed_fit,
                          fitting_speedup_including_index=reference_fit/(indexed_fit+index_seconds),
                          reference_opening_seconds=reference_opening,indexed_opening_seconds=indexed_opening,
                          reference_export_seconds=reference_export,indexed_export_seconds=indexed_export,
                          geometry_matches=True,source_records_match_exactly=True,
                          stage_visits={s:index.report(s) for s in ("original_wall_fitting","openings","evidence_export")},
                          acceptance_210_million_points="pending, synthetic results do not establish runtime")
            assert visits<25
            return result
        finally:
            index.close()


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--walls",type=int,default=24)
    args = parser.parse_args()
    if args.walls<1:
        parser.error("--walls must be positive")
    print(json.dumps(benchmark(args.walls),indent=2),flush=True)
