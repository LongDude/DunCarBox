import multiprocessing
from time import monotonic, sleep

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes import get_jobs
from app.domain.models import BoxType, PackingOptions, PackingRequest, Product
from app.packing.workloads import make_request
from app.services.packing_jobs import PackingJobs


def wait_for(jobs: PackingJobs, job_id: str) -> dict:
    deadline = monotonic() + 15
    while monotonic() < deadline:
        state = jobs.status(job_id)
        if state["status"] != "running":
            return state
        sleep(0.03)
    raise AssertionError("Job did not finish")


def small_request() -> PackingRequest:
    return PackingRequest(
        (BoxType("box", "Box", 20, 20, 20, 100, 1),),
        (Product("item", "Item", 10, 10, 10, 1, 2),),
    )


def hanging_worker(request, path, cancel_event):
    sleep(60)


def failed_worker(request, path, cancel_event):
    raise RuntimeError("Private test details")


def test_menu_demo_uses_the_same_reproducible_workload(client: TestClient):
    scenarios = client.get("/api/v1/demo/scenarios").json()
    scenario = next(row for row in scenarios if row["id"] == "large-order")
    assert "10 000" in scenario["name"]
    assert "Нагрузочный" not in scenario["name"]
    response = client.get("/api/v1/demo/scenarios/large-order")
    assert response.status_code == 200
    value = response.json()
    assert len(value["products"]) == 100
    assert len(value["boxes"]) == 8
    assert sum(p["quantity"] for p in value["products"]) == 10_000
    assert value["products"][0]["length"] == make_request().products[0].length


def test_background_api_runs_real_engine_and_serves_instructions(client: TestClient, order: dict):
    response = client.post("/api/v1/pack/jobs", json=order)
    assert response.status_code == 202
    job_id = response.json()["id"]
    assert response.json()["timeout_seconds"] is None
    state = wait_for(client.app.state.packing_jobs, job_id)
    assert state["status"] == "completed", state
    result = client.get(f"/api/v1/pack/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.json()["metrics"]["packed_items"] == 2
    assert len(result.json()["packed_boxes"][0]["instructions"]) == 4
    assert client.delete(f"/api/v1/pack/jobs/{job_id}").status_code == 204
    assert client.get("/api/v1/pack/jobs/missing").status_code == 404


def test_regular_pack_endpoint_accepts_more_than_1000_units(client: TestClient, order: dict):
    order["boxes"] = []
    order["products"][0]["quantity"] = 10_001
    response = client.post("/api/v1/pack", json=order)
    assert response.status_code == 200
    assert response.json()["metrics"]["total_items"] == 10_001


def test_job_concurrency_cancellation_and_application_cleanup(client: TestClient):
    previous = {p.pid for p in multiprocessing.active_children()}
    jobs = PackingJobs(worker=hanging_worker)
    client.app.dependency_overrides[get_jobs] = lambda: jobs
    paths = []
    try:
        request = client.get("/api/v1/demo/scenarios/large-order").json()
        started = client.post("/api/v1/pack/jobs", json=request)
        assert started.status_code == 202
        job_id = started.json()["id"]
        paths.append(jobs._jobs[job_id].path.parent)
        assert client.post("/api/v1/pack/jobs", json=request).status_code == 409
        assert client.get(f"/api/v1/pack/jobs/{job_id}/result").status_code == 409
        assert client.delete(f"/api/v1/pack/jobs/{job_id}").status_code == 204
        assert jobs.status(job_id)["status"] == "cancelled"
        second = jobs.submit(small_request())
        paths.append(jobs._jobs[second["id"]].path.parent)
    finally:
        jobs.close()
        client.app.dependency_overrides.clear()
    assert all(not path.exists() for path in paths)
    assert {p.pid for p in multiprocessing.active_children()} <= previous


@pytest.mark.parametrize("worker,timeout", [(hanging_worker, 0.001), (failed_worker, 10)])
def test_deadline_or_worker_failure_never_serves_a_false_result(worker, timeout):
    jobs = PackingJobs(timeout_seconds=timeout, worker=worker)
    try:
        job = jobs.submit(small_request())
        state = wait_for(jobs, job["id"])
        assert state["status"] == "failed"
        assert "Private" not in state["error"]
        with pytest.raises(HTTPException) as error:
            jobs.result_path(job["id"])
        assert error.value.status_code == 409
    finally:
        jobs.close()


def test_z3_background_cancellation_reaches_solver_controller():
    jobs = PackingJobs()
    previous = {p.pid for p in multiprocessing.active_children()}
    try:
        value = small_request()
        request = PackingRequest(
            value.boxes,
            value.products,
            PackingOptions(algorithm="z3", solver_timeout_ms=600_000, solver_workers=16),
        )
        started = jobs.submit(request)
        # This case may already be optimal; cancellation is valid in either state.
        sleep(1)
        jobs.cancel(started["id"])
        assert jobs.status(started["id"])["status"] in {"cancelled", "completed"}
        assert {p.pid for p in multiprocessing.active_children()} <= previous
    finally:
        jobs.close()


def test_catalog_accepts_stock_above_32bit_integer(client: TestClient, order: dict):
    box = {**order["boxes"][0], "id": "many-boxes", "available_count": 10_000_000_000}
    assert client.post("/api/v1/boxes", json=box).status_code == 201
    assert next(b for b in client.get("/api/v1/boxes").json() if b["id"] == box["id"]) == box


def test_retention_starts_after_completion_even_for_long_calculations():
    jobs = PackingJobs()
    try:
        first = jobs.submit(small_request())
        assert wait_for(jobs, first["id"])["status"] == "completed"
        jobs._jobs[first["id"]].started -= 3600
        second = jobs.submit(small_request())
        assert jobs.result_path(first["id"]).is_file()
        assert wait_for(jobs, second["id"])["status"] == "completed"
    finally:
        jobs.close()
