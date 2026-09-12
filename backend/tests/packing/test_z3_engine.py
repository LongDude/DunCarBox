"""Solver semantics, full-support geometry and bounded process orchestration."""

import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from fractions import Fraction
from threading import BoundedSemaphore
from time import monotonic, sleep

import pytest
import z3

from app.domain.models import BoxType, PackingOptions, PackingRequest, Product
from app.packing.diagnostics import build_issues
from app.packing.engine import _metrics
from app.packing.strategies import expand_items
from app.packing.validation import validate_solution
from app.packing.z3_engine import MAX_MODEL_ITEMS, Z3PackingEngine
from app.packing.z3_model import _build_model, box_slots


def box(identifier="box", size=(10, 10, 10), weight=100, stock=1):
    return BoxType(identifier, identifier, *size, weight, stock)


def product(identifier="item", size=(10, 10, 10), weight=1, quantity=1, rotation=False):
    return Product(identifier, identifier, *size, weight, quantity, rotation)


def request(boxes, products, *, timeout=5000, workers=1):
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


def test_box_count_precedes_empty_volume():
    value = request(
        [box("small", size=(10, 10, 1), stock=2), box("large", size=(30, 10, 1))],
        [product(size=(10, 10, 1), quantity=2)],
    )
    result = pack(value)
    assert result.metrics.packed_items == 2
    assert result.metrics.boxes_by_type == {"large": 1}
    assert result.metrics.empty_volume == 100
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


def test_large_order_uses_explicit_fallback_without_dropping_units():
    value = request([box(stock=MAX_MODEL_ITEMS + 1)], [product(quantity=MAX_MODEL_ITEMS + 1)])
    result = pack(value)
    assert result.metrics.total_items == result.metrics.packed_items == MAX_MODEL_ITEMS + 1
    assert result.optimization.status == "fallback"
    assert result.optimization.reason == "size_limit"
    assert result.optimization.workers == 0


def test_box_slot_limit_is_explicit_and_does_not_truncate_catalog():
    value = request([box(str(i)) for i in range(65)], [product()])
    result = pack(value)
    assert result.metrics.packed_items == 1
    assert result.optimization.status == "fallback"
    assert result.optimization.reason == "size_limit"


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
    connection.send(("time_limit", None))
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
    connection.send(("time_limit", None))
    connection.close()


def test_valid_solver_incumbent_without_proof_is_feasible(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _feasible_only_worker)
    result = pack(request([box()], [product()]))
    assert result.optimization.status == "feasible"
    assert result.optimization.reason == "time_limit"
    assert result.metrics.packed_items == 1


def test_inferior_solver_candidate_never_replaces_strict_baseline(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _inferior_worker)
    result = pack(request([box()], [product()]))
    assert result.metrics.packed_items == 1
    assert result.optimization.status == "fallback"
    assert result.optimization.reason == "time_limit"


def test_deadline_terminates_a_stuck_worker_and_keeps_full_support_baseline(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _unresponsive_worker)
    value = request([box(size=(10, 10, 20))], [product(quantity=2)], timeout=300)
    previous = {child.pid for child in multiprocessing.active_children()}
    started = monotonic()
    result = pack(value)
    assert monotonic() - started < 3
    assert result.metrics.packed_items == 2
    assert result.optimization.status == "fallback"
    assert result.optimization.reason == "time_limit"
    assert {child.pid for child in multiprocessing.active_children()} <= previous


def test_solver_exception_is_never_reported_as_an_optimality_proof(monkeypatch):
    monkeypatch.setattr("app.packing.z3_engine._worker", _failing_worker)
    result = pack(request([box()], [product()]))
    assert result.metrics.packed_items == 1
    assert result.optimization.status == "fallback"
    assert result.optimization.reason == "solver_error"


def test_busy_process_budget_waits_only_until_deadline(monkeypatch):
    gate = BoundedSemaphore(1)
    gate.acquire()
    monkeypatch.setattr("app.packing.z3_engine._WORKER_SLOTS", gate)
    started = monotonic()
    result = pack(request([box()], [product()], timeout=50))
    assert 0.04 <= monotonic() - started < 2
    assert result.optimization.status == "fallback"
    assert result.optimization.reason == "time_limit"
    assert result.optimization.workers == 0
    gate.release()


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
