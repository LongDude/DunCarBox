"""Independent regressions for aggregate optimality certificates and real replay."""

import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from random import Random
from threading import Event, Timer

import pytest
import z3

from app.domain.models import (
    BoxType,
    Dimensions,
    PackedBox,
    PackingOptions,
    PackingRequest,
    PackingResult,
    Placement,
    Position,
    Product,
)
from app.packing.engine import DeterministicPackingEngine, _metrics
from app.packing.options import EngineOptions
from app.packing.validation import validate_solution
from app.packing.z3_certificate import _axis_scale, _capacity, certify_incumbent, pair_scale
from app.packing.z3_constraints import _build_model, compatible_box_types, objective
from app.packing.z3_engine import Z3PackingEngine, _worker
from app.packing.z3_model import _extract
from app.packing.z3_support import full_support
from app.schemas.packing import PackingRequestSchema


def screenshot_request():
    fixture = Path(__file__).resolve().parents[3] / "demo/benchmarks/z3-mixed-66.request.json"
    return PackingRequestSchema.model_validate(
        json.loads(fixture.read_text(encoding="utf-8"))
    ).to_domain()


def baseline(request):
    return DeterministicPackingEngine(EngineOptions(min_support_ratio=Fraction(1))).pack(request)


def test_axis_scales_preserve_every_small_feasible_chain():
    # Exhaust all two-type interval patterns, independently of the lifting loop.
    for capacity in range(1, 13):
        for a in range(1, capacity + 1):
            for b in range(1, capacity + 1):
                alpha, beta = _axis_scale(capacity, a, b, 4, 5)
                for p in range(5):
                    for q in range(6):
                        if p * a + q * b <= capacity:
                            assert p * alpha + q * beta <= 1


def test_axis_work_cap_weakens_instead_of_invalidating_a_scale():
    alpha, beta = _axis_scale(10000, 1, 1, 10000, 10000)
    assert alpha == Fraction(1, 10000)
    assert beta == 0


def test_screenshot_pair_bound_excludes_two_steel_boxes():
    request = screenshot_request()
    steel = request.boxes[0]
    kettle, thermos = request.products[1:]
    assert pair_scale(steel, kettle, thermos) == (28, 3, 336)
    assert 28 * 22 + 3 * 22 > 336 * 2
    with pytest.raises(ValueError, match="fixed orientations"):
        pair_scale(steel, replace(kettle, allow_rotation=True), thermos)


@pytest.mark.parametrize("quantity,volume,boxes", [(11, 155_000_000, 2), (22, 280_000_000, 3)])
def test_screenshot_order_finishes_with_a_proved_optimum(quantity, volume, boxes):
    request = screenshot_request()
    request = replace(
        request, products=tuple(replace(p, quantity=quantity) for p in request.products)
    )
    cancel = Event()
    guard = Timer(30, cancel.set)
    guard.start()
    try:
        result = Z3PackingEngine(cancel_event=cancel).pack(request)
    finally:
        guard.cancel()
    validate_solution(request, result, Fraction(1))
    assert result.metrics.packed_items == quantity * 3
    assert result.metrics.total_box_volume == volume
    assert result.metrics.boxes_used == boxes
    assert result.optimization.status == "optimal"
    assert result.optimization.reason == "completed"
    assert result.optimization.time_limit_ms is None
    assert result.metrics.boxes_by_type == {"box-1": boxes - 1, "box-m": 1}


def test_rotating_pinwheel_is_not_limited_to_a_single_orientation_grid():
    carton = BoxType("b", "b", 5, 5, 1, 100, 1)
    product = Product("p", "p", 3, 2, 1, 1, 4, True)
    request = PackingRequest((carton,), (product,), PackingOptions(algorithm="z3"))
    placements = tuple(
        Placement(f"p:{i}", "p", Position(x, y, 0), Dimensions(dx, dy, 1), orientation, i)
        for i, (x, y, dx, dy, orientation) in enumerate(
            (
                (0, 0, 3, 2, "LWH"),
                (3, 0, 2, 3, "WLH"),
                (2, 3, 3, 2, "LWH"),
                (0, 2, 2, 3, "WLH"),
            ),
            1,
        )
    )
    packed = (PackedBox("b:1", "b", "b", 5, 5, 1, 100, 4, 24, 0.96, placements),)
    incumbent = PackingResult("success", _metrics(packed, 4), packed, ())
    validate_solution(request, incumbent, Fraction(1))
    assert _capacity(carton, product) == 4
    assert certify_incumbent(request, incumbent)


def test_partial_incumbent_is_never_certified_as_a_full_order():
    request = PackingRequest(
        (BoxType("b", "b", 2, 2, 2, 100, 1),), (Product("p", "p", 2, 2, 2, 1, 2, False),)
    )
    incumbent = baseline(request)
    assert incumbent.metrics.packed_items == 1
    assert not certify_incumbent(request, incumbent)


def test_certificate_preserves_box_count_tie_breaker():
    request = PackingRequest(
        (
            BoxType("small", "small", 2, 2, 2, 100, 2),
            BoxType("large", "large", 4, 2, 2, 100, 1),
        ),
        (Product("p", "p", 2, 2, 2, 1, 2, False),),
    )
    poor = baseline(replace(request, boxes=(request.boxes[0],)))
    better = baseline(replace(request, boxes=(request.boxes[1],)))
    assert poor.metrics.total_box_volume == better.metrics.total_box_volume == 16
    assert not certify_incumbent(request, poor)
    assert certify_incumbent(request, better)


@pytest.mark.parametrize("seed", range(12))
def test_certificates_agree_with_independent_geometric_optimization(seed):
    rng = Random(seed)
    request = PackingRequest(
        (
            BoxType("a", "a", 3, 3, 3, 4, 2),
            BoxType("b", "b", 4, 3, 2, 4, 2),
        ),
        (
            Product("a", "a", *(rng.randint(1, 3) for _ in range(3)), 2, 2, bool(seed % 2)),
            Product("b", "b", *(rng.randint(1, 3) for _ in range(3)), 2, 1, False),
        ),
    )
    incumbent = baseline(request)
    certified = certify_incumbent(request, incumbent)
    model = _build_model(request, compatible_box_types(request), z3.Context(), symmetry=False)
    full_support(model)
    model.optimizer.set(timeout=10_000)
    assert model.optimizer.check() == z3.sat
    assert all(handle.lower().eq(handle.upper()) for handle in model.objectives)
    optimum = _extract(request, model, model.optimizer.model())
    if certified:
        assert objective(incumbent) == objective(optimum)
    if objective(incumbent) != objective(optimum):
        assert not certified


def test_unknown_certificate_falls_through_to_the_exact_worker(monkeypatch):
    request = screenshot_request()
    incumbent = baseline(request)

    class UnknownSolver:
        def set(self, **kwargs):
            pass

        def check(self):
            return z3.unknown

    monkeypatch.setattr(
        "app.packing.z3_certificate._better_plan_solver", lambda *args: UnknownSolver()
    )
    messages = []

    def solve(request, types, incumbent, variant, emit, receive_bound):
        messages.append("geometric search")
        emit("optimal", incumbent)

    monkeypatch.setattr("app.packing.z3_model.solve", solve)

    class Connection:
        def send(self, message):
            messages.append(message)

        def close(self):
            messages.append("closed")

    _worker(Connection(), request, compatible_box_types(request), incumbent, 0)
    assert messages == ["geometric search", ("optimal", incumbent), "closed"]


def test_invalid_geometry_cannot_become_an_optimal_certificate():
    request = screenshot_request()
    incumbent = baseline(request)
    carton = incumbent.packed_boxes[0]
    invalid = replace(
        carton, placements=tuple(replace(p, position=Position(0, 0, 0)) for p in carton.placements)
    )
    with pytest.raises(ValueError):
        certify_incumbent(
            request, replace(incumbent, packed_boxes=(invalid, *incumbent.packed_boxes[1:]))
        )
