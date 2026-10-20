import numpy as np

from punctora_core.compute import ComputeBackend
from punctora_core.convergence import compare_budgets
from punctora_core.fixtures import demo_cloud
from punctora_core.performance import ResourcePlan, StageProfiler, _process
from punctora_core.reconstruction import ReconstructionSettings, reconstruct
from punctora_core.sampling import voxel_sample


def test_cpu_backend_and_bounded_voxel_sampling_are_deterministic():
    points = np.asarray([[0.0, 0.0, 0.0], [0.001, 0.001, 0.001],
                         [0.10, 0.10, 0.10], [0.12, 0.10, 0.10]])
    backend = ComputeBackend("cpu")
    first = voxel_sample(points, .05, 10, 2, workers=2, backend=backend)
    second = voxel_sample(points, .05, 10, 1, workers=1, backend=backend)
    np.testing.assert_array_equal(first.cloud_indices, second.cloud_indices)
    assert backend.report()["backend"] == "CPU"


def test_two_voxel_representatives_keep_original_boundary_rows_deterministically():
    points=np.asarray([[.001,.001,.001],[.002,.002,.002],[.003,.003,.003],
                       [.101,.101,.101],[.102,.102,.102]])
    first=voxel_sample(points,.05,10,2,workers=2,representatives_per_voxel=2)
    second=voxel_sample(points,.05,10,1,workers=1,representatives_per_voxel=2)
    np.testing.assert_array_equal(first.cloud_indices,[0,2,3,4])
    np.testing.assert_array_equal(first.cloud_indices,second.cloud_indices)
    np.testing.assert_array_equal(first.points,points[first.cloud_indices])


def test_packed_voxel_selection_matches_tuple_reference_across_adaptation(monkeypatch):
    import punctora_core.sampling as sampling
    points=np.random.default_rng(73).uniform(-2,2,(5000,3))
    real_unique=np.unique
    def tuples(values,*args,**kwargs):
        return real_unique(values,*args,**kwargs)
    # A single original-order reference pass establishes first/last rows for
    # the final adapted size, independent of streaming wave boundaries.
    for copies in (1,2):
        sample=voxel_sample(points,.02,700,317,workers=3,representatives_per_voxel=copies)
        cells=np.floor((points-points.min(axis=0))/sample.voxel_size_m+1e-9).astype(np.int64)
        _,first=real_unique(cells,axis=0,return_index=True)
        ids=first
        if copies==2:
            _,reverse=real_unique(cells[::-1],axis=0,return_index=True)
            ids=np.r_[first,len(cells)-1-reverse]
        np.testing.assert_array_equal(sample.cloud_indices,np.unique(ids))


def test_resource_plan_reserves_source_and_exposes_parallel_budget():
    settings = ReconstructionSettings(maximum_detection_points=100_000,
                                      processing_chunk_points=2_000)
    plan = ResourcePlan.create(settings, 10_000, storeys=2)
    assert plan.workers >= 1
    assert plan.concurrent_storeys >= 1
    assert 30 <= plan.point_limit <= 100_000
    assert plan.chunk_points <= settings.processing_chunk_points


def test_insufficient_admission_reclaims_completed_memory_then_retains_ceiling(monkeypatch):
    from punctora_core import performance, sampling
    from types import SimpleNamespace
    released = []
    monkeypatch.setattr(sampling, "release_completed_working_memory", lambda: released.append(True))
    monkeypatch.setattr(performance, "available_memory_bytes", lambda: (1024 if released else 64) * 1024**2)
    monkeypatch.setattr(performance, "total_memory_bytes", lambda: 1024 * 1024**2)
    monkeypatch.setattr(performance, "_process", lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=(50 if released else 200) * 1024**2)))
    settings = ReconstructionSettings(cpu_workers=1)
    plan = ResourcePlan.create(settings, 10000)
    assert released == [True]
    assert plan.available_memory_fraction_limit == .70
    assert plan.memory_bytes + plan.source_cloud_bytes_estimate <= int(plan.available_at_start * .70)
    assert plan.process_memory_limit_bytes <= int(plan.total_physical_memory_bytes * .70)
    released.clear()
    with __import__("pytest").raises(ValueError, match="Insufficient"):
        ResourcePlan.create(ReconstructionSettings(maximum_working_memory_gb=.01), 10000)


def test_mapped_source_reserve_is_bounded_without_editing_the_source(tmp_path,monkeypatch):
    from punctora_core.cloud_io import CloudData
    import punctora_core.performance as performance
    path=tmp_path/'points.f64'
    np.zeros((10000,3),dtype='<f8').tofile(path)
    points=np.memmap(path,dtype='<f8',shape=(10000,3),mode='r')
    cloud=CloudData(points)
    monkeypatch.setattr(performance,'available_memory_bytes',lambda:10*1024**3)
    settings=ReconstructionSettings(processing_chunk_points=100)
    plan=ResourcePlan.create(settings,len(points),source_cloud=cloud)
    assert plan.source_cloud_bytes_estimate==100*24
    assert not np.any(cloud.points)
    points._mmap.close()


def test_automatic_resource_plan_never_exceeds_seventy_percent_available(monkeypatch):
    from types import SimpleNamespace
    import punctora_core.performance as performance
    available = 10 * 1024**3
    monkeypatch.setattr(performance, "available_memory_bytes", lambda: available)
    monkeypatch.setattr(performance, "total_memory_bytes", lambda: 16 * 1024**3)
    monkeypatch.setattr(
        performance,
        "_process",
        lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=1024**3)),
    )
    plan = ResourcePlan.create(ReconstructionSettings(maximum_working_memory_gb=0), 1_000)
    working = plan.memory_bytes + plan.source_cloud_bytes_estimate
    accounted = working + plan.baseline_process_rss_bytes
    assert working <= int(available * .70)
    assert accounted <= int(plan.total_physical_memory_bytes * .70)
    assert accounted == plan.process_memory_limit_bytes
    assert plan.available_memory_fraction_limit == .70


def test_resource_plan_does_not_subtract_existing_process_rss_from_available_ram(monkeypatch):
    """Reproduce the A36 64 GiB EG Kita admission failure.

    Windows available physical memory already excludes the current process RSS.
    The planner must budget from that available amount without subtracting the
    same 17.28 GiB working set a second time.
    """
    from types import SimpleNamespace
    import punctora_core.performance as performance
    import punctora_core.sampling as sampling

    available = 24_298_508_288
    baseline = 17_276_260_352
    total = 64 * 1024**3
    monkeypatch.setattr(performance, "available_memory_bytes", lambda: available)
    monkeypatch.setattr(performance, "total_memory_bytes", lambda: total)
    monkeypatch.setattr(sampling, "release_mapped_source_pages", lambda cloud: True)
    monkeypatch.setattr(
        performance,
        "_process",
        lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=baseline)),
    )

    settings = ReconstructionSettings(processing_chunk_points=1_000_000)
    plan = ResourcePlan.create(settings, 68_757_314, storeys=1, source_cloud=object())

    expected_source_reserve = settings.processing_chunk_points * 24
    expected_working_budget = int(available * .70) - expected_source_reserve
    assert plan.memory_bytes == expected_working_budget
    assert plan.memory_bytes > 15 * 1024**3
    assert baseline + plan.memory_bytes + expected_source_reserve <= int(total * .70)


def test_stage_profiler_records_cpu_ram_and_backend_fields():
    profiler = StageProfiler(ComputeBackend("cpu"))
    with profiler.stage("unit", sample_points=4) as record:
        record["detected_elements"] = {"walls": 1}
    report = profiler.report()
    stage = report["stages"][0]
    assert stage["status"] == "complete"
    assert stage["sample_points"] == 4
    assert stage["detected_elements"]["walls"] == 1
    assert stage["peak_process_rss_bytes"] >= 0
    assert "gpu_counter_status" in stage


def test_stage_profiler_emits_running_heartbeat_and_terminal_snapshot():
    snapshots = []
    profiler = StageProfiler(ComputeBackend("cpu"), diagnostics=snapshots.append,
                             context={"job_id": "a"*32}, heartbeat_seconds=1)
    with profiler.stage("unit", source_points=4, point_cloud_passes=2) as record:
        record.update(sample_points=4, points_processed=8)
    profiler.finish("completed")
    assert snapshots[0]["status"] == "running"
    assert any(s["active_stages"] == ["unit"] for s in snapshots)
    assert snapshots[-1]["status"] == "completed"
    assert snapshots[-1]["stages"][0]["points_per_second"] > 0


def test_stage_profiler_distinguishes_logical_visits_from_unique_source_reference():
    profiler = StageProfiler(ComputeBackend("cpu"))
    with profiler.stage("indexed", point_cloud_passes=.25) as record:
        record.update(points_processed=250, unique_source_points=1_000)
    report = profiler.report()
    assert report["logical_point_visits_total"] == 250
    assert report["unique_source_points_reference"] == 1_000


def test_linux_memory_counter_matches_own_procfs_when_available():
    import os
    if not os.path.isfile('/proc/self/statm'):
        return
    with open('/proc/self/statm',encoding='ascii') as stream:
        expected = int(stream.read().split()[1])*os.sysconf('SC_PAGE_SIZE')
    assert abs(_process().memory_info().rss-expected) < 8*1024**2


def test_subset_passes_are_normalized_to_complete_cloud():
    profiler = StageProfiler(ComputeBackend("cpu"), context={"source_points": 1_000})
    with profiler.stage("subset", point_cloud_passes=3) as record:
        record.update(points_processed=900, source_point_count=300)
    with profiler.stage("indexed", point_cloud_passes=.25) as record:
        record.update(points_processed=250, unique_source_points=1_000)
    report = profiler.report()
    assert report["point_cloud_passes_total"] == 1.15
    assert report["stage_passes_total"] == 3.25
    assert report["logical_point_visits_total"] == 1_150


def test_parallel_reconstruction_preserves_element_counts():
    cloud = demo_cloud(two_storeys=True)
    serial = reconstruct(cloud, ReconstructionSettings(cpu_workers=1))
    parallel = reconstruct(cloud, ReconstructionSettings(cpu_workers=-1))
    for kind in ("storeys", "walls", "slabs", "spaces", "openings", "stairs", "landings", "slab_openings"):
        assert len(getattr(serial, kind)) == len(getattr(parallel, kind))
    assert parallel.metadata["performance"]["resource_plan"]["workers"] >= 1
    index_stages = [r for r in parallel.metadata["performance"]["stages"] if r["stage"]=="wall_spatial_index"]
    assert len(index_stages)==1
    assert index_stages[0]["points_processed"]==len(cloud.points)
    serial._spatial_index.close()
    parallel._spatial_index.close()


def test_budget_comparison_reports_stability_without_claiming_accuracy():
    model, report = compare_budgets(demo_cloud(), budgets=(250_000, 500_000, 1_000_000))
    assert report["runs"]
    assert report["selected_requested_points"] <= 1_000_000
    assert report["accuracy_verified"] is False
    assert model.metadata["budget_comparison"]["scope"].startswith("candidate geometry")
