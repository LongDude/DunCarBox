"""Exact, finite separation of full-support constraints.

Only numeric geometry is swept while inspecting a candidate. A returned witness
names symbolic edges, so its cut also excludes other layouts with the same gap.
No valid fully supported layout is excluded, regardless of its coordinates.
"""

from typing import TYPE_CHECKING

import z3

if TYPE_CHECKING:
    from app.packing.z3_constraints import _Model

SupportPoint = tuple[int, int, int]


def support_violations(model: "_Model", values: z3.ModelRef) -> set[SupportPoint]:
    """Return one uncovered point per unsupported item, using an exact x sweep."""
    rows = [
        tuple(
            values.eval(v[i], model_completion=True).as_long()
            for v in (model.box, model.x, model.y, model.z, model.dx, model.dy, model.dz)
        )
        for i in range(len(model.items))
    ]
    violations = set()
    for i, (slot, x, y, z, dx, dy, _) in enumerate(rows):
        if slot < 0 or z == 0:
            continue
        supports = [
            (j, sx, sx + sdx, sy, sy + sdy)
            for j, (other_slot, sx, sy, sz, sdx, sdy, sdz) in enumerate(rows)
            if j != i
            and other_slot == slot
            and sz + sdz == z
            and sx < x + dx
            and sx + sdx > x
            and sy < y + dy
            and sy + sdy > y
        ]
        # A newly uncovered x strip starts at the item's left edge or at a
        # support's right edge. Within it a y gap starts at y or a support's back.
        edges = [(x, i)] + [(right, j) for j, _, right, _, _ in supports if x <= right < x + dx]
        for point_x, a in edges:
            intervals = sorted(
                (front, back, j)
                for j, left, right, front, back in supports
                if left <= point_x < right
            )
            end, b = y, i
            for front, back, j in intervals:
                if front > end:
                    break
                if back > end:
                    end, b = back, j
                if end >= y + dy:
                    break
            if end < y + dy:
                violations.add((i, a, b))
                break
    return violations


def support_constraint(model: "_Model", point: SupportPoint) -> z3.BoolRef:
    i, a, b = point
    box, x, y, z = model.box, model.x, model.y, model.z
    p = x[i] if a == i else x[a] + model.dx[a]
    q = y[i] if b == i else y[b] + model.dy[b]
    covered = [
        z3.And(
            box[j] == box[i],
            z[j] + model.dz[j] == z[i],
            x[j] <= p,
            p < x[j] + model.dx[j],
            y[j] <= q,
            q < y[j] + model.dy[j],
        )
        for j in range(len(box))
        if j != i
    ]
    return z3.Implies(
        z3.And(
            box[i] >= 0,
            z[i] > 0,
            x[i] <= p,
            p < x[i] + model.dx[i],
            y[i] <= q,
            q < y[i] + model.dy[i],
        ),
        z3.Or(*covered) if covered else z3.BoolVal(False, ctx=model.optimizer.ctx),
    )


def add_support_cuts(model: "_Model", points: set[SupportPoint]) -> int:
    fresh = points - model.support_points
    for point in sorted(fresh):
        model.optimizer.add(support_constraint(model, point))
    model.support_points.update(fresh)
    return len(fresh)


def full_support(model: "_Model") -> None:
    """Eager equivalent for small-model differential tests; not used by workers."""
    add_support_cuts(
        model,
        {
            (i, a, b)
            for i in range(len(model.items))
            for a in range(len(model.items))
            for b in range(len(model.items))
        },
    )
