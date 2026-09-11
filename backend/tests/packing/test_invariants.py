"""Seeded input diversity and independent, discrete-geometry packing checks."""

import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from fractions import Fraction
from itertools import product
from pathlib import Path
from random import Random

import pytest

from app.domain.models import (
    BoxType,
    Dimensions,
    PackingOptions,
    PackingRequest,
    Placement,
    Position,
    Product,
)
from app.packing.engine import DeterministicPackingEngine
from app.packing.geometry import aabb_intersects, support_area
from app.packing.options import EngineOptions
from app.packing.relationships import placement_relationships
from app.packing.validation import validate_solution


def generated_order(seed: int) -> PackingRequest:
    random = Random(seed)
    boxes = tuple(
        BoxType(
            f"box-{index}",
            f"Box {index}",
            *(random.randint(5, 12) for _ in range(3)),
            max_weight=random.randint(4, 25),
            available_count=random.randint(0, 3),
        )
        for index in range(random.randint(1, 3))
    )
    products = tuple(
        Product(
            f"item-{index}",
            f"Item {index}",
            *(random.randint(1, 7) for _ in range(3)),
            weight=random.randint(1, 12),
            quantity=random.randint(1, 3),
            allow_rotation=bool(random.getrandbits(1)),
        )
        for index in range(random.randint(2, 5))
    )
    if seed % 4 == 0:
        products = (replace(products[0], length=20, width=20, height=20), *products[1:])
    if seed % 4 == 1:
        products = (replace(products[0], weight=26), *products[1:])
    return PackingRequest(boxes, products, PackingOptions(max_alternatives=2))


def _cells(placement: Placement) -> set[tuple[int, int, int]]:
    p, d = placement.position, placement.dimensions
    return set(
        product(
            range(p.x, p.x + d.length),
            range(p.y, p.y + d.width),
            range(p.z, p.z + d.height),
        )
    )


def _check_discrete_plan(request, plan, threshold: Fraction) -> None:
    expected = Counter(
        {
            f"{item.id}:{index}": 1
            for item in request.products
            for index in range(1, item.quantity + 1)
        }
    )
    products = {item.id: item for item in request.products}
    stock = {box.id: box.available_count for box in request.boxes}
    used = Counter(box.box_type_id for box in plan.packed_boxes)
    assert all(count <= stock[identifier] for identifier, count in used.items())
    actual = Counter(item.id for item in plan.unpacked_items)
    for box in plan.packed_boxes:
        occupied: set[tuple[int, int, int]] = set()
        weight = 0
        steps = {placement.item_instance_id: placement.step for placement in box.placements}
        for relation in placement_relationships(box.placements):
            assert all(
                steps[below] < steps[relation.item_instance_id] for below in relation.supported_by
            )
            assert relation.on_floor or relation.supported_by
        for step, placement in enumerate(box.placements, 1):
            assert placement.step == step
            cells = _cells(placement)
            assert cells
            assert all(
                0 <= x < box.length and 0 <= y < box.width and 0 <= z < box.height
                for x, y, z in cells
            )
            assert not occupied.intersection(cells)
            p, d = placement.position, placement.dimensions
            if p.z > 0:
                supported = sum(
                    (x, y, p.z - 1) in occupied
                    for x in range(p.x, p.x + d.length)
                    for y in range(p.y, p.y + d.width)
                )
                assert supported > 0
                assert supported * threshold.denominator >= (
                    d.length * d.width * threshold.numerator
                )
            occupied.update(cells)
            weight += products[placement.product_id].weight
            actual[placement.item_instance_id] += 1
        assert weight == box.total_weight <= box.max_weight
        assert len(occupied) == box.used_volume
    assert actual == expected


@pytest.mark.parametrize("seed", range(48))
def test_seeded_orders_preserve_geometry_stock_quantities_and_step_support(seed: int) -> None:
    request = generated_order(seed)
    original = asdict(request)
    threshold = (Fraction(3, 4), Fraction(4, 5), Fraction(1))[seed % 3]
    engine = DeterministicPackingEngine(EngineOptions(min_support_ratio=threshold))
    result = engine.pack(request)
    validate_solution(request, result, threshold)
    for plan in (result, *result.alternatives):
        _check_discrete_plan(request, plan, threshold)
    assert asdict(request) == original
    if seed % 8 == 0:
        reordered = replace(request, products=request.products[::-1], boxes=request.boxes[::-1])
        assert asdict(engine.pack(reordered)) == asdict(result)


def test_seeded_aabb_and_support_match_independent_voxel_oracles() -> None:
    random = Random(719)
    for case in range(100):
        placements = tuple(
            Placement(
                f"item:{index}",
                "item",
                Position(*(random.randint(0, 5) for _ in range(3))),
                Dimensions(*(random.randint(1, 4) for _ in range(3))),
                "LWH",
                index,
            )
            for index in range(5)
        )
        a, b = placements[:2]
        assert aabb_intersects(a, b) == bool(_cells(a) & _cells(b))
        target = replace(a, position=Position(a.position.x, a.position.y, 5))
        if case % 2 == 0:
            placements = tuple(
                replace(p, position=Position(p.position.x, p.position.y, 5 - p.dimensions.height))
                for p in placements
            )
        p, d = target.position, target.dimensions
        support_cells = {
            (x, y)
            for lower in placements
            if lower.position.z + lower.dimensions.height == p.z
            for x in range(lower.position.x, lower.position.x + lower.dimensions.length)
            for y in range(lower.position.y, lower.position.y + lower.dimensions.width)
            if p.x <= x < p.x + d.length and p.y <= y < p.y + d.width
        }
        assert support_area(target, placements) == len(support_cells)


def test_shared_engine_is_reentrant_and_does_not_reuse_mutable_result_state() -> None:
    engine = DeterministicPackingEngine()
    requests = [generated_order(seed) for seed in (5, 6, 7, 11)]
    original_requests = [asdict(request) for request in requests]
    expected = [asdict(engine.pack(request)) for request in requests]
    repeated = [index for _ in range(3) for index in range(len(requests))]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda index: engine.pack(requests[index]), repeated))
    assert [asdict(result) for result in results] == [expected[index] for index in repeated]
    assert [asdict(request) for request in requests] == original_requests
    results[0].metrics.boxes_by_type["caller-mutated"] = 123
    assert asdict(engine.pack(requests[0])) == expected[0]


def test_normalized_result_is_equal_across_python_hash_seeds() -> None:
    source = """
import json
from dataclasses import asdict
from app.domain.models import BoxType, PackingRequest, Product
from app.packing.engine import DeterministicPackingEngine
request = PackingRequest(
    (BoxType('wide', 'Wide', 12, 10, 8, 30, 2), BoxType('tall', 'Tall', 8, 8, 12, 30, 2)),
    (Product('b', 'B', 4, 3, 2, 3, 3, True), Product('a', 'A', 6, 4, 3, 5, 3, True)),
)
print(json.dumps(asdict(DeterministicPackingEngine().pack(request)), sort_keys=True))
"""
    outputs = []
    for seed in ("1", "937"):
        environment = dict(os.environ, PYTHONHASHSEED=seed)
        completed = subprocess.run(
            [sys.executable, "-c", source],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        outputs.append(json.loads(completed.stdout))
    assert outputs[0] == outputs[1]
