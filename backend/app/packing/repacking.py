"""Improve carton layouts without changing item assignment or fill metrics."""

from dataclasses import replace
from fractions import Fraction

from app.domain.models import Dimensions, PackingRequest, PackingResult, Position
from app.packing.control import SearchControl
from app.packing.engine import _fill_box
from app.packing.options import EngineOptions
from app.packing.orientations import unique_orientations
from app.packing.strategies import expand_items, volume


def layout_score(placements) -> tuple:
    height = max((p.position.z + p.dimensions.height for p in placements), default=0)
    length = max((p.position.x + p.dimensions.length for p in placements), default=0)
    width = max((p.position.y + p.dimensions.width for p in placements), default=0)
    return (
        height,
        sum(p.position.z for p in placements),
        length * width * height,
        sum(p.position.x + p.position.y for p in placements),
    )


def repack_cartons(
    request: PackingRequest, result: PackingResult, control: SearchControl
) -> PackingResult:
    items = {item.id: item for item in expand_items(request)}
    cartons = {box.id: box for box in request.boxes}
    orientations = {
        p.id: unique_orientations(Dimensions(p.length, p.width, p.height), p.allow_rotation)
        for p in request.products
    }
    options = EngineOptions(min_support_ratio=Fraction(1), max_candidate_points=64)
    packed = []
    for index, box in enumerate(result.packed_boxes):
        control.report("repacking", index / max(1, len(result.packed_boxes)))
        # Translating the entire layout preserves contacts and full support.
        left = min(p.position.x for p in box.placements)
        front = min(p.position.y for p in box.placements)
        best = tuple(
            replace(p, position=Position(p.position.x - left, p.position.y - front, p.position.z))
            for p in box.placements
        )
        assigned = tuple(items[p.item_instance_id] for p in box.placements)
        orders = (
            sorted(assigned, key=lambda item: (-volume(item), item.id)),
            sorted(assigned, key=lambda item: (-item.length * item.width, -item.weight, item.id)),
        )
        for ordered in orders:
            if control.expired():
                break
            filled = _fill_box(
                cartons[box.box_type_id], tuple(ordered), orientations, options, control
            )
            # A greedy repack is accepted only if every assigned item still fits.
            if (
                len(filled.placements) == len(assigned)
                and layout_score(filled.placements) < layout_score(best)
            ):
                best = filled.placements
        packed.append(replace(box, placements=best, instructions=()))
    return replace(result, packed_boxes=tuple(packed))
