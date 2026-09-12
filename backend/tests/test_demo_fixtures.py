"""Cross-field checks for authored demo snapshots, independent of the stub."""

import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any

import pytest

from app.schemas.packing import PackingRequestSchema, PackingResultSchema

DEMO = Path(__file__).resolve().parents[2] / "demo"
EXPECTED = {
    "simple-order": "success",
    "multiple-boxes": "success",
    "oversized": "impossible",
    "stock-shortage": "partial",
}
AXES = (("x", "length"), ("y", "width"), ("z", "height"))
ORIENTATIONS = ("LWH", "LHW", "WLH", "WHL", "HLW", "HWL")


def read_json(name: str) -> Any:
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


def volume(value: dict[str, Any]) -> int:
    return value["length"] * value["width"] * value["height"]


@pytest.fixture(params=list(EXPECTED))
def snapshot(request: pytest.FixtureRequest) -> tuple[dict[str, Any], dict[str, Any]]:
    return read_json(f"{request.param}.request.json"), read_json(f"{request.param}.response.json")


def test_scenario_catalog_has_all_four_expected_outcomes() -> None:
    scenarios = read_json("scenarios.json")
    assert len(scenarios) == 4
    assert {entry["id"]: entry["expected_status"] for entry in scenarios} == EXPECTED
    for entry in scenarios:
        assert set(entry) == {"id", "name", "description", "expected_status"}
        assert entry["name"] and entry["description"]
        assert read_json(f"{entry['id']}.response.json")["status"] == entry["expected_status"]
    for suffix in ("request", "response"):
        assert {
            path.name.removesuffix(f".{suffix}.json") for path in DEMO.glob(f"*.{suffix}.json")
        } == set(EXPECTED)
    catalog = read_json("catalog.boxes.json")
    assert [entry["id"] for entry in catalog] == sorted(entry["id"] for entry in catalog)
    PackingRequestSchema.model_validate(
        {"boxes": catalog, "products": read_json("simple-order.request.json")["products"]}
    )


def test_fixture_schema_and_stub_disclosure(
    snapshot: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    request, response = snapshot
    PackingRequestSchema.model_validate(request)
    validated = PackingResultSchema.model_validate(response)
    # Legacy demo snapshots intentionally omit optional solver metadata.
    assert validated.model_dump(mode="json", exclude_unset=True) == response
    assert response["algorithm_version"] == "demo-stub-v1"
    assert any(issue["code"] == "DEMO_STUB" for issue in response["issues"])
    assert response["alternatives"] == []


def test_every_physical_item_is_accounted_for_once(
    snapshot: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    request, response = snapshot
    expected = {
        f"{product['id']}:{unit}": (product, unit)
        for product in request["products"]
        for unit in range(1, product["quantity"] + 1)
    }
    packed_ids = []
    for box in response["packed_boxes"]:
        for placement in box["placements"]:
            identifier = placement["item_instance_id"]
            assert identifier in expected
            assert placement["product_id"] == expected[identifier][0]["id"]
            packed_ids.append(identifier)
    unpacked_ids = []
    for item in response["unpacked_items"]:
        identifier = item["id"]
        assert identifier in expected
        product, unit = expected[identifier]
        assert item == {
            **{
                key: product[key]
                for key in ("name", "length", "width", "height", "weight", "allow_rotation")
            },
            "id": identifier,
            "product_id": product["id"],
            "unit_index": unit,
        }
        unpacked_ids.append(identifier)
    assert Counter(packed_ids + unpacked_ids) == Counter(expected.keys())
    assert response["unpacked_items"] == sorted(
        response["unpacked_items"], key=lambda item: (item["product_id"], item["unit_index"])
    )
    reasons = {
        identifier
        for issue in response["issues"]
        if issue["code"] not in {"DEMO_STUB", "PARTIAL_PACKING"}
        for identifier in issue["item_instance_ids"]
    }
    assert set(unpacked_ids) <= reasons
    assert response["issues"] == sorted(
        response["issues"], key=lambda issue: (issue["code"], issue["item_instance_ids"])
    )


def test_geometry_and_orientations(snapshot: tuple[dict[str, Any], dict[str, Any]]) -> None:
    request, response = snapshot
    products = {product["id"]: product for product in request["products"]}
    for box in response["packed_boxes"]:
        for placement in box["placements"]:
            product = products[placement["product_id"]]
            dimensions = {"L": product["length"], "W": product["width"], "H": product["height"]}
            orientation = placement["orientation"]
            assert orientation in ORIENTATIONS
            if not product["allow_rotation"]:
                assert orientation == "LWH"
            actual = tuple(placement["dimensions"][axis] for _, axis in AXES)
            assert actual == tuple(dimensions[axis] for axis in orientation)
            equivalent_orientations = [
                value
                for value in ORIENTATIONS
                if tuple(dimensions[axis] for axis in value) == actual
            ]
            assert orientation == equivalent_orientations[0]
            for coordinate, dimension in AXES:
                start = placement["position"][coordinate]
                assert 0 <= start
                assert start + placement["dimensions"][dimension] <= box[dimension]
            assert placement["position"]["z"] == 0, (
                "Authored snapshots place every item on the floor."
            )
        for first, second in combinations(box["placements"], 2):
            overlaps = all(
                first["position"][coordinate]
                < second["position"][coordinate] + second["dimensions"][dimension]
                and second["position"][coordinate]
                < first["position"][coordinate] + first["dimensions"][dimension]
                for coordinate, dimension in AXES
            )
            assert not overlaps, (box["id"], first["item_instance_id"], second["item_instance_id"])


def test_box_stock_weights_and_metrics(snapshot: tuple[dict[str, Any], dict[str, Any]]) -> None:
    request, response = snapshot
    box_types = {box["id"]: box for box in request["boxes"]}
    products = {product["id"]: product for product in request["products"]}
    stock_used: Counter[str] = Counter()
    used_volume = total_box_volume = total_weight = packed_items = 0
    for box in response["packed_boxes"]:
        original = box_types[box["box_type_id"]]
        stock_used[box["box_type_id"]] += 1
        assert box["id"] == f"{box['box_type_id']}:{stock_used[box['box_type_id']]}"
        assert stock_used[box["box_type_id"]] <= original["available_count"]
        for field in ("name", "length", "width", "height", "max_weight"):
            assert box[field] == original[field]
        assert box["placements"], "The response must not allocate empty boxes."
        weight = sum(products[item["product_id"]]["weight"] for item in box["placements"])
        used = sum(volume(products[item["product_id"]]) for item in box["placements"])
        assert box["total_weight"] == weight <= box["max_weight"]
        assert box["used_volume"] == used <= volume(box)
        assert box["fill_ratio"] == round(used / volume(box), 6)
        used_volume += used
        total_box_volume += volume(box)
        total_weight += weight
        packed_items += len(box["placements"])
    total_items = sum(product["quantity"] for product in request["products"])
    assert response["metrics"] == dict(
        total_items=total_items,
        packed_items=packed_items,
        unpacked_items=total_items - packed_items,
        boxes_used=sum(stock_used.values()),
        boxes_by_type=dict(stock_used),
        total_box_volume=total_box_volume,
        used_volume=used_volume,
        empty_volume=total_box_volume - used_volume,
        fill_ratio=round(used_volume / total_box_volume, 6) if total_box_volume else 0,
        total_weight=total_weight,
    )
    status = (
        "success" if packed_items == total_items else "partial" if packed_items else "impossible"
    )
    assert response["status"] == status


def test_instructions_match_each_placement(snapshot: tuple[dict[str, Any], dict[str, Any]]) -> None:
    _, response = snapshot
    reference_fields = ("item_instance_id", "product_id", "position", "dimensions", "orientation")
    for box in response["packed_boxes"]:
        instructions = box["instructions"]
        assert len(instructions) == len(box["placements"]) + 2
        assert [entry["step"] for entry in instructions] == list(range(len(instructions)))
        assert instructions[0]["action"] == "prepare_box"
        assert instructions[-1]["action"] == "close_box"
        for instruction in (instructions[0], instructions[-1]):
            assert all(instruction[field] is None for field in reference_fields)
        for step, placement in enumerate(box["placements"], 1):
            instruction = instructions[step]
            assert placement["step"] == step
            assert instruction["action"] == "place_item"
            assert all(instruction[field] == placement[field] for field in reference_fields)
        for instruction in instructions:
            assert instruction["box_id"] == box["id"]
            assert instruction["message"].strip()
            assert any("а" <= character.lower() <= "я" for character in instruction["message"])
