from fractions import Fraction
from itertools import product

import pytest

from app.domain.models import BoxType, Dimensions, Placement, Position
from app.packing.candidates import candidate_points, point_is_valid
from app.packing.geometry import (
    aabb_intersects,
    fits_inside_box,
    has_support,
    placement_inside_bounds,
    support_area,
    support_ratio,
)
from app.packing.orientations import ORIENTATION_ORDER, unique_orientations
from app.packing.relationships import placement_relationships


def box(length=100, width=100, height=100):
    return BoxType("box", "Box", length, width, height, 1000, 10)


def placed(item="a:1", position=(0, 0, 0), dimensions=(10, 10, 10), step=1):
    return Placement(
        item, item.split(":")[0], Position(*position), Dimensions(*dimensions), "LWH", step
    )


def test_six_unique_rotations_follow_contract_labels():
    orientations = unique_orientations(Dimensions(2, 3, 5))
    assert tuple(label for label, _ in orientations) == ORIENTATION_ORDER
    assert tuple(d for _, d in orientations) == (
        Dimensions(2, 3, 5),
        Dimensions(2, 5, 3),
        Dimensions(3, 2, 5),
        Dimensions(3, 5, 2),
        Dimensions(5, 2, 3),
        Dimensions(5, 3, 2),
    )


@pytest.mark.parametrize(
    ("dimensions", "labels"),
    [((2, 2, 2), ("LWH",)), ((2, 2, 3), ("LWH", "LHW", "HLW"))],
)
def test_rotation_duplicates_keep_first_contract_label(dimensions, labels):
    result = unique_orientations(Dimensions(*dimensions))
    assert tuple(label for label, _ in result) == labels
    assert len({dimensions for _, dimensions in result}) == len(result)


def test_tilting_disabled_still_allows_yaw():
    assert unique_orientations(Dimensions(2, 3, 5), False) == (
        ("LWH", Dimensions(2, 3, 5)),
        ("WLH", Dimensions(3, 2, 5)),
    )
    assert unique_orientations(Dimensions(2, 2, 5), False) == (("LWH", Dimensions(2, 2, 5)),)


@pytest.mark.parametrize("offset", [(10, 0, 0), (0, 10, 0), (0, 0, 10), (10, 10, 10)])
def test_touching_faces_edges_and_corners_are_not_collisions(offset):
    assert not aabb_intersects(placed(), placed("b:1", offset))
    assert not aabb_intersects(placed("b:1", offset), placed())


@pytest.mark.parametrize("offset", [(9, 0, 0), (0, 9, 0), (0, 0, 9), (9, 9, 9)])
def test_positive_overlap_is_collision(offset):
    assert aabb_intersects(placed(), placed("b:1", offset))
    assert aabb_intersects(placed("b:1", offset), placed())


def test_containment_is_collision():
    assert aabb_intersects(placed(dimensions=(30, 30, 30)), placed("b:1", (10, 10, 10)))


def test_integer_aabb_matches_small_voxel_oracle():
    # Independent discrete-volume oracle exercises all axes and one-mm boundaries.
    anchor = placed(dimensions=(2, 3, 2))
    anchor_cells = set(product(range(2), range(3), range(2)))
    for x, y, z in product(range(4), repeat=3):
        other = placed("b:1", (x, y, z), (2, 1, 2))
        other_cells = set(product(range(x, x + 2), range(y, y + 1), range(z, z + 2)))
        assert aabb_intersects(anchor, other) == bool(anchor_cells & other_cells)


def test_exact_fit_and_maximum_boundary_placement():
    assert fits_inside_box(Dimensions(100, 100, 100), box())
    assert placement_inside_bounds(placed(position=(90, 90, 90)), box())
    assert placement_inside_bounds(placed(dimensions=(100, 100, 100)), box())


@pytest.mark.parametrize("position", [(91, 0, 0), (0, 91, 0), (0, 0, 91), (-1, 0, 0)])
def test_out_of_bounds_by_one_mm(position):
    assert not placement_inside_bounds(placed(position=position), box())


def test_orientation_fit_and_invalid_zero_size():
    assert not fits_inside_box(Dimensions(101, 100, 100), box())
    assert not placement_inside_bounds(placed(dimensions=(0, 10, 10)), box())
    assert not aabb_intersects(placed(), placed("zero:1", (5, 0, 0), (0, 10, 10)))


def test_floor_support_needs_no_other_items():
    assert support_area(placed(), ()) == 100
    assert support_ratio(placed(), ()) == 1
    assert has_support(placed(), (), Fraction(1))


def test_full_support_and_vertical_gap():
    below = placed()
    above = placed("b:1", (0, 0, 10))
    assert support_area(above, (below,)) == 100
    assert support_ratio(above, (below,)) == 1
    assert has_support(above, (below,), Fraction(1))
    assert not has_support(placed("b:1", (0, 0, 11)), (below,))


def test_partial_support_threshold_uses_exact_integer_comparison():
    above = placed("top:1", (0, 0, 10), (100, 100, 10))
    enough = placed(dimensions=(80, 100, 10))
    short = placed(dimensions=(79, 100, 10))
    assert support_ratio(above, (enough,)) == 0.8
    assert has_support(above, (enough,), Fraction(4, 5))
    assert not has_support(above, (short,), Fraction(4, 5))
    assert has_support(above, (short,), Fraction(3, 4))


def test_unsupported_even_with_zero_threshold_and_edge_contact():
    above = placed("top:1", (10, 0, 10))
    assert support_area(above, (placed(),)) == 0
    assert not has_support(above, (placed(),), Fraction(0))
    assert not has_support(above, (), Fraction(0))


def test_support_union_does_not_double_count_overlapping_surfaces():
    above = placed("top:1", (0, 0, 10))
    supports = (
        placed("left:1", dimensions=(6, 10, 10)),
        placed("right:1", (4, 0, 0), (6, 10, 10)),
        placed("duplicate:1", dimensions=(6, 10, 10)),
    )
    # Deliberately overlapping inputs test geometry independently from valid packing.
    assert support_area(above, supports) == 100
    assert support_ratio(above, supports) == 1


def test_support_union_clips_to_bottom_face_and_preserves_holes():
    above = placed("top:1", (5, 5, 10))
    supports = (
        placed("left:1", dimensions=(10, 30, 10)),
        placed("right:1", (12, 0, 0), (20, 30, 10)),
    )
    assert support_area(above, supports) == 80


def test_support_union_matches_integer_area_oracle():
    above = placed("top:1", (1, 1, 2), (5, 5, 1))
    supports = (
        placed("a:1", (0, 0, 0), (3, 4, 2)),
        placed("b:1", (2, 2, 0), (4, 2, 2)),
        placed("c:1", (4, 3, 0), (3, 4, 2)),
    )
    covered = {
        (x, y)
        for support in supports
        for x in range(
            max(1, support.position.x), min(6, support.position.x + support.dimensions.length)
        )
        for y in range(
            max(1, support.position.y), min(6, support.position.y + support.dimensions.width)
        )
    }
    assert support_area(above, supports) == len(covered)


@pytest.mark.parametrize("threshold", [Fraction(-1, 10), Fraction(11, 10)])
def test_invalid_support_threshold(threshold):
    with pytest.raises(ValueError):
        has_support(placed(), (), threshold)


def test_empty_box_and_three_positive_face_candidates():
    assert candidate_points(box(), ()) == (Position(0, 0, 0),)
    assert set(candidate_points(box(), (placed(),))) == {
        Position(10, 0, 0),
        Position(0, 10, 0),
        Position(0, 0, 10),
    }


@pytest.mark.parametrize("point", [(0, 0, 0), (5, 5, 5), (0, 9, 9)])
def test_candidate_excludes_occupied_minimum_faces_and_interior(point):
    assert not point_is_valid(Position(*point), box(), (placed(),))


@pytest.mark.parametrize("point", [(10, 0, 0), (0, 10, 0), (0, 0, 10)])
def test_candidate_allows_positive_item_faces(point):
    assert point_is_valid(Position(*point), box(), (placed(),))


@pytest.mark.parametrize("point", [(100, 0, 0), (0, 100, 0), (0, 0, 100), (-1, 0, 0)])
def test_candidate_excludes_outer_box_maxima_and_negative_coordinates(point):
    assert not point_is_valid(Position(*point), box(), ())


def test_projection_recovers_wall_corner():
    placements = (placed(), placed("b:1", (10, 0, 0), (5, 20, 10)))
    points = candidate_points(box(), placements)
    assert Position(0, 20, 0) in points  # x projection of (10, 20, 0)
    assert all(point_is_valid(point, box(), placements) for point in points)


def test_projection_stops_at_blocking_face():
    placements = (
        placed(),
        placed("b:1", (20, 20, 0), (5, 5, 10)),
        placed("c:1", (0, 20, 0)),
    )
    assert Position(10, 25, 0) in candidate_points(box(), placements)


def test_candidate_coordinate_dominance_does_not_remove_supported_top():
    points = candidate_points(box(), (placed(position=(10, 10, 0)),))
    assert Position(0, 0, 0) in points
    assert Position(10, 10, 10) in points


def test_candidate_cap_deduplication_and_input_permutation_are_deterministic():
    placements = (placed(), placed("b:1", (10, 0, 0)), placed("c:1", (0, 10, 0)))
    points = candidate_points(box(), placements, 3)
    assert len(points) == len(set(points)) == 3
    assert points == candidate_points(box(), tuple(reversed(placements)), 3)
    assert list(points) == sorted(points, key=lambda p: (p.z, p.x + p.y, p.x, p.y))


def test_exactly_full_box_has_no_candidates():
    assert candidate_points(box(10, 10, 10), (placed(),)) == ()


def test_relationships_report_support_and_direct_side_contacts():
    placements = (
        placed("a:1"),
        placed("b:1", (10, 0, 0), step=2),
        placed("c:1", (0, 10, 0), step=3),
        placed("top:1", (0, 0, 10), (20, 10, 10), step=4),
    )
    relationships = placement_relationships(tuple(reversed(placements)))
    assert tuple(r.item_instance_id for r in relationships) == ("a:1", "b:1", "c:1", "top:1")
    assert relationships[0].on_floor
    assert relationships[1].right_of == ("a:1",)
    assert relationships[2].behind == ("a:1",)
    assert relationships[3].supported_by == ("a:1", "b:1")
    assert not relationships[3].on_floor


def test_relationships_ignore_edge_contacts_and_vertical_gaps():
    relationships = placement_relationships(
        (placed(), placed("diagonal:1", (10, 10, 0), step=2), placed("air:1", (0, 0, 11), step=3))
    )
    assert relationships[1].right_of == relationships[1].behind == ()
    assert relationships[2].supported_by == ()
