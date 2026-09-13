"""Integer packing constraints adapted from the user's root ``test_code.py``.

Every worker owns its Z3 context. No Z3 expressions cross process boundaries.
Full support covers the union of coplanar supporting faces, not a single item.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from fractions import Fraction

import z3

from app.domain.models import (
    BoxType,
    Dimensions,
    ItemInstance,
    PackedBox,
    PackingRequest,
    PackingResult,
    Placement,
    Position,
)
from app.packing.diagnostics import build_issues
from app.packing.engine import _metrics
from app.packing.orientations import unique_orientations
from app.packing.strategies import expand_items, volume
from app.packing.validation import validate_solution


@dataclass(slots=True)
class _Model:
    optimizer: z3.Optimize
    items: tuple[ItemInstance, ...]
    boxes: tuple[BoxType, ...]
    box: list
    x: list
    y: list
    z: list
    dx: list
    dy: list
    dz: list
    objectives: list


def box_slots(request: PackingRequest) -> tuple[BoxType, ...]:
    """Only compatible cartons are useful; at most N copies of each are needed."""
    items = expand_items(request)
    slots = []
    for box in sorted(request.boxes, key=lambda value: value.id):
        if any(
            item.weight <= box.max_weight
            and any(
                size.length <= box.length and size.width <= box.width and size.height <= box.height
                for _, size in unique_orientations(
                    Dimensions(item.length, item.width, item.height), item.allow_rotation
                )
            )
            for item in items
        ):
            slots.extend([box] * min(box.available_count, len(items)))
    return tuple(slots)


def _full_support(model: _Model) -> None:
    """Check every potential uncovered cell's lower-left corner symbolically.

    A supporting face can introduce an uncovered cell only at its right/back
    edge or at the supported item's own left/front edge. Thus O(n^2) candidate
    points per item suffice, independently of box dimensions in millimetres.
    """
    opt, box, x, y, z = model.optimizer, model.box, model.x, model.y, model.z
    X = [x[i] + model.dx[i] for i in range(len(box))]
    Y = [y[i] + model.dy[i] for i in range(len(box))]
    Z = [z[i] + model.dz[i] for i in range(len(box))]
    for i in range(len(box)):
        others = [j for j in range(len(box)) if j != i]
        if not others:
            opt.add(z3.Implies(box[i] >= 0, z[i] == 0))
            continue
        touching = [
            z3.And(box[i] >= 0, box[j] >= 0, box[i] == box[j], Z[j] == z[i]) for j in others
        ]
        xs, ys = [x[i]] + [X[j] for j in others], [y[i]] + [Y[j] for j in others]
        active = [z3.BoolVal(True, ctx=opt.ctx)] + touching
        inside_x = [z3.And(x[i] <= p, p < X[i]) for p in xs]
        inside_y = [z3.And(y[i] <= p, p < Y[i]) for p in ys]
        covered_x = [[z3.And(x[j] <= p, p < X[j]) for j in others] for p in xs]
        covered_y = [[z3.And(y[j] <= p, p < Y[j]) for j in others] for p in ys]
        for a in range(len(xs)):
            for b in range(len(ys)):
                covered = z3.Or(
                    *[
                        z3.And(touching[k], covered_x[a][k], covered_y[b][k])
                        for k in range(len(others))
                    ]
                )
                opt.add(
                    z3.Implies(
                        z3.And(
                            box[i] >= 0, z[i] > 0, active[a], active[b], inside_x[a], inside_y[b]
                        ),
                        covered,
                    )
                )


def _build_model(
    request: PackingRequest,
    slots: tuple[BoxType, ...],
    ctx: z3.Context,
    variant: int = 0,
    incumbent: PackingResult | None = None,
) -> _Model:
    items = expand_items(request)
    opt = z3.Optimize(ctx=ctx)
    opt.set(priority="lex")
    count = len(items)
    variables = [
        [z3.Int(f"v{variant}_{name}_{i}", ctx) for i in range(count)]
        for name in ("box", "x", "y", "z", "dx", "dy", "dz")
    ]
    model = _Model(opt, items, slots, *variables, [])
    box, x, y, z, dx, dy, dz = variables
    used = [z3.Bool(f"used_{j}", ctx) for j in range(len(slots))]

    # Different variable/assertion orders give independent solver search paths.
    indices = list(range(count))
    if variant % 2:
        indices.reverse()
    for i in indices:
        item = items[i]
        rotations = unique_orientations(
            Dimensions(item.length, item.width, item.height), item.allow_rotation
        )
        if variant % 2:
            rotations = tuple(reversed(rotations))
        opt.add(x[i] >= 0, y[i] >= 0, z[i] >= 0)
        opt.add(
            z3.Or(
                *[
                    z3.And(dx[i] == size.length, dy[i] == size.width, dz[i] == size.height)
                    for _, size in rotations
                ]
            )
        )
        candidates = [box[i] == -1]
        for j, carton in enumerate(slots):
            if item.weight <= carton.max_weight and any(
                size.length <= carton.length
                and size.width <= carton.width
                and size.height <= carton.height
                for _, size in rotations
            ):
                candidates.append(box[i] == j)
                opt.add(
                    z3.Implies(
                        box[i] == j,
                        z3.And(
                            x[i] + dx[i] <= carton.length,
                            y[i] + dy[i] <= carton.width,
                            z[i] + dz[i] <= carton.height,
                        ),
                    )
                )
        opt.add(z3.Or(*candidates))
        opt.add(z3.Implies(box[i] == -1, z3.And(x[i] == 0, y[i] == 0, z[i] == 0)))
        # Identical units are interchangeable, so packed units form an ID prefix.
        if i and items[i - 1].product_id == item.product_id:
            opt.add(z3.Implies(box[i] >= 0, z3.And(box[i - 1] >= 0, box[i - 1] <= box[i])))

    for j, carton in enumerate(slots):
        assigned = [box[i] == j for i in range(count)]
        opt.add(used[j] == z3.Or(*assigned))
        opt.add(
            z3.Sum(*[z3.If(assigned[i], items[i].weight, 0) for i in range(count)])
            <= carton.max_weight
        )
        opt.add(
            z3.Sum(*[z3.If(assigned[i], volume(items[i]), 0) for i in range(count)])
            <= volume(carton)
        )
        if j and slots[j - 1].id == carton.id:
            opt.add(z3.Implies(used[j], used[j - 1]))

    for i in range(count):
        for j in range(i):
            opt.add(
                z3.Or(
                    box[i] < 0,
                    box[j] < 0,
                    box[i] != box[j],
                    x[i] + dx[i] <= x[j],
                    x[j] + dx[j] <= x[i],
                    y[i] + dy[i] <= y[j],
                    y[j] + dy[j] <= y[i],
                    z[i] + dz[i] <= z[j],
                    z[j] + dz[j] <= z[i],
                )
            )
    _full_support(model)

    packed_count = z3.Sum(*[z3.If(b >= 0, 1, 0) for b in box])
    packed_volume = z3.Sum(*[z3.If(box[i] >= 0, volume(items[i]), 0) for i in range(count)])
    used_count = z3.Sum(*[z3.If(value, 1, 0) for value in used])
    box_volume = z3.Sum(*[z3.If(used[j], volume(slots[j]), 0) for j in range(len(slots))])
    if incumbent is not None:
        # Safe lexicographic bound: a validated full-support plan already exists.
        metrics = incumbent.metrics
        opt.add(
            z3.Or(
                packed_count > metrics.packed_items,
                z3.And(packed_count == metrics.packed_items, packed_volume > metrics.used_volume),
                z3.And(
                    packed_count == metrics.packed_items,
                    packed_volume == metrics.used_volume,
                    box_volume < metrics.total_box_volume,
                ),
                z3.And(
                    packed_count == metrics.packed_items,
                    packed_volume == metrics.used_volume,
                    box_volume == metrics.total_box_volume,
                    used_count <= metrics.boxes_used,
                ),
            )
        )
    model.objectives = [
        opt.maximize(packed_count),
        opt.maximize(packed_volume),
        opt.minimize(box_volume),
        opt.minimize(used_count),
    ]
    return model


def _extract(request: PackingRequest, problem: _Model, values: z3.ModelRef) -> PackingResult:
    def integer(expression) -> int:
        return values.eval(expression, model_completion=True).as_long()

    groups: dict[int, list[Placement]] = {}
    for i, item in enumerate(problem.items):
        slot = integer(problem.box[i])
        if slot < 0:
            continue
        if slot >= len(problem.boxes):
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
        carton = problem.boxes[slot]
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
    slots: tuple[BoxType, ...],
    incumbent: PackingResult,
    variant: int,
    emit: Callable[[str, PackingResult | None], None],
) -> None:
    """Run inside a dedicated process, reporting only validated plain dataclasses."""
    # Global Z3 settings are isolated by the owning process, never shared between
    # simultaneous requests. Each portfolio member gets a distinct fixed seed.
    z3.set_param("smt.random_seed", variant + 1)
    ctx = z3.Context()
    problem = _build_model(request, slots, ctx, variant, incumbent)

    def on_model(model: z3.ModelRef) -> None:
        # Optimize can report intermediate models while proving optimality.
        # Never serialize a model that fails the independent geometry validator.
        try:
            candidate = _extract(request, problem, model)
        except (ValueError, z3.Z3Exception, StopIteration):
            return
        emit("feasible", candidate)

    problem.optimizer.set_on_model(on_model)
    status = problem.optimizer.check()
    if status == z3.sat:
        result = _extract(request, problem, problem.optimizer.model())
        proved = all(objective.lower().eq(objective.upper()) for objective in problem.objectives)
        emit("optimal" if proved else "solver_error", result)
    elif status == z3.unknown:
        # ``unknown`` means neither optimal nor impossible. The callback may
        # already have sent a feasible incumbent; otherwise the parent has one.
        emit("solver_error", None)
    else:
        # The validated incumbent makes this model satisfiable. UNSAT therefore
        # indicates a modelling/solver error, never proof of packing impossibility.
        emit("solver_error", None)
