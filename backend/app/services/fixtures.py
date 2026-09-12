import json
from pathlib import Path

from pydantic import TypeAdapter

from app.domain.models import BoxType, PackingRequest, PackingResult
from app.packing.workloads import make_request
from app.schemas.packing import BoxTypeSchema, PackingRequestSchema, PackingResultSchema


class DemoFixtures:
    """Load and validate trusted, committed fixtures once during application startup."""

    def __init__(self, directory: Path) -> None:
        self.scenarios = json.loads((directory / "scenarios.json").read_text(encoding="utf-8"))
        self._requests: dict[str, PackingRequestSchema] = {}
        pairs = []
        for scenario in self.scenarios:
            scenario_id = scenario["id"]
            request = PackingRequestSchema.model_validate_json(
                (directory / f"{scenario_id}.request.json").read_text(encoding="utf-8")
            )
            response = PackingResultSchema.model_validate_json(
                (directory / f"{scenario_id}.response.json").read_text(encoding="utf-8")
            )
            self._requests[scenario_id] = request
            pairs.append(
                (
                    request.to_domain(),
                    TypeAdapter(PackingResult).validate_python(response.model_dump()),
                )
            )
        self.pairs: tuple[tuple[PackingRequest, PackingResult], ...] = tuple(pairs)
        # This server-only demo is calculated afresh, never replayed from a saved result.
        self.scenarios.append(
            {
                "id": "large-order",
                "name": "Большой заказ: 10 000 предметов · 100 видов · 8 типов коробок",
                "description": (
                    "100 разных товаров по 100 единиц и 8 типов коробок. "
                    "Выберите алгоритм и рассчитайте новый план."
                ),
                "expected_status": "success",
            }
        )
        self._requests["large-order"] = PackingRequestSchema.model_validate(make_request())
        self.catalog: tuple[BoxType, ...] = tuple(
            box.to_domain()
            for box in TypeAdapter(list[BoxTypeSchema]).validate_json(
                (directory / "catalog.boxes.json").read_text(encoding="utf-8")
            )
        )

    def request(self, scenario_id: str) -> PackingRequestSchema | None:
        return self._requests.get(scenario_id)
