"""Bounded Z3 portfolio with a validated full-support heuristic incumbent.

The solver budget covers process startup, model construction and optimization.
The initial heuristic shares that budget; validation and process cleanup add
overhead. Worker limits apply across concurrent requests in this API process.
"""

import logging
import multiprocessing
import os
from dataclasses import replace
from fractions import Fraction
from multiprocessing.connection import Connection, wait
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
    deadline: float,
    variant: int,
) -> None:
    """Spawn target; each process imports and owns its own Z3 runtime/context."""
    try:
        from app.packing.z3_model import solve

        def emit(status: str, result: PackingResult | None) -> None:
            connection.send((status, result))

        solve(request, slots, incumbent, deadline, variant, emit)
    except Exception:
        _LOGGER.exception("Z3 packing worker failed")
        # Broken pipes occur if the deadline controller has already stopped us.
        try:
            connection.send(("solver_error", None))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


class Z3PackingEngine:
    version = "z3-packing-v1"

    def __init__(self, cancel_event=None, progress=None) -> None:
        self._cancel_event = cancel_event
        self._progress = progress

    def _cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def pack(self, request: PackingRequest) -> PackingResult:
        started = monotonic()
        timeout_ms = request.options.solver_timeout_ms
        deadline = started + timeout_ms / 1000
        control = SearchControl(
            deadline=deadline, cancel_event=self._cancel_event, progress=self._progress
        )
        control.report("preparing", None)
        # Alternatives from an 80%-support engine cannot be reused in this model.
        baseline_request = replace(
            request, options=replace(request.options, include_alternatives=False)
        )
        baseline = DeterministicPackingEngine(
            EngineOptions(
                min_support_ratio=_FULL_SUPPORT,
                max_candidate_points=64,
                max_strategies=2,
                max_alternatives=0,
            ),
            control=control,
            strategies=(STRATEGIES[0], STRATEGIES[6]),
        ).pack(baseline_request)
        validate_solution(request, baseline, _FULL_SUPPORT)
        if self._cancelled():
            raise RuntimeError("Packing cancelled")
        workers_requested = min(max(1, request.options.solver_workers), MAX_SOLVER_WORKERS)

        def finish(
            result: PackingResult,
            status: Literal["optimal", "feasible", "fallback"],
            reason: Literal["completed", "time_limit", "size_limit", "solver_error"],
            workers: int,
        ) -> PackingResult:
            result = repack_cartons(request, result, control)
            completed = replace(
                result,
                algorithm_version=self.version,
                alternatives=(),
                optimization=OptimizationInfo(status, reason, workers, timeout_ms, 1.0),
            )
            validate_solution(request, completed, _FULL_SUPPORT)
            return completed

        if control.expired():
            return finish(baseline, "fallback", "time_limit", 0)
        # This import remains lazy so heuristic-only requests do not load Z3.
        from app.packing.z3_model import box_slots

        slots = box_slots(request)
        if not slots or not baseline.metrics.total_items:
            return finish(baseline, "optimal", "completed", 0)
        context = multiprocessing.get_context("spawn")
        # Reserve a small part of the same budget for a neat per-carton layout.
        solver_deadline = deadline - min(0.5, timeout_ms / 1000 * 0.1)
        running: list[tuple[multiprocessing.Process, Connection]] = []
        acquired = 0
        best = baseline
        best_from_solver = False
        reason: Literal["time_limit", "solver_error"] = "time_limit"
        proof: tuple[int, int, int, int] | None = None
        try:
            for variant in range(workers_requested):
                remaining = solver_deadline - monotonic()
                if remaining <= 0 or self._cancelled():
                    break
                granted = _WORKER_SLOTS.acquire(blocking=False)
                while (
                    not granted and not running
                    and monotonic() < solver_deadline and not self._cancelled()
                ):
                    granted = _WORKER_SLOTS.acquire(
                        timeout=min(0.1, max(0, solver_deadline - monotonic()))
                    )
                if not granted:
                    break
                acquired += 1
                receiver, sender = context.Pipe(duplex=False)
                process = context.Process(
                    target=_worker,
                    args=(sender, request, slots, baseline, solver_deadline, variant),
                    name=f"duncarbox-z3-{variant}",
                    daemon=True,
                )
                try:
                    process.start()
                except Exception:
                    _LOGGER.exception("Could not start Z3 packing worker")
                    receiver.close()
                    sender.close()
                    reason = "solver_error"
                    break
                sender.close()
                running.append((process, receiver))

            active = [connection for _, connection in running]
            while (
                active and monotonic() < solver_deadline
                and proof is None and not self._cancelled()
            ):
                control.report("solver", min(1, (monotonic() - started) / (timeout_ms / 1000)))
                ready = wait(active, timeout=min(0.05, max(0, solver_deadline - monotonic())))
                for connection in ready:
                    try:
                        status, candidate = connection.recv()
                    except (EOFError, OSError):
                        if monotonic() < deadline:
                            reason = "solver_error"
                            _LOGGER.error("Z3 packing worker exited without a final result")
                        active.remove(connection)
                        continue
                    if candidate is not None:
                        try:
                            validate_solution(request, candidate, _FULL_SUPPORT)
                        except ValueError:
                            reason = "solver_error"
                            continue
                        if (_objective(candidate), solution_signature(candidate.packed_boxes)) <= (
                            _objective(best),
                            solution_signature(best.packed_boxes),
                        ):
                            best = candidate
                            best_from_solver = True
                    if status == "optimal" and candidate is not None:
                        proof = _objective(candidate)
                    elif status == "solver_error":
                        reason = "solver_error"
                    if status != "feasible":
                        active.remove(connection)
        finally:
            # No executor context manager that waits indefinitely on timed-out jobs.
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

        if proof is not None and proof == _objective(best):
            # The incumbent can be the selected plan: a solver proof of the same
            # objective also proves that independently validated plan optimal.
            return finish(best, "optimal", "completed", len(running))
        if self._cancelled():
            raise RuntimeError("Packing cancelled")
        if proof is not None:
            reason = "solver_error"
        return finish(best, "feasible" if best_from_solver else "fallback", reason, len(running))
