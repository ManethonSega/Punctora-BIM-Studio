"""Trace actual original-plane/frame decisions for large glazing proposals."""
import numpy as np

from punctora_core.reconstruction import ReconstructionSettings
from punctora_core.recognition.geometry_fusion import fuse_geometry
from test_run4_repair import Control, fusion_fixture, index_for, model


def test_large_single_bay_reports_measured_bounds_and_hostless_decision(tmp_path):
    cloud, manifest = fusion_fixture(tmp_path, 'window', frame=True)
    index = index_for(cloud, tmp_path)
    result_model = model()
    try:
        report = fuse_geometry(cloud, result_model, manifest, tmp_path, index.index,
                               Control(), ReconstructionSettings())
    finally:
        index.close()
    decision, = report['opening_decisions']
    assert decision['status'] == 'added_standalone_window'
    assert decision['host_wall_id'] is None
    assert decision['original_plane_point_count'] > 100
    assert min(decision['independent_frame_support_fractions']) >= .65
    assert decision['measured_height_m'] > 2.5
    assert decision['measured_width_m'] > 3.5
    assert decision['element_id'] == result_model.facade_panels[0].id


def test_semantic_glazing_rejection_retains_the_original_frame_test(tmp_path):
    cloud, manifest = fusion_fixture(tmp_path, 'window', frame=False)
    index = index_for(cloud, tmp_path)
    result_model = model()
    try:
        report = fuse_geometry(cloud, result_model, manifest, tmp_path, index.index,
                               Control(), ReconstructionSettings())
    finally:
        index.close()
    decision, = report['opening_decisions']
    assert decision['status'] == 'rejected'
    assert decision['reason'] == 'independent_frame_support_failed'
    assert decision['independent_frame_support_fractions'] == [0., 0., 0., 0.]
    assert not result_model.openings and not result_model.facade_panels
    assert report['accepted_cuts'] == report['user_acceptance_changes'] == 0
