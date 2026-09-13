import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.config import DEFAULT_DATABASE_URL, Settings
from app.domain.models import PackingResult
from app.main import create_app
from app.packing.validation import validate_solution
from app.schemas.packing import PackingRequestSchema


def test_default_settings_resolve_from_backend_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DUNCARBOX_DATABASE_URL", raising=False)
    monkeypatch.delenv("DUNCARBOX_DEMO_DIR", raising=False)
    settings = Settings.from_env()
    backend_root = Path(__file__).resolve().parents[1]
    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.demo_dir == backend_root.parent / "demo"
    assert (settings.demo_dir / "scenarios.json").is_file()


def test_health_and_openapi(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {
        "status": "ok",
        "api_version": "v1",
        "engine": "candidate-packing-v1",
    }
    schema = client.get("/openapi.json").json()
    response = schema["paths"]["/api/v1/pack"]["post"]["responses"]
    assert response["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorResponse"
    )
    assert {"200", "422"} <= response.keys()
    wrong_method = client.post("/api/v1/health")
    assert wrong_method.status_code == 405
    assert "GET" in wrong_method.headers["allow"]


@pytest.mark.parametrize(
    "scenario_id",
    [
        "simple-order",
        "multiple-boxes",
        "oversized",
        "stock-shortage",
    ],
)
def test_demo_api_is_deterministic_and_physically_valid(
    client: TestClient,
    settings: Settings,
    scenario_id: str,
) -> None:
    scenarios = client.get("/api/v1/demo/scenarios").json()
    assert len(scenarios) == 5
    request = client.get(f"/api/v1/demo/scenarios/{scenario_id}").json()
    first = client.post("/api/v1/pack", json=request)
    assert first.status_code == 200, first.text
    expected = json.loads(
        (settings.demo_dir / f"{scenario_id}.response.json").read_text(encoding="utf-8")
    )
    result = first.json()
    assert result["status"] == expected["status"]
    assert result["metrics"]["packed_items"] == expected["metrics"]["packed_items"]
    # Authored demo layouts predate upright yaw and fill-first search.
    assert result["metrics"]["fill_ratio"] >= expected["metrics"]["fill_ratio"]
    assert result["algorithm_version"] == "candidate-packing-v1"
    assert not any(issue["code"] == "DEMO_STUB" for issue in result["issues"])
    validate_solution(
        PackingRequestSchema.model_validate(request).to_domain(),
        TypeAdapter(PackingResult).validate_python(result),
    )
    for plan in [result, *result["alternatives"]]:
        for box in plan["packed_boxes"]:
            assert len(box["instructions"]) == len(box["placements"]) + 2
            assert box["instructions"][0]["action"] == "prepare_box"
            assert box["instructions"][-1]["action"] == "close_box"
    request["boxes"].reverse()
    request["products"].reverse()
    second = client.post("/api/v1/pack", json=request).json()
    assert result.pop("calculation_seconds") >= 0
    assert second.pop("calculation_seconds") >= 0
    assert second == result


def test_box_crud_is_persistent_and_does_not_reseed_deleted_entries(
    settings: Settings,
    order: dict,
) -> None:
    app = create_app(settings)
    box = {**order["boxes"][0], "id": "new-box", "available_count": 0}
    with TestClient(app) as client:
        catalog = client.get("/api/v1/boxes").json()
        assert catalog and [b["id"] for b in catalog] == sorted(b["id"] for b in catalog)
        assert client.post("/api/v1/boxes", json=box).status_code == 201
        assert client.post("/api/v1/boxes", json=box).status_code == 409
        box["available_count"] = 12
        assert client.put("/api/v1/boxes/new-box", json=box).json() == box
        assert client.put("/api/v1/boxes/wrong-id", json=box).status_code == 422
        assert client.put("/api/v1/boxes/missing", json={**box, "id": "missing"}).status_code == 404
        for seeded in catalog:
            deleted = client.delete(f"/api/v1/boxes/{seeded['id']}")
            assert deleted.status_code == 204 and deleted.content == b""
        assert client.delete("/api/v1/boxes/missing").status_code == 404
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/api/v1/boxes").json() == [box]
        assert restarted.delete("/api/v1/boxes/new-box").status_code == 204
    with TestClient(create_app(settings)) as restarted_empty:
        assert restarted_empty.get("/api/v1/boxes").json() == []


def test_duplicate_create_is_atomic(client: TestClient, order: dict) -> None:
    box = {**order["boxes"][0], "id": "concurrent"}
    with ThreadPoolExecutor(max_workers=4) as workers:
        codes = list(
            workers.map(lambda _: client.post("/api/v1/boxes", json=box).status_code, range(4))
        )
    assert sorted(codes) == [201, 409, 409, 409]


def test_pack_uses_snapshot_without_mutating_catalog(client: TestClient, order: dict) -> None:
    for box in client.get("/api/v1/boxes").json():
        client.delete(f"/api/v1/boxes/{box['id']}")
    assert client.post("/api/v1/pack", json=order).status_code == 200
    assert client.get("/api/v1/boxes").json() == []


def test_arbitrary_order_uses_real_engine(client: TestClient, order: dict) -> None:
    order["products"][0]["quantity"] = 3
    response = client.post("/api/v1/pack", json=order)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "success"
    assert result["metrics"]["packed_items"] == 3
    validate_solution(
        PackingRequestSchema.model_validate(order).to_domain(),
        TypeAdapter(PackingResult).validate_python(result),
    )


def test_error_envelope_for_unknown_paths_and_bad_json(client: TestClient) -> None:
    for path in ("/api/v1/no-such-route", "/api/v1/demo/scenarios/missing"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    malformed = client.post(
        "/api/v1/pack", content="{", headers={"Content-Type": "application/json"}
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "VALIDATION_ERROR"
    assert set(malformed.json()["error"]["details"][0]) == {"field", "message", "type"}


def test_cors_allows_configured_frontend(client: TestClient) -> None:
    response = client.options(
        "/api/v1/pack",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_engine_can_be_injected_without_http_dependencies(settings: Settings, order: dict) -> None:
    from app.domain.models import PackingRequest, PackingResult
    from app.services.fixtures import DemoFixtures

    fixture_result = DemoFixtures(settings.demo_dir).pairs[0][1]

    class RecordingEngine:
        version = "recording-v1"
        received: PackingRequest | None = None

        def pack(self, request: PackingRequest) -> PackingResult:
            self.received = request
            return fixture_result

    # Choose the request corresponding to the first fixture instead of relying on file ordering.
    fixtures = DemoFixtures(settings.demo_dir)
    request = fixtures.request(fixtures.scenarios[0]["id"])
    assert request is not None
    engine = RecordingEngine()
    with TestClient(create_app(settings, engine)) as client:
        assert client.post("/api/v1/pack", json=request.model_dump()).status_code == 200
        assert isinstance(engine.received, PackingRequest)
        assert client.get("/api/v1/health").json()["engine"] == "recording-v1"


def test_internal_errors_do_not_leak_details(settings: Settings, order: dict) -> None:
    from app.domain.models import PackingRequest, PackingResult

    class BrokenEngine:
        def pack(self, request: PackingRequest) -> PackingResult:
            raise RuntimeError("private path /database/internal.sql")

    with TestClient(create_app(settings, BrokenEngine()), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/pack",
            json=order,
            headers={
                "Origin": "http://localhost:5173",
            },
        )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "private" not in response.text
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_domain_and_stub_have_no_framework_imports() -> None:
    import ast

    root = Path(__file__).resolve().parents[1] / "app"
    files = [*(root / "domain").glob("*.py"), *(root / "packing").glob("*.py")]
    forbidden = {"fastapi", "pydantic", "sqlalchemy", "psycopg", "httpx"}
    for file in files:
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert not {entry.name.split(".")[0] for entry in node.names} & forbidden
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden
