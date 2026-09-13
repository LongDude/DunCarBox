"""Exactness regressions for lazy support, compact stock and safe search bounds."""

from dataclasses import replace
from fractions import Fraction
from queue import Queue
from random import Random

import pytest
import z3

from app.domain.models import BoxType, PackingOptions, PackingRequest, PackingResult, Product
from app.packing.diagnostics import build_issues
from app.packing.engine import DeterministicPackingEngine, _metrics
from app.packing.options import EngineOptions
from app.packing.strategies import expand_items
from app.packing.validation import validate_solution
from app.packing.z3_constraints import _build_model, add_bound, compatible_box_types, objective
from app.packing.z3_engine import MAX_SOLVER_WORKERS, Z3PackingEngine, _publish_bound
from app.packing.z3_model import _extract, solve
from app.packing.z3_support import add_support_cuts, full_support, support_violations


def carton(identifier="box", size=(4, 4, 4), stock=1, weight=100):
    return BoxType(identifier, identifier, *size, weight, stock)


def item(identifier="item", size=(2, 2, 2), quantity=1, rotation=False, weight=1):
    return Product(identifier, identifier, *size, weight, quantity, rotation)


def order(boxes, products):
    return PackingRequest(tuple(boxes), tuple(products), PackingOptions(algorithm="z3"))


def empty_plan(request):
    items = expand_items(request)
    return PackingResult(
        "impossible", _metrics((), len(items)), (), items, build_issues(request, (), items)
    )


def baseline(request):
    return DeterministicPackingEngine(EngineOptions(min_support_ratio=Fraction(1))).pack(request)


@pytest.mark.parametrize("gap", [False, True])
def test_lazy_cut_preserves_joint_support_and_rejects_a_gap(gap):
    width = 1 if gap else 2
    request = order(
        [carton(size=(4, 2, 2))],
        [
            item("a", (width, 2, 1)),
            item("b", (width, 2, 1)),
            item("top", (4, 2, 1)),
        ],
    )
    model = _build_model(request, compatible_box_types(request), z3.Context())
    for i, (x, z) in enumerate(((0, 0), (4 - width, 0), (0, 1))):
        model.optimizer.add(model.box[i] == 0, model.x[i] == x, model.y[i] == 0, model.z[i] == z)
        model.optimizer.add(model.dx[i] == request.products[i].length)
    assert model.optimizer.check() == z3.sat
    points = support_violations(model, model.optimizer.model())
    assert bool(points) == gap
    assert add_support_cuts(model, points) == len(points)
    assert model.optimizer.check() == (z3.unsat if gap else z3.sat)


def test_support_separator_finds_interior_hole_with_all_corners_supported():
    request = order(
        [carton(size=(4, 4, 2))],
        [item(str(i), (1, 1, 1)) for i in range(4)] + [item("top", (4, 4, 1))],
    )
    model = _build_model(request, compatible_box_types(request), z3.Context(), symmetry=False)
    for i, (x, y, z) in enumerate(((0, 0, 0), (3, 0, 0), (0, 3, 0), (3, 3, 0), (0, 0, 1))):
        model.optimizer.add(model.box[i] == 0, model.x[i] == x, model.y[i] == y, model.z[i] == z)
    assert model.optimizer.check() == z3.sat
    points = support_violations(model, model.optimizer.model())
    assert {point[0] for point in points} == {4}
    add_support_cuts(model, points)
    assert model.optimizer.check() == z3.unsat


def test_refinement_interrupts_reject_unsupported_relaxed_optimum(monkeypatch):
    request = order(
        [carton(size=(4, 2, 2))],
        [
            item("a", (1, 2, 1)),
            item("b", (1, 2, 1)),
            item("top", (4, 2, 1)),
        ],
    )
    built = []

    def build(*args):
        model = _build_model(*args)
        # Restrict this test to a raised top. The relaxation packs all three;
        # exact support can pack only the two bases. The empty incumbent remains
        # feasible in both models, so a proof must emerge after refinement.
        model.optimizer.add(z3.Implies(model.box[2] >= 0, model.z[2] == 1))
        built.append(model)
        return model

    monkeypatch.setattr("app.packing.z3_model._build_model", build)
    messages = []
    solve(
        request,
        compatible_box_types(request),
        empty_plan(request),
        0,
        lambda *message: messages.append(message),
    )
    assert built[0].support_points
    assert messages[-1][0] == "optimal"
    assert messages[-1][1].metrics.packed_items == 2
    assert messages[-1][1].metrics.used_volume == 4
    for _, candidate in messages:
        assert candidate.metrics.packed_items <= 2
        validate_solution(request, candidate, Fraction(1))


def test_compact_model_caps_slots_globally_and_keeps_all_types():
    request = order([carton(str(i), stock=1000) for i in range(12)], [item(quantity=3)])
    types = compatible_box_types(request)
    model = _build_model(request, types, z3.Context())
    assert len(model.boxes) == 12
    assert len(model.carton_type) == 3
    assert not model.support_points


def test_70_items_do_not_eagerly_build_cubic_support_assertions():
    request = order([carton(stock=1000)], [item(quantity=70)])
    model = _build_model(request, compatible_box_types(request), z3.Context())
    assert len(model.carton_type) == 70
    assert len(model.optimizer.assertions()) < 12_000
    assert not model.support_points


def test_70_individually_boxed_items_reach_a_proved_optimum(monkeypatch):
    request = order([carton(size=(10, 10, 10), stock=1000)], [item(size=(10, 10, 10), quantity=70)])
    incumbent = baseline(request)

    def build(*args):
        model = _build_model(*args)
        # Bound this regression only; production has no deadline. Without the
        # explicit forced-slot consequence SMT can spend minutes on pigeonholes.
        model.optimizer.set(timeout=10_000)
        return model

    monkeypatch.setattr("app.packing.z3_model._build_model", build)
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
    assert result.metrics.packed_items == result.metrics.boxes_used == 70
    assert result.metrics.fill_ratio == 1
    validate_solution(request, result, Fraction(1))


def test_full_incumbent_prunes_only_proven_worse_volume_and_fixes_packing():
    request = order(
        [carton("small", (2, 2, 2), 10), carton("huge", (10, 10, 10))], [item(quantity=2)]
    )
    incumbent = baseline(request)
    assert incumbent.metrics.total_box_volume == 16
    model = _build_model(request, compatible_box_types(request), z3.Context(), incumbent=incumbent)
    assert [box.id for box in model.boxes] == ["small"]
    assert len(model.carton_type) == 2
    model.optimizer.add(model.box[0] == -1)
    assert model.optimizer.check() == z3.unsat


def test_partial_incumbent_does_not_prune_larger_box_needed_to_pack_more():
    request = order([carton("small", (2, 2, 2)), carton("large", (4, 2, 2))], [item(quantity=2)])
    incumbent = baseline(replace(request, boxes=(request.boxes[0],)))
    validate_solution(request, incumbent, Fraction(1))
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
    assert result.metrics.packed_items == 2
    assert result.metrics.total_box_volume == 16


@pytest.mark.parametrize("seed", range(12))
def test_lazy_symmetric_model_matches_eager_unsymmetrized_optimum(seed, exact_optimum):
    rng = Random(seed)
    request = order(
        [
            carton("a", (3, 3, 3), stock=1, weight=4),
            carton("b", (4, 3, 2), stock=2, weight=3),
        ],
        [
            item(
                "a",
                tuple(rng.randint(1, 3) for _ in range(3)),
                quantity=2,
                rotation=bool(seed % 2),
                weight=2,
            ),
            item("b", tuple(rng.randint(1, 3) for _ in range(3)), weight=2),
        ],
    )
    types = compatible_box_types(request)
    expected = exact_optimum(request)
    messages = []
    solve(request, types, empty_plan(request), seed % 2, lambda *message: messages.append(message))
    status, actual = messages[-1]
    assert status == "optimal"
    assert objective(actual) == objective(expected)
    for _, candidate in messages:
        if candidate is not None:
            validate_solution(request, candidate, Fraction(1))


def test_shared_bound_is_inclusive_and_never_prefers_fewer_items():
    request = order([carton(stock=3)], [item(quantity=3)])
    best = baseline(request)
    model = _build_model(request, compatible_box_types(request), z3.Context())
    add_bound(model, objective(best))
    full_support(model)
    assert model.optimizer.check() == z3.sat
    result = _extract(request, model, model.optimizer.model())
    assert objective(result) <= objective(best)
    model.optimizer.add(model.box[-1] == -1)
    assert model.optimizer.check() == z3.unsat


def test_worker_applies_received_bound_and_still_proves_the_optimum():
    request = order([carton()], [item(quantity=2)])
    expected = baseline(request)
    pending = [objective(expected)]
    messages = []
    solve(
        request,
        compatible_box_types(request),
        empty_plan(request),
        0,
        lambda *message: messages.append(message),
        lambda: pending.pop() if pending else None,
    )
    assert not pending
    assert messages[-1][0] == "optimal"
    assert objective(messages[-1][1]) == objective(expected)


def test_bounded_mailboxes_replace_unread_updates_without_blocking():
    queues = [Queue(maxsize=1), Queue(maxsize=1)]
    _publish_bound(queues, (-2, -16, 64, 1))
    _publish_bound(queues, (-3, -24, 64, 1))
    assert [queue.get_nowait() for queue in queues] == [(-3, -24, 64, 1)] * 2


def _sharing_worker(connection, request, types, incumbent, variant, updates):
    """Fake proof messages test IPC only; exact solver proofs are tested above."""
    improved = baseline(request)
    if variant == 0:
        connection.send(("feasible", improved))
        connection.send(("solver_error", None))
    else:
        received = updates.get(timeout=5)
        connection.send(
            ("optimal" if received == objective(improved) else "solver_error", improved)
        )
    connection.close()


@pytest.mark.skipif(MAX_SOLVER_WORKERS < 2, reason="Requires two process slots")
def test_controller_delivers_verified_improvement_to_another_process(monkeypatch):
    request = order([carton("small", (2, 2, 2)), carton("large", (4, 4, 4))], [item()])
    request = replace(request, options=replace(request.options, solver_workers=2))
    poor = baseline(replace(request, boxes=(request.boxes[1],)))
    monkeypatch.setattr(DeterministicPackingEngine, "pack", lambda self, value: poor)
    monkeypatch.setattr("app.packing.z3_engine._worker", _sharing_worker)
    result = Z3PackingEngine().pack(request)
    validate_solution(request, result, Fraction(1))
    assert result.optimization.status == "optimal"
    assert result.metrics.total_box_volume == 8
    assert result.optimization.workers == 2
