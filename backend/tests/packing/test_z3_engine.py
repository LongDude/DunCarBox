"""Solver semantics, full-support geometry and cancellable process orchestration."""

import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from fractions import Fraction
from threading import BoundedSemaphore, Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
import z3

from app.domain.models import BoxType, PackingOptions, PackingRequest, Product
from app.packing.diagnostics import build_issues
from app.packing.engine import _metrics
from app.packing.strategies import expand_items
from app.packing.validation import validate_solution
from app.packing.z3_engine import Z3PackingEngine
from app.packing.z3_model import _build_model, box_slots, solve


def box(identifier="box", size=(10, 10, 10), weight=100, stock=1):
    return BoxType(identifier, identifier, *size, weight, stock)


def product(identifier="item", size=(10, 10, 10), weight=1, quantity=1, rotation=False):
    return Product(identifier, identifier, *size, weight, quantity, rotation)


def request(boxes, products, *, timeout=None, workers=1):
    return PackingRequest(
        tuple(boxes),
        tuple(products),
        PackingOptions(
            algorithm="z3",
            solver_timeout_ms=timeout,
            solver_workers=workers,
        ),
    )


def pack(value):
    result = Z3PackingEngine().pack(value)
    validate_solution(value, result, Fraction(1))
    assert result.algorithm_version == "z3-packing-v1"
    assert result.optimization.support_ratio == 1
    assert result.optimization.time_limit_ms is None
    return result


@pytest.mark.parametrize("rotation,expected", [(False, 0), (True, 1)])
def test_rotation_and_combined_weight(rotation, expected):
    value = request(
        [box(size=(6, 4, 4), weight=10)],
        [
            product(size=(4, 6, 2), weight=6, quantity=2, rotation=rotation),
        ],
    )
    result = pack(value)
    assert result.metrics.packed_items == expected
    assert result.optimization.status == "optimal"


def test_stock_partial_plan_and_incompatible_sentinel():
    value = request([box(stock=2)], [product(quantity=3), product("huge", size=(100, 100, 100))])
    result = pack(value)
    assert result.status == "partial"
    assert result.metrics.packed_items == result.metrics.boxes_used == 2
    assert result.metrics.unpacked_items == 2
    assert result.optimization.status == "optimal"
    assert {item.id for item in result.unpacked_items} == {"item:3", "huge:1"}


@pytest.mark.parametrize("boxes", [[], [box(stock=0)], [box(size=(1, 1, 1))]])
def test_trivially_impossible_does_not_start_processes(boxes):
    result = pack(request(boxes, [product()]))
    assert result.status == "impossible"
    assert result.optimization.status == "optimal"
    assert result.optimization.reason == "completed"
    assert result.optimization.workers == 0


def test_count_precedes_packed_volume():
    value = request(
        [box(size=(10, 10, 1))],
        [
            product("large", size=(10, 10, 1)),
            product("small", size=(5, 5, 1), quantity=2),
        ],
    )
    result = pack(value)
    assert result.metrics.packed_items == 2
    assert result.metrics.used_volume == 50
    assert {p.product_id for b in result.packed_boxes for p in b.placements} == {"small"}
    assert result.optimization.status == "optimal"


def test_packed_volume_breaks_equal_count_tie():
    value = request(
        [box(size=(10, 10, 1))],
        [
            product("a", size=(10, 9, 1)),
            product("b", size=(10, 8, 1)),
        ],
    )
    result = pack(value)
    assert result.metrics.packed_items == 1
    assert result.metrics.used_volume == 90
    assert result.optimization.status == "optimal"


def test_overall_fill_precedes_box_count():
    value = request(
        [box("small", size=(10, 10, 1), stock=2), box("large", size=(30, 10, 1))],
        [product(size=(10, 10, 1), quantity=2)],
    )
    result = pack(value)
    assert result.metrics.packed_items == 2
    assert result.metrics.boxes_by_type == {"small": 2}
    assert result.metrics.fill_ratio == 1
    assert result.metrics.empty_volume == 0
    assert result.optimization.status == "optimal"


def test_box_volume_breaks_equal_box_count_tie():
    value = request(
        [box("large", size=(30, 10, 1)), box("small", size=(20, 10, 1))],
        [product(size=(10, 10, 1), quantity=2)],
    )
    result = pack(value)
    assert result.metrics.boxes_by_type == {"small": 1}
    assert result.metrics.empty_volume == 0
    assert result.optimization.status == "optimal"


@pytest.mark.parametrize("support_width,second_x,expected", [(5, 5, z3.sat), (4, 6, z3.unsat)])
def test_union_of_multiple_support_faces_and_overhang(support_width, second_x, expected):
    value = request(
        [box(size=(10, 4, 4))],
        [
            product("base-a", size=(support_width, 4, 2)),
            product("base-b", size=(support_width, 4, 2)),
            product("top", size=(10, 4, 2)),
        ],
    )
    model = _build_model(value, box_slots(value), z3.Context())
    for index, (x, y, z) in enumerate([(0, 0, 0), (second_x, 0, 0), (0, 0, 2)]):
        model.optimizer.add(
            model.box[index] == 0, model.x[index] == x, model.y[index] == y, model.z[index] == z
        )
    model.optimizer.set(timeout=3000)
    assert model.optimizer.check() == expected


def test_unpacked_item_cannot_support_a_packed_item():
    value = request([box(size=(10, 10, 20))], [product(quantity=2)])
    model = _build_model(value, box_slots(value), z3.Context())
    model.optimizer.add(model.box[0] == 0, model.z[0] == 10, model.box[1] == -1)
    model.optimizer.set(timeout=3000)
    assert model.optimizer.check() == z3.unsat


def test_large_order_attempts_solver_without_dropping_units(monkeypatch):
    # Exercise input forwarding without an expensive optimality proof.
    monkeypatch.setattr("app.packing.z3_engine._worker", _feasible_only_worker)
    value = request([box(stock=17)], [product(quantity=17)], timeout=100)
    result = pack(value)
    assert result.metrics.total_items == result.metrics.packed_items == 17
    assert result.optimization.status == "feasible"
    assert result.optimization.reason == "solver_error"
    assert result.optimization.workers == 1


def test_box_slots_above_previous_limit_still_reach_solver(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _feasible_only_worker)
    value = request([box(str(i)) for i in range(65)], [product()], timeout=100)
    result = pack(value)
    assert result.metrics.packed_items == 1
    assert result.optimization.status == "feasible"
    assert result.optimization.reason == "solver_error"
    assert result.optimization.workers == 1


def _unresponsive_worker(*args):
    sleep(60)


def _failing_worker(connection, *args):
    connection.send(("solver_error", None))
    connection.close()


def _abrupt_worker(*args):
    os._exit(1)


def test_abrupt_worker_exit_is_a_solver_error_not_a_timeout(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _abrupt_worker)
    result = pack(request([box()], [product()]))
    assert result.metrics.packed_items == 1
    assert result.optimization.status == "fallback"
    assert result.optimization.reason == "solver_error"


def _feasible_only_worker(connection, request, slots, incumbent, *args):
    connection.send(("feasible", incumbent))
    connection.send(("solver_error", None))
    connection.close()


def _inferior_worker(connection, request, slots, incumbent, *args):
    items = expand_items(request)
    result = replace(
        incumbent,
        status="impossible",
        metrics=_metrics((), len(items)),
        packed_boxes=(),
        unpacked_items=items,
        issues=build_issues(request, (), items),
    )
    connection.send(("feasible", result))
    connection.send(("solver_error", None))
    connection.close()


def test_valid_solver_incumbent_without_proof_is_feasible(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _feasible_only_worker)
    result = pack(request([box()], [product()]))
    assert result.optimization.status == "feasible"
    assert result.optimization.reason == "solver_error"
    assert result.metrics.packed_items == 1


def test_inferior_solver_candidate_never_replaces_strict_baseline(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _inferior_worker)
    result = pack(request([box()], [product()]))
    assert result.metrics.packed_items == 1
    assert result.optimization.status == "fallback"
    assert result.optimization.reason == "solver_error"


def test_cancellation_terminates_a_stuck_worker_and_releases_process_slot(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _unresponsive_worker)
    gate = BoundedSemaphore(1)
    monkeypatch.setattr("app.packing.z3_engine._WORKER_SLOTS", gate)
    cancel = Event()
    solver_started = Event()
    engine = Z3PackingEngine(
        cancel_event=cancel,
        progress=lambda stage, fraction: solver_started.set() if stage == "solver" else None,
    )
    value = request([box(size=(10, 10, 20))], [product(quantity=2)], timeout=1)
    previous = {child.pid for child in multiprocessing.active_children()}
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(engine.pack, value)
        try:
            assert solver_started.wait(5)
            started = monotonic()
            while {child.pid for child in multiprocessing.active_children()} <= previous:
                assert monotonic() - started < 5
                sleep(0.01)
            sleep(0.05)
            assert not future.done(), "Legacy 1 ms timeout must not stop the worker"
        finally:
            cancel.set()
        with pytest.raises(RuntimeError, match="cancelled"):
            future.result(timeout=5)
    assert {child.pid for child in multiprocessing.active_children()} <= previous
    assert gate.acquire(blocking=False)
    gate.release()


def test_solver_exception_is_never_reported_as_an_optimality_proof(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _failing_worker)
    result = pack(request([box()], [product()]))
    assert result.metrics.packed_items == 1
    assert result.optimization.status == "fallback"
    assert result.optimization.reason == "solver_error"


def test_busy_process_budget_waits_until_cancelled(monkeypatch):
    gate = BoundedSemaphore(1)
    gate.acquire()
    monkeypatch.setattr("app.packing.z3_engine._WORKER_SLOTS", gate)
    cancel = Event()
    waiting = Event()
    engine = Z3PackingEngine(
        cancel_event=cancel,
        progress=lambda stage, fraction: waiting.set() if stage == "solver" else None,
    )
    previous = {child.pid for child in multiprocessing.active_children()}
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(engine.pack, request([box()], [product()], timeout=1))
        try:
            assert waiting.wait(5)
            sleep(0.15)
            assert not future.done()
        finally:
            cancel.set()
        with pytest.raises(RuntimeError, match="cancelled"):
            future.result(timeout=2)
    assert {child.pid for child in multiprocessing.active_children()} <= previous
    assert not gate.acquire(blocking=False), "Controller must not release another owner's slot"
    gate.release()


def test_real_solver_ignores_legacy_timeout_and_reports_unknown_progress():
    progress = []
    value = request([box(size=(20, 10, 10))], [product(quantity=2)], timeout=1)
    result = Z3PackingEngine(progress=lambda *values: progress.append(values)).pack(value)
    validate_solution(value, result, Fraction(1))
    assert result.metrics.packed_items == 2
    assert result.optimization.status == "optimal"
    assert result.optimization.reason == "completed"
    assert result.optimization.time_limit_ms is None
    assert ("solver", None) in progress
    assert all(fraction is None for stage, fraction in progress if stage == "solver")


@pytest.mark.parametrize("solver_status", [z3.unknown, z3.unsat])
def test_solver_without_a_proof_reports_error_without_configuring_timeout(
    monkeypatch, solver_status
):
    class Optimizer:
        def set_on_model(self, callback):
            pass

        def check(self):
            return solver_status

    monkeypatch.setattr(
        "app.packing.z3_model._build_model",
        lambda *args: SimpleNamespace(optimizer=Optimizer()),
    )
    value = request([box()], [product()], timeout=1)
    from app.packing.engine import DeterministicPackingEngine

    incumbent = DeterministicPackingEngine().pack(value)
    messages = []
    solve(value, box_slots(value), incumbent, 0, lambda *message: messages.append(message))
    assert messages == [("solver_error", None)]


def test_parallel_requests_own_their_solver_contexts_and_preserve_inputs():
    value = request([box(size=(20, 10, 10))], [product(quantity=2)], workers=2)
    before = asdict(value)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(pack, [value, value]))
    for result in results:
        assert result.optimization.status == "optimal"
        assert result.metrics.packed_items == 2
        assert 1 <= result.optimization.workers <= 2
    assert asdict(value) == before


def test_completed_single_worker_reordered_input_is_canonical():
    value = request(
        [box("b", size=(20, 10, 10)), box("a", size=(10, 10, 10))], [product("b"), product("a")]
    )
    first = pack(value)
    second = pack(
        replace(value, boxes=tuple(reversed(value.boxes)), products=tuple(reversed(value.products)))
    )
    assert first.optimization.status == second.optimization.status == "optimal"
    assert first == second
