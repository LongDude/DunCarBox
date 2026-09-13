"""Compact exact packing model, symmetry representatives and incumbent bounds."""

from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction

import z3

from app.domain.models import BoxType, Dimensions, ItemInstance, PackingRequest, PackingResult
from app.packing.orientations import unique_orientations
from app.packing.scoring import packing_objective
from app.packing.strategies import expand_items, volume
from app.packing.z3_support import SupportPoint

Score = tuple[Fraction, int, int, int]


def objective(result: PackingResult) -> Score:
    return packing_objective(result.metrics)


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
    carton_type: list
    scores: list
    objectives: list = field(default_factory=list)
    support_points: set[SupportPoint] = field(default_factory=set)
    ratio: Fraction = Fraction(0)
    objective_scores: list = field(default_factory=list)


def compatible_box_types(request: PackingRequest) -> tuple[BoxType, ...]:
    """Keep types once, without expanding stock into dedicated physical slots."""
    rotations = [
        (
            item.weight,
            unique_orientations(
                Dimensions(item.length, item.width, item.height), item.allow_rotation
            ),
        )
        for item in request.products
    ]
    return tuple(
        box
        for box in sorted(request.boxes, key=lambda value: value.id)
        if box.available_count > 0
        and any(
            weight <= box.max_weight
            and any(
                size.length <= box.length and size.width <= box.width and size.height <= box.height
                for _, size in orientations
            )
            for weight, orientations in rotations
        )
    )


def _sum(terms, ctx):
    terms = list(terms)
    return z3.Sum(*terms) if terms else z3.IntVal(0, ctx)


def _lex_le(left, right):
    result = left[-1] <= right[-1]
    for a, b in reversed(list(zip(left[:-1], right[:-1], strict=True))):
        result = z3.Or(a < b, z3.And(a == b, result))
    return result


def add_bound(model: _Model, score: Score) -> None:
    """Inclusive lexicographic bound: a verified feasible witness remains."""
    opt, ctx = model.optimizer, model.optimizer.ctx
    ratio = -score[0]
    gain = -model.scores[1] * ratio.denominator - model.scores[2] * ratio.numerator
    opt.add(_lex_le((-gain, model.scores[0], model.scores[1], model.scores[3]), (0, *score[1:])))
    if ratio > 0:
        # Even packing the entire order cannot improve this fill above this
        # denominator. This bound also remains safe for partial incumbents.
        max_volume = sum(map(volume, model.items)) * ratio.denominator // ratio.numerator
        opt.add(model.scores[2] <= max_volume)
        for t, carton in enumerate(model.boxes):
            opt.add(
                _sum((z3.If(kind == t, 1, 0) for kind in model.carton_type), ctx)
                <= min(carton.available_count, max_volume // volume(carton))
            )
    if ratio == 1 and -score[1] == len(model.items):
        # Only 100% fill AND a full order prove the first three objectives.
        # A full but loosely packed incumbent must still allow leaving items out.
        opt.add(*[slot >= 0 for slot in model.box])
        opt.add(model.scores[2] == -score[2])


def set_objectives(model: _Model, ratio: Fraction) -> None:
    """One exact Dinkelbach step: maximize q*used_volume - p*box_volume.

    A zero optimum proves the best ratio p/q; positive gain requires another
    step. All objectives remain bounded integer linear arithmetic.
    """
    previous = model.optimizer
    opt = z3.Optimize(ctx=previous.ctx)
    opt.set(priority="lex")
    opt.add(*previous.assertions())
    model.optimizer = opt
    model.ratio = ratio
    gain = -model.scores[1] * ratio.denominator - model.scores[2] * ratio.numerator
    # Since V >= U and U <= order_volume, gain <= (q-p)*order_volume.
    # At 100% fill this explicitly proves that the primary gain cannot be positive.
    opt.add(-gain >= -(ratio.denominator - ratio.numerator) * sum(map(volume, model.items)))
    model.objective_scores = [-gain, model.scores[0], model.scores[1], model.scores[3]]
    model.objectives = [opt.minimize(score) for score in model.objective_scores]


def _seed(model: _Model, incumbent: PackingResult) -> None:
    """Hint a canonical relabelling of the incumbent; never fix its geometry."""
    item_index = {item.id: i for i, item in enumerate(model.items)}
    # More copies of the earliest product sorts first among boxes sharing it.
    # Relabel identical units afterward to satisfy both first-use slot numbering
    # and increasing (slot,z,x,y) unit order.
    products = sorted({item.product_id for item in model.items})
    cartons = sorted(
        incumbent.packed_boxes,
        key=lambda carton: (
            tuple(-sum(p.product_id == product for p in carton.placements) for product in products),
            carton.box_type_id,
            carton.id,
        ),
    )
    by_product = defaultdict(list)
    type_index = {carton.id: i for i, carton in enumerate(model.boxes)}
    for slot, carton in enumerate(cartons):
        model.optimizer.set_initial_value(model.carton_type[slot], type_index[carton.box_type_id])
        for p in carton.placements:
            by_product[p.product_id].append((slot, p.position.z, p.position.x, p.position.y, p))
    for entries in by_product.values():
        entries.sort(key=lambda entry: entry[:4])
    offsets = defaultdict(int)
    for item in model.items:
        i = item_index[item.id]
        entries = by_product[item.product_id]
        offset = offsets[item.product_id]
        offsets[item.product_id] += 1
        if offset >= len(entries):
            model.optimizer.set_initial_value(model.box[i], -1)
            continue
        slot, _, _, _, placement = entries[offset]
        for variable, value in zip(
            (
                model.box[i],
                model.x[i],
                model.y[i],
                model.z[i],
                model.dx[i],
                model.dy[i],
                model.dz[i],
            ),
            (
                slot,
                placement.position.x,
                placement.position.y,
                placement.position.z,
                placement.dimensions.length,
                placement.dimensions.width,
                placement.dimensions.height,
            ),
            strict=True,
        ):
            model.optimizer.set_initial_value(variable, value)
    for slot in range(len(cartons), len(model.carton_type)):
        model.optimizer.set_initial_value(model.carton_type[slot], -1)


def _build_model(
    request: PackingRequest,
    types: tuple[BoxType, ...],
    ctx: z3.Context,
    variant: int = 0,
    incumbent: PackingResult | None = None,
    *,
    symmetry: bool = True,
) -> _Model:
    items = expand_items(request)
    count = len(items)
    full = (
        incumbent is not None
        and incumbent.metrics.packed_items == count
        and incumbent.metrics.used_volume == incumbent.metrics.total_box_volume
    )
    ratio = -objective(incumbent)[0] if incumbent is not None else Fraction(0)
    max_volume = (
        sum(map(volume, items)) * ratio.denominator // ratio.numerator if ratio > 0 else None
    )
    if max_volume is not None:
        types = tuple(box for box in types if volume(box) <= max_volume)
    capacity = min(count, sum(box.available_count for box in types))
    if max_volume is not None and types:
        capacity = min(capacity, max_volume // min(map(volume, types)))
    opt = z3.Optimize(ctx=ctx)
    opt.set(priority="lex")
    variables = [
        [z3.Int(f"v{variant}_{name}_{i}", ctx) for i in range(count)]
        for name in ("box", "x", "y", "z", "dx", "dy", "dz")
    ]
    box, x, y, z, dx, dy, dz = variables
    kinds = [z3.Int(f"type_{j}", ctx) for j in range(capacity)]
    # Each slot chooses its dimensions, capacity and volume from the type table.
    attributes = [
        [z3.Int(f"carton_{name}_{j}", ctx) for j in range(capacity)]
        for name in ("length", "width", "height", "weight", "volume")
    ]
    lengths, widths, heights, weights, volumes = attributes
    model = _Model(opt, items, types, *variables, kinds, [])
    rotations_by_product = {
        item.product_id: unique_orientations(
            Dimensions(item.length, item.width, item.height), item.allow_rotation
        )
        for item in items
    }
    fitting = {
        (pid, t): tuple(
            size
            for _, size in rotations
            if size.length <= carton.length
            and size.width <= carton.width
            and size.height <= carton.height
        )
        for pid, rotations in rotations_by_product.items()
        for t, carton in enumerate(types)
    }
    pairs = {}

    def pair_fits(item, other):
        key = tuple(sorted((item.product_id, other.product_id)))
        if key not in pairs:
            pairs[key] = any(
                item.weight + other.weight <= carton.max_weight
                and volume(item) + volume(other) <= volume(carton)
                and any(
                    a.length + b.length <= carton.length
                    or a.width + b.width <= carton.width
                    or a.height + b.height <= carton.height
                    for a in fitting[item.product_id, t]
                    for b in fitting[other.product_id, t]
                )
                for t, carton in enumerate(types)
            )
        return pairs[key]

    can_share = [
        [i != j and pair_fits(item, other) for j, other in enumerate(items)]
        for i, item in enumerate(items)
    ]
    for j, kind in enumerate(kinds):
        choices = [z3.And(kind == -1, *[attr[j] == 0 for attr in attributes])]
        for t, carton in enumerate(types):
            choices.append(
                z3.And(
                    kind == t,
                    *[
                        attr[j] == value
                        for attr, value in zip(
                            attributes,
                            (
                                carton.length,
                                carton.width,
                                carton.height,
                                carton.max_weight,
                                volume(carton),
                            ),
                            strict=True,
                        )
                    ],
                )
            )
        opt.add(z3.Or(*choices))
        assigned = [b == j for b in box]
        opt.add((kind >= 0) == z3.Or(*assigned))
        opt.add(
            _sum((z3.If(assigned[i], items[i].weight, 0) for i in range(count)), ctx) <= weights[j]
        )
        opt.add(
            _sum((z3.If(assigned[i], volume(items[i]), 0) for i in range(count)), ctx) <= volumes[j]
        )
    for t, carton in enumerate(types):
        opt.add(_sum((z3.If(kind == t, 1, 0) for kind in kinds), ctx) <= carton.available_count)

    indices = range(count) if variant % 2 == 0 else reversed(range(count))
    for i in indices:
        item = items[i]
        rotations = rotations_by_product[item.product_id]
        if variant % 2:
            rotations = tuple(reversed(rotations))
        opt.add(box[i] >= -1, box[i] < capacity, x[i] >= 0, y[i] >= 0, z[i] >= 0)
        opt.add(
            z3.Or(
                *[
                    z3.And(dx[i] == size.length, dy[i] == size.width, dz[i] == size.height)
                    for _, size in rotations
                ]
            )
        )
        opt.add(z3.Implies(box[i] == -1, z3.And(x[i] == 0, y[i] == 0, z[i] == 0)))
        for j in range(capacity):
            compatible = [
                t
                for t, carton in enumerate(types)
                if fitting[item.product_id, t] and item.weight <= carton.max_weight
            ]
            if len(compatible) < len(types):
                opt.add(z3.Implies(box[i] == j, z3.Or(*[kinds[j] == t for t in compatible])))
            opt.add(
                z3.Implies(
                    box[i] == j,
                    z3.And(
                        x[i] + dx[i] <= lengths[j],
                        y[i] + dy[i] <= widths[j],
                        z[i] + dz[i] <= heights[j],
                        item.weight <= weights[j],
                    ),
                )
            )
        if symmetry and i and items[i - 1].product_id == item.product_id:
            opt.add(
                z3.Implies(
                    box[i] >= 0,
                    z3.And(
                        box[i - 1] >= 0,
                        box[i - 1] < box[i]
                        if not can_share[i][i - 1]
                        else _lex_le(
                            (box[i - 1], z[i - 1], x[i - 1], y[i - 1]), (box[i], z[i], x[i], y[i])
                        ),
                    ),
                )
            )
        for j in range(i):
            if not can_share[i][j]:
                # An aggregate capacity contradiction is cheaper to expose
                # directly than to rediscover through six geometric branches.
                opt.add(z3.Or(box[i] < 0, box[j] < 0, box[i] != box[j]))
                continue
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
        # Necessary O(N²) support condition prevents floating items. Exact union
        # coverage is separated lazily; a single supporting face need not suffice.
        touching = [
            z3.And(
                box[j] == box[i],
                z[j] + dz[j] == z[i],
                x[j] < x[i] + dx[i],
                x[i] < x[j] + dx[j],
                y[j] < y[i] + dy[i],
                y[i] < y[j] + dy[j],
            )
            for j in range(count)
            if can_share[i][j]
        ]
        opt.add(z3.Or(box[i] < 0, z[i] == 0, *touching))

    if symmetry:
        previous = z3.IntVal(-1, ctx)
        for i in range(count):
            # A box is numbered when first encountered in item order. This
            # removes all slot permutations, including slots of different types.
            prefix = z3.Int(f"prefix_{i}", ctx)
            opt.add(box[i] <= previous + 1, prefix == z3.If(box[i] > previous, box[i], previous))
            previous = prefix
        if full and not any(any(row) for row in can_share):
            # No pair can share, and every item must be packed. First-use
            # numbering therefore fixes each slot outright. Make this explicit
            # instead of asking SMT to prove a large pigeonhole consequence.
            opt.add(*[box[i] == i for i in range(count)])
    model.scores = [
        -_sum((z3.If(b >= 0, 1, 0) for b in box), ctx),
        -_sum((z3.If(box[i] >= 0, volume(item), 0) for i, item in enumerate(items)), ctx),
        _sum(volumes, ctx),
        _sum((z3.If(kind >= 0, 1, 0) for kind in kinds), ctx),
    ]
    opt.add(model.scores[2] >= -model.scores[1])
    if types:
        packed_weight = _sum(
            (z3.If(box[i] >= 0, item.weight, 0) for i, item in enumerate(items)), ctx
        )
        opt.add(model.scores[3] * max(map(volume, types)) >= -model.scores[1])
        opt.add(model.scores[3] * max(carton.max_weight for carton in types) >= packed_weight)
        density = min(
            (Fraction(volume(carton), carton.max_weight) for carton in types if carton.max_weight),
            default=Fraction(0),
        )
        opt.add(model.scores[2] * density.denominator >= packed_weight * density.numerator)
    if incumbent is not None:
        add_bound(model, objective(incumbent))
    set_objectives(model, -objective(incumbent)[0] if incumbent is not None else Fraction(0))
    if incumbent is not None:
        _seed(model, incumbent)
    return model
