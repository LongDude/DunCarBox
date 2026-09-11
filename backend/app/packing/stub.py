from copy import deepcopy
from dataclasses import replace

from app.domain.errors import EngineNotImplementedError
from app.domain.models import PackingRequest, PackingResult


class DemoPackingEngine:
    """Exact fixture playback only. This class deliberately performs no packing."""

    version = "demo-stub-v1"

    def __init__(self, fixtures: tuple[tuple[PackingRequest, PackingResult], ...]) -> None:
        self._fixtures = deepcopy(fixtures)

    def pack(self, request: PackingRequest) -> PackingResult:
        boxes = tuple(sorted(request.boxes, key=lambda box: box.id))
        products = tuple(sorted(request.products, key=lambda product: product.id))
        for fixture_request, fixture_result in self._fixtures:
            if boxes == fixture_request.boxes and products == fixture_request.products:
                result = deepcopy(fixture_result)
                count = (
                    request.options.max_alternatives if request.options.include_alternatives else 0
                )
                return replace(result, alternatives=result.alternatives[:count])
        raise EngineNotImplementedError(
            "Доступны только демонстрационные сценарии. Расчёт произвольного заказа "
            "будет доступен после подключения packing engine."
        )
