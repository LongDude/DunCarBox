"""Bounded Z3 portfolio with a validated full-support heuristic incumbent.

The solver budget covers process startup, model construction and optimization.
The inexpensive bounded heuristic runs first; validation and process cleanup add
small overhead. Worker limits apply across concurrent requests in this API process.
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
from app.packing.engine import DeterministicPackingEngine
from app.packing.options import EngineOptions
from app.packing.scoring import solution_signature
from app.packing.validation import validate_solution

MAX_MODEL_ITEMS = 16
MAX_MODEL_BOX_SLOTS = 64


def _available_cpus() -> int:
    process_count = getattr(os, "process_cpu_count", None)
    if process_count is not None:
        return process_count() or 1
    affinity = getattr(os, "sched_getaffinity", None)
    if affinity is not None:
        return len(affinity(0)) or 1
    return os.cpu_count() or 1


MAX_SOLVER_WORKERS = min(8, _available_cpus())
_WORKER_SLOTS = BoundedSemaphore(MAX_SOLVER_WORKERS)
_FULL_SUPPORT = Fraction(1)
_LOGGER = logging.getLogger(__name__)


def _objective(result: PackingResult) -> tuple[int, int, int, int]:
    metrics = result.metrics
    return (
        -metrics.packed_items,
        -metrics.used_volume,
        metrics.boxes_used,
        metrics.total_box_volume,
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

    def pack(self, request: PackingRequest) -> PackingResult:
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
            )
        ).pack(baseline_request)
        validate_solution(request, baseline, _FULL_SUPPORT)
        timeout_ms = request.options.solver_timeout_ms
        workers_requested = min(max(1, request.options.solver_workers), MAX_SOLVER_WORKERS)

        def finish(
            result: PackingResult,
            status: Literal["optimal", "feasible", "fallback"],
            reason: Literal["completed", "time_limit", "size_limit", "solver_error"],
            workers: int,
        ) -> PackingResult:
            completed = replace(
                result,
                algorithm_version=self.version,
                alternatives=(),
                optimization=OptimizationInfo(status, reason, workers, timeout_ms, 1.0),
            )
            validate_solution(request, completed, _FULL_SUPPORT)
            return completed

        if baseline.metrics.total_items > MAX_MODEL_ITEMS:
            return finish(baseline, "fallback", "size_limit", 0)

        # This import remains lazy so heuristic-only requests do not load Z3.
        from app.packing.z3_model import box_slots

        slots = box_slots(request)
        if not slots or not baseline.metrics.total_items:
            return finish(baseline, "optimal", "completed", 0)
        if len(slots) > MAX_MODEL_BOX_SLOTS:
            return finish(baseline, "fallback", "size_limit", 0)

        context = multiprocessing.get_context("spawn")
        deadline = monotonic() + max(1, timeout_ms) / 1000
        running: list[tuple[multiprocessing.Process, Connection]] = []
        acquired = 0
        best = baseline
        best_from_solver = False
        reason: Literal["time_limit", "solver_error"] = "time_limit"
        proof: tuple[int, int, int, int] | None = None
        try:
            for variant in range(workers_requested):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                granted = (
                    _WORKER_SLOTS.acquire(timeout=remaining)
                    if not running
                    else _WORKER_SLOTS.acquire(blocking=False)
                )
                if not granted:
                    break
                acquired += 1
                receiver, sender = context.Pipe(duplex=False)
                process = context.Process(
                    target=_worker,
                    args=(sender, request, slots, baseline, deadline, variant),
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
            while active and monotonic() < deadline and proof is None:
                ready = wait(active, timeout=min(0.05, max(0, deadline - monotonic())))
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
            for process, _ in running:
                process.join(timeout=0.5)
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
        if proof is not None:
            reason = "solver_error"
        return finish(best, "feasible" if best_from_solver else "fallback", reason, len(running))
