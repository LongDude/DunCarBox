"""Run independent heuristic starts in CPU processes and rank their valid plans."""

import multiprocessing
from dataclasses import replace
from multiprocessing.connection import wait
from time import monotonic

from app.domain.models import PackingAlternative, PackingResult
from app.packing.control import SearchControl
from app.packing.engine import DeterministicPackingEngine
from app.packing.scoring import solution_score, solution_signature
from app.packing.strategies import STRATEGIES
from app.packing.validation import validate_solution
from app.packing.z3_engine import _WORKER_SLOTS, MAX_SOLVER_WORKERS


def _search(connection, request, strategies, cancel_event):
    last_report = 0.0

    def progress(stage, fraction):
        nonlocal last_report
        now = monotonic()
        if now - last_report >= 0.1 or fraction == 1:
            connection.send(("progress", fraction))
            last_report = now

    try:
        # Keep each group's runner-up plans for the final global comparison.
        value = replace(request, options=replace(request.options, include_alternatives=True))
        result = DeterministicPackingEngine(
            strategies=strategies,
            control=SearchControl(cancel_event=cancel_event, progress=progress),
        ).pack(value)
        connection.send(("result", result))
    finally:
        connection.close()


def _merge(request, results):
    candidates = {}
    for result in results:
        for plan in (result, *result.alternatives):
            candidate = PackingResult(
                status=plan.status,
                metrics=plan.metrics,
                packed_boxes=plan.packed_boxes,
                unpacked_items=plan.unpacked_items,
                issues=plan.issues,
                algorithm_version=DeterministicPackingEngine.version,
            )
            candidates.setdefault(solution_signature(plan.packed_boxes), candidate)
    boxes = {box.id: box for box in request.boxes}
    ranked = sorted(candidates.values(), key=lambda value: solution_score(value, boxes))
    best = ranked[0]
    alternatives = []
    for result in ranked[1:]:
        if (
            not request.options.include_alternatives
            or len(alternatives) >= min(3, request.options.max_alternatives)
        ):
            break
        if (result.metrics.packed_items, result.metrics.used_volume) != (
            best.metrics.packed_items, best.metrics.used_volume
        ):
            continue
        alternatives.append(PackingAlternative(
            id=f"alternative-{len(alternatives) + 1}",
            description=(
                f"Коробок: {result.metrics.boxes_used}; "
                f"заполнение: {result.metrics.fill_ratio:.1%}."
            ),
            status=result.status,
            metrics=result.metrics,
            packed_boxes=result.packed_boxes,
            unpacked_items=result.unpacked_items,
            issues=result.issues,
        ))
    return replace(best, alternatives=tuple(alternatives))


def pack_parallel(request, *, cancel_event=None, progress=None):
    control = SearchControl(cancel_event=cancel_event, progress=progress)
    requested = min(request.options.solver_workers, MAX_SOLVER_WORKERS, len(STRATEGIES))
    # On small orders, process startup costs more than the placement search.
    if requested <= 1 or sum(p.quantity for p in request.products) < 100 or not request.boxes:
        return DeterministicPackingEngine(control=control).pack(request)
    acquired = 0
    for _ in range(requested):
        if not _WORKER_SLOTS.acquire(blocking=False):
            break
        acquired += 1
    if not acquired:
        return DeterministicPackingEngine(control=control).pack(request)
    context = multiprocessing.get_context("spawn")
    running = []
    results = {}
    fractions = [0.0] * acquired
    groups = [STRATEGIES[index::acquired] for index in range(acquired)]
    try:
        for index, strategies in enumerate(groups):
            control.expired()
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_search, args=(sender, request, strategies, cancel_event),
                name=f"duncarbox-heuristic-{index}", daemon=True,
            )
            try:
                process.start()
            except BaseException:
                receiver.close()
                raise
            finally:
                sender.close()
            running.append((process, receiver))
        active = {connection: index for index, (_, connection) in enumerate(running)}
        while active:
            control.expired()
            for connection in wait(active, timeout=0.1):
                index = active[connection]
                try:
                    kind, value = connection.recv()
                except EOFError as error:
                    # A cancelled child can close its pipe before the next loop check.
                    control.expired()
                    raise RuntimeError("Heuristic worker exited without a result") from error
                if kind == "result":
                    results[index] = value
                    fractions[index] = 1.0
                    del active[connection]
                else:
                    fractions[index] = value
                control.report("heuristic", sum(
                    fraction * len(group) for fraction, group in zip(fractions, groups)
                ) / len(STRATEGIES))
    finally:
        for process, connection in running:
            if process.is_alive():
                process.terminate()
            connection.close()
        cleanup_deadline = monotonic() + 1
        for process, _ in running:
            process.join(timeout=max(0, cleanup_deadline - monotonic()))
            if process.is_alive():
                process.kill()
                process.join(timeout=0.5)
            process.close()
        for _ in range(acquired):
            _WORKER_SLOTS.release()
    result = _merge(request, [results[index] for index in sorted(results)])
    validate_solution(request, result)
    return result
