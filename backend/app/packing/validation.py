"""Independent postconditions for every packing plan, without engine imports.

The explicit AABB and rectangle-union checks deliberately do not share heuristic
implementation code: a geometry bug must not validate itself.
"""

from collections import Counter
from fractions import Fraction

from app.domain.models import (
    ItemInstance,
    PackedBox,
    PackingAlternative,
    PackingMetrics,
    PackingRequest,
    PackingResult,
    Placement,
)

_ORIENTATIONS = ("LWH", "LHW", "WLH", "WHL", "HLW", "HWL")
_CAUSES = frozenset(
    {
        "ITEM_TOO_LARGE",
        "ITEM_TOO_HEAVY",
        "BOX_STOCK_EXHAUSTED",
        "NO_BOX_TYPES",
        "NO_FEASIBLE_PLACEMENT",
    }
)


class PackingValidationError(ValueError):
    """A produced plan violates a domain or physical invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PackingValidationError(message)


def _bounds(placement: Placement) -> tuple[int, int, int, int, int, int]:
    point, size = placement.position, placement.dimensions
    return (
        point.x,
        point.x + size.length,
        point.y,
        point.y + size.width,
        point.z,
        point.z + size.height,
    )


def _supported_area(placement: Placement, previous: tuple[Placement, ...]) -> int:
    """Exact union of clipped coplanar support rectangles via an x sweep."""
    x1, x2, y1, y2, z1, _ = _bounds(placement)
    rectangles = []
    for supporting in previous:
        sx1, sx2, sy1, sy2, _, sz2 = _bounds(supporting)
        if sz2 != z1:
            continue
        left, right, front, back = max(x1, sx1), min(x2, sx2), max(y1, sy1), min(y2, sy2)
        if left < right and front < back:
            rectangles.append((left, right, front, back))
    edges = sorted({x for left, right, _, _ in rectangles for x in (left, right)})
    area = 0
    for left, right in zip(edges, edges[1:]):
        intervals = sorted(
            (front, back)
            for x_start, x_end, front, back in rectangles
            if x_start <= left and right <= x_end
        )
        covered, end = 0, -1
        for front, back in intervals:
            covered += max(0, back - max(front, end))
            end = max(end, back)
        area += (right - left) * covered
    return area


def _validate_instructions(box: PackedBox) -> None:
    if not box.instructions:
        return
    _require(len(box.instructions) == len(box.placements) + 2, "Instruction count is incorrect")
    for step, instruction in enumerate(box.instructions):
        _require(instruction.step == step, "Instruction steps must be contiguous")
        _require(instruction.box_id == box.id, "Instruction references another box")
        _require(bool(instruction.message.strip()), "Instruction message must be present")
        if step in (0, len(box.instructions) - 1):
            action = "prepare_box" if step == 0 else "close_box"
            _require(instruction.action == action, "Invalid prepare/close instruction")
            _require(
                all(
                    getattr(instruction, field) is None
                    for field in (
                        "item_instance_id",
                        "product_id",
                        "position",
                        "dimensions",
                        "orientation",
                    )
                ),
                "Prepare/close instruction must not reference an item",
            )
        else:
            _require(instruction.action == "place_item", "Invalid placement instruction")
            placement = box.placements[step - 1]
            _require(
                all(
                    getattr(instruction, field) == getattr(placement, field)
                    for field in (
                        "item_instance_id",
                        "product_id",
                        "position",
                        "dimensions",
                        "orientation",
                    )
                ),
                "Instruction differs from placement",
            )


def _fingerprint(solution: PackingResult | PackingAlternative) -> tuple:
    # Swapping identical units or identical physical boxes is the same plan.
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
            for box in solution.packed_boxes
        )
    )


def validate_solution(
    request: PackingRequest,
    solution: PackingResult | PackingAlternative,
    min_support_ratio: Fraction = Fraction(4, 5),
) -> None:
    """Raise PackingValidationError on geometry, accounting or contract violations.

    Checks support against earlier steps, thereby validating the reproducibility
    of stacking instructions as well as the final static arrangement. Empty
    instruction tuples are legal because the application service generates them.
    """
    threshold = Fraction(str(min_support_ratio))
    _require(0 < threshold <= 1, "Support threshold must be in (0, 1]")
    expected = {}
    for product in sorted(request.products, key=lambda item: item.id):
        for index in range(1, product.quantity + 1):
            item = ItemInstance(
                f"{product.id}:{index}",
                product.id,
                product.name,
                index,
                product.length,
                product.width,
                product.height,
                product.weight,
                product.allow_rotation,
            )
            _require(item.id not in expected, "Request contains duplicate product ids")
            expected[item.id] = item
    box_types = {box.id: box for box in request.boxes}
    _require(len(box_types) == len(request.boxes), "Request contains duplicate box type ids")
    used_types: Counter[str] = Counter()
    packed_ids = set()
    total_weight = used_volume = box_volume = 0
    for box in solution.packed_boxes:
        _require(box.box_type_id in box_types, "Unknown box type")
        source = box_types[box.box_type_id]
        used_types[source.id] += 1
        _require(box.id == f"{source.id}:{used_types[source.id]}", "Invalid box instance id")
        _require(used_types[source.id] <= source.available_count, "Box stock exceeded")
        _require(bool(box.placements), "Empty boxes must not be returned")
        _require(
            all(
                getattr(box, field) == getattr(source, field)
                for field in (
                    "name",
                    "length",
                    "width",
                    "height",
                    "max_weight",
                )
            ),
            "Box metadata differs from the request",
        )
        actual_weight = actual_volume = 0
        for index, placement in enumerate(box.placements):
            _require(placement.step == index + 1, "Placement steps must be contiguous")
            _require(placement.item_instance_id in expected, "Unknown item instance")
            _require(placement.item_instance_id not in packed_ids, "Item instance used twice")
            item = expected[placement.item_instance_id]
            _require(placement.product_id == item.product_id, "Incorrect placement product id")
            point, size = placement.position, placement.dimensions
            coordinates = (point.x, point.y, point.z)
            dimensions = (size.length, size.width, size.height)
            _require(
                all(type(value) is int and value >= 0 for value in coordinates),
                "Coordinates must be nonnegative integer millimetres",
            )
            _require(
                all(type(value) is int and value > 0 for value in dimensions),
                "Dimensions must be positive integer millimetres",
            )
            axis = {"L": item.length, "W": item.width, "H": item.height}
            orientations = _ORIENTATIONS if item.allow_rotation else ("LWH",)
            canonical = {}
            for orientation in orientations:
                canonical.setdefault(tuple(axis[letter] for letter in orientation), orientation)
            _require(
                dimensions in canonical and canonical[dimensions] == placement.orientation,
                "Dimensions or orientation are not allowed for this item",
            )
            x1, x2, y1, y2, z1, z2 = _bounds(placement)
            _require(
                x2 <= box.length and y2 <= box.width and z2 <= box.height,
                "Placement is outside box bounds",
            )
            for previous in box.placements[:index]:
                px1, px2, py1, py2, pz1, pz2 = _bounds(previous)
                intersects = (
                    x1 < px2 and px1 < x2 and y1 < py2 and py1 < y2 and z1 < pz2 and pz1 < z2
                )
                _require(not intersects, "Placements overlap")
            if point.z > 0:
                area = _supported_area(placement, box.placements[:index])
                _require(
                    area * threshold.denominator >= size.length * size.width * threshold.numerator,
                    "Placement lacks support from earlier steps",
                )
            packed_ids.add(item.id)
            actual_weight += item.weight
            actual_volume += item.length * item.width * item.height
        _require(actual_weight <= source.max_weight, "Box maximum weight exceeded")
        _require(box.total_weight == actual_weight, "Box total weight is incorrect")
        _require(box.used_volume == actual_volume, "Box used volume is incorrect")
        volume = box.length * box.width * box.height
        _require(box.fill_ratio == round(actual_volume / volume, 6), "Box fill ratio is incorrect")
        _validate_instructions(box)
        total_weight += actual_weight
        used_volume += actual_volume
        box_volume += volume
    unpacked_ids = set()
    _require(
        solution.unpacked_items
        == tuple(
            sorted(
                solution.unpacked_items,
                key=lambda item: (item.product_id, item.unit_index),
            )
        ),
        "Unpacked items are not canonically ordered",
    )
    for item in solution.unpacked_items:
        _require(item.id in expected and item == expected[item.id], "Invalid unpacked item")
        _require(item.id not in unpacked_ids | packed_ids, "Item instance accounted for twice")
        unpacked_ids.add(item.id)
    _require(packed_ids | unpacked_ids == set(expected), "Requested quantities are not conserved")
    metrics = PackingMetrics(
        len(expected),
        len(packed_ids),
        len(unpacked_ids),
        len(solution.packed_boxes),
        dict(sorted(used_types.items())),
        box_volume,
        used_volume,
        box_volume - used_volume,
        round(used_volume / box_volume, 6) if box_volume else 0.0,
        total_weight,
    )
    _require(solution.metrics == metrics, "Solution metrics are incorrect")
    status = "success" if not unpacked_ids else "partial" if packed_ids else "impossible"
    _require(solution.status == status, "Solution status is incorrect")
    _require(
        solution.issues
        == tuple(
            sorted(
                solution.issues,
                key=lambda issue: (issue.code, issue.item_instance_ids),
            )
        ),
        "Issues are not canonically ordered",
    )
    explained = set()
    for issue in solution.issues:
        _require(bool(issue.message.strip()), "Issue must contain an explanation")
        _require(set(issue.item_instance_ids) <= set(expected), "Issue references unknown item")
        _require(set(issue.box_type_ids) <= set(box_types), "Issue references unknown box type")
        if issue.code in _CAUSES:
            explained.update(issue.item_instance_ids)
    _require(unpacked_ids <= explained, "Unpacked item has no explanatory issue")
    if isinstance(solution, PackingResult):
        limit = request.options.max_alternatives if request.options.include_alternatives else 0
        _require(len(solution.alternatives) <= limit, "Too many alternatives")
        _require(
            solution.alternatives
            == tuple(
                sorted(
                    solution.alternatives,
                    key=lambda alternative: (
                        alternative.metrics.unpacked_items,
                        -alternative.metrics.used_volume,
                        alternative.metrics.empty_volume,
                        alternative.metrics.boxes_used,
                        alternative.id,
                    ),
                )
            ),
            "Alternatives are not canonically ordered",
        )
        fingerprints, alternative_ids = {_fingerprint(solution)}, set()
        for alternative in solution.alternatives:
            _require(alternative.id not in alternative_ids, "Duplicate alternative id")
            alternative_ids.add(alternative.id)
            validate_solution(request, alternative, threshold)
            fingerprint = _fingerprint(alternative)
            _require(fingerprint not in fingerprints, "Alternative repeats a packing plan")
            fingerprints.add(fingerprint)
