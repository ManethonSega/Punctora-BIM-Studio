"""Room-graph regressions independent of the production topology implementation.

Saved slab boundaries below are final exported footprints, never raw occupancy.
They reproduce the returned run's lack of useful completion, not a measured
ceiling reconstruction acceptance test. Synthetic rooms isolate each boundary.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely.affinity import rotate, translate

from punctora_core.ceiling_completion import complete_ceiling_rooms
from punctora_core.model import Storey, Wall


def walls_from_segments(segments):
    return [
        Wall(f"wall-{index}", "room-storey", start, end, 0., 3., .2,
             evidence_count=100, fit_rmse_m=.005)
        for index, (start, end) in enumerate(segments)
    ]


def closed_segments():
    return [((0., 0.), (4., 0.)), ((4., 0.), (4., 4.)),
            ((4., 4.), (0., 4.)), ((0., 4.), (0., 0.))]


def complete_fixture(segments, *, raw=None, floor=None, protected=None):
    owner = Storey("room-storey", "Synthetic room", 0., 3.,
                   [(0., 0.), (4., 0.), (4., 4.), (0., 4.)])
    if raw is None:
        raw = box(0, 0, 4, 4).difference(box(1.6, 1.6, 2.4, 2.4))
    if floor is None:
        floor = box(0, 0, 4, 4)
    if protected is None:
        protected = Polygon()
    completed, addition, report = complete_ceiling_rooms(
        raw, raw, floor, walls_from_segments(segments), owner, 3., protected,
    )
    return raw, completed, addition, report


def test_near_t_junction_uses_independent_wall_segment_within_existing_limit():
    # The bottom wall's endpoints are distant; the side-wall ends lie 8 cm
    # from its interior. Endpoint-to-endpoint joining cannot close this room.
    segments = [((-1., 0.), (5., 0.)), ((4., .08), (4., 4.)),
                ((4., 4.), (0., 4.)), ((0., 4.), (0., .08))]
    _, completed, addition, report = complete_fixture(segments)

    assert completed.equals(box(0, 0, 4, 4))
    assert addition.area == pytest.approx(.64)
    assert addition.difference(box(0, 0, 4, 4)).is_empty
    accepted = [entry for entry in report if entry['state'] == 'justified_completion']
    assert len(accepted) == 1
    assert accepted[0]['maximum_endpoint_join_m'] == .12


@pytest.mark.parametrize('angle', [1., 13., 30., 45., 60., 83., 91., 137.])
def test_near_t_junction_is_stable_after_rotation_and_translation(angle):
    from shapely.geometry import LineString
    segments = [((-1., 0.), (5., 0.)), ((4., .08), (4., 4.)),
                ((4., 4.), (0., 4.)), ((0., 4.), (0., .08))]
    def transform(shape):
        return translate(rotate(shape, angle, origin=(0., 0.)), 10., 20.)
    transformed = [list(transform(LineString(segment)).coords) for segment in segments]
    room = transform(box(0, 0, 4, 4))
    raw = transform(box(0, 0, 4, 4).difference(box(1.6, 1.6, 2.4, 2.4)))
    _, completed, addition, _ = complete_fixture(transformed, raw=raw, floor=room)
    assert addition.area == pytest.approx(.64, abs=1e-9)
    assert completed.symmetric_difference(room).area < 1e-9


def test_offset_corner_closes_only_to_the_nearby_crossing_of_observed_lines():
    # Both observed line ends are 10 cm from their common crossing. The
    # diagonal endpoint gap is >12 cm; neither arm needs >12 cm extension.
    segments = [((0., 0.), (3.9, 0.)), ((4., .1), (4., 4.)),
                ((4., 4.), (0., 4.)), ((0., 4.), (0., 0.))]
    _, completed, addition, report = complete_fixture(segments)

    assert completed.equals(box(0, 0, 4, 4))
    assert addition.area == pytest.approx(.64)
    assert all(entry['maximum_endpoint_join_m'] == .12 for entry in report)


def test_open_portal_beyond_existing_limit_does_not_become_a_room():
    # A 13 cm gap in a straight wall is a missing boundary, not an
    # independently crossing segment. No tolerance increase may close it.
    segments = [((0., 0.), (1.935, 0.)), ((2.065, 0.), (4., 0.)),
                ((4., 0.), (4., 4.)), ((4., 4.), (0., 4.)),
                ((0., 4.), (0., 0.))]
    raw, completed, addition, report = complete_fixture(segments)

    assert completed.equals(raw)
    assert addition.is_empty
    assert not any(entry['state'] == 'justified_completion' for entry in report)
    summary = next(entry for entry in report if entry['state'] == 'topology_diagnostic')
    assert summary['reason'] == 'no_closed_useful_wall_rooms'
    assert summary['useful_room_count'] == 0
    assert summary['completion_area_m2'] == 0.
    assert summary['maximum_endpoint_join_m'] == .12


def test_near_t_junction_preserves_independently_protected_real_void():
    segments = [((-1., 0.), (5., 0.)), ((4., .08), (4., 4.)),
                ((4., 4.), (0., 4.)), ((0., 4.), (0., .08))]
    missing = box(1.4, 1.4, 2.6, 2.6)
    protected = box(1.8, 1.8, 2.2, 2.2)
    raw = box(0, 0, 4, 4).difference(missing)
    _, completed, addition, report = complete_fixture(
        segments, raw=raw, protected=protected,
    )

    assert completed.equals(box(0, 0, 4, 4).difference(protected))
    assert addition.area == pytest.approx(1.28)
    assert addition.intersection(protected).area == 0.
    assert completed.intersection(protected).area == 0.
    assert any(entry['state'] == 'justified_completion' for entry in report)


@pytest.mark.parametrize(
    'raw,floor,reason,ceiling_fraction,floor_fraction',
    [
        (box(0, 0, 1.76, 4), box(0, 0, 4, 4),
         'insufficient_measured_ceiling_support', .44, 1.),
        (box(0, 0, 4, 4).difference(box(1.6, 1.6, 2.4, 2.4)),
         box(0, 0, 3.16, 4), 'insufficient_floor_support', .96, .79),
    ],
)
def test_rejected_room_reports_which_support_gate_failed(
    raw, floor, reason, ceiling_fraction, floor_fraction,
):
    _, completed, addition, report = complete_fixture(
        closed_segments(), raw=raw, floor=floor,
    )

    assert completed.equals(raw)
    assert addition.is_empty
    rejected = next(entry for entry in report if entry['state'] == 'rejected_completion')
    assert rejected['reason'] == reason
    assert rejected['room_area_m2'] == pytest.approx(16.)
    assert rejected['measured_ceiling_fraction'] == pytest.approx(ceiling_fraction)
    assert rejected['floor_support_fraction'] == pytest.approx(floor_fraction)
    assert rejected['completion_area_m2'] == 0.
    assert rejected['maximum_endpoint_join_m'] == .12
    summary = next(entry for entry in report if entry['state'] == 'topology_diagnostic')
    assert summary['reason'] == 'no_supported_wall_rooms'
    assert summary['useful_room_count'] == 1
    assert summary['supported_room_count'] == 0
    assert summary['completion_area_m2'] == 0.


@pytest.mark.parametrize('raw,floor', [
    (box(0, 0, 1.8, 4), box(0, 0, 4, 4)),  # measured fraction exactly .45
    (box(0, 0, 4, 4).difference(box(1.6, 1.6, 2.4, 2.4)),
     box(0, 0, 3.2, 4)),  # floor fraction exactly .80
])
def test_existing_support_gate_boundaries_remain_inclusive(raw, floor):
    _, completed, addition, report = complete_fixture(closed_segments(), raw=raw, floor=floor)

    assert addition.area > 0.
    assert completed.area > raw.area
    assert any(entry['state'] == 'justified_completion' for entry in report)


def test_returned_saved_boundaries_have_no_supported_room_completion_and_explain_why():
    data = json.loads((Path(__file__).parent / 'fixtures' /
                       'returned_kita_ceiling_topology.json').read_text())
    owner = SimpleNamespace(id='returned-storey')
    walls = [SimpleNamespace(storey_id=owner.id, **entry) for entry in data['walls']]
    ceiling_proxy = unary_union([Polygon(ring) for ring in data['ceiling_boundaries']])
    floor_proxy = unary_union([Polygon(ring) for ring in data['floor_boundaries']])
    completed, addition, report = complete_ceiling_rooms(
        ceiling_proxy, ceiling_proxy, floor_proxy, walls, owner,
        data['ceiling_elevation_m'], Polygon(),
    )

    assert addition.is_empty
    assert completed.equals(ceiling_proxy)
    assert not any(entry['state'] == 'justified_completion' for entry in report)
    rejected = next(entry for entry in report
                    if entry.get('reason') == 'insufficient_measured_ceiling_support'
                    and entry.get('room_area_m2', 0.) >= 1.)
    assert rejected['room_area_m2'] == pytest.approx(1.581125343930123)
    assert rejected['measured_ceiling_fraction'] == 0.
    assert rejected['floor_support_fraction'] == pytest.approx(.8834862601089247)
    summary = next(entry for entry in report if entry['state'] == 'topology_diagnostic')
    assert summary['reason'] == 'no_supported_wall_rooms'
    assert summary['useful_room_count'] >= 1
    assert summary['supported_room_count'] == 0
    assert summary['completion_area_m2'] == 0.
    assert summary['maximum_endpoint_join_m'] == .12
