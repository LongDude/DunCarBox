"""Explain leftovers without confusing a heuristic failure with a proof."""

from collections import Counter, defaultdict
from itertools import permutations

from app.domain.models import (
    BoxType,
    ItemInstance,
    PackedBox,
    PackingIssue,
    PackingRequest,
)


def _fits(item: ItemInstance, box: BoxType) -> bool:
    dimensions = (item.length, item.width, item.height)
    orientations = (
        set(permutations(dimensions))
        if item.allow_rotation
        else (
            dimensions,
            (item.width, item.length, item.height),
        )
    )
    return any(
        length <= box.length and width <= box.width and height <= box.height
        for length, width, height in orientations
    )


def build_issues(
    request: PackingRequest,
    packed_boxes: tuple[PackedBox, ...],
    unpacked_items: tuple[ItemInstance, ...],
) -> tuple[PackingIssue, ...]:
    """Classify individual items against all types, including zero-stock types.

    A depleted current plan can still be improved by repacking its opened boxes.
    Therefore that case carries an explicit heuristic-failure issue as well.
    """
    if not unpacked_items:
        return ()
    used = Counter(box.box_type_id for box in packed_boxes)
    grouped = defaultdict(list)

    def add(code, severity, message, item, boxes=()):
        key = (code, severity, message, tuple(sorted(box.id for box in boxes)))
        grouped[key].append(item.id)

    for item in sorted(unpacked_items, key=lambda value: (value.product_id, value.unit_index)):
        if not request.boxes:
            add("NO_BOX_TYPES", "error", "В запросе не указаны типы транспортных коробок.", item)
            continue
        fitting = tuple(box for box in request.boxes if _fits(item, box))
        if not fitting:
            add(
                "ITEM_TOO_LARGE",
                "error",
                "Ни одна разрешённая ориентация товара не помещается ни в один тип коробки.",
                item,
                request.boxes,
            )
            continue
        suitable = tuple(box for box in fitting if item.weight <= box.max_weight)
        if not suitable:
            add(
                "ITEM_TOO_HEAVY",
                "error",
                "Вес одной единицы превышает предел всех подходящих по размерам коробок.",
                item,
                fitting,
            )
            continue
        exhausted = all(used[box.id] >= box.available_count for box in suitable)
        if exhausted:
            initially_empty = all(box.available_count == 0 for box in suitable)
            add(
                "BOX_STOCK_EXHAUSTED",
                "error" if initially_empty else "warning",
                "На складе нет ни одной подходящей по размерам и весу коробки."
                if initially_empty
                else "В текущем плане использован весь запас подходящих коробок; "
                "возможность перераспределения товаров не исключена.",
                item,
                suitable,
            )
            if initially_empty:
                continue
        add(
            "NO_FEASIBLE_PLACEMENT",
            "warning",
            "Товар не включён в выбранный план с приоритетом общего заполнения. "
            "Это не доказывает невозможность его упаковки в другом плане.",
            item,
            suitable,
        )
    issues = [
        PackingIssue(code, severity, message, tuple(sorted(ids)), box_ids)
        for (code, severity, message, box_ids), ids in grouped.items()
    ]
    if any(box.placements for box in packed_boxes):
        issues.append(
            PackingIssue(
                "PARTIAL_PACKING",
                "warning",
                "Заказ упакован частично; причины указаны для каждой неуложенной единицы.",
                tuple(sorted(item.id for item in unpacked_items)),
            )
        )
    return tuple(sorted(issues, key=lambda issue: (issue.code, issue.item_instance_ids)))
