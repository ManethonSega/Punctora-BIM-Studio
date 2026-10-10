from dataclasses import replace
import json
import numpy as np
import pytest
from punctora_core.benchmark import accuracy_metrics, benchmark_fixture
from punctora_core.cloud_io import CloudData
from punctora_core.evidence import write_wall_evidence, wall_batches
from punctora_core.fixtures import demo_cloud
from punctora_core.ifc_export import write_ifc
from punctora_core.reconstruction import reconstruct, ReconstructionSettings
from punctora_core.sampling import voxel_sample
from punctora_core.surfaces import region_growing


@pytest.mark.parametrize("case", ["clean", "rotated", "thin_partition"])
def test_contour_original_record_refinement_retains_reference_extents(case):
    cloud, reference, footprints = benchmark_fixture(case)
    model = reconstruct(cloud)
    metrics = accuracy_metrics(model, reference, footprints)
    assert metrics["face_recall"] == 1
    assert metrics["unmatched_proposed_faces"] == 0
    assert metrics["overlapping_proposal_length_m"] < .02


@pytest.mark.parametrize("case", ["clean", "rotated", "thin_partition", "noisy", "sparse", "two_storeys"])
def test_region_provider_fits_independent_reference_faces(case):
    cloud, reference, footprints = benchmark_fixture(case)
    model = reconstruct(cloud, ReconstructionSettings(surface_method="region_growing"))
    metrics = accuracy_metrics(model, reference, footprints)
    assert metrics["face_recall"] == 1
    assert metrics["unmatched_proposed_faces"] == 0
    assert metrics["maximum_matched_plane_error_m"] < .003
    assert all(w.evidence_count > 0 and w.detection_method == "region_growing" for w in model.walls)
    paired = [w for w in model.walls if w.provenance["thickness"] == "measured"]
    assert len(paired) == 1
    assert paired[0].thickness == pytest.approx(.12 if case == "thin_partition" else .2, abs=.003)
    if case == "thin_partition":
        assert paired[0].thickness == pytest.approx(.12, abs=1e-6)


def test_region_does_not_join_close_parallel_or_disconnected_planes():
    yy, zz = np.meshgrid(np.arange(0., 1.025, .05), np.arange(0., 1.025, .05))
    planes = [np.column_stack([np.full(yy.size, x), yy.ravel()+shift, zz.ravel()])
              for x in [0., .12] for shift in [0., 2.]]
    points = np.concatenate(planes)
    sample = voxel_sample(points, .02)
    patches, _ = region_growing(sample, ReconstructionSettings())
    significant = [p for p in patches if p.sample_count >= 150]
    assert len(significant) == 4
    assert all(p.bounds[1][0]-p.bounds[0][0] < 1e-8 and p.bounds[1][1]-p.bounds[0][1] <= 1. for p in significant)


def test_bounded_sampling_is_chunk_independent_and_keeps_original_rows(tmp_path):
    original = demo_cloud().points
    mapped = np.lib.format.open_memmap(tmp_path/"cloud.npy", mode="w+", dtype="float64", shape=(len(original)*3, 3))
    for start in range(3):
        mapped[start*len(original):(start+1)*len(original)] = original
    first = voxel_sample(mapped, .02, maximum_points=4000, chunk_points=317)
    second = voxel_sample(mapped, .02, maximum_points=4000, chunk_points=10_000)
    parallel = voxel_sample(mapped, .02, maximum_points=4000, chunk_points=317, workers=4)
    assert len(first.points) <= 4000
    assert first.source_point_count == len(mapped)
    assert first.voxel_size_m > .02
    np.testing.assert_array_equal(first.cloud_indices, second.cloud_indices)
    np.testing.assert_array_equal(first.cloud_indices, parallel.cloud_indices)
    np.testing.assert_array_equal(first.points, mapped[first.cloud_indices])
    assert first.cloud_indices.max() < len(original)


def test_wall_evidence_retains_complete_original_scan_record_mapping(tmp_path):
    cloud = demo_cloud()
    n = len(cloud.points)
    cloud = CloudData(cloud.points, scan_index=np.arange(n)%2,
                      source_record_index=np.arange(n)*3+7)
    model = reconstruct(cloud, ReconstructionSettings(surface_method="region_growing"))
    directory = tmp_path/"evidence"/"generation-one"
    write_wall_evidence(cloud, model.walls, directory, chunk_points=271)
    for wall in model.walls:
        data = np.load(tmp_path/wall.evidence["records"]["path"], mmap_mode="r")
        assert len(data) == wall.evidence_count == sum(s["count"] for s in wall.evidence["scan_counts"])
        np.testing.assert_array_equal(data[:, 1], cloud.scan_index[data[:, 0]])
        np.testing.assert_array_equal(data[:, 2], cloud.source_record_index[data[:, 0]])
        all_ids = np.concatenate([ids for ids, _ in wall_batches(cloud, wall, chunk_points=103)])
        np.testing.assert_array_equal(data[:, 0], all_ids)
        assert len(np.unique(data[:, 0])) == len(data)
        assert len(wall.evidence["record_examples"]) <= 32
        assert wall.fit_rmse_m < 1e-8


def test_original_resolution_fitting_recovers_extent_after_coarse_detection():
    cloud = demo_cloud()
    settings = ReconstructionSettings(surface_method="region_growing", maximum_detection_points=25_000)
    model = reconstruct(cloud, settings)
    cloud2, reference, footprints = benchmark_fixture("clean")
    assert accuracy_metrics(model, reference, footprints)["face_recall"] == 1
    assert all(w.evidence_count > 100 for w in model.walls)
    assert max(d["sample_points"] for d in model.metadata["detection"]) <= 25_000


def test_region_model_exports_valid_ifc_with_fit_scope(tmp_path):
    model = reconstruct(demo_cloud(), ReconstructionSettings(surface_method="region_growing"))
    assert write_ifc(model, tmp_path/"model.ifc")["valid"]
    assert model.to_dict()["schema_version"] == 2


@pytest.mark.parametrize("field,value", [("surface_method", "invented"), ("region_neighbours", 3),
    ("region_adaptive", "true"), ("maximum_detection_points", 20), ("region_minimum_wall_height_fraction", 2),
    ("region_normal_angle_deg", 90), ("processing_chunk_points", True),
    ("cpu_workers", -2), ("maximum_working_memory_gb", -1)])
def test_invalid_provider_settings_fail_before_processing(field, value):
    with pytest.raises(ValueError):
        replace(ReconstructionSettings(), **{field:value}).validate()


def test_benchmark_distinguishes_convex_search_envelope_from_slab_geometry():
    cloud, reference, footprints = benchmark_fixture("void")
    model = reconstruct(cloud)
    metrics = accuracy_metrics(model, reference, footprints)
    assert metrics["face_recall"] == 1
    assert metrics["footprint_area_error_m2"] == pytest.approx(4.)
    assert metrics["footprint_area_scope"] == "storey search envelope, not exported slab geometry"
    # Raster boundary uncertainty is bounded by one cell along all boundaries.
    assert metrics["slab_footprint_symmetric_difference_m2"] < footprints[0].length*ReconstructionSettings().slab_raster_cell_m
    assert model.slab_openings
