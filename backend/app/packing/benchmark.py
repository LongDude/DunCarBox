"""Deterministic scenarios; timings are printed, never added to PackingResult.

Run from backend: python -m app.packing.benchmark --repeat 3 [--stress]
The benchmark uses only the standard library and domain/engine modules.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter

from app.domain.models import BoxType, PackingOptions, PackingRequest, Product
from app.packing.engine import DeterministicPackingEngine
from app.packing.validation import validate_solution


def _read_demo(path: Path) -> PackingRequest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PackingRequest(
        boxes=tuple(BoxType(**entry) for entry in payload["boxes"]),
        products=tuple(Product(**entry) for entry in payload["products"]),
        options=PackingOptions(**payload.get("options", {})),
    )


def benchmark_scenarios(stress: bool = False) -> tuple[tuple[str, PackingRequest], ...]:
    demo_dir = Path(__file__).resolve().parents[3] / "demo"
    scenarios = [
        (path.name.removesuffix(".request.json"), _read_demo(path))
        for path in sorted(demo_dir.glob("*.request.json"))
    ]
    scenarios.extend(
        [
            (
                "cube-layers-64",
                PackingRequest(
                    (BoxType("cube", "Cube", 200, 200, 200, 10000, 2),),
                    (Product("unit", "Unit", 50, 50, 50, 100, 64),),
                ),
            ),
            (
                "mixed-shapes-24",
                PackingRequest(
                    (
                        BoxType("small", "Small", 180, 140, 100, 3000, 3),
                        BoxType("medium", "Medium", 280, 200, 180, 8000, 3),
                        BoxType("large", "Large", 400, 300, 250, 15000, 2),
                    ),
                    (
                        Product("book", "Book", 160, 100, 30, 450, 6, False),
                        Product("bottle", "Bottle", 50, 50, 160, 300, 6, False),
                        Product("kit", "Kit", 90, 70, 60, 200, 6),
                        Product("snack", "Snack", 60, 40, 30, 80, 6),
                    ),
                ),
            ),
            (
                "weight-limited-18",
                PackingRequest(
                    (
                        BoxType("light", "Light", 200, 200, 200, 1000, 4),
                        BoxType("strong", "Strong", 180, 180, 180, 5000, 2),
                    ),
                    (
                        Product("dense", "Dense", 50, 50, 50, 900, 10),
                        Product("light", "Light", 60, 40, 30, 100, 8),
                    ),
                ),
            ),
            (
                "scarce-versatile-box",
                PackingRequest(
                    (
                        BoxType("versatile", "Versatile", 100, 100, 100, 1000, 1),
                        BoxType("narrow", "Narrow", 80, 100, 100, 1000, 1),
                    ),
                    (
                        Product("large", "Large", 90, 100, 100, 100, 1, False),
                        Product("small", "Small", 80, 100, 100, 100, 1, False),
                    ),
                ),
            ),
        ]
    )
    if stress:
        scenarios.extend(
            [
                (
                    "stress-identical-216",
                    PackingRequest(
                        (BoxType("bulk", "Bulk", 300, 300, 300, 50000, 2),),
                        (Product("unit", "Unit", 50, 50, 50, 100, 216),),
                    ),
                ),
                (
                    "stress-mixed-120",
                    PackingRequest(
                        (
                            BoxType("small", "Small", 200, 150, 120, 5000, 10),
                            BoxType("bulk", "Bulk", 400, 300, 250, 20000, 8),
                        ),
                        tuple(
                            Product(
                                f"p{index:02d}",
                                f"Product {index}",
                                40 + index * 7,
                                30 + index % 4 * 10,
                                20 + index % 3 * 20,
                                100 + index * 30,
                                10,
                                index % 3 != 0,
                            )
                            for index in range(12)
                        ),
                    ),
                ),
            ]
        )
    return tuple(scenarios)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1, help="Runs per scenario (default: 1)")
    parser.add_argument("--stress", action="store_true", help="Include larger synthetic orders")
    arguments = parser.parse_args()
    if arguments.repeat < 1:
        parser.error("--repeat must be positive")

    engine = DeterministicPackingEngine()
    print(
        f"{'scenario':27} {'items':>5} {'packed':>6} {'boxes':>5} {'fill':>8} {'ms':>10} issues",
        flush=True,
    )
    for name, request in benchmark_scenarios(arguments.stress):
        timings = []
        expected = None
        for _ in range(arguments.repeat):
            started = perf_counter()
            result = engine.pack(request)
            timings.append((perf_counter() - started) * 1000)
            validate_solution(request, result)
            normalized = asdict(result)
            if expected is not None and normalized != expected:
                raise AssertionError(f"Nondeterministic output: {name}")
            expected = normalized
        metrics = result.metrics
        issues = ",".join(sorted({issue.code for issue in result.issues})) or "-"
        print(
            f"{name:27} {metrics.total_items:5} {metrics.packed_items:6} "
            f"{metrics.boxes_used:5} {metrics.fill_ratio:8.2%} {median(timings):10.2f} {issues}",
            flush=True,
        )


if __name__ == "__main__":
    main()
