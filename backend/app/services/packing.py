from dataclasses import replace

from app.domain.interfaces import PackingEngine
from app.domain.models import PackedBox, PackingRequest, PackingResult
from app.services.instructions import build_instructions


class PackingService:
    def __init__(self, engine: PackingEngine) -> None:
        self._engine = engine

    def pack(self, request: PackingRequest) -> PackingResult:
        result = self._engine.pack(request)
        products = {product.id: product for product in request.products}

        def with_instructions(box: PackedBox) -> PackedBox:
            return replace(box, instructions=build_instructions(box, products))

        return replace(
            result,
            packed_boxes=tuple(with_instructions(box) for box in result.packed_boxes),
            alternatives=tuple(
                replace(alt, packed_boxes=tuple(with_instructions(box) for box in alt.packed_boxes))
                for alt in result.alternatives
            ),
        )
