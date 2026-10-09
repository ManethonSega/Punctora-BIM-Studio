import numpy as np

from punctora_core.compute import ComputeBackend
from punctora_core.convergence import compare_budgets
from punctora_core.fixtures import demo_cloud
from punctora_core.performance import ResourcePlan, StageProfiler
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


def test_resource_plan_reserves_source_and_exposes_parallel_budget():
    settings = ReconstructionSettings(maximum_detection_points=100_000,
                                      processing_chunk_points=2_000)
    plan = ResourcePlan.create(settings, 10_000, storeys=2)
    assert plan.workers >= 1
    assert plan.concurrent_storeys >= 1
    assert 30 <= plan.point_limit <= 100_000
    assert plan.chunk_points <= settings.processing_chunk_points


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


def test_parallel_reconstruction_preserves_element_counts():
    cloud = demo_cloud(two_storeys=True)
    serial = reconstruct(cloud, ReconstructionSettings(cpu_workers=1))
    parallel = reconstruct(cloud, ReconstructionSettings(cpu_workers=-1))
    for kind in ("storeys", "walls", "slabs", "spaces", "openings", "stairs"):
        assert len(getattr(serial, kind)) == len(getattr(parallel, kind))
    assert parallel.metadata["performance"]["resource_plan"]["workers"] >= 1


def test_budget_comparison_reports_stability_without_claiming_accuracy():
    model, report = compare_budgets(demo_cloud(), budgets=(250_000, 500_000, 1_000_000))
    assert report["runs"]
    assert report["selected_requested_points"] <= 1_000_000
    assert report["accuracy_verified"] is False
    assert model.metadata["budget_comparison"]["scope"].startswith("candidate geometry")
