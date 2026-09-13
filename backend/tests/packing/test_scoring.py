"""Behavioral comparisons for documented priorities, independent of search order."""

from dataclasses import replace

from app.domain.models import (
    BoxType,
    Dimensions,
    ItemInstance,
    Orientation,
    PackedBox,
    PackingMetrics,
    PackingResult,
    Placement,
    Position,
)
from app.packing.scoring import (
    contact_area,
    packing_complexity,
    placement_score,
    solution_score,
    solution_signature,
)


def placed(
    identifier: str = "item:1",
    position: tuple[int, int, int] = (0, 0, 0),
    dimensions: tuple[int, int, int] = (10, 10, 10),
    orientation: Orientation = "LWH",
) -> Placement:
    return Placement(
        identifier,
        identifier.split(":")[0],
        Position(*position),
        Dimensions(*dimensions),
        orientation,
        1,
    )


def box_type(
    identifier: str = "box",
    dimensions: tuple[int, int, int] = (100, 100, 100),
    stock: int = 10,
) -> BoxType:
    return BoxType(identifier, identifier, *dimensions, 10000, stock)


def packed_box(source: BoxType, placements: tuple[Placement, ...], index: int = 1) -> PackedBox:
    used = sum(p.dimensions.length * p.dimensions.width * p.dimensions.height for p in placements)
    return PackedBox(
        f"{source.id}:{index}",
        source.id,
        source.name,
        source.length,
        source.width,
        source.height,
        source.max_weight,
        len(placements),
        used,
        round(used / (source.length * source.width * source.height), 6),
        tuple(replace(p, step=step) for step, p in enumerate(placements, 1)),
    )


def solution(boxes: tuple[PackedBox, ...], unpacked: int = 0) -> PackingResult:
    count = sum(len(box.placements) for box in boxes)
    used = sum(box.used_volume for box in boxes)
    volume = sum(box.length * box.width * box.height for box in boxes)
    by_type = {}
    for box in boxes:
        by_type[box.box_type_id] = by_type.get(box.box_type_id, 0) + 1
    return PackingResult(
        "partial" if unpacked else "success",
        PackingMetrics(
            count + unpacked,
            count,
            unpacked,
            len(boxes),
            by_type,
            volume,
            used,
            volume - used,
            round(used / volume, 6) if volume else 0,
            count,
        ),
        boxes,
        tuple(
            ItemInstance(f"leftover:{index}", "leftover", "Leftover", index, 1, 1, 1, 1, False)
            for index in range(1, unpacked + 1)
        ),
    )


def test_lower_z_precedes_better_contact_and_lower_envelope() -> None:
    box = box_type()
    support = placed("support:1")
    floor = placed(position=(20, 20, 0))
    raised = placed(position=(0, 0, 10))
    assert contact_area(floor, box, (support,)) < contact_area(raised, box, (support,))
    assert placement_score(floor, box, (support,)) < placement_score(raised, box, (support,))


def test_lower_resulting_height_precedes_contact() -> None:
    box = box_type()
    short = placed(position=(20, 20, 0), dimensions=(20, 10, 5))
    tall = placed(dimensions=(10, 5, 20))
    assert contact_area(short, box, ()) < contact_area(tall, box, ())
    assert placement_score(short, box, ()) < placement_score(tall, box, ())


def test_wall_contact_precedes_smaller_envelope_and_distance() -> None:
    box = box_type()
    wall = placed(position=(0, 70, 0))
    interior = placed(position=(10, 10, 0))
    assert contact_area(wall, box, ()) == 200
    assert contact_area(interior, box, ()) == 100
    assert placement_score(wall, box, ()) < placement_score(interior, box, ())


def test_smaller_envelope_precedes_shorter_origin_distance() -> None:
    box = box_type()
    compact = placed(position=(1, 20, 0))
    near_origin = placed(position=(10, 10, 0))
    assert contact_area(compact, box, ()) == contact_area(near_origin, box, ())
    assert placement_score(compact, box, ()) < placement_score(near_origin, box, ())


def test_origin_distance_breaks_equal_contact_and_envelope_tie() -> None:
    box = box_type()
    near = placed(position=(20, 10, 0))
    far = placed(position=(30, 5, 0))
    assert placement_score(near, box, ()) < placement_score(far, box, ())


def test_orientation_index_breaks_equal_geometry_tie() -> None:
    placement, box = placed(), box_type()
    assert placement_score(placement, box, (), 0) < placement_score(placement, box, (), 5)


def test_placement_coordinate_tie_break_is_stable() -> None:
    box = box_type()
    left = placed(position=(10, 20, 0))
    right = placed(position=(20, 10, 0))
    assert placement_score(left, box, ()) < placement_score(right, box, ())
    assert placement_score(left, box, ()) == placement_score(left, box, ())


def test_contact_area_counts_box_faces_in_square_millimetres() -> None:
    assert contact_area(placed(), box_type(), ()) == 300
    assert contact_area(placed(position=(20, 20, 20)), box_type(), ()) == 0
    assert contact_area(placed(), box_type(dimensions=(10, 10, 10)), ()) == 600


def test_contact_area_counts_partial_neighbor_faces_but_not_edges() -> None:
    candidate = placed(position=(20, 20, 20))
    neighbor = placed("other:1", position=(10, 25, 20))
    edge = placed("other:1", position=(10, 30, 20))
    assert contact_area(candidate, box_type(), (neighbor,)) == 50
    assert contact_area(candidate, box_type(), (edge,)) == 0


def test_complexity_empty_plan_and_flat_layer() -> None:
    empty = packing_complexity(())
    assert empty.steps == empty.extra_layers == empty.raised_items == empty.orientation_changes == 0
    assert empty.total == 0
    flat = packing_complexity(
        (
            packed_box(
                box_type(),
                (
                    placed(),
                    placed("item:2", position=(10, 0, 0)),
                ),
            ),
        )
    )
    assert flat.steps == flat.total == 2
    assert flat.extra_layers == flat.raised_items == flat.orientation_changes == 0


def test_complexity_counts_layers_raised_items_and_orientation_changes() -> None:
    stacked = packed_box(
        box_type(),
        (
            placed("a:1"),
            placed("b:1", position=(10, 0, 0), dimensions=(20, 10, 10), orientation="WLH"),
            placed("c:1", position=(0, 0, 10), dimensions=(20, 10, 10), orientation="WLH"),
            placed("d:1", position=(0, 0, 20)),
        ),
    )
    complexity = packing_complexity((stacked,))
    assert complexity.steps == 4
    assert complexity.extra_layers == 2
    assert complexity.raised_items == 2
    assert complexity.orientation_changes == 2
    assert complexity.total == 10


def test_complexity_does_not_count_orientation_transition_between_boxes() -> None:
    first = packed_box(box_type(), (placed(),))
    second = packed_box(
        box_type(), (placed("other:1", dimensions=(30, 20, 10), orientation="HWL"),), index=2
    )
    complexity = packing_complexity((first, second))
    assert complexity.steps == complexity.total == 2
    assert complexity.orientation_changes == 0


def test_solution_fill_precedes_packed_count() -> None:
    source = box_type(dimensions=(10, 10, 10))
    one_large = solution((packed_box(source, (placed(),)),), unpacked=2)
    two_small = solution(
        (
            packed_box(
                source,
                (
                    placed("small:1", dimensions=(5, 5, 5)),
                    placed("small:2", position=(5, 0, 0), dimensions=(5, 5, 5)),
                ),
            ),
        ),
        unpacked=1,
    )
    assert two_small.metrics.used_volume < one_large.metrics.used_volume
    assert solution_score(one_large, {source.id: source}) < solution_score(
        two_small, {source.id: source}
    )


def test_solution_fill_precedes_packed_volume_for_equal_count() -> None:
    roomy = box_type("roomy", (20, 20, 20))
    tiny = box_type("tiny", (5, 5, 5))
    large = solution((packed_box(roomy, (placed(),)),), unpacked=1)
    small = solution((packed_box(tiny, (placed(dimensions=(5, 5, 5)),)),), unpacked=1)
    assert large.metrics.empty_volume > small.metrics.empty_volume
    assert solution_score(small, {tiny.id: tiny}) < solution_score(large, {roomy.id: roomy})


def test_solution_packed_volume_precedes_box_count_for_equal_item_count() -> None:
    source = box_type(dimensions=(10, 10, 10))
    larger_volume = solution(
        (
            packed_box(source, (placed("large:1"),)),
            packed_box(source, (placed("large:2"),), index=2),
        )
    )
    fewer_boxes = solution(
        (
            packed_box(
                source,
                (
                    placed("small:1", dimensions=(5, 5, 5)),
                    placed("small:2", position=(5, 0, 0), dimensions=(5, 5, 5)),
                ),
            ),
        )
    )
    assert larger_volume.metrics.packed_items == fewer_boxes.metrics.packed_items
    assert larger_volume.metrics.boxes_used > fewer_boxes.metrics.boxes_used
    assert solution_score(larger_volume, {source.id: source}) < solution_score(
        fewer_boxes, {source.id: source}
    )


def test_solution_overall_fill_precedes_fewer_boxes() -> None:
    roomy = box_type("roomy", (30, 10, 10))
    tight = box_type("tight", (10, 10, 10))
    single = solution((packed_box(roomy, (placed(), placed("item:2", (10, 0, 0)))),))
    double = solution(
        (packed_box(tight, (placed(),)), packed_box(tight, (placed("item:2"),), index=2))
    )
    assert single.metrics.used_volume == double.metrics.used_volume
    assert single.metrics.empty_volume > double.metrics.empty_volume
    assert solution_score(double, {tight.id: tight}) < solution_score(single, {roomy.id: roomy})


def test_solution_less_unused_volume_breaks_equal_count_volume_and_box_tie() -> None:
    roomy = box_type("roomy", (30, 10, 10))
    tight = box_type("tight", (20, 10, 10))
    placements = (placed(), placed("item:2", (10, 0, 0)))
    loose = solution((packed_box(roomy, placements),))
    compact = solution((packed_box(tight, placements),))
    assert solution_score(compact, {tight.id: tight}) < solution_score(loose, {roomy.id: roomy})


def test_solution_simpler_packing_breaks_equal_physical_utilization_tie() -> None:
    source = box_type(dimensions=(20, 10, 20))
    flat = solution((packed_box(source, (placed(), placed("item:2", (10, 0, 0)))),))
    stacked = solution((packed_box(source, (placed(), placed("item:2", (0, 0, 10)))),))
    assert flat.metrics == stacked.metrics
    assert solution_score(flat, {source.id: source}) < solution_score(stacked, {source.id: source})


def test_solution_stock_usage_breaks_equal_quality_tie_before_identifier() -> None:
    scarce = box_type("a-scarce", (10, 10, 10), stock=1)
    plentiful = box_type("z-plentiful", (10, 10, 10), stock=5)
    exhausted = solution((packed_box(scarce, (placed(),)),))
    reserved = solution((packed_box(plentiful, (placed(),)),))
    assert solution_score(reserved, {plentiful.id: plentiful}) < solution_score(
        exhausted, {scarce.id: scarce}
    )


def test_solution_complexity_precedes_conserving_stock() -> None:
    scarce = box_type("z-scarce", (20, 10, 20), stock=1)
    plentiful = box_type("a-plentiful", (20, 10, 20), stock=5)
    flat = solution((packed_box(scarce, (placed(), placed("item:2", (10, 0, 0)))),))
    stacked = solution((packed_box(plentiful, (placed(), placed("item:2", (0, 0, 10)))),))
    assert solution_score(flat, {scarce.id: scarce}) < solution_score(
        stacked, {plentiful.id: plentiful}
    )


def test_solution_signature_ignores_box_order_and_swapped_identical_units() -> None:
    source = box_type(dimensions=(20, 10, 10))
    first = packed_box(source, (placed(), placed("item:2", (10, 0, 0))))
    second = packed_box(source, (placed("item:3"),), index=2)
    swapped = replace(
        first,
        placements=(
            replace(first.placements[1], item_instance_id="item:1", step=1),
            replace(first.placements[0], item_instance_id="item:2", step=2),
        ),
    )
    assert solution_signature((first, second)) == solution_signature((second, swapped))
    moved = replace(
        first,
        placements=(first.placements[0], replace(first.placements[1], position=Position(0, 0, 10))),
    )
    assert solution_signature((first, second)) != solution_signature((moved, second))
