"""Prove incumbent fill optimal with a small, necessary-condition relaxation.

No coordinates or individual unit permutations occur here. Every real packing
maps to these aggregate counts, so UNSAT for a strictly better score certifies
the independently validated incumbent. SAT/UNKNOWN simply leave the exact
geometric search to the existing worker.

Pair bounds are conservative scales (Fekete/Schepers, arXiv:cs/0402044).
Their one-dimensional inequalities are derived with exact rational arithmetic.
"""

import logging
from dataclasses import replace
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


def _fixed_pair_scale(box: BoxType, a: Product, b: Product) -> tuple[int, int, int]:
    """Return integer coefficients A,B,C for A*count(a)+B*count(b) <= C.

    Fixed orientation is essential: rotating units cannot use these axis sizes.
    Each axis scale preserves every feasible chain of disjoint intervals.
    Rescheduling those chains into a unit interval preserves all separating
    axes, so the transformed cuboids fit a unit cube. Their volumes sum to <=1.
    """
    scales = [
        _axis_scale(getattr(box, axis), getattr(a, axis), getattr(b, axis), a.quantity, b.quantity)
        for axis in ("length", "width", "height")
    ]
    alpha = prod(value[0] for value in scales)
    beta = prod(value[1] for value in scales)
    denominator = lcm(alpha.denominator, beta.denominator)
    return int(alpha * denominator), int(beta * denominator), denominator


def pair_scale(box: BoxType, a: Product, b: Product) -> tuple[int, int, int]:
    """Conservative product-level bound, valid for every allowed orientation.

    Shrink each axis to its minimum over rotations before applying fixed scales.
    The stronger orientation-specific cuts below retain the actual dimensions.
    """

    def shrink(product):
        sizes = unique_orientations(
            Dimensions(product.length, product.width, product.height), product.allow_rotation
        )
        return replace(
            product,
            **{
                axis: min(getattr(size, axis) for _, size in sizes)
                for axis in ("length", "width", "height")
            },
        )

    return _fixed_pair_scale(box, shrink(a), shrink(b))


def _fixed_capacity(box: BoxType, product: Product) -> int:
    return min(
        product.quantity,
        box.max_weight // product.weight if product.weight else product.quantity,
        prod(
            getattr(box, axis) // getattr(product, axis) for axis in ("length", "width", "height")
        ),
    )


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
    if len(rotations) == 1:
        # For identical fixed cuboids the product of per-axis floor capacities
        # is an upper bound even in an irregular, interleaved arrangement.
        count = min(
            count,
            prod(
                getattr(box, axis) // getattr(product, axis)
                for axis in ("length", "width", "height")
            ),
        )
    elif not product.allow_rotation:
        # Equal-height intervals split into floor(H/h) overlapping height bands.
        # Within each band, base rectangles are disjoint, including mixed yaw.
        count = min(
            count,
            (box.height // product.height)
            * (box.length * box.width // (product.length * product.width)),
        )
    return count


def _better_plan_solver(request: PackingRequest, incumbent: PackingResult) -> z3.Solver:
    ctx = z3.Context()
    solver = z3.Solver(ctx=ctx)
    metrics = incumbent.metrics
    products = tuple(sorted(request.products, key=lambda product: product.id))
    # Split by orientation: a pinwheel can mix LWH and WLH even when tilting is
    # forbidden. Fixed-axis bounds may only constrain these separate counts.
    variants = tuple(
        replace(product, length=size.length, width=size.width, height=size.height)
        for product in products
        for _, size in unique_orientations(
            Dimensions(product.length, product.width, product.height), product.allow_rotation
        )
    )
    boxes = compatible_box_types(request)
    counts = [z3.Int(f"cartons_{t}", ctx) for t in range(len(boxes))]
    assigned = [
        [z3.Int(f"units_{t}_{p}", ctx) for p in range(len(variants))] for t in range(len(boxes))
    ]

    def total(terms):
        return z3.Sum([z3.IntVal(0, ctx), *terms])

    for product in products:
        solver.add(
            total(
                row[p]
                for row in assigned
                for p, variant in enumerate(variants)
                if variant.id == product.id
            )
            <= product.quantity
        )
    for t, box in enumerate(boxes):
        count, row = counts[t], assigned[t]
        solver.add(
            count >= 0,
            count <= min(box.available_count, metrics.total_items),
        )
        solver.add(total(row) >= count)
        capacities = [_fixed_capacity(box, product) for product in variants]
        for p, product in enumerate(variants):
            solver.add(row[p] >= 0, row[p] <= product.quantity, row[p] <= capacities[p] * count)
        for product in products:
            solver.add(
                total(row[p] for p, variant in enumerate(variants) if variant.id == product.id)
                <= _capacity(box, product) * count
            )
        solver.add(
            total(row[p] * volume(product) for p, product in enumerate(variants))
            <= volume(box) * count
        )
        solver.add(
            total(row[p] * product.weight for p, product in enumerate(variants))
            <= box.max_weight * count
        )
        # Optional cuts must have bounded construction cost on large catalogues.
        fixed = (
            [p for p in range(len(variants)) if capacities[p] > 0] if len(variants) <= 24 else []
        )
        for a, b in permutations(fixed, 2):
            alpha, beta, denominator = _fixed_pair_scale(box, variants[a], variants[b])
            solver.add(alpha * row[a] + beta * row[b] <= denominator * count)
    box_volume = total(count * volume(box) for count, box in zip(counts, boxes, strict=True))
    packed_count = total(unit for row in assigned for unit in row)
    used_volume = total(
        row[p] * volume(product) for row in assigned for p, product in enumerate(variants)
    )
    gain = used_volume * (metrics.total_box_volume or 1) - box_volume * metrics.used_volume
    solver.add(
        z3.Or(
            gain > 0,
            z3.And(gain == 0, packed_count > metrics.packed_items),
            z3.And(
                gain == 0, packed_count == metrics.packed_items, used_volume > metrics.used_volume
            ),
            z3.And(
                gain == 0,
                packed_count == metrics.packed_items,
                used_volume == metrics.used_volume,
                total(counts) < metrics.boxes_used,
            ),
        )
    )
    return solver


def certify_incumbent(request: PackingRequest, incumbent: PackingResult) -> bool:
    """Only an UNSAT proof is a certificate; resource exhaustion falls through."""
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
