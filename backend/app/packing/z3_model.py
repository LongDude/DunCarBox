"""Exact lazy Z3 optimization; only independently validated plans leave a worker."""

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction
from time import monotonic

import z3

from app.domain.models import (
    BoxType,
    Dimensions,
    PackedBox,
    PackingRequest,
    PackingResult,
    Placement,
    Position,
)
from app.packing.diagnostics import build_issues
from app.packing.engine import _metrics
from app.packing.orientations import unique_orientations
from app.packing.strategies import volume
from app.packing.validation import validate_solution
from app.packing.z3_constraints import Score, _build_model, _Model, add_bound, objective
from app.packing.z3_support import add_support_cuts, support_violations

_LOGGER = logging.getLogger(__name__)


def _extract(request: PackingRequest, problem: _Model, values: z3.ModelRef) -> PackingResult:
    def integer(expression) -> int:
        return values.eval(expression, model_completion=True).as_long()

    groups: dict[int, list[Placement]] = {}
    for i, item in enumerate(problem.items):
        slot = integer(problem.box[i])
        if slot < 0:
            continue
        if slot >= len(problem.carton_type):
            raise ValueError("Solver returned an invalid box assignment")
        dimensions = Dimensions(
            integer(problem.dx[i]), integer(problem.dy[i]), integer(problem.dz[i])
        )
        orientation = next(
            code
            for code, size in unique_orientations(
                Dimensions(item.length, item.width, item.height), item.allow_rotation
            )
            if size == dimensions
        )
        groups.setdefault(slot, []).append(
            Placement(
                item.id,
                item.product_id,
                Position(integer(problem.x[i]), integer(problem.y[i]), integer(problem.z[i])),
                dimensions,
                orientation,
                0,
            )
        )
    boxes = []
    copies: Counter = Counter()
    by_id = {item.id: item for item in problem.items}
    for slot, placements in sorted(groups.items()):
        kind = integer(problem.carton_type[slot])
        if not 0 <= kind < len(problem.boxes):
            raise ValueError("Solver returned an invalid carton type")
        carton = problem.boxes[kind]
        copies[carton.id] += 1
        ordered = sorted(
            placements,
            key=lambda p: (
                p.position.z,
                p.position.x,
                p.position.y,
                p.product_id,
                by_id[p.item_instance_id].unit_index,
            ),
        )
        used_volume = sum(volume(p.dimensions) for p in ordered)
        boxes.append(
            PackedBox(
                f"{carton.id}:{copies[carton.id]}",
                carton.id,
                carton.name,
                carton.length,
                carton.width,
                carton.height,
                carton.max_weight,
                sum(by_id[p.item_instance_id].weight for p in ordered),
                used_volume,
                round(used_volume / volume(carton), 6),
                tuple(replace(p, step=step) for step, p in enumerate(ordered, 1)),
            )
        )
    packed = tuple(boxes)
    chosen = {p.item_instance_id for carton in packed for p in carton.placements}
    unpacked = tuple(item for item in problem.items if item.id not in chosen)
    issues = tuple(
        replace(
            issue,
            message=(
                "Для этой единицы не найдено размещение в текущем плане Z3 с соблюдением "
                "размеров, веса, остатков и полной опоры. Статус доказательства указан отдельно."
            ),
        )
        if issue.code == "NO_FEASIBLE_PLACEMENT"
        else issue
        for issue in build_issues(request, packed, unpacked)
    )
    result = PackingResult(
        "success" if not unpacked else "partial" if chosen else "impossible",
        _metrics(packed, len(problem.items)),
        packed,
        unpacked,
        issues,
        algorithm_version="z3-packing-v1",
    )
    validate_solution(request, result, Fraction(1))
    return result


def solve(
    request: PackingRequest,
    types: tuple[BoxType, ...],
    incumbent: PackingResult,
    variant: int,
    emit: Callable[[str, PackingResult | None], None],
    receive_bound: Callable[[], Score | None] | None = None,
) -> None:
    """Refine a relaxation until its proved optimum passes the exact validator.

    Model callbacks only inspect/copy values and request an interrupt. Assertions
    are added after check() returns; Z3 is never mutated reentrantly in a callback.
    An internal refinement interrupt is not a deadline and is not an error.
    """
    z3.set_param("smt.random_seed", variant + 1)
    ctx = z3.Context()
    started = monotonic()
    problem = _build_model(request, types, ctx, variant, incumbent)
    _LOGGER.info("Z3 worker %s model built in %.3fs", variant, monotonic() - started)
    best_score = objective(incumbent)
    applied_score = best_score
    pending_points = set()
    pending_score = None
    rounds = 0

    def read_bound() -> None:
        nonlocal pending_score
        score = receive_bound() if receive_bound is not None else None
        if score is not None and score < (pending_score or applied_score):
            pending_score = score

    def on_model(values: z3.ModelRef) -> None:
        nonlocal best_score
        try:
            violations = support_violations(problem, values)
            pending_points.update(violations - problem.support_points)
            if not violations:
                candidate = _extract(request, problem, values)
                score = objective(candidate)
                if score < best_score:
                    best_score = score
                    emit("feasible", candidate)
            read_bound()
            if pending_points or pending_score is not None:
                ctx.interrupt()
        except (ValueError, z3.Z3Exception, StopIteration):
            # Early Optimize callbacks may not describe a complete hard model.
            # The final model is checked again outside the callback.
            return

    try:
        problem.optimizer.set_on_model(on_model)
        while True:
            read_bound()
            next_score = min(best_score, pending_score or applied_score)
            if next_score < applied_score:
                applied_score = next_score
                best_score = min(best_score, applied_score)
                add_bound(problem, applied_score)
            pending_score = None
            rounds += 1
            status = problem.optimizer.check()
            if pending_points:
                add_support_cuts(problem, pending_points)
                pending_points.clear()
                continue
            if pending_score is not None:
                continue
            if status != z3.sat:
                # The inclusive bound has a verified full-support witness. UNSAT is
                # a model error; UNKNOWN without our own refinement is not a proof.
                emit("solver_error", None)
                return
            values = problem.optimizer.model()
            violations = support_violations(problem, values)
            if violations:
                if not add_support_cuts(problem, violations):
                    emit("solver_error", None)
                    return
                continue
            result = _extract(request, problem, values)
            proved = all(handle.lower().eq(handle.upper()) for handle in problem.objectives)
            _LOGGER.info(
                "Z3 worker %s finished in %.3fs, %s rounds, %s support cuts; %s",
                variant,
                monotonic() - started,
                rounds,
                len(problem.support_points),
                problem.optimizer.statistics(),
            )
            emit("optimal" if proved else "solver_error", result)
            return
    finally:
        # Z3's callback registry retains the closure. Release its model reference
        # so completed in-process solves do not retain entire solver contexts.
        problem = None
