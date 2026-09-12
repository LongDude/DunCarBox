from fractions import Fraction

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.domain.models import PackingResult
from app.packing.validation import validate_solution
from app.schemas.packing import PackingRequestSchema


def assert_valid_response(order: dict, result: dict) -> None:
    validate_solution(
        PackingRequestSchema.model_validate(order).to_domain(),
        TypeAdapter(PackingResult).validate_python(result),
        Fraction(1, 1),
    )
    for plan in [result, *result["alternatives"]]:
        for box in plan["packed_boxes"]:
            assert len(box["instructions"]) == len(box["placements"]) + 2
            for placement in box["placements"]:
                instruction = box["instructions"][placement["step"]]
                assert all(instruction[key] == value for key, value in placement.items())


@pytest.mark.parametrize(
    ("scenario", "status", "packed"),
    [
        ("simple-order", "success", 2),
        ("multiple-boxes", "success", 6),
        ("oversized", "impossible", 0),
        ("stock-shortage", "partial", 1),
    ],
)
def test_real_z3_through_api_and_instructions(
    client: TestClient, scenario: str, status: str, packed: int
) -> None:
    order = client.get(f"/api/v1/demo/scenarios/{scenario}").json()
    order["options"].update(algorithm="z3", solver_timeout_ms=10_000, solver_workers=2)
    response = client.post("/api/v1/pack", json=order)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == status
    assert result["metrics"]["packed_items"] == packed
    assert result["optimization"]["support_ratio"] == 1
    assert result["optimization"]["time_limit_ms"] == 10_000
    assert 0 <= result["optimization"]["workers"] <= 2
    assert not any(issue["code"] == "DEMO_STUB" for issue in result["issues"])
    assert_valid_response(order, result)


def test_switching_algorithms_does_not_change_default_or_catalog(
    client: TestClient, order: dict
) -> None:
    before = client.get("/api/v1/boxes").json()
    order["products"][0]["quantity"] = 1
    implicit = client.post("/api/v1/pack", json=order).json()
    order["options"].update(algorithm="z3", solver_timeout_ms=10_000, solver_workers=1)
    optimized = client.post("/api/v1/pack", json=order).json()
    assert optimized["optimization"]["status"] == "optimal"
    assert optimized["optimization"]["reason"] == "completed"
    assert optimized["algorithm_version"].startswith("z3-packing-v1")
    assert_valid_response(order, optimized)
    order["options"]["algorithm"] = "heuristic"
    explicit = client.post("/api/v1/pack", json=order).json()
    assert explicit == implicit
    assert explicit["algorithm_version"] == "candidate-packing-v1"
    assert explicit["optimization"] is None
    assert client.get("/api/v1/boxes").json() == before


def test_large_z3_request_returns_explained_valid_fallback(client: TestClient, order: dict) -> None:
    order["products"][0]["quantity"] = 17
    order["options"].update(algorithm="z3", solver_timeout_ms=1000, solver_workers=8)
    response = client.post("/api/v1/pack", json=order)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["optimization"]["status"] == "fallback"
    assert result["optimization"]["reason"] == "time_limit"
    assert result["optimization"]["workers"] > 0
    assert result["metrics"]["total_items"] == 17
    assert_valid_response(order, result)
