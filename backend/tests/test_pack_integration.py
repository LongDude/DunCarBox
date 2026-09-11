from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.domain.models import PackingResult
from app.packing.validation import validate_solution
from app.schemas.packing import PackingRequestSchema


def check_plan(order: dict, result: dict) -> None:
    validate_solution(
        PackingRequestSchema.model_validate(order).to_domain(),
        TypeAdapter(PackingResult).validate_python(result),
    )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("no-boxes", "NO_BOX_TYPES"),
        ("zero-stock", "BOX_STOCK_EXHAUSTED"),
        ("too-heavy", "ITEM_TOO_HEAVY"),
        ("too-large", "ITEM_TOO_LARGE"),
    ],
)
def test_impossible_orders_are_explained_by_real_api(
    client: TestClient,
    order: dict,
    case: str,
    expected_code: str,
) -> None:
    if case == "no-boxes":
        order["boxes"] = []
    elif case == "zero-stock":
        order["boxes"][0]["available_count"] = 0
    elif case == "too-heavy":
        order["products"][0]["weight"] = order["boxes"][0]["max_weight"] + 1
    else:
        order["products"][0]["length"] = 1000
    response = client.post("/api/v1/pack", json=order)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "impossible"
    assert result["metrics"]["packed_items"] == 0
    assert expected_code in {issue["code"] for issue in result["issues"]}
    check_plan(order, result)


def test_rotation_is_respected_across_http_boundary(client: TestClient, order: dict) -> None:
    order["boxes"][0].update(length=100, width=80, height=60)
    order["products"][0].update(length=80, width=100, height=60, quantity=1, allow_rotation=False)
    blocked = client.post("/api/v1/pack", json=order).json()
    assert blocked["status"] == "impossible"
    check_plan(order, blocked)
    order["products"][0]["allow_rotation"] = True
    fitted = client.post("/api/v1/pack", json=order).json()
    assert fitted["status"] == "success"
    assert fitted["packed_boxes"][0]["placements"][0]["orientation"] == "WLH"
    check_plan(order, fitted)


@pytest.mark.parametrize(
    "options",
    [
        {"include_alternatives": False, "max_alternatives": 3},
        {"include_alternatives": True, "max_alternatives": 0},
        {"include_alternatives": True, "max_alternatives": 1},
    ],
)
def test_alternative_options_do_not_change_recommended_plan(
    client: TestClient,
    order: dict,
    options: dict,
) -> None:
    baseline = client.post("/api/v1/pack", json=order).json()
    order["options"] = options
    changed = client.post("/api/v1/pack", json=order).json()
    assert changed["packed_boxes"] == baseline["packed_boxes"]
    assert changed["metrics"] == baseline["metrics"]
    expected_limit = options["max_alternatives"] if options["include_alternatives"] else 0
    assert len(changed["alternatives"]) <= expected_limit
    check_plan(order, changed)


def test_partial_plan_accounts_for_oversized_and_packed_goods(
    client: TestClient, order: dict
) -> None:
    large = {
        **deepcopy(order["products"][0]),
        "id": "oversized-extra",
        "length": 1000,
        "quantity": 1,
    }
    order["products"].append(large)
    response = client.post("/api/v1/pack", json=order)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "partial"
    assert result["metrics"]["packed_items"] == 2
    assert result["unpacked_items"][0]["id"] == "oversized-extra:1"
    check_plan(order, result)
