import multiprocessing
from dataclasses import replace
from fractions import Fraction
from threading import Event, Timer
from time import monotonic

import pytest

from app.domain.models import BoxType, PackingOptions, PackingRequest, Position, Product
from app.packing.control import SearchControl
from app.packing.engine import DeterministicPackingEngine
from app.packing.parallel import pack_parallel
from app.packing.repacking import layout_score, repack_cartons
from app.packing.scoring import solution_signature
from app.packing.validation import validate_solution
from app.packing.z3_engine import Z3PackingEngine
from app.services.packing import PackingService


def order(quantity=2):
    return PackingRequest(
        (BoxType("box", "Box", 60, 10, 10, 100, quantity),),
        (Product("item", "Item", 10, 10, 10, 1, quantity, False),),
    )


def test_z3_initial_heuristic_remains_cancellable_without_a_time_limit():
    value = order(2000)
    value = replace(value, options=PackingOptions(algorithm="z3"))
    cancel = Event()
    timer = Timer(0.05, cancel.set)
    timer.start()
    started = monotonic()
    try:
        with pytest.raises(RuntimeError, match="cancelled"):
            Z3PackingEngine(cancel_event=cancel).pack(value)
        assert monotonic() - started < 2
    finally:
        timer.cancel()


def test_repacking_removes_gaps_without_changing_assignment_or_fill():
    value = order()
    original = DeterministicPackingEngine().pack(value)
    box = original.packed_boxes[0]
    scattered = replace(box, placements=tuple(
        replace(p, position=Position(x, 0, 0))
        for p, x in zip(box.placements, (10, 40))
    ))
    original = replace(original, packed_boxes=(scattered,))
    validate_solution(value, original, Fraction(1))
    result = repack_cartons(value, original, SearchControl())
    validate_solution(value, result, Fraction(1))
    assert result.metrics == original.metrics
    assert {p.item_instance_id for p in result.packed_boxes[0].placements} == {"item:1", "item:2"}
    assert layout_score(result.packed_boxes[0].placements) < layout_score(scattered.placements)
    assert [p.position.x for p in result.packed_boxes[0].placements] == [0, 10]


def test_incomplete_repack_keeps_all_assigned_items(monkeypatch):
    value = order()
    original = DeterministicPackingEngine().pack(value)
    from app.packing.engine import _FilledBox

    monkeypatch.setattr("app.packing.repacking._fill_box", lambda *args: _FilledBox((), 0, 0))
    result = repack_cartons(value, original, SearchControl())
    assert result == original


def test_heuristic_parallelism_preserves_search_quality_and_reaps_workers():
    value = order(100)
    value = replace(value, options=PackingOptions(solver_workers=2))
    serial = DeterministicPackingEngine().pack(value)
    previous = {child.pid for child in multiprocessing.active_children()}
    progress = []
    parallel = pack_parallel(value, progress=lambda stage, fraction: progress.append(fraction))
    validate_solution(value, parallel)
    assert parallel.metrics == serial.metrics
    assert solution_signature(parallel.packed_boxes) == solution_signature(serial.packed_boxes)
    assert progress[-1] == 1
    assert progress == sorted(progress)
    assert {child.pid for child in multiprocessing.active_children()} <= previous


def test_python_search_observes_cancellation():
    cancel = Event()
    cancel.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        DeterministicPackingEngine(control=SearchControl(cancel_event=cancel)).pack(order(100))


def test_parallel_cancellation_terminates_children():
    cancel = multiprocessing.get_context("spawn").Event()
    previous = {child.pid for child in multiprocessing.active_children()}
    timer = Timer(0.15, cancel.set)
    timer.start()
    try:
        with pytest.raises(RuntimeError, match="cancelled"):
            pack_parallel(order(2000), cancel_event=cancel)
        assert {child.pid for child in multiprocessing.active_children()} <= previous
    finally:
        timer.cancel()


def test_service_reports_time_and_sorts_cartons_with_valid_instructions():
    value = order(8)

    class ReverseEngine:
        def pack(self, request):
            result = DeterministicPackingEngine().pack(request)
            boxes = tuple(replace(box, id=f"box:{index}") for index, box in enumerate(
                reversed(result.packed_boxes), 1
            ))
            return replace(result, packed_boxes=boxes)

    result = PackingService(ReverseEngine()).pack(value)
    validate_solution(value, result)
    assert result.calculation_seconds is not None and result.calculation_seconds >= 0
    fills = [box.fill_ratio for box in result.packed_boxes]
    assert fills == sorted(fills, reverse=True)
    for box in result.packed_boxes:
        assert all(instruction.box_id == box.id for instruction in box.instructions)
