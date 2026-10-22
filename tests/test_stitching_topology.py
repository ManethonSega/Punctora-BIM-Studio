"""Evidence envelopes must remain bounded when specialist tiles are stitched."""

from itertools import permutations

import numpy as np
import pytest
from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from punctora_core.recognition.streaming_views import stitch_proposals


def proposal(identifier, shape, *, kind="wall", observed_z=None):
    value = {
        "id": identifier,
        "branch": "I" if kind == "window" else "D",
        "class": kind,
        "status": "proposed",
        "geometry_authority": "review_only",
        "polygon_xy_m": [list(point) for point in shape.exterior.coords[:-1]],
        "z_min_m": 0.0,
        "z_max_m": 3.0,
        "support_points": 2,
    }
    if observed_z is not None:
        value["observed_z_bounds_m"] = list(observed_z)
    return value


def support_for(items):
    return {
        item["id"]: np.array([2 * index, 2 * index + 1], dtype="<u8")
        for index, item in enumerate(items)
    }


@pytest.mark.parametrize("angle", [0.0, 17.0, 45.0, 89.0])
@pytest.mark.parametrize("offset", [0.0, 1_000_000.0])
def test_multiway_stitch_respects_aggregate_area_bound_and_input_order(angle, offset):
    # The last tile touches two separate prior components. Each pair passes
    # the existing straight-seam test, but their three-way envelope bridges
    # unsupported corners and fails that same test against the total union.
    shapes = [box(-1, 0, 0, 0.13), box(1, -0.03, 2, 0.1), box(0, 0, 1, 0.1)]
    shapes = [translate(rotate(shape, angle, origin=(0, 0)), offset, 2 * offset)
              for shape in shapes]
    items = [proposal(identifier, shape) for identifier, shape in zip("abc", shapes)]
    originals = dict(zip("abc", shapes))
    support = support_for(items)

    assert shapes[0].distance(shapes[1]) > 0.055
    for previous in shapes[:2]:
        pair = previous.union(shapes[2])
        assert previous.distance(shapes[2]) <= 0.055
        assert pair.minimum_rotated_rectangle.area <= pair.area * 1.15 + 0.005
    aggregate = unary_union(shapes)
    assert aggregate.minimum_rotated_rectangle.area > aggregate.area * 1.15 + 0.005

    canonical = None
    for ordered in permutations(items):
        result, references = stitch_proposals(list(ordered), support)
        signature = (result, {key: value.tolist() for key, value in references.items()})
        if canonical is None:
            canonical = signature
        else:
            assert signature == canonical
        assert len(result) >= 2, "A multiway seam must not invent the unsupported corner area"
        members_seen = []
        for stitched in result:
            members = stitched.get("stitched_from", [stitched["id"]])
            members_seen.extend(members)
            measured = unary_union([originals[member] for member in members])
            emitted = Polygon(stitched["polygon_xy_m"])
            assert emitted.area <= measured.area * 1.15 + 0.005 + 1e-7
            assert stitched["support_points"] == sum(2 for _ in members)
            expected = np.unique(np.concatenate([support[member] for member in members]))
            np.testing.assert_array_equal(references[stitched["id"]], expected)
        assert sorted(members_seen) == ["a", "b", "c"]


def test_stitch_keeps_disjoint_measured_window_heights_separate():
    shape = box(0, 0, 2, 0.1)
    items = [
        proposal("a", shape, kind="window", observed_z=(0.4, 1.2)),
        proposal("b", shape, kind="window", observed_z=(1.8, 2.6)),
    ]
    support = support_for(items)

    first, references = stitch_proposals(items, support)
    second, reversed_references = stitch_proposals(list(reversed(items)), support)

    assert first == second
    assert len(first) == 2, "An opaque vertical separation is not a shared tile seam"
    assert [item["observed_z_bounds_m"] for item in first] == [[0.4, 1.2], [1.8, 2.6]]
    for item in first:
        np.testing.assert_array_equal(references[item["id"]], support[item["id"]])
        np.testing.assert_array_equal(references[item["id"]], reversed_references[item["id"]])


def test_stitch_retains_combined_measured_height_for_adjacent_window_parts():
    shape = box(0, 0, 2, 0.1)
    items = [
        proposal("a", shape, kind="window", observed_z=(0.4, 1.2)),
        proposal("b", shape, kind="window", observed_z=(1.2, 2.6)),
    ]
    support = support_for(items)

    result, references = stitch_proposals(items, support)

    assert len(result) == 1
    assert result[0]["observed_z_bounds_m"] == [0.4, 2.6]
    assert result[0]["stitched_from"] == ["a", "b"]
    assert result[0]["support_points"] == 4
    np.testing.assert_array_equal(references[result[0]["id"]], [0, 1, 2, 3])


def test_multiway_straight_seam_keeps_all_proposals_and_exact_source_keys():
    items = [proposal(key, shape) for key, shape in zip('abc', [
        box(-1, 0, 0, .1), box(1, 0, 2, .1), box(0, 0, 1, .1)])]
    support = support_for(items)
    result, references = stitch_proposals(items, support)
    assert len(result) == 1
    assert Polygon(result[0]['polygon_xy_m']).symmetric_difference(box(-1, 0, 2, .1)).area < 1e-12
    assert result[0]['stitched_from'] == ['a', 'b', 'c']
    np.testing.assert_array_equal(references[result[0]['id']], np.arange(6, dtype='<u8'))


def test_stitch_retains_declared_level_envelope_of_measured_parts():
    shape = box(0, 0, 2, .1)
    items = [proposal('a', shape, kind='window', observed_z=(.01, 2.9)),
             proposal('b', shape, kind='window', observed_z=(.1, 3.01))]
    items[1].update(z_min_m=.02, z_max_m=3.02)
    result, _ = stitch_proposals(items, support_for(items))
    assert len(result) == 1
    item, = result
    assert item['z_min_m'] <= item['observed_z_bounds_m'][0]
    assert item['z_max_m'] >= item['observed_z_bounds_m'][1]
    assert [item['z_min_m'], item['z_max_m']] == [0., 3.02]


@pytest.mark.parametrize('bounded_id', ['a', 'b'])
def test_stitch_does_not_apply_partial_measured_bounds_to_an_unknown_part(bounded_id):
    items = [proposal(key, box(0, 0, 2, .1), kind='window',
                      observed_z=(.4, 1.2) if key == bounded_id else None) for key in 'ab']
    result, references = stitch_proposals(items, support_for(items))
    assert len(result) == 2
    assert next(p for p in result if p['id'] == bounded_id)['observed_z_bounds_m'] == [.4, 1.2]
    assert 'observed_z_bounds_m' not in next(p for p in result if p['id'] != bounded_id)
    assert sum(len(rows) for rows in references.values()) == 4
