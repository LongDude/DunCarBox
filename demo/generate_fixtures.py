"""Rebuild fixed demo snapshots; no placement search or packing optimization.

Every box choice, position and orientation below is authored explicitly.
Run from any directory: python demo/generate_fixtures.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]
Layout = tuple[str, tuple[int, int, int], str]
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))

from app.domain.models import Dimensions, PackedBox, Placement, Position, Product  # noqa: E402
from app.services.instructions import build_instructions  # noqa: E402


def box(identifier: str, size: tuple[int, int, int], weight: int, stock: int) -> JsonObject:
    return dict(
        id=identifier,
        name=f"Коробка {identifier[-1].upper()}",
        length=size[0],
        width=size[1],
        height=size[2],
        max_weight=weight,
        available_count=stock,
    )


def product(
    identifier: str,
    name: str,
    size: tuple[int, int, int],
    weight: int,
    quantity: int,
    rotate: bool = True,
) -> JsonObject:
    return dict(
        id=identifier,
        name=name,
        length=size[0],
        width=size[1],
        height=size[2],
        weight=weight,
        quantity=quantity,
        allow_rotation=rotate,
    )


def volume(value: JsonObject) -> int:
    return value["length"] * value["width"] * value["height"]


def item_instance(value: JsonObject, unit: int) -> JsonObject:
    return {
        key: value[key] for key in ("name", "length", "width", "height", "weight", "allow_rotation")
    } | {"id": f"{value['id']}:{unit}", "product_id": value["id"], "unit_index": unit}


def issue(
    code: str,
    severity: str,
    message: str,
    items: list[str] | None = None,
    boxes: list[str] | None = None,
) -> JsonObject:
    return dict(
        code=code,
        severity=severity,
        message=message,
        item_instance_ids=items or [],
        box_type_ids=boxes or [],
    )


def fixed_box(
    value: JsonObject, index: int, products: list[JsonObject], layout: list[Layout]
) -> JsonObject:
    """Serialize an explicitly specified box; never decide where an item goes."""
    by_product = {entry["id"]: entry for entry in products}
    box_id = f"{value['id']}:{index}"
    placements: list[JsonObject] = []
    for step, (item_id, point, orientation) in enumerate(layout, 1):
        entry = by_product[item_id.rsplit(":", 1)[0]]
        axes = dict(L=entry["length"], W=entry["width"], H=entry["height"])
        dimensions = dict(
            zip(("length", "width", "height"), (axes[axis] for axis in orientation), strict=True)
        )
        placement = dict(
            item_instance_id=item_id,
            product_id=entry["id"],
            position=dict(zip(("x", "y", "z"), point, strict=True)),
            dimensions=dimensions,
            orientation=orientation,
            step=step,
        )
        placements.append(placement)
    weight = sum(by_product[item_id.rsplit(":", 1)[0]]["weight"] for item_id, _, _ in layout)
    used = sum(volume(placement["dimensions"]) for placement in placements)
    snapshot = {
        key: value[key] for key in ("name", "length", "width", "height", "max_weight")
    } | dict(
        id=box_id,
        box_type_id=value["id"],
        total_weight=weight,
        used_volume=used,
        fill_ratio=round(used / volume(value), 6),
    )
    domain_placements = tuple(
        Placement(
            **(
                entry
                | dict(
                    position=Position(**entry["position"]),
                    dimensions=Dimensions(**entry["dimensions"]),
                )
            )
        )
        for entry in placements
    )
    domain_box = PackedBox(**snapshot, placements=domain_placements)
    instructions = build_instructions(
        domain_box, {entry["id"]: Product(**entry) for entry in products}
    )
    return snapshot | dict(
        placements=placements, instructions=[asdict(step) for step in instructions]
    )


def save(name: str, value: Any) -> None:
    (ROOT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def scenario(
    identifier: str,
    status: str,
    boxes: list[JsonObject],
    products: list[JsonObject],
    packed: list[JsonObject],
    unpacked: list[JsonObject] | None = None,
    issues: list[JsonObject] | None = None,
) -> None:
    unpacked = unpacked or []
    issues = (issues or []) + [
        issue(
            "DEMO_STUB",
            "info",
            "Демонстрационный фиксированный план. Алгоритм упаковки ещё не подключён; оптимальность не проверялась.",
        )
    ]
    used = sum(entry["used_volume"] for entry in packed)
    box_volume = sum(volume(entry) for entry in packed)
    save(
        f"{identifier}.request.json",
        dict(
            boxes=boxes,
            products=products,
            options=dict(include_alternatives=True, max_alternatives=3),
        ),
    )
    save(
        f"{identifier}.response.json",
        dict(
            status=status,
            metrics=dict(
                total_items=sum(entry["quantity"] for entry in products),
                packed_items=sum(len(entry["placements"]) for entry in packed),
                unpacked_items=len(unpacked),
                boxes_used=len(packed),
                boxes_by_type=dict(
                    sorted(Counter(entry["box_type_id"] for entry in packed).items())
                ),
                total_box_volume=box_volume,
                used_volume=used,
                empty_volume=box_volume - used,
                fill_ratio=round(used / box_volume, 6) if box_volume else 0,
                total_weight=sum(entry["total_weight"] for entry in packed),
            ),
            packed_boxes=packed,
            unpacked_items=unpacked,
            issues=sorted(issues, key=lambda entry: (entry["code"], entry["item_instance_ids"])),
            alternatives=[],
            algorithm_version="demo-stub-v1",
        ),
    )


def main() -> None:
    small = box("box-s", (300, 200, 150), 5000, 5)
    medium = box("box-m", (400, 300, 250), 10000, 3)
    large = box("box-l", (500, 350, 300), 15000, 2)
    save("catalog.boxes.json", [large, medium, small])

    tea = product("tea", "Чай, подарочная упаковка", (100, 80, 60), 250, 2)
    scenario(
        "simple-order",
        "success",
        [small],
        [tea],
        [fixed_box(small, 1, [tea], [("tea:1", (0, 0, 0), "LWH"), ("tea:2", (100, 0, 0), "LWH")])],
    )

    appliances = [
        product("filters", "Набор фильтров для воды", (120, 80, 40), 150, 2),
        product("kettle", "Чайник в заводской упаковке", (220, 160, 200), 1100, 2, False),
        product("thermos", "Термос в индивидуальной коробке", (70, 70, 190), 350, 2, False),
    ]
    scenario(
        "multiple-boxes",
        "success",
        [medium],
        appliances,
        [
            fixed_box(
                medium,
                1,
                appliances,
                [
                    ("kettle:1", (0, 0, 0), "LWH"),
                    ("filters:1", (220, 0, 0), "WLH"),
                    ("thermos:1", (300, 0, 0), "LWH"),
                ],
            ),
            fixed_box(
                medium,
                2,
                appliances,
                [
                    ("kettle:2", (0, 0, 0), "LWH"),
                    ("filters:2", (220, 0, 0), "WLH"),
                    ("thermos:2", (300, 0, 0), "LWH"),
                ],
            ),
        ],
    )

    poster = product("poster", "Постер в прямоугольном тубусе", (650, 80, 80), 700, 1)
    scenario(
        "oversized",
        "impossible",
        [medium, small],
        [poster],
        [],
        [item_instance(poster, 1)],
        [
            issue(
                "ITEM_TOO_LARGE",
                "error",
                "Тубус длиной 650 мм не помещается ни в одну доступную коробку ни при одном разрешённом повороте: наибольшая сторона коробки — 400 мм.",
                ["poster:1"],
                ["box-m", "box-s"],
            )
        ],
    )

    gift = product("gift-set", "Подарочный набор посуды", (280, 180, 140), 1800, 3, False)
    last_small = small | dict(available_count=1)
    absent_medium = medium | dict(available_count=0)
    remaining_ids = ["gift-set:2", "gift-set:3"]
    scenario(
        "stock-shortage",
        "partial",
        [absent_medium, last_small],
        [gift],
        [fixed_box(last_small, 1, [gift], [("gift-set:1", (0, 0, 0), "LWH")])],
        [item_instance(gift, 2), item_instance(gift, 3)],
        [
            issue(
                "BOX_STOCK_EXHAUSTED",
                "warning",
                "В наличии только одна коробка S, в которую помещается один набор. Коробок M на складе нет. Для двух оставшихся наборов не хватает коробок.",
                remaining_ids,
                ["box-m", "box-s"],
            ),
            issue(
                "PARTIAL_PACKING",
                "warning",
                "Упакован 1 из 3 наборов. Два набора остаются неупакованными.",
                remaining_ids,
            ),
        ],
    )
    save(
        "scenarios.json",
        [
            dict(
                id="simple-order",
                name="Простой заказ",
                description="Две подарочные упаковки чая в одной коробке S.",
                expected_status="success",
            ),
            dict(
                id="multiple-boxes",
                name="Несколько коробок",
                description="Два чайника с фильтрами и термосами в двух коробках M; показан поворот товара.",
                expected_status="success",
            ),
            dict(
                id="oversized",
                name="Товар не помещается",
                description="Тубус длиной 650 мм превышает размеры всех предложенных коробок.",
                expected_status="impossible",
            ),
            dict(
                id="stock-shortage",
                name="Нехватка коробок",
                description="Для трёх подарочных наборов осталась только одна подходящая коробка.",
                expected_status="partial",
            ),
        ],
    )


if __name__ == "__main__":
    main()
