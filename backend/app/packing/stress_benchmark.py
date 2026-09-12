"""An opt-in, single-order benchmark: 10,000 units, 100 SKUs, eight carton types.

Run from backend: python -m app.packing.stress_benchmark --timeout-seconds 600
This exercises the same real engine and instruction service as the large-order
menu demo. It never splits the order or truncates the requested goods.
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

from app.domain.models import PackingRequest
from app.packing.dispatcher import PackingEngineDispatcher
from app.packing.validation import validate_solution
from app.packing.workloads import WORKLOAD_ID, make_request
from app.services.packing import PackingService

DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / ".cache" / "stress-10000"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _worker(
    connection: Connection, request: PackingRequest, result_path: Path, cancel_event
) -> None:
    try:
        original = asdict(request)
        started = perf_counter()
        result = PackingService(PackingEngineDispatcher(cancel_event=cancel_event)).pack(request)
        packing_seconds = perf_counter() - started
        connection.send({"phase": "validation"})
        started = perf_counter()
        support = Fraction(1) if request.options.algorithm == "z3" else Fraction(4, 5)
        validate_solution(request, result, support)
        if asdict(request) != original:
            raise AssertionError("Packing mutated the input order")
        if result.status != "success" or result.metrics.packed_items != 10_000:
            raise AssertionError("This feasible workload must pack all 10,000 units")
        if request.options.algorithm == "z3" and result.optimization is None:
            raise AssertionError("Z3 must report its actual optimization outcome")
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

    Cancellation is forwarded to the Z3 controller to reap nested workers
    before stopping the benchmark process.
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
    cancel_event = context.Event()
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker,
        args=(sender, request, result_path, cancel_event),
        name="duncarbox-stress-10000",
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
            cancel_event.set()
            process.join(timeout=5 if algorithm == "z3" else 0)
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
