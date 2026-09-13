"""Cancellable Z3 portfolio with a validated full-support heuristic incumbent.

Search has no time limit. Worker limits apply across concurrent requests in
this API process; cancellation also interrupts waiting for an available worker.
"""

import logging
import multiprocessing
import os
from dataclasses import replace
from fractions import Fraction
from multiprocessing.connection import Connection, wait
from queue import Empty, Full
from threading import BoundedSemaphore
from time import monotonic
from typing import Literal

from app.domain.models import OptimizationInfo, PackingRequest, PackingResult
from app.packing.control import SearchControl
from app.packing.engine import DeterministicPackingEngine
from app.packing.options import EngineOptions
from app.packing.repacking import repack_cartons
from app.packing.scoring import solution_signature
from app.packing.strategies import STRATEGIES
from app.packing.validation import validate_solution


def _available_cpus() -> int:
    process_count = getattr(os, "process_cpu_count", None)
    if process_count is not None:
        return process_count() or 1
    affinity = getattr(os, "sched_getaffinity", None)
    if affinity is not None:
        return len(affinity(0)) or 1
    return os.cpu_count() or 1


MAX_SOLVER_WORKERS = _available_cpus()
_WORKER_SLOTS = BoundedSemaphore(MAX_SOLVER_WORKERS)
_FULL_SUPPORT = Fraction(1)
_LOGGER = logging.getLogger(__name__)


def _objective(result: PackingResult) -> tuple[int, int, int, int]:
    metrics = result.metrics
    return (
        -metrics.packed_items,
        -metrics.used_volume,
        metrics.total_box_volume,
        metrics.boxes_used,
    )


def _worker(
    connection: Connection,
    request: PackingRequest,
    slots: tuple,
    incumbent: PackingResult,
    variant: int,
    updates=None,
) -> None:
    """Spawn target; each process imports and owns its own Z3 runtime/context."""
    try:
        from app.packing.z3_certificate import certify_incumbent
        from app.packing.z3_model import solve

        def emit(status: str, result: PackingResult | None) -> None:
            connection.send((status, result))

        def receive_bound():
            score = None
            if updates is not None:
                while True:
                    try:
                        received = updates.get_nowait()
                    except Empty:
                        break
                    score = received if score is None else min(score, received)
            return score

        if certify_incumbent(request, incumbent):
            emit("optimal", incumbent)
        else:
            solve(request, slots, incumbent, variant, emit, receive_bound)
    except Exception:
        _LOGGER.exception("Z3 packing worker failed")
        # Broken pipes occur if the controller has already stopped this worker.
        try:
            connection.send(("solver_error", None))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def _publish_bound(queues, score) -> None:
    """Bounded, nonblocking mailboxes: a slow worker cannot stall cancellation."""
    for updates in queues:
        try:
            # Replace an unread older bound when possible. Queue feeder races
            # may leave a previous bound for one round, which is still safe.
            updates.get_nowait()
        except Empty:
            pass
        try:
            updates.put_nowait(score)
        except Full:
            pass


class Z3PackingEngine:
    version = "z3-packing-v1"

    def __init__(self, cancel_event=None, progress=None) -> None:
        self._cancel_event = cancel_event
        self._progress = progress

    def _cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def pack(self, request: PackingRequest) -> PackingResult:
        control = SearchControl(cancel_event=self._cancel_event, progress=self._progress)
        control.report("preparing", None)
        # Alternatives from an 80%-support engine cannot be reused in this model.
        baseline_request = replace(
            request, options=replace(request.options, include_alternatives=False)
        )
        baseline = DeterministicPackingEngine(
            EngineOptions(
                min_support_ratio=_FULL_SUPPORT,
                max_candidate_points=64,
                max_strategies=3,
                max_alternatives=0,
            ),
            control=control,
            strategies=(STRATEGIES[0], STRATEGIES[6], STRATEGIES[11]),
        ).pack(baseline_request)
        validate_solution(request, baseline, _FULL_SUPPORT)
        if self._cancelled():
            raise RuntimeError("Packing cancelled")
        workers_requested = min(max(1, request.options.solver_workers), MAX_SOLVER_WORKERS)

        def finish(
            result: PackingResult,
            status: Literal["optimal", "feasible", "fallback"],
            reason: Literal["completed", "solver_error"],
            workers: int,
        ) -> PackingResult:
            result = repack_cartons(request, result, control)
            completed = replace(
                result,
                algorithm_version=self.version,
                alternatives=(),
                optimization=OptimizationInfo(status, reason, workers, None, 1.0),
            )
            validate_solution(request, completed, _FULL_SUPPORT)
            return completed

        # This import remains lazy so heuristic-only requests do not load Z3.
        from app.packing.z3_constraints import compatible_box_types

        slots = compatible_box_types(request)
        if not slots or not baseline.metrics.total_items:
            return finish(baseline, "optimal", "completed", 0)
        context = multiprocessing.get_context("spawn")
        running: list[tuple[multiprocessing.Process, Connection]] = []
        bound_queues = []
        acquired = 0
        best = baseline
        best_from_solver = False
        proof: tuple[int, int, int, int] | None = None
        # There is no known completion fraction for an unlimited solver search.
        control.report("solver", None)
        try:
            for variant in range(workers_requested):
                if self._cancelled():
                    break
                granted = _WORKER_SLOTS.acquire(blocking=False)
                while not granted and not running and not self._cancelled():
                    granted = _WORKER_SLOTS.acquire(timeout=0.1)
                if not granted:
                    break
                acquired += 1
                receiver, sender = context.Pipe(duplex=False)
                updates = context.Queue(maxsize=1)
                bound_queues.append(updates)
                process = context.Process(
                    target=_worker,
                    args=(sender, request, slots, baseline, variant, updates),
                    name=f"duncarbox-z3-{variant}",
                    daemon=True,
                )
                try:
                    process.start()
                except Exception:
                    _LOGGER.exception("Could not start Z3 packing worker")
                    receiver.close()
                    sender.close()
                    break
                sender.close()
                running.append((process, receiver))

            active = [connection for _, connection in running]
            while active and proof is None and not self._cancelled():
                ready = wait(active, timeout=0.05)
                for connection in ready:
                    try:
                        status, candidate = connection.recv()
                    except (EOFError, OSError):
                        _LOGGER.error("Z3 packing worker exited without a final result")
                        active.remove(connection)
                        continue
                    if candidate is not None:
                        try:
                            validate_solution(request, candidate, _FULL_SUPPORT)
                        except ValueError:
                            _LOGGER.exception("Z3 packing worker returned an invalid plan")
                            continue
                        if (_objective(candidate), solution_signature(candidate.packed_boxes)) <= (
                            _objective(best),
                            solution_signature(best.packed_boxes),
                        ):
                            improved = _objective(candidate) < _objective(best)
                            best = candidate
                            best_from_solver = True
                            if improved:
                                _publish_bound(bound_queues, _objective(best))
                    if status == "optimal" and candidate is not None:
                        proof = _objective(candidate)
                    if status != "feasible":
                        active.remove(connection)
        finally:
            # Reap the whole portfolio on proof, cancellation or worker failure.
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
            for updates in bound_queues:
                updates.cancel_join_thread()
                updates.close()

        if self._cancelled():
            raise RuntimeError("Packing cancelled")
        if proof is not None and proof == _objective(best):
            # The incumbent can be the selected plan: a solver proof of the same
            # objective also proves that independently validated plan optimal.
            return finish(best, "optimal", "completed", len(running))
        return finish(
            best, "feasible" if best_from_solver else "fallback", "solver_error", len(running)
        )
