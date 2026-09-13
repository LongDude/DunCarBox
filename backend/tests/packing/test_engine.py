"""Behavioral regressions for the real engine, without HTTP or database fixtures."""

import json
from collections import Counter
from dataclasses import asdict, replace
from fractions import Fraction
from pathlib import Path

import pytest

from app.domain.models import (
    BoxType,
    PackingAlternative,
    PackingOptions,
    PackingRequest,
    PackingResult,
    Product,
)
from app.packing.engine import DeterministicPackingEngine
from app.packing.options import EngineOptions
from app.packing.validation import validate_solution
from app.schemas.packing import PackingRequestSchema, PackingResultSchema
from app.services.packing import PackingService

DEMO = Path(__file__).resolve().parents[3] / "demo"


def box(
    identifier: str = "box",
    dimensions: tuple[int, int, int] = (10, 10, 10),
    weight: int = 100,
    stock: int = 1,
) -> BoxType:
    return BoxType(identifier, identifier, *dimensions, weight, stock)


def product(
    identifier: str = "item",
    dimensions: tuple[int, int, int] = (10, 10, 10),
    weight: int = 1,
    quantity: int = 1,
    rotation: bool = False,
) -> Product:
    return Product(identifier, identifier, *dimensions, weight, quantity, rotation)


def pack(request: PackingRequest, options: EngineOptions | None = None) -> PackingResult:
    result = DeterministicPackingEngine(options).pack(request)
    validate_solution(
        request,
        result,
        min_support_ratio=options.min_support_ratio if options else Fraction(4, 5),
    )
    PackingResultSchema.model_validate(result)
    assert result.algorithm_version != "demo-stub-v1"
    assert all(issue.code != "DEMO_STUB" for issue in result.issues)
    return result


def issue_ids(result: PackingResult, code: str) -> set[str]:
    return {
        identifier
        for issue in result.issues
        if issue.code == code
        for identifier in issue.item_instance_ids
    }


def physical_signature(plan: PackingResult | PackingAlternative) -> tuple:
    """Interchanging identical units or box opening order is not an alternative."""
    return (
        tuple(
            sorted(
                (
                    packed_box.box_type_id,
                    tuple(
                        sorted(
                            (
                                placement.product_id,
                                placement.position.x,
                                placement.position.y,
                                placement.position.z,
                                placement.dimensions.length,
                                placement.dimensions.width,
                                placement.dimensions.height,
                            )
                            for placement in packed_box.placements
                        )
                    ),
                )
                for packed_box in plan.packed_boxes
            )
        ),
        tuple(sorted(Counter(item.product_id for item in plan.unpacked_items).items())),
    )


def test_single_item_exact_fit() -> None:
    result = pack(PackingRequest((box(),), (product(weight=100),)))
    assert result.status == "success"
    assert result.metrics.packed_items == result.metrics.boxes_used == 1
    assert result.metrics.total_weight == 100
    assert result.metrics.fill_ratio == 1
    assert result.metrics.empty_volume == 0
    placement = result.packed_boxes[0].placements[0]
    assert asdict(placement.position) == {"x": 0, "y": 0, "z": 0}
    assert placement.item_instance_id == "item:1"
    assert placement.orientation == "LWH"
    assert placement.step == 1


def test_identical_items_fill_multiple_layers() -> None:
    request = PackingRequest((box(dimensions=(20, 20, 20)),), (product(quantity=8),))
    result = pack(request)
    assert result.status == "success"
    assert result.metrics.fill_ratio == 1
    placements = result.packed_boxes[0].placements
    assert Counter(placement.position.z for placement in placements) == {0: 4, 10: 4}
    assert [placement.step for placement in placements] == list(range(1, 9))
    assert [placement.position.z for placement in placements] == sorted(
        placement.position.z for placement in placements
    )


def test_quantity_expansion_uses_colon_ids_and_numeric_unit_order() -> None:
    request = PackingRequest((), (product("z", quantity=2), product("a", quantity=12)))
    result = pack(request)
    assert [item.id for item in result.unpacked_items] == [
        *(f"a:{index}" for index in range(1, 13)),
        "z:1",
        "z:2",
    ]
    assert [item.unit_index for item in result.unpacked_items[:12]] == list(range(1, 13))


@pytest.mark.parametrize("rotation", [True, False])
def test_rotation_required_and_rotation_disabled(rotation: bool) -> None:
    request = PackingRequest(
        (box(dimensions=(30, 20, 10)),),
        (product(dimensions=(10, 20, 30), rotation=rotation),),
    )
    result = pack(request)
    if rotation:
        assert result.status == "success"
        placement = result.packed_boxes[0].placements[0]
        assert placement.orientation == "HWL"
        assert asdict(placement.dimensions) == {"length": 30, "width": 20, "height": 10}
    else:
        assert result.status == "impossible"
        assert issue_ids(result, "ITEM_TOO_LARGE") == {"item:1"}


@pytest.mark.parametrize("weight,expected", [(100, "success"), (101, "impossible")])
def test_single_item_weight_exact_limit_and_one_gram_over(weight: int, expected: str) -> None:
    result = pack(PackingRequest((box(weight=100),), (product(weight=weight),)))
    assert result.status == expected
    if expected == "impossible":
        assert issue_ids(result, "ITEM_TOO_HEAVY") == {"item:1"}


@pytest.mark.parametrize("limit,packed", [(100, 2), (99, 1)])
def test_combined_weight_exact_limit_and_one_gram_over(limit: int, packed: int) -> None:
    request = PackingRequest(
        (box(dimensions=(20, 10, 10), weight=limit),),
        (product(weight=50, quantity=2),),
    )
    result = pack(request)
    assert result.metrics.packed_items == packed
    assert result.metrics.total_weight == packed * 50
    assert not issue_ids(result, "ITEM_TOO_HEAVY")


@pytest.mark.parametrize("stock,packed", [(0, 0), (1, 1), (2, 2), (3, 3)])
def test_multiple_boxes_and_stock_limit(stock: int, packed: int) -> None:
    request = PackingRequest((box(stock=stock),), (product(quantity=3),))
    result = pack(request)
    assert result.metrics.packed_items == result.metrics.boxes_used == packed
    assert [entry.id for entry in result.packed_boxes] == [
        f"box:{index}" for index in range(1, packed + 1)
    ]
    assert result.metrics.boxes_by_type == ({"box": packed} if packed else {})
    if stock < 3:
        assert len(issue_ids(result, "BOX_STOCK_EXHAUSTED")) == 3 - packed
    if 0 < stock < 3:
        assert result.status == "partial"
        assert any(issue.code == "PARTIAL_PACKING" for issue in result.issues)


def test_zero_stock_box_is_retained_for_diagnostics_but_never_opened() -> None:
    request = PackingRequest(
        (box("large", (20, 20, 20), stock=0), box("small")),
        (product("large-item", (15, 15, 15)), product("small-item")),
    )
    result = pack(request)
    assert result.status == "partial"
    assert result.metrics.boxes_by_type == {"small": 1}
    assert issue_ids(result, "BOX_STOCK_EXHAUSTED") == {"large-item:1"}
    assert not issue_ids(result, "ITEM_TOO_LARGE")


def test_oversized_and_overweight_have_independent_proven_reasons() -> None:
    request = PackingRequest(
        (box(),),
        (product("large", (11, 11, 11)), product("heavy", weight=101), product("fits")),
    )
    result = pack(request)
    assert result.status == "partial"
    assert issue_ids(result, "ITEM_TOO_LARGE") == {"large:1"}
    assert issue_ids(result, "ITEM_TOO_HEAVY") == {"heavy:1"}
    assert result.metrics.packed_items == 1


def test_overweight_checks_only_geometrically_fitting_types() -> None:
    request = PackingRequest(
        (box("fits-shape", weight=10), box("strong-but-small", (5, 5, 5), weight=1000)),
        (product(weight=11),),
    )
    result = pack(request)
    assert issue_ids(result, "ITEM_TOO_HEAVY") == {"item:1"}


def test_no_box_types_explains_every_unit() -> None:
    result = pack(PackingRequest((), (product(quantity=2),)))
    assert result.status == "impossible"
    assert result.metrics.boxes_used == result.metrics.fill_ratio == 0
    assert result.packed_boxes == ()
    assert issue_ids(result, "NO_BOX_TYPES") == {"item:1", "item:2"}


def test_fill_ratio_precedes_packed_count() -> None:
    request = PackingRequest(
        (box(dimensions=(100, 100, 100), weight=2),),
        (
            product("large", (100, 100, 100), weight=2),
            product("small", (50, 50, 50), weight=1, quantity=2),
        ),
    )
    result = pack(request)
    assert result.metrics.packed_items == 1
    assert [item.id for item in result.unpacked_items] == ["small:1", "small:2"]
    assert result.metrics.fill_ratio == 1


def test_improved_fill_ratio_precedes_fewer_boxes() -> None:
    request = PackingRequest(
        (box("small", stock=2), box("large", (30, 10, 10))),
        (product(quantity=2),),
    )
    result = pack(request)
    assert result.status == "success"
    assert result.metrics.boxes_by_type == {"small": 2}
    assert result.metrics.fill_ratio == 1


def test_lower_fill_carton_is_left_out_even_when_all_items_could_be_packed() -> None:
    request = PackingRequest(
        (box("versatile"), box("narrow", (8, 10, 10))),
        (product("needs-large", (9, 10, 10)), product("fits-both", (8, 10, 10))),
    )
    result = pack(request)
    assert result.status == "partial"
    assert result.metrics.boxes_by_type == {"narrow": 1}
    assert result.metrics.fill_ratio == 1
    assert [item.id for item in result.unpacked_items] == ["needs-large:1"]
    locations = {
        placement.product_id: packed_box.box_type_id
        for packed_box in result.packed_boxes
        for placement in packed_box.placements
    }
    assert locations == {"fits-both": "narrow"}


def test_stacked_placements_have_supporters_at_earlier_steps() -> None:
    request = PackingRequest((box(dimensions=(10, 10, 30)),), (product(quantity=3),))
    result = pack(request, EngineOptions(min_support_ratio=Fraction(1)))
    assert result.status == "success"
    placements = result.packed_boxes[0].placements
    assert [placement.position.z for placement in placements] == [0, 10, 20]
    for upper in placements[1:]:
        assert any(
            lower.position.z + lower.dimensions.height == upper.position.z
            and lower.step < upper.step
            for lower in placements
        )


def test_repeated_calls_and_reordered_input_produce_identical_full_results() -> None:
    request = PackingRequest(
        (box("large", (30, 20, 20), stock=2), box("small", (20, 10, 10), stock=2)),
        (product("b", (10, 5, 5), quantity=3, rotation=True), product("a", quantity=3)),
    )
    engine = DeterministicPackingEngine()
    expected = asdict(engine.pack(request))
    for _ in range(3):
        assert asdict(engine.pack(request)) == expected
    reordered = replace(request, boxes=request.boxes[::-1], products=request.products[::-1])
    assert asdict(engine.pack(reordered)) == expected
    assert asdict(DeterministicPackingEngine().pack(reordered)) == expected


@pytest.mark.parametrize("request_limit,engine_limit", [(1, 3), (5, 2), (3, 0)])
def test_alternative_limits_and_physical_distinctness(
    request_limit: int, engine_limit: int
) -> None:
    request = PackingRequest(
        (
            box("a", (20, 10, 10), stock=2),
            box("b", (30, 10, 10), stock=2),
            box("c", (20, 20, 10), stock=2),
        ),
        (product(quantity=3),),
        PackingOptions(max_alternatives=request_limit),
    )
    result = pack(request, EngineOptions(max_alternatives=engine_limit))
    assert len(result.alternatives) <= min(request_limit, engine_limit)
    if min(request_limit, engine_limit) > 0:
        assert result.alternatives, "This order has genuinely distinct discovered plans"
    signatures = [physical_signature(plan) for plan in (result, *result.alternatives)]
    assert len(signatures) == len(set(signatures))
    assert list(result.alternatives) == sorted(
        result.alternatives,
        key=lambda plan: (
            plan.metrics.unpacked_items,
            -plan.metrics.used_volume,
            plan.metrics.empty_volume,
            plan.metrics.boxes_used,
            plan.id,
        ),
    )


@pytest.mark.parametrize("options", [PackingOptions(False, 3), PackingOptions(True, 0)])
def test_alternatives_can_be_disabled(options: PackingOptions) -> None:
    request = PackingRequest(
        (box("a", stock=2), box("b", (30, 10, 10))), (product(quantity=2),), options
    )
    assert pack(request).alternatives == ()


def test_bounded_search_options_keep_simple_placements_valid() -> None:
    request = PackingRequest((box(dimensions=(20, 10, 10)),), (product(quantity=2),))
    result = pack(request, EngineOptions(max_candidate_points=1, max_strategies=1))
    assert result.status == "success"


def test_support_option_changes_acceptance_of_eighty_percent_overhang() -> None:
    request = PackingRequest(
        (box(dimensions=(10, 10, 3)),),
        (product("base", (8, 10, 2)), product("upper", (10, 10, 1))),
    )
    # One start fixes the larger base first, isolating the support constraint.
    relaxed = pack(request, EngineOptions(max_strategies=1))
    strict = pack(request, EngineOptions(max_strategies=1, min_support_ratio=Fraction(1)))
    assert relaxed.status == "success"
    assert strict.status == "partial"
    assert relaxed.packed_boxes[0].placements[1].position.z == 2
    assert relaxed.algorithm_version != strict.algorithm_version


def test_equivalent_configuration_has_identical_algorithm_version() -> None:
    default = DeterministicPackingEngine()
    decimal = DeterministicPackingEngine(EngineOptions(min_support_ratio=0.8))
    exact = DeterministicPackingEngine(EngineOptions(min_support_ratio=Fraction(4, 5)))
    assert default.version == decimal.version == exact.version


def test_service_generates_contract_instructions_for_main_and_alternative_plans() -> None:
    request = PackingRequest(
        (box("tower", (10, 10, 30)), box("flat", (30, 10, 10))),
        (product(quantity=3),),
    )
    result = PackingService(DeterministicPackingEngine()).pack(request)
    validate_solution(request, result)
    PackingResultSchema.model_validate(result)
    for plan in (result, *result.alternatives):
        for packed_box in plan.packed_boxes:
            instructions = packed_box.instructions
            assert [entry.step for entry in instructions] == list(range(len(instructions)))
            assert len(instructions) == len(packed_box.placements) + 2
            assert instructions[0].action == "prepare_box"
            assert instructions[-1].action == "close_box"
            for entry in (instructions[0], instructions[-1]):
                assert entry.item_instance_id is entry.product_id is entry.position is None
                assert entry.dimensions is entry.orientation is None
            for instruction, placement in zip(instructions[1:-1], packed_box.placements):
                assert instruction.action == "place_item"
                for field in (
                    "step",
                    "item_instance_id",
                    "product_id",
                    "position",
                    "dimensions",
                    "orientation",
                ):
                    assert getattr(instruction, field) == getattr(placement, field)
            assert all(instruction.box_id == packed_box.id for instruction in instructions)
            assert all(instruction.message.strip() for instruction in instructions)


@pytest.mark.parametrize(
    "scenario,status,packed,boxes",
    [
        ("simple-order", "success", 2, 1),
        ("multiple-boxes", "success", 6, 2),
        ("oversized", "impossible", 0, 0),
        ("stock-shortage", "partial", 1, 1),
    ],
)
def test_real_engine_regression_on_existing_demo_requests(
    scenario: str, status: str, packed: int, boxes: int
) -> None:
    payload = json.loads((DEMO / f"{scenario}.request.json").read_text(encoding="utf-8"))
    request = PackingRequestSchema.model_validate(payload).to_domain()
    result = pack(request)
    assert result.status == status
    assert result.metrics.packed_items == packed
    assert result.metrics.boxes_used <= boxes


def test_every_unpacked_item_has_a_specific_diagnostic() -> None:
    request = PackingRequest(
        (box(),),
        (product("fit", quantity=3), product("heavy", weight=101), product("big", (11, 11, 11))),
    )
    result = pack(request)
    explained = {
        identifier
        for issue in result.issues
        if issue.code not in {"PARTIAL_PACKING", "SIMILAR_ALTERNATIVES"}
        for identifier in issue.item_instance_ids
    }
    assert {item.id for item in result.unpacked_items} <= explained
    assert list(result.issues) == sorted(
        result.issues, key=lambda issue: (issue.code, issue.item_instance_ids)
    )


def test_depleted_current_plan_does_not_claim_general_geometric_impossibility() -> None:
    request = PackingRequest((box(),), (product(quantity=2),))
    result = pack(request)
    leftover = {item.id for item in result.unpacked_items}
    assert leftover
    assert issue_ids(result, "BOX_STOCK_EXHAUSTED") == leftover
    assert issue_ids(result, "NO_FEASIBLE_PLACEMENT") == leftover
    assert not issue_ids(result, "ITEM_TOO_LARGE")
    assert not issue_ids(result, "ITEM_TOO_HEAVY")
