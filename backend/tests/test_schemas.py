from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.schemas.packing import PackingRequestSchema


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("boxes", "length", 0),
        ("boxes", "width", -1),
        ("boxes", "height", 100001),
        ("boxes", "max_weight", 0),
        ("boxes", "available_count", -1),
        ("boxes", "length", True),
        ("products", "length", 1.5),
        ("products", "weight", "250"),
        ("products", "quantity", 0),
        ("products", "quantity", False),
        ("products", "allow_rotation", "false"),
        ("products", "id", "a:b"),
        ("products", "name", "  "),
        ("products", "unexpected", "field"),
    ],
)
def test_invalid_input_fields(
    client: TestClient,
    order: dict,
    section: str,
    field: str,
    value: object,
) -> None:
    order[section][0][field] = value
    response = client.post("/api/v1/pack", json=order)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]


@pytest.mark.parametrize("section", ["boxes", "products"])
def test_duplicate_ids_are_rejected(client: TestClient, order: dict, section: str) -> None:
    order[section].append(deepcopy(order[section][0]))
    assert client.post("/api/v1/pack", json=order).status_code == 422


def test_large_orders_are_valid_without_fixed_count_limits(order: dict) -> None:
    order["products"][0]["quantity"] = 100_000
    order["products"].append({**order["products"][0], "id": "more", "quantity": 1})
    order["boxes"][0]["available_count"] = 10_000_000_000
    order["options"].update(solver_workers=32, solver_timeout_ms=600_000)
    parsed = PackingRequestSchema.model_validate(order).to_domain()
    assert sum(product.quantity for product in parsed.products) == 100_001
    assert parsed.options.solver_workers == 32
    assert parsed.options.solver_timeout_ms == 600_000


def test_default_options_and_boolean_values(order: dict) -> None:
    order.pop("options")
    order["products"][0].pop("allow_rotation")
    result = PackingRequestSchema.model_validate(order).to_domain()
    assert result.options.include_alternatives is True
    assert result.options.max_alternatives == 3
    assert result.options.algorithm == "heuristic"
    assert result.options.solver_timeout_ms is None
    assert result.options.solver_workers == 4
    assert result.products[0].allow_rotation is True


def test_null_solver_timeout_is_accepted_and_field_is_deprecated(order: dict) -> None:
    order["options"]["solver_timeout_ms"] = None
    result = PackingRequestSchema.model_validate(order).to_domain()
    assert result.options.solver_timeout_ms is None
    schema = PackingRequestSchema.model_json_schema()
    field = schema["$defs"]["PackingOptionsSchema"]["properties"]["solver_timeout_ms"]
    assert field["deprecated"] is True


def test_zero_stock_and_empty_boxes_are_valid_domain_inputs(order: dict) -> None:
    order["boxes"][0]["available_count"] = 0
    assert PackingRequestSchema.model_validate(order).boxes[0].available_count == 0
    order["boxes"] = []
    assert PackingRequestSchema.model_validate(order).to_domain().boxes == ()


@pytest.mark.parametrize(
    "options",
    [
        {"max_alternatives": 6},
        {"max_alternatives": -1},
        {"max_alternatives": True},
        {"include_alternatives": 1},
        {"unknown": True},
        {"algorithm": "unknown"},
        {"algorithm": 2},
        {"solver_timeout_ms": 0},
        {"solver_timeout_ms": True},
        {"solver_timeout_ms": "1000"},
        {"solver_workers": 0},
        {"solver_workers": 2.5},
    ],
)
def test_invalid_options(client: TestClient, order: dict, options: dict) -> None:
    order["options"] = options
    assert client.post("/api/v1/pack", json=order).status_code == 422


def test_empty_products_and_unknown_fields(client: TestClient, order: dict) -> None:
    assert client.post("/api/v1/pack", json={**order, "products": []}).status_code == 422
    assert client.post("/api/v1/pack", json={**order, "extra": 1}).status_code == 422
