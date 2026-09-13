"""Regressions for upright yaw, exact fill priority, and sound finite Z3 search."""

import multiprocessing
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest
import z3

from app.domain.models import BoxType, PackingOptions, PackingRequest, Product
from app.packing.engine import DeterministicPackingEngine
from app.packing.options import EngineOptions
from app.packing.scoring import packing_objective
from app.packing.validation import validate_solution
from app.packing.z3_certificate import certify_incumbent
from app.packing.z3_constraints import _build_model, compatible_box_types, objective, set_objectives
from app.packing.z3_engine import Z3PackingEngine
from app.packing.z3_model import _proved, _resource_count, solve


def baseline(request):
    return DeterministicPackingEngine(EngineOptions(min_support_ratio=Fraction(1))).pack(request)


@pytest.mark.parametrize("engine", [DeterministicPackingEngine, Z3PackingEngine])
@pytest.mark.parametrize("carton_size,packed", [((3, 2, 5), 1), ((5, 3, 2), 0)])
def test_upright_item_can_turn_on_its_base_but_cannot_tilt(engine, carton_size, packed):
    request = PackingRequest(
        (BoxType("b", "b", *carton_size, 100, 1),),
        (Product("p", "p", 2, 3, 5, 1, 1, False),),
        PackingOptions(solver_workers=1),
    )
    result = engine().pack(request)
    validate_solution(request, result, Fraction(1))
    assert result.metrics.packed_items == packed
    if packed:
        placement = result.packed_boxes[0].placements[0]
        assert placement.orientation == "WLH"
        assert placement.dimensions.height == 5


def test_full_incumbent_does_not_force_items_that_reduce_fill(exact_optimum):
    request = PackingRequest(
        (BoxType("loose", "loose", 3, 2, 1, 100, 1), BoxType("tight", "tight", 2, 2, 1, 100, 1)),
        (
            Product("big", "big", 2, 2, 1, 1, 1, False),
            Product("small", "small", 1, 1, 1, 1, 1, False),
        ),
    )
    incumbent = baseline(replace(request, boxes=(request.boxes[0],)))
    assert incumbent.metrics.packed_items == 2
    assert incumbent.metrics.fill_ratio == round(5 / 6, 6)
    assert not certify_incumbent(request, incumbent)
    messages = []
    solve(
        request,
        compatible_box_types(request),
        incumbent,
        0,
        lambda *message: messages.append(message),
    )
    status, result = messages[-1]
    assert status == "optimal"
    assert objective(result) == objective(exact_optimum(request))
    assert result.metrics.fill_ratio == result.metrics.packed_items == 1
    assert result.metrics.boxes_by_type == {"tight": 1}


def test_bound_uses_all_order_volume_for_a_partial_incumbent(exact_optimum):
    request = PackingRequest(
        (BoxType("small", "small", 2, 2, 1, 100, 1), BoxType("large", "large", 4, 2, 1, 100, 1)),
        (Product("p", "p", 2, 2, 1, 1, 2, False),),
    )
    incumbent = baseline(replace(request, boxes=(request.boxes[0],)))
    assert incumbent.metrics.packed_items == 1
    model = _build_model(request, compatible_box_types(request), z3.Context(), incumbent=incumbent)
    assert {box.id for box in model.boxes} == {"small", "large"}
    messages = []
    solve(
        request,
        compatible_box_types(request),
        incumbent,
        0,
        lambda *message: messages.append(message),
    )
    assert messages[-1][0] == "optimal"
    assert objective(messages[-1][1]) == objective(exact_optimum(request))
    assert messages[-1][1].metrics.packed_items == 2


def test_geometrically_incompatible_pair_is_separated_despite_sufficient_volume():
    request = PackingRequest(
        (BoxType("b", "b", 3, 3, 1, 100, 2),),
        (Product("p", "p", 2, 2, 1, 1, 2, False),),
    )
    model = _build_model(request, compatible_box_types(request), z3.Context())
    model.optimizer.add(model.box[0] == 0, model.box[1] == 0)
    assert model.optimizer.check() == z3.unsat


def test_matching_lower_and_upper_bounds_must_equal_actual_model_score():
    request = PackingRequest(
        (BoxType("b", "b", 2, 2, 1, 100, 1),),
        (Product("p", "p", 2, 2, 1, 1, 1, False),),
    )
    model = _build_model(request, compatible_box_types(request), z3.Context())
    assert model.optimizer.check() == z3.sat
    values = model.optimizer.model()
    assert _proved(model, values)
    model.objectives[0] = SimpleNamespace(
        lower=lambda: z3.IntVal(-999, values.ctx), upper=lambda: z3.IntVal(-999, values.ctx)
    )
    assert not _proved(model, values)


def test_fill_comparison_does_not_round_or_average_carton_percentages():
    first = SimpleNamespace(
        used_volume=5_000_001, total_box_volume=10_000_000, packed_items=1, boxes_used=1
    )
    second = SimpleNamespace(
        used_volume=5_000_000, total_box_volume=10_000_000, packed_items=2, boxes_used=1
    )
    assert round(first.used_volume / first.total_box_volume, 6) == 0.5
    assert packing_objective(first) < packing_objective(second)


def test_real_solver_exhausts_work_budget_without_claiming_a_proof(monkeypatch):
    request = PackingRequest(
        (BoxType("b", "b", 3, 3, 2, 100, 2),),
        (Product("p", "p", 2, 2, 1, 1, 3, False),),
    )
    monkeypatch.setattr("app.packing.z3_model.SOLVER_RESOURCE_LIMIT", 1)
    messages = []
    solve(
        request,
        compatible_box_types(request),
        baseline(request),
        0,
        lambda *message: messages.append(message),
    )
    assert messages[-1] == ("resource_limit", None)


def test_resource_counter_survives_replacing_fractional_objectives():
    request = PackingRequest(
        (BoxType("b", "b", 3, 3, 2, 100, 2),),
        (Product("p", "p", 2, 2, 1, 1, 3, False),),
    )
    model = _build_model(request, compatible_box_types(request), z3.Context())
    assert model.optimizer.check() == z3.sat
    consumed = _resource_count(model.optimizer)
    assert consumed > 0
    set_objectives(model, Fraction(1, 2))
    assert _resource_count(model.optimizer) >= consumed
    assert model.optimizer.check() == z3.sat
    assert _resource_count(model.optimizer) > consumed


def _resource_limited_worker(connection, request, types, incumbent, variant, updates):
    connection.send(("resource_limit", None))
    connection.close()


def test_controller_preserves_baseline_and_reaps_resource_limited_workers(monkeypatch):
    request = PackingRequest(
        (BoxType("b", "b", 3, 3, 2, 100, 2),),
        (Product("p", "p", 2, 2, 1, 1, 3, False),),
        PackingOptions(solver_workers=1),
    )
    monkeypatch.setattr("app.packing.z3_engine._worker", _resource_limited_worker)
    previous = {child.pid for child in multiprocessing.active_children()}
    result = Z3PackingEngine().pack(request)
    validate_solution(request, result, Fraction(1))
    assert result.optimization.reason == "resource_limit"
    assert result.optimization.status == "fallback"
    assert result.metrics.packed_items > 0
    assert {child.pid for child in multiprocessing.active_children()} <= previous
