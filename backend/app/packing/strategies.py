"""Small, fixed multi-start portfolio; no item permutation search or randomness."""

from dataclasses import dataclass

from app.domain.models import BoxType, ItemInstance, PackingRequest


def volume(value) -> int:
    return value.length * value.width * value.height


def expand_items(request: PackingRequest) -> tuple[ItemInstance, ...]:
    return tuple(
        ItemInstance(
            id=f"{product.id}:{unit}",
            product_id=product.id,
            name=product.name,
            unit_index=unit,
            length=product.length,
            width=product.width,
            height=product.height,
            weight=product.weight,
            allow_rotation=product.allow_rotation,
        )
        for product in sorted(request.products, key=lambda product: product.id)
        for unit in range(1, product.quantity + 1)
    )


@dataclass(frozen=True, slots=True)
class Strategy:
    ordering: str
    box_policy: str

    @property
    def name(self) -> str:
        return f"{self.ordering}-{self.box_policy}"


STRATEGIES = (
    Strategy("scarcity", "count"),
    Strategy("volume", "count"),
    Strategy("max_dimension", "count"),
    Strategy("weight", "count"),
    Strategy("base_area", "count"),
    Strategy("count", "count"),
    Strategy("volume", "smallest"),
    Strategy("max_dimension", "smallest"),
    Strategy("scarcity", "smallest"),
    Strategy("count", "fill"),
    Strategy("volume", "volume"),
    Strategy("base_area", "fill"),
)


def order_items(
    items: tuple[ItemInstance, ...],
    ordering: str,
    compatible: dict[str, tuple[str, ...]],
    boxes: dict[str, BoxType],
) -> tuple[ItemInstance, ...]:
    def key(item: ItemInstance) -> tuple:
        size = volume(item)
        if ordering == "volume":
            primary = (-size,)
        elif ordering == "max_dimension":
            primary = (-max(item.length, item.width, item.height), -size)
        elif ordering == "weight":
            primary = (-item.weight, -size)
        elif ordering == "base_area":
            dims = sorted((item.length, item.width, item.height))
            base = dims[1] * dims[2] if item.allow_rotation else item.length * item.width
            primary = (-base, -size)
        elif ordering == "count":
            primary = (item.weight, size)
        elif ordering == "scarcity":
            supply = sum(boxes[bid].available_count for bid in compatible[item.product_id])
            primary = (supply, -size, -item.weight)
        else:
            raise ValueError(f"Unknown ordering: {ordering}")
        return (*primary, item.product_id, item.unit_index)

    return tuple(sorted(items, key=key))
