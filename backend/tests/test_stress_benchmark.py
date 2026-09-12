import hashlib
import json
import multiprocessing
from dataclasses import asdict
from pathlib import Path

import pytest

from app.packing.stress_benchmark import make_request, run_benchmark
from app.schemas.packing import PackingRequestSchema


def test_stress_workload_is_reproducible_diverse_and_fully_feasible() -> None:
    request = make_request()
    assert request == make_request()
    assert len(request.products) == len({p.id for p in request.products}) == 100
    assert len({(p.length, p.width, p.height) for p in request.products}) == 100
    assert len({p.weight for p in request.products}) == 100
    assert {p.allow_rotation for p in request.products} == {True, False}
    assert sum(p.quantity for p in request.products) == 10_000
    assert all(p.quantity == 100 for p in request.products)
    assert len(request.boxes) == len({b.id for b in request.boxes}) == 8
    assert len({(b.length, b.width, b.height) for b in request.boxes}) == 8
    # Every item fits every empty carton even without rotation. With 10,000
    # cartons in stock there is a constructive full solution: one item per box.
    assert sum(box.available_count for box in request.boxes) == 10_000
    for box in request.boxes:
        for item in request.products:
            assert item.length <= box.length
            assert item.width <= box.width
            assert item.height <= box.height
            assert item.weight <= box.max_weight


def test_large_demo_is_accepted_by_the_public_api_schema() -> None:
    parsed = PackingRequestSchema.model_validate(asdict(make_request()))
    assert sum(p.quantity for p in parsed.products) == 10_000
    assert make_request("z3").options.algorithm == "z3"


def test_stress_timeout_is_a_failure_report_and_leaves_no_worker(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text('{"old":true}', encoding="utf-8")
    previous = {p.pid for p in multiprocessing.active_children()}
    report = run_benchmark(tmp_path, timeout_seconds=0.001)
    assert report["status"] == "timeout"
    assert report["validated"] is False
    assert report["elapsed_seconds"] < 5
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8")) == report
    assert len(json.loads((tmp_path / "request.json").read_text())["products"]) == 100
    assert (
        hashlib.sha256((tmp_path / "request.json").read_bytes()).hexdigest()
        == report["request_sha256"]
    )
    assert not (tmp_path / "result.json").exists()
    assert {p.pid for p in multiprocessing.active_children()} <= previous


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 86401])
def test_stress_rejects_unbounded_or_invalid_timeout(tmp_path: Path, timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        run_benchmark(tmp_path, timeout_seconds=timeout)
