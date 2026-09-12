from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain import models as domain

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Dimension = Annotated[int, Field(strict=True, gt=0, le=100_000)]
Weight = Annotated[int, Field(strict=True, gt=0, le=100_000_000)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Ratio = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class BoxTypeSchema(ContractModel):
    id: Identifier
    name: Name
    length: Dimension
    width: Dimension
    height: Dimension
    max_weight: Weight
    available_count: NonNegativeInt

    def to_domain(self) -> domain.BoxType:
        return domain.BoxType(**self.model_dump())


class ProductSchema(ContractModel):
    id: Identifier
    name: Name
    length: Dimension
    width: Dimension
    height: Dimension
    weight: Weight
    quantity: PositiveInt
    allow_rotation: Annotated[bool, Field(strict=True)] = True

    def to_domain(self) -> domain.Product:
        return domain.Product(**self.model_dump())


class PackingOptionsSchema(ContractModel):
    include_alternatives: Annotated[bool, Field(strict=True)] = True
    max_alternatives: Annotated[int, Field(strict=True, ge=0, le=5)] = 3
    algorithm: domain.PackingAlgorithm = "heuristic"
    solver_timeout_ms: PositiveInt = 10_000
    solver_workers: PositiveInt = 4


class PackingRequestSchema(ContractModel):
    boxes: list[BoxTypeSchema]
    products: Annotated[list[ProductSchema], Field(min_length=1)]
    options: PackingOptionsSchema = Field(default_factory=PackingOptionsSchema)

    @model_validator(mode="after")
    def validate_order(self) -> "PackingRequestSchema":
        for name, entries in (("boxes", self.boxes), ("products", self.products)):
            ids = [entry.id for entry in entries]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name}: duplicate id")
        return self

    def to_domain(self) -> domain.PackingRequest:
        return domain.PackingRequest(
            boxes=tuple(box.to_domain() for box in sorted(self.boxes, key=lambda box: box.id)),
            products=tuple(
                product.to_domain()
                for product in sorted(self.products, key=lambda product: product.id)
            ),
            options=domain.PackingOptions(**self.options.model_dump()),
        )


class PositionSchema(ContractModel):
    x: NonNegativeInt
    y: NonNegativeInt
    z: NonNegativeInt


class DimensionsSchema(ContractModel):
    length: Dimension
    width: Dimension
    height: Dimension


class ItemInstanceSchema(ContractModel):
    id: str
    product_id: Identifier
    name: Name
    unit_index: PositiveInt
    length: Dimension
    width: Dimension
    height: Dimension
    weight: Weight
    allow_rotation: bool


class PlacementSchema(ContractModel):
    item_instance_id: str
    product_id: Identifier
    position: PositionSchema
    dimensions: DimensionsSchema
    orientation: domain.Orientation
    step: PositiveInt


class PackingInstructionStepSchema(ContractModel):
    step: NonNegativeInt
    action: Literal["prepare_box", "place_item", "close_box"]
    box_id: str
    message: str
    item_instance_id: str | None = None
    product_id: Identifier | None = None
    position: PositionSchema | None = None
    dimensions: DimensionsSchema | None = None
    orientation: domain.Orientation | None = None


class PackedBoxSchema(ContractModel):
    id: str
    box_type_id: Identifier
    name: Name
    length: Dimension
    width: Dimension
    height: Dimension
    max_weight: Weight
    total_weight: NonNegativeInt
    used_volume: NonNegativeInt
    fill_ratio: Ratio
    placements: list[PlacementSchema]
    instructions: list[PackingInstructionStepSchema]


class PackingMetricsSchema(ContractModel):
    total_items: NonNegativeInt
    packed_items: NonNegativeInt
    unpacked_items: NonNegativeInt
    boxes_used: NonNegativeInt
    boxes_by_type: dict[str, NonNegativeInt]
    total_box_volume: NonNegativeInt
    used_volume: NonNegativeInt
    empty_volume: NonNegativeInt
    fill_ratio: Ratio
    total_weight: NonNegativeInt


class PackingIssueSchema(ContractModel):
    code: domain.IssueCode
    severity: Literal["info", "warning", "error"]
    message: str
    item_instance_ids: list[str]
    box_type_ids: list[Identifier]


class PackingAlternativeSchema(ContractModel):
    id: str
    description: str
    status: domain.PackingStatus
    metrics: PackingMetricsSchema
    packed_boxes: list[PackedBoxSchema]
    unpacked_items: list[ItemInstanceSchema]
    issues: list[PackingIssueSchema]


class OptimizationInfoSchema(ContractModel):
    status: Literal["optimal", "feasible", "fallback"]
    reason: Literal["completed", "time_limit", "size_limit", "solver_error"]
    workers: NonNegativeInt
    time_limit_ms: PositiveInt
    support_ratio: Ratio = 1.0


class PackingResultSchema(ContractModel):
    status: domain.PackingStatus
    metrics: PackingMetricsSchema
    packed_boxes: list[PackedBoxSchema]
    unpacked_items: list[ItemInstanceSchema]
    issues: list[PackingIssueSchema]
    alternatives: list[PackingAlternativeSchema]
    algorithm_version: str
    optimization: OptimizationInfoSchema | None = None
    calculation_seconds: float | None = Field(default=None, ge=0)
