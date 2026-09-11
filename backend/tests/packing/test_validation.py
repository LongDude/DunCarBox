"""Adversarial postcondition tests, with plans constructed independently of the engine."""

from dataclasses import replace
from fractions import Fraction

import pytest

from app.domain.models import (
    BoxType,
    Dimensions,
    ItemInstance,
    PackedBox,
    PackingAlternative,
    PackingInstructionStep,
    PackingMetrics,
    PackingRequest,
    PackingResult,
    Placement,
    Position,
    Product,
)
from app.packing.diagnostics import build_issues
from app.packing.validation import PackingValidationError, validate_solution


def _items(request):
    return tuple(
        ItemInstance(
            f"{p.id}:{i}", p.id, p.name, i, p.length, p.width, p.height, p.weight, p.allow_rotation
        )
        for p in sorted(request.products, key=lambda product: product.id)
        for i in range(1, p.quantity + 1)
    )


def _placement(identifier, x=0, y=0, z=0, size=(10, 10, 10), step=1):
    return Placement(
        identifier, identifier.split(":")[0], Position(x, y, z), Dimensions(*size), "LWH", step
    )


def _result(request, placements=()):
    items = {item.id: item for item in _items(request)}
    packed_ids = {placement.item_instance_id for placement in placements}
    weight = sum(items[p.item_instance_id].weight for p in placements)
    volume = sum(p.dimensions.length * p.dimensions.width * p.dimensions.height for p in placements)
    boxes = ()
    box_volume = 0
    counts = {}
    if placements:
        box = request.boxes[0]
        box_volume = box.length * box.width * box.height
        boxes = (
            PackedBox(
                f"{box.id}:1",
                box.id,
                box.name,
                box.length,
                box.width,
                box.height,
                box.max_weight,
                weight,
                volume,
                round(volume / box_volume, 6),
                tuple(placements),
            ),
        )
        counts = {box.id: 1}
    unpacked = tuple(item for item in items.values() if item.id not in packed_ids)
    metrics = PackingMetrics(
        len(items),
        len(placements),
        len(unpacked),
        len(boxes),
        counts,
        box_volume,
        volume,
        box_volume - volume,
        round(volume / box_volume, 6) if boxes else 0.0,
        weight,
    )
    return PackingResult(
        "success" if not unpacked else "partial" if boxes else "impossible",
        metrics,
        boxes,
        unpacked,
        build_issues(request, boxes, unpacked),
    )


@pytest.fixture
def valid_plan():
    request = PackingRequest(
        (BoxType("box", "Коробка", 20, 10, 20, 20, 1),), (Product("a", "Товар", 10, 10, 10, 10, 2),)
    )
    result = _result(request, (_placement("a:1"), _placement("a:2", x=10, step=2)))
    return request, result


def test_validator_accepts_touching_faces_exact_weight_and_metrics(valid_plan):
    validate_solution(*valid_plan)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"position": Position(11, 0, 0)}, "bounds"),
        ({"position": Position(-1, 0, 0)}, "integer"),
        ({"position": Position(10.0, 0, 0)}, "integer"),
        ({"position": Position(True, 0, 0)}, "integer"),
        ({"position": Position(9, 0, 0)}, "overlap"),
        ({"position": Position(10, 0, 1)}, "support"),
        ({"dimensions": Dimensions(9, 10, 10)}, "orientation"),
        ({"orientation": "WLH"}, "orientation"),
        ({"step": 3}, "contiguous"),
        ({"product_id": "unknown"}, "product"),
        ({"item_instance_id": "unknown:1"}, "Unknown item"),
        ({"item_instance_id": "a:1"}, "twice"),
    ],
)
def test_validator_rejects_corrupt_placement(valid_plan, changes, message):
    request, result = valid_plan
    box = result.packed_boxes[0]
    placements = box.placements[:1] + (replace(box.placements[1], **changes),)
    result = replace(result, packed_boxes=(replace(box, placements=placements),))
    with pytest.raises(PackingValidationError, match=message):
        validate_solution(request, result)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"total_weight": 19}, "total weight"),
        ({"used_volume": 1999}, "used volume"),
        ({"fill_ratio": 0.500001}, "fill ratio"),
        ({"max_weight": 21}, "metadata"),
        ({"name": "Wrong"}, "metadata"),
        ({"id": "box:2"}, "instance id"),
        ({"box_type_id": "unknown"}, "Unknown box type"),
        ({"placements": ()}, "Empty boxes"),
    ],
)
def test_validator_rejects_corrupt_box(valid_plan, changes, message):
    request, result = valid_plan
    result = replace(result, packed_boxes=(replace(result.packed_boxes[0], **changes),))
    with pytest.raises(PackingValidationError, match=message):
        validate_solution(request, result)


def test_validator_checks_actual_weight_instead_of_reported_weight(valid_plan):
    request, result = valid_plan
    request = replace(request, boxes=(replace(request.boxes[0], max_weight=19),))
    result = replace(result, packed_boxes=(replace(result.packed_boxes[0], max_weight=19),))
    with pytest.raises(PackingValidationError, match="maximum weight"):
        validate_solution(request, result)


def test_validator_checks_stock_independently(valid_plan):
    request, result = valid_plan
    request = replace(request, boxes=(replace(request.boxes[0], available_count=0),))
    with pytest.raises(PackingValidationError, match="stock"):
        validate_solution(request, result)


def test_validator_catches_missing_and_double_accounted_items(valid_plan):
    request, result = valid_plan
    with pytest.raises(PackingValidationError, match="conserved"):
        validate_solution(request, replace(result, packed_boxes=()))
    with pytest.raises(PackingValidationError, match="twice"):
        validate_solution(request, replace(result, unpacked_items=_items(request)[:1]))


@pytest.mark.parametrize(
    "field",
    [
        "total_items",
        "packed_items",
        "unpacked_items",
        "boxes_used",
        "total_box_volume",
        "used_volume",
        "empty_volume",
        "fill_ratio",
        "total_weight",
    ],
)
def test_validator_catches_corrupt_metrics(valid_plan, field):
    request, result = valid_plan
    metrics = replace(result.metrics, **{field: getattr(result.metrics, field) + 1})
    with pytest.raises(PackingValidationError, match="metrics"):
        validate_solution(request, replace(result, metrics=metrics))


def test_validator_catches_wrong_status_and_missing_explanations(valid_plan):
    request, result = valid_plan
    with pytest.raises(PackingValidationError, match="status"):
        validate_solution(request, replace(result, status="impossible"))
    partial = _result(request, result.packed_boxes[0].placements[:1])
    validate_solution(request, partial)
    with pytest.raises(PackingValidationError, match="explanatory"):
        validate_solution(request, replace(partial, issues=()))


def test_support_uses_multiple_surfaces_and_exact_configurable_threshold():
    request = PackingRequest(
        (BoxType("box", "Коробка", 20, 10, 20, 100, 1),),
        (
            Product("base", "Опоры", 8, 10, 10, 1, 2, False),
            Product("top", "Верхний товар", 20, 10, 10, 1, 1, False),
        ),
    )
    placements = (
        _placement("base:1", size=(8, 10, 10)),
        _placement("base:2", x=12, size=(8, 10, 10), step=2),
        _placement("top:1", z=10, size=(20, 10, 10), step=3),
    )
    result = _result(request, placements)
    validate_solution(request, result, Fraction(4, 5))
    with pytest.raises(PackingValidationError, match="support"):
        validate_solution(request, result, Fraction(81, 100))


def test_validator_rejects_top_before_support(valid_plan):
    request, _ = valid_plan
    placements = (_placement("a:1", z=10), _placement("a:2", step=2))
    with pytest.raises(PackingValidationError, match="earlier steps"):
        validate_solution(request, _result(request, placements))
    ordered = (replace(placements[1], step=1), replace(placements[0], step=2))
    validate_solution(request, _result(request, ordered))


def test_validator_checks_optional_instructions(valid_plan):
    request, result = valid_plan
    box = result.packed_boxes[0]
    instructions = (PackingInstructionStep(0, "prepare_box", box.id, "Откройте коробку."),)
    instructions += tuple(
        PackingInstructionStep(
            p.step,
            "place_item",
            box.id,
            "Положите товар.",
            p.item_instance_id,
            p.product_id,
            p.position,
            p.dimensions,
            p.orientation,
        )
        for p in box.placements
    )
    instructions += (PackingInstructionStep(3, "close_box", box.id, "Закройте коробку."),)
    result = replace(result, packed_boxes=(replace(box, instructions=instructions),))
    validate_solution(request, result)
    changed = instructions[:1] + (replace(instructions[1], position=Position(1, 0, 0)),)
    changed += instructions[2:]
    result = replace(result, packed_boxes=(replace(box, instructions=changed),))
    with pytest.raises(PackingValidationError, match="differs"):
        validate_solution(request, result)


def test_validator_rejects_duplicate_alternative_even_after_instance_swap(valid_plan):
    request, result = valid_plan
    box = result.packed_boxes[0]
    placements = (
        replace(box.placements[0], item_instance_id="a:2"),
        replace(box.placements[1], item_instance_id="a:1"),
    )
    alternative = PackingAlternative(
        "compact",
        "Другой план",
        result.status,
        result.metrics,
        (replace(box, placements=placements),),
        (),
    )
    with pytest.raises(PackingValidationError, match="repeats"):
        validate_solution(request, replace(result, alternatives=(alternative,)))


def test_validator_checks_alternative_postconditions(valid_plan):
    request, result = valid_plan
    box = result.packed_boxes[0]
    placements = (box.placements[0], replace(box.placements[1], position=Position(0, 0, 10)))
    alternative = PackingAlternative(
        "easy",
        "Другой план",
        result.status,
        result.metrics,
        (replace(box, placements=placements),),
        (),
    )
    validate_solution(request, replace(result, alternatives=(alternative,)))
    broken = replace(alternative, metrics=replace(alternative.metrics, used_volume=1))
    with pytest.raises(PackingValidationError, match="metrics"):
        validate_solution(request, replace(result, alternatives=(broken,)))


@pytest.mark.parametrize(
    ("boxes", "product", "expected_codes"),
    [
        ((), Product("p", "Товар", 1, 1, 1, 1, 1), {"NO_BOX_TYPES"}),
        (
            (BoxType("box", "Коробка", 10, 10, 10, 100, 1),),
            Product("p", "Товар", 11, 10, 10, 1, 1),
            {"ITEM_TOO_LARGE"},
        ),
        (
            (BoxType("box", "Коробка", 10, 10, 10, 100, 1),),
            Product("p", "Товар", 10, 10, 10, 101, 1),
            {"ITEM_TOO_HEAVY"},
        ),
        (
            (BoxType("box", "Коробка", 10, 10, 10, 100, 0),),
            Product("p", "Товар", 10, 10, 10, 1, 1),
            {"BOX_STOCK_EXHAUSTED"},
        ),
        (
            (BoxType("box", "Коробка", 10, 10, 10, 100, 1),),
            Product("p", "Товар", 10, 10, 10, 1, 1),
            {"NO_FEASIBLE_PLACEMENT"},
        ),
    ],
)
def test_diagnostics_distinguish_proofs_from_heuristic_failure(boxes, product, expected_codes):
    request = PackingRequest(boxes, (product,))
    result = _result(request)
    assert {issue.code for issue in result.issues} == expected_codes
    assert all(issue.item_instance_ids == ("p:1",) for issue in result.issues)
    validate_solution(request, result)


def test_diagnostics_uses_weight_of_geometrically_fitting_boxes_only():
    request = PackingRequest(
        (
            BoxType("small", "Малая", 1, 1, 1, 10000, 1),
            BoxType("large", "Большая", 10, 10, 10, 10, 0),
        ),
        (Product("p", "Товар", 10, 10, 10, 11, 1),),
    )
    issues = build_issues(request, (), _items(request))
    assert issues[0].code == "ITEM_TOO_HEAVY"
    assert issues[0].box_type_ids == ("large",)


def test_current_plan_stock_exhaustion_does_not_claim_global_impossibility(valid_plan):
    request, result = valid_plan
    result = _result(request, result.packed_boxes[0].placements[:1])
    assert {issue.code for issue in result.issues} == {
        "BOX_STOCK_EXHAUSTED",
        "NO_FEASIBLE_PLACEMENT",
        "PARTIAL_PACKING",
    }
    assert "текущем плане" in result.issues[0].message
    heuristic = next(issue for issue in result.issues if issue.code == "NO_FEASIBLE_PLACEMENT")
    assert "не доказывает" in heuristic.message


def test_diagnostics_is_deterministic_for_reordered_inputs():
    request = PackingRequest(
        (BoxType("b", "B", 1, 1, 1, 1, 0), BoxType("a", "A", 2, 2, 2, 1, 0)),
        (Product("b", "B", 3, 3, 3, 1, 2), Product("a", "A", 3, 3, 3, 1, 2)),
    )
    reverse = replace(request, boxes=request.boxes[::-1], products=request.products[::-1])
    assert build_issues(request, (), _items(request)) == build_issues(reverse, (), _items(reverse))


def test_diagnostics_success_has_no_issues(valid_plan):
    request, result = valid_plan
    assert build_issues(request, result.packed_boxes, ()) == ()
