"""An opt-in, single-order benchmark: 10,000 units, 100 SKUs, eight carton types.

Run from backend: python -m app.packing.stress_benchmark --timeout-seconds 600
This exercises the real engine and instruction service directly, above the HTTP
limit of 1,000 units. It never splits the order or truncates the requested goods.
"""

import argparse
import hashlib
import json
import multiprocessing
import os
import platform
import traceback
from collections.abc import Callable
from dataclasses import asdict
from fractions import Fraction
from importlib.metadata import version
from multiprocessing.connection import Connection
from pathlib import Path
from time import monotonic, perf_counter

from app.domain.models import BoxType, PackingOptions, PackingRequest, Product
from app.packing.dispatcher import PackingEngineDispatcher
from app.packing.validation import validate_solution
from app.services.packing import PackingService

WORKLOAD_ID = "packing-10000-100sku-8boxes-v1"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / ".cache" / "stress-10000"


def make_request(algorithm: str = "heuristic") -> PackingRequest:
    if algorithm not in {"heuristic", "z3"}:
        raise ValueError("algorithm must be heuristic or z3")
    box_sizes = (
        (250, 200, 150, 2500),
        (300, 220, 180, 5000),
        (350, 250, 200, 7500),
        (400, 280, 220, 10000),
        (450, 300, 250, 15000),
        (500, 350, 300, 20000),
        (550, 400, 350, 25000),
        (600, 450, 400, 30000),
    )
    return PackingRequest(
        boxes=tuple(
            BoxType(f"box-{i + 1:02}", f"Carton {i + 1}", *size, available_count=1250)
            for i, size in enumerate(box_sizes)
        ),
        products=tuple(
            Product(
                id=f"sku-{i + 1:03}",
                name=f"Product {i + 1:03}",
                length=60 + i * 37 % 181,
                width=40 + i * 23 % 141,
                height=25 + i * 17 % 116,
                weight=100 + i * 97 % 1901,
                quantity=100,
                allow_rotation=i % 4 != 0,
            )
            for i in range(100)
        ),
        options=PackingOptions(algorithm=algorithm),
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _worker(connection: Connection, request: PackingRequest, result_path: Path) -> None:
    try:
        original = asdict(request)
        started = perf_counter()
        result = PackingService(PackingEngineDispatcher()).pack(request)
        packing_seconds = perf_counter() - started
        connection.send({"phase": "validation"})
        started = perf_counter()
        support = Fraction(1) if request.options.algorithm == "z3" else Fraction(4, 5)
        validate_solution(request, result, support)
        if asdict(request) != original:
            raise AssertionError("Packing mutated the input order")
        if result.status != "success" or result.metrics.packed_items != 10_000:
            raise AssertionError("This feasible workload must pack all 10,000 units")
        if request.options.algorithm == "z3" and (
            result.optimization is None
            or result.optimization.status != "fallback"
            or result.optimization.reason != "size_limit"
            or result.optimization.workers != 0
        ):
            raise AssertionError("10,000 units must use an explicit Z3 size-limit fallback")
        validation_seconds = perf_counter() - started
        connection.send({"phase": "serialization"})
        result_path.write_text(_json(asdict(result)), encoding="utf-8", newline="\n")
        connection.send(
            {
                "status": "passed",
                "packing_seconds": round(packing_seconds, 3),
                "validation_seconds": round(validation_seconds, 3),
                "validated": True,
                "algorithm_version": result.algorithm_version,
                "optimization": asdict(result.optimization) if result.optimization else None,
                "metrics": asdict(result.metrics),
            }
        )
    except Exception as error:
        traceback.print_exc()
        connection.send({"status": "failed", "error": f"{type(error).__name__}: {error}"})
    finally:
        connection.close()


def run_benchmark(
    output: Path,
    *,
    algorithm: str = "heuristic",
    timeout_seconds: float = 600,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Bound the complete run, including Z3's heuristic fallback and validation.

    Only this fixed 10,000-unit workload is accepted. It exceeds the Z3 model
    cap, so the worker cannot spawn any nested Z3 processes. The parent can
    terminate and join it reliably without leaving an optimizer running.
    """
    if not 0 < timeout_seconds <= 86_400:
        raise ValueError("timeout_seconds must be in (0, 86400]")
    request = make_request(algorithm)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    payload = _json(asdict(request))
    (output / "request.json").write_text(payload, encoding="utf-8", newline="\n")
    # A failed rerun must not leave an old result masquerading as its own output.
    result_path = output / "result.json"
    result_path.unlink(missing_ok=True)
    report = {
        "workload": WORKLOAD_ID,
        "status": "running",
        "algorithm_requested": algorithm,
        "items": 10_000,
        "product_types": 100,
        "box_types": 8,
        "request_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "timeout_seconds": timeout_seconds,
        "validated": False,
        "phase": "packing",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "z3_solver": version("z3-solver"),
        },
    }
    (output / "report.json").write_text(_json(report), encoding="utf-8", newline="\n")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker, args=(sender, request, result_path), name="duncarbox-stress-10000"
    )
    started = monotonic()
    next_progress = started
    try:
        process.start()
        sender.close()
        while report["status"] == "running":
            now = monotonic()
            if now - started >= timeout_seconds:
                report.update(status="timeout", error="Whole-run time limit exceeded")
                break
            if progress and now >= next_progress:
                progress(f"{algorithm}: {report['phase']}, elapsed={now - started:.1f}s")
                next_progress = now + 15
            if receiver.poll(min(0.1, timeout_seconds - (now - started))):
                try:
                    report.update(receiver.recv())
                except EOFError:
                    report.update(status="failed", error="Worker exited without a final report")
            elif not process.is_alive():
                report.update(status="failed", error=f"Worker exited with code {process.exitcode}")
    except KeyboardInterrupt:
        report.update(status="interrupted", error="Interrupted by user")
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            process.close()
        report["elapsed_seconds"] = round(monotonic() - started, 3)
        if report["status"] != "passed":
            result_path.unlink(missing_ok=True)
        (output / "report.json").write_text(_json(report), encoding="utf-8", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--algorithm", choices=("heuristic", "z3"), default="heuristic")
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--output", type=Path, help="Directory for request/report/result JSON")
    parser.add_argument("--generate-only", action="store_true", help="Write input without packing")
    arguments = parser.parse_args()
    if not 0 < arguments.timeout_seconds <= 86_400:
        parser.error("--timeout-seconds must be in (0, 86400]")
    output = arguments.output or DEFAULT_OUTPUT / arguments.algorithm
    if arguments.generate_only:
        output.mkdir(parents=True, exist_ok=True)
        path = output / "request.json"
        path.write_text(
            _json(asdict(make_request(arguments.algorithm))), encoding="utf-8", newline="\n"
        )
        print(path.resolve())
        return 0
    print(f"{WORKLOAD_ID}: 10000 units / 100 SKUs / 8 carton types", flush=True)
    report = run_benchmark(
        output,
        algorithm=arguments.algorithm,
        timeout_seconds=arguments.timeout_seconds,
        progress=lambda text: print(text, flush=True),
    )
    print(_json(report), flush=True)
    return 0 if report["status"] == "passed" else 124 if report["status"] == "timeout" else 1


if __name__ == "__main__":
    raise SystemExit(main())
