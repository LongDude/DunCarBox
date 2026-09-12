"""Opt in with DUNCARBOX_RUN_STRESS_10000=1; never burden the fast suite."""

import os
from pathlib import Path

import pytest

from app.packing.stress_benchmark import run_benchmark


@pytest.mark.stress
@pytest.mark.skipif(
    os.getenv("DUNCARBOX_RUN_STRESS_10000") != "1",
    reason="Set DUNCARBOX_RUN_STRESS_10000=1 to pack 10000 items / 100 SKUs / 8 box types",
)
def test_pack_10000_items_100_types_8_box_types(tmp_path: Path) -> None:
    report = run_benchmark(
        tmp_path,
        algorithm=os.getenv("DUNCARBOX_STRESS_ALGORITHM", "heuristic"),
        timeout_seconds=float(os.getenv("DUNCARBOX_STRESS_TIMEOUT", "600")),
        progress=lambda message: print(message, flush=True),
    )
    assert report["status"] == "passed", report
    assert report["validated"] is True
    assert report["metrics"]["packed_items"] == 10_000
    assert report["metrics"]["unpacked_items"] == 0
