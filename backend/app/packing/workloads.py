"""Reproducible workloads shared by the menu and command-line benchmarks."""

from app.domain.models import BoxType, PackingOptions, PackingRequest, Product

WORKLOAD_ID = "packing-10000-100sku-8boxes-v1"


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
