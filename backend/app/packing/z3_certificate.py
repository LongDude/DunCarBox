"""Prove a full incumbent optimal with a small, necessary-condition relaxation.

No coordinates or individual unit permutations occur here. Every real packing
maps to these aggregate counts, so UNSAT for a strictly better score certifies
the independently validated incumbent. SAT/UNKNOWN simply leave the exact
geometric search to the existing worker.

Pair bounds are conservative scales (Fekete/Schepers, arXiv:cs/0402044).
Their one-dimensional inequalities are derived with exact rational arithmetic.
"""

import logging
from fractions import Fraction
from itertools import permutations
from math import lcm, prod
from time import monotonic

import z3

from app.domain.models import BoxType, Dimensions, PackingRequest, PackingResult, Product
from app.packing.orientations import unique_orientations
from app.packing.strategies import volume
from app.packing.validation import validate_solution
from app.packing.z3_constraints import compatible_box_types

_LOGGER = logging.getLogger(__name__)


def _axis_scale(capacity: int, a: int, b: int, count_a: int, count_b: int):
    """Weights satisfying p*alpha + q*beta <= 1 whenever p*a+q*b <= C.

    p and q cannot exceed the order quantities. Fix alpha at its valid maximum
    and lift beta against every possible p. Other products have weight zero.
    A work cap can weaken the bound, but never remove a feasible packing.
    """
    limit = min(capacity // a, count_a)
    if not limit or b > capacity or not count_b:
        return Fraction(0), Fraction(0)
    alpha = Fraction(1, limit)
    if limit > 256:
        return alpha, Fraction(0)
    beta = min(
        (1 - p * alpha) / q
        for p in range(limit + 1)
        if (q := min((capacity - p * a) // b, count_b)) > 0
    )
    return alpha, beta


def pair_scale(box: BoxType, a: Product, b: Product) -> tuple[int, int, int]:
    """Return integer coefficients A,B,C for A*count(a)+B*count(b) <= C.

    Fixed orientation is essential: rotating units cannot use these axis sizes.
    Each axis scale preserves every feasible chain of disjoint intervals.
    Rescheduling those chains into a unit interval preserves all separating
    axes, so the transformed cuboids fit a unit cube. Their volumes sum to <=1.
    """
    if a.allow_rotation or b.allow_rotation:
        raise ValueError("Pair scales require fixed orientations")
    scales = [
        _axis_scale(getattr(box, axis), getattr(a, axis), getattr(b, axis), a.quantity, b.quantity)
        for axis in ("length", "width", "height")
    ]
    alpha = prod(value[0] for value in scales)
    beta = prod(value[1] for value in scales)
    denominator = lcm(alpha.denominator, beta.denominator)
    return int(alpha * denominator), int(beta * denominator), denominator


def _capacity(box: BoxType, product: Product) -> int:
    rotations = unique_orientations(
        Dimensions(product.length, product.width, product.height), product.allow_rotation
    )
    if product.weight > box.max_weight or not any(
        size.length <= box.length and size.width <= box.width and size.height <= box.height
        for _, size in rotations
    ):
        return 0
    count = min(product.quantity, volume(box) // volume(product))
    if product.weight:
        count = min(count, box.max_weight // product.weight)
    if not product.allow_rotation:
        # For identical fixed cuboids the product of per-axis floor capacities
        # is an upper bound even in an irregular, interleaved arrangement.
        count = min(
            count,
            prod(
                getattr(box, axis) // getattr(product, axis)
                for axis in ("length", "width", "height")
            ),
        )
    return count


def _better_plan_solver(request: PackingRequest, incumbent: PackingResult) -> z3.Solver:
    ctx = z3.Context()
    solver = z3.Solver(ctx=ctx)
    metrics = incumbent.metrics
    products = tuple(sorted(request.products, key=lambda product: product.id))
    boxes = tuple(
        box for box in compatible_box_types(request) if volume(box) <= metrics.total_box_volume
    )
    counts = [z3.Int(f"cartons_{t}", ctx) for t in range(len(boxes))]
    assigned = [
        [z3.Int(f"units_{t}_{p}", ctx) for p in range(len(products))] for t in range(len(boxes))
    ]

    def total(terms):
        return z3.Sum([z3.IntVal(0, ctx), *terms])

    for p, product in enumerate(products):
        solver.add(total(row[p] for row in assigned) == product.quantity)
    for t, box in enumerate(boxes):
        count, row = counts[t], assigned[t]
        solver.add(
            count >= 0,
            count
            <= min(
                box.available_count, metrics.total_items, metrics.total_box_volume // volume(box)
            ),
        )
        solver.add(total(row) >= count)
        capacities = [_capacity(box, product) for product in products]
        for p, product in enumerate(products):
            solver.add(row[p] >= 0, row[p] <= product.quantity, row[p] <= capacities[p] * count)
        solver.add(
            total(row[p] * volume(product) for p, product in enumerate(products))
            <= volume(box) * count
        )
        solver.add(
            total(row[p] * product.weight for p, product in enumerate(products))
            <= box.max_weight * count
        )
        fixed = [
            p
            for p, product in enumerate(products)
            if not product.allow_rotation and capacities[p] > 0
        ]
        for a, b in permutations(fixed, 2):
            alpha, beta, denominator = pair_scale(box, products[a], products[b])
            solver.add(alpha * row[a] + beta * row[b] <= denominator * count)
    box_volume = total(count * volume(box) for count, box in zip(counts, boxes, strict=True))
    solver.add(
        z3.Or(
            box_volume < metrics.total_box_volume,
            z3.And(box_volume == metrics.total_box_volume, total(counts) < metrics.boxes_used),
        )
    )
    return solver


def certify_incumbent(request: PackingRequest, incumbent: PackingResult) -> bool:
    """Only an UNSAT proof is a certificate; resource exhaustion falls through."""
    if incumbent.metrics.packed_items != sum(product.quantity for product in request.products):
        return False
    # This is an optional proof accelerator. Large catalogues still use the full
    # model; no products or box types are silently dropped from a certificate.
    if len(request.products) > 12 or len(request.boxes) > 64:
        return False
    validate_solution(request, incumbent, Fraction(1))
    started = monotonic()
    solver = _better_plan_solver(request, incumbent)
    solver.set(rlimit=50_000)
    status = solver.check()
    _LOGGER.info("Z3 aggregate certificate: %s in %.3fs", status, monotonic() - started)
    return status == z3.unsat
