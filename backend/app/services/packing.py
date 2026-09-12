from collections import Counter
from dataclasses import replace
from fractions import Fraction
from time import monotonic

from app.domain.interfaces import PackingEngine
from app.domain.models import PackedBox, PackingRequest, PackingResult
from app.services.instructions import build_instructions


class PackingService:
    def __init__(self, engine: PackingEngine, progress=None) -> None:
        self._engine = engine
        self._progress = progress

    def pack(self, request: PackingRequest) -> PackingResult:
        started = monotonic()
        result = self._engine.pack(request)
        if self._progress:
            self._progress("instructions", None)
        products = {product.id: product for product in request.products}

        def with_instructions(box: PackedBox) -> PackedBox:
            return replace(box, instructions=build_instructions(box, products))

        def sorted_boxes(boxes):
            counts = Counter()
            completed = []
            for box in sorted(
                boxes,
                key=lambda box: (
                    -Fraction(box.used_volume, box.length * box.width * box.height), box.id
                ),
            ):
                counts[box.box_type_id] += 1
                box = replace(box, id=f"{box.box_type_id}:{counts[box.box_type_id]}")
                completed.append(with_instructions(box))
            return tuple(completed)

        completed = replace(
            result,
            packed_boxes=sorted_boxes(result.packed_boxes),
            alternatives=tuple(
                replace(alt, packed_boxes=sorted_boxes(alt.packed_boxes))
                for alt in result.alternatives
            ),
        )
        return replace(completed, calculation_seconds=round(monotonic() - started, 3))
