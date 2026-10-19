"""Trace actual original-plane/frame decisions for large glazing proposals."""
import numpy as np
import json
import pytest

from punctora_core.reconstruction import ReconstructionSettings
from punctora_core.model import Wall
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


@pytest.mark.parametrize('hosted', [False, True])
@pytest.mark.parametrize('z_intervals', [((.25, 1.15), (1.85, 2.75)),
                                      ((.25, 1.35), (1.45, 2.75))], ids=['wide_gap', 'inside_frame_halo'])
def test_original_refit_preserves_separate_measured_window_heights(tmp_path, hosted, z_intervals):
    cloud, manifest = fusion_fixture(tmp_path, 'window', frame=True)
    points = cloud.points
    inside = (points[:, 0] >= .15) & (points[:, 0] <= 3.85)
    lower = inside & (points[:, 2] >= z_intervals[0][0]) & (points[:, 2] <= z_intervals[0][1])
    upper = inside & (points[:, 2] >= z_intervals[1][0]) & (points[:, 2] <= z_intervals[1][1])
    labels = np.zeros(len(points), dtype='<i2')
    labels[lower | upper] = 2
    np.save(tmp_path / 'labels.npy', labels)
    original = json.loads((tmp_path / 'proposals.json').read_text())['proposals'][0]
    proposals, entries, support = [], [], []
    offset = 0
    for number, mask in enumerate((lower, upper)):
        rows = np.flatnonzero(mask).astype('<u8')
        item = dict(original, id=f'I:window-{number}',
                    observed_z_bounds_m=[float(points[rows, 2].min()), float(points[rows, 2].max())])
        proposals.append(item)
        entries.append({'id': item['id'], 'offset': offset, 'count': len(rows)})
        support.append(rows)
        offset += len(rows)
    np.save(tmp_path / 'support.npy', np.concatenate(support))
    (tmp_path / 'proposals.json').write_text(json.dumps({'proposals': proposals}))
    (tmp_path / 'support.json').write_text(json.dumps({'entries': entries}))
    index = index_for(cloud, tmp_path)
    result_model = model()
    if hosted:
        result_model.walls.append(Wall('host', 's', (0., 0.), (4., 0.), 0., 3., .2))
    try:
        report = fuse_geometry(cloud, result_model, manifest, tmp_path, index.index,
                               Control(), ReconstructionSettings())
    finally:
        index.close()
    elements = result_model.openings if hosted else result_model.facade_panels
    ranges = sorted([(p.sill, p.sill + p.height) if hosted else (p.base, p.base + p.height)
                     for p in elements])
    assert len(elements) == 2
    np.testing.assert_allclose(ranges, [item['observed_z_bounds_m'] for item in proposals], atol=1e-12)
    assert ranges[0][1] < ranges[1][0]
    assert {d['status'] for d in report['opening_decisions']} == {
        'added_hosted_opening' if hosted else 'added_standalone_window'}
    assert report['accepted_cuts'] == report['user_acceptance_changes'] == 0
