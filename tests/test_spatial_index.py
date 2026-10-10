from copy import deepcopy
from pathlib import Path
import numpy as np
import pytest
from punctora_core.cloud_io import CloudData
from punctora_core.evidence import attach_evidence, face_selection, write_wall_evidence
from punctora_core.features import detect_openings
from punctora_core.model import Wall
from punctora_core.reconstruction import ReconstructionSettings
from punctora_core.spatial_index import SpatialPointIndex


def test_cyclic_index_closes_maps_before_directory_cleanup(monkeypatch):
    import gc
    from tempfile import TemporaryDirectory
    index = SpatialPointIndex.build(CloudData(np.zeros((10, 3))))
    index.local_cloud([dict(start=[0, 0], end=[1, 0], z_min=0, z_max=1)], .1, .1, stage="fit")
    mapped = list(index.visited.values())
    directory = Path(index.scratch.name)
    cleanup = TemporaryDirectory.cleanup
    calls = []

    def checked_cleanup(scratch):
        if Path(scratch.name) == directory:
            calls.append(True)
            assert mapped and all(array._mmap.closed for array in mapped)
        cleanup(scratch)

    monkeypatch.setattr(TemporaryDirectory, "cleanup", checked_cleanup)
    index.cycle = index
    del index
    gc.collect()
    assert calls == [True]
    assert not directory.exists()


@pytest.mark.parametrize("angle",[0,17,45,90,135,221,315])
def test_cells_are_conservative_for_rotated_faces_and_height(angle):
    rng = np.random.default_rng(721)
    p = rng.uniform([-4,-4,-2],[4,4,5],size=(12_000,3))
    theta = np.deg2rad(angle)
    direction = np.array([np.cos(theta),np.sin(theta)])
    f = dict(start=(-2*direction).tolist(),end=(2*direction).tolist(),z_min=.3,z_max=1.7)
    cloud = CloudData(p)
    index = SpatialPointIndex.build(cloud,.2,chunk_points=317)
    try:
        expected = np.flatnonzero(face_selection(p,f,.4,.08)[0])
        rows = index.rows_near_faces([f],.4,.08)
        assert set(expected)<=set(rows)
        assert len(rows)<len(p)/5
        assert np.all(p[rows,2]>=.2-1e-10)
        assert np.all(p[rows,2]<1.8+1e-10)
    finally:
        index.close()


def test_diagonal_neighbour_that_old_index_dropped():
    p = np.array([[2.05,2.25,1.],[2.05,2.05,1.]])
    index = SpatialPointIndex.build(CloudData(p),.2)
    try:
        face = dict(start=[0,0],end=[6,6],z_min=0,z_max=3)
        assert index.rows_near_faces([face],.4,.05).tolist()==[0,1]
    finally:
        index.close()


def survey(angle=0):
    x,z = np.meshgrid(np.arange(0,6.001,.04),np.arange(0,3.001,.04))
    p = np.column_stack((x.ravel(),np.zeros(x.size),z.ravel()))
    window = (p[:,0]>=1)&(p[:,0]<2.5)&(p[:,2]>=.9)&(p[:,2]<2.1)
    p[:,1] = .23
    p[window,1] += .31
    theta = np.deg2rad(angle)
    rotation = np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
    near = p.copy()
    p = np.vstack([near,near+[0,0,5],near+[60,80,0]])
    p[:,:2] = p[:,:2]@rotation.T
    ids = np.arange(len(p),dtype=np.int64)
    cloud = CloudData(p,scan_index=(ids%7).astype(np.int32),source_record_index=ids+10_000,
                      working_index=ids+2_000)
    start = (np.array([0,.23])@rotation.T).tolist()
    end = (np.array([6,.23])@rotation.T).tolist()
    wall = Wall('w','s',tuple(start),tuple(end),0,3,.2,
                observed_faces=[dict(start=start,end=end,z_min=0,z_max=3)])
    return cloud,wall


@pytest.mark.parametrize("angle,spill",[(0,False),(45,False),(137,False),(45,True)])
def test_fitting_openings_and_export_match_original_records(tmp_path,angle,spill):
    cloud,wall = survey(angle)
    indexed,reference = deepcopy(wall),deepcopy(wall)
    settings = ReconstructionSettings(cpu_workers=1)
    index = SpatialPointIndex.build(cloud,.2,memory_budget_bytes=128*1024 if spill else None,chunk_points=997)
    try:
        attach_evidence(cloud,[reference],997,.08,.02,1)
        attach_evidence(cloud,[indexed],997,.08,.02,1,index)
        assert indexed.start==pytest.approx(reference.start,abs=1e-10)
        assert indexed.end==pytest.approx(reference.end,abs=1e-10)
        assert indexed.evidence_count==reference.evidence_count
        assert indexed.fit_rmse_m==pytest.approx(reference.fit_rmse_m,abs=1e-10)
        assert indexed.evidence["scan_counts"]==reference.evidence["scan_counts"]
        old = detect_openings(cloud,[reference],settings,1)
        new = detect_openings(cloud,[indexed],settings,1,index)
        assert len(new)==len(old)==1
        assert new[0].offset==pytest.approx(old[0].offset,abs=.05)
        assert new[0].evidence["signed_interior_depth_m"]==pytest.approx(old[0].evidence["signed_interior_depth_m"],abs=1e-10)
        write_wall_evidence(cloud,[reference],tmp_path/"old",997)
        write_wall_evidence(cloud,[indexed],tmp_path/"new",997,spatial_index=index)
        assert np.array_equal(np.load(tmp_path/"old/wall-1.npy"),np.load(tmp_path/"new/wall-1.npy"))
        report = index.report("original_wall_fitting")
        assert report["unique_points_visited"]<len(cloud.points)/2
        assert report["points_processed"]>report["unique_points_visited"]
    finally:
        index.close()


def test_spill_cache_accounting_and_cleanup():
    cloud,wall = survey()
    index = SpatialPointIndex.build(cloud,.2,memory_budget_bytes=128*1024,chunk_points=1000)
    directory = Path(index.scratch.name)
    try:
        assert index.spilled
        assert all(isinstance(a,np.memmap) for run in index.runs for a in run)
        local,rows = index.local_cloud(wall.observed_faces,.05,.08,"test")
        assert local.points.dtype==np.float64
        assert np.array_equal(local.points,cloud.points[rows])
        assert np.array_equal(local.scan_index,cloud.scan_index[rows])
        assert np.array_equal(local.source_record_index,cloud.source_record_index[rows])
        assert np.array_equal(local.working_index,cloud.working_index[rows])
        index.local_cloud(wall.observed_faces,.05,.08,"test")
        assert index.report("test")["unique_points_visited"]==len(rows)
        index.visit("test",len(rows)*3)
        assert index.report("test")["points_processed"]>=len(rows)*4
        assert index.cache_bytes<=index.cache_limit
    finally:
        index.close()
    assert not directory.exists()
    index.close()


def test_interrupted_build_cleans_spill(tmp_path):
    cloud,_ = survey()
    def interrupt(*_):
        raise InterruptedError("cancelled")
    with pytest.raises(InterruptedError):
        SpatialPointIndex.build(cloud,.2,128*1024,1000,progress=interrupt,scratch_directory=tmp_path)
    assert not list(tmp_path.iterdir())


def test_evidence_export_extends_live_report_and_closes_index(tmp_path):
    from punctora_core.compute import ComputeBackend
    from punctora_core.evidence import write_model_evidence
    from punctora_core.model import BuildingModel
    from punctora_core.performance import StageProfiler
    cloud,wall = survey()
    index = SpatialPointIndex.build(cloud,.2)
    attach_evidence(cloud,[wall],997,.08,.02,1,index)
    model = BuildingModel("Test",walls=[wall])
    snapshots = []
    profiler = StageProfiler(ComputeBackend("cpu"),diagnostics=snapshots.append)
    with profiler.stage("wall_spatial_index",source_points=len(cloud.points),
                        points_processed=len(cloud.points),unique_points_visited=len(cloud.points),point_cloud_passes=1):
        pass
    profiler.finish("completed")
    model.metadata["performance"] = profiler.report()
    model._spatial_index,model._performance_profiler = index,profiler
    write_model_evidence(cloud,model,tmp_path/"evidence")
    assert index.closed
    report = model.metadata["performance"]
    export = report["stages"][-1]
    assert export["stage"]=="evidence_export"
    assert export["points_processed"]>0
    assert export["unique_points_visited"]<len(cloud.points)
    assert report["unique_points_visited_total"]==len(cloud.points)
    assert report["status"]=="completed"
    assert any(s["status"]=="running" and "evidence_export" in s["active_stages"] for s in snapshots)


def test_openings_use_full_host_interval_and_height():
    x,z = np.meshgrid(np.arange(0,6.001,.025),np.arange(0,3.001,.025))
    p = np.column_stack((x.ravel(),np.zeros(x.size),z.ravel()))
    keep = ~((p[:,0]>=4.5)&(p[:,0]<5.5)&(p[:,2]>=.9)&(p[:,2]<2.1))
    cloud = CloudData(p[keep])
    wall = Wall("w","s",(0,0),(6,0),0,3,.2,
                observed_faces=[dict(start=[0,0],end=[4,0],z_min=.3,z_max=.7)])
    settings = ReconstructionSettings(cpu_workers=1)
    index = SpatialPointIndex.build(cloud,.2)
    try:
        reference = detect_openings(cloud,[wall],settings,1)
        indexed = detect_openings(cloud,[wall],settings,1,index)
        assert len(reference)==len(indexed)==1
        assert indexed[0].offset==reference[0].offset
        assert indexed[0].width==reference[0].width
    finally:
        index.close()
