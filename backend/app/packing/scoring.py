"""Exact lexicographic scores: smaller is better; units never become magic weights."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models import BoxType, PackedBox, PackingResult, Placement


def _overlap(a: int, end_a: int, b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(a, b))


def contact_area(placement: Placement, box: BoxType, placements: Sequence[Placement]) -> int:
    """Contact with walls/floor/lid and existing faces, in square millimetres."""
    p, d = placement.position, placement.dimensions
    x1, y1, z1 = p.x + d.length, p.y + d.width, p.z + d.height
    area = (
        d.width * d.height * ((p.x == 0) + (x1 == box.length))
        + d.length * d.height * ((p.y == 0) + (y1 == box.width))
        + d.length * d.width * ((p.z == 0) + (z1 == box.height))
    )
    for other in placements:
        q, e = other.position, other.dimensions
        qx1, qy1, qz1 = q.x + e.length, q.y + e.width, q.z + e.height
        if p.x == qx1 or x1 == q.x:
            area += _overlap(p.y, y1, q.y, qy1) * _overlap(p.z, z1, q.z, qz1)
        if p.y == qy1 or y1 == q.y:
            area += _overlap(p.x, x1, q.x, qx1) * _overlap(p.z, z1, q.z, qz1)
        if p.z == qz1 or z1 == q.z:
            area += _overlap(p.x, x1, q.x, qx1) * _overlap(p.y, y1, q.y, qy1)
    return area


def placement_score(
    placement: Placement,
    box: BoxType,
    placements: Sequence[Placement],
    orientation_index: int = 0,
    *,
    occupied_bounds: tuple[int, int, int] | None = None,
) -> tuple[int, ...]:
    p, d = placement.position, placement.dimensions
    if occupied_bounds is None:
        height = max((q.position.z + q.dimensions.height for q in placements), default=0)
        length = max((q.position.x + q.dimensions.length for q in placements), default=0)
        width = max((q.position.y + q.dimensions.width for q in placements), default=0)
    else:
        length, width, height = occupied_bounds
    resulting_height = max(height, p.z + d.height)
    # A compact occupied envelope is a modest fragmentation proxy, not a free-space proof.
    envelope = max(length, p.x + d.length) * max(width, p.y + d.width) * resulting_height
    return (
        p.z,
        resulting_height,
        -contact_area(placement, box, placements),
        envelope,
        p.x + p.y,
        orientation_index,
        p.x,
        p.y,
        d.length,
        d.width,
        d.height,
    )


@dataclass(frozen=True, slots=True)
class PackingComplexity:
    steps: int
    extra_layers: int
    raised_items: int
    orientation_changes: int

    @property
    def total(self) -> int:
        return self.steps + self.extra_layers + self.raised_items + self.orientation_changes


def packing_complexity(boxes: Sequence[PackedBox]) -> PackingComplexity:
    return PackingComplexity(
        steps=sum(len(box.placements) for box in boxes),
        extra_layers=sum(max(0, len({p.position.z for p in box.placements}) - 1) for box in boxes),
        raised_items=sum(p.position.z > 0 for box in boxes for p in box.placements),
        orientation_changes=sum(
            a.orientation != b.orientation
            for box in boxes
            for a, b in zip(box.placements, box.placements[1:])
        ),
    )


def solution_signature(boxes: Sequence[PackedBox]) -> tuple:
    """Ignore opening order and interchangeable units of the same product."""
    return tuple(
        sorted(
            (
                box.box_type_id,
                tuple(
                    sorted(
                        (
                            p.product_id,
                            p.position.x,
                            p.position.y,
                            p.position.z,
                            p.dimensions.length,
                            p.dimensions.width,
                            p.dimensions.height,
                            p.orientation,
                        )
                        for p in box.placements
                    )
                ),
            )
            for box in boxes
        )
    )


def solution_score(result: PackingResult, boxes: dict[str, BoxType]) -> tuple:
    m = result.metrics
    # With packed count/volume fixed, minimum carton volume maximizes overall fill.
    scarce_usage = sum(
        count for bid, count in m.boxes_by_type.items() if boxes[bid].available_count == count
    )
    return (
        m.unpacked_items,
        -m.used_volume,
        m.empty_volume,
        m.boxes_used,
        packing_complexity(result.packed_boxes).total,
        scarce_usage,
        solution_signature(result.packed_boxes),
    )
