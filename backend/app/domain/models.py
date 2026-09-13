"""Framework-free data contract. Dimensions are millimetres; weights are grams."""

from dataclasses import dataclass, field
from typing import Literal

Orientation = Literal["LWH", "LHW", "WLH", "WHL", "HLW", "HWL"]
PackingStatus = Literal["success", "partial", "impossible"]
PackingAlgorithm = Literal["heuristic", "z3"]
IssueCode = Literal[
    "ITEM_TOO_LARGE",
    "ITEM_TOO_HEAVY",
    "BOX_STOCK_EXHAUSTED",
    "NO_BOX_TYPES",
    "NO_FEASIBLE_PLACEMENT",
    "PARTIAL_PACKING",
    "SIMILAR_ALTERNATIVES",
    "DEMO_STUB",
]


@dataclass(frozen=True, slots=True)
class BoxType:
    id: str
    name: str
    length: int
    width: int
    height: int
    max_weight: int
    available_count: int


@dataclass(frozen=True, slots=True)
class Product:
    id: str
    name: str
    length: int
    width: int
    height: int
    weight: int
    quantity: int
    allow_rotation: bool = True


@dataclass(frozen=True, slots=True)
class ItemInstance:
    id: str
    product_id: str
    name: str
    unit_index: int
    length: int
    width: int
    height: int
    weight: int
    allow_rotation: bool


@dataclass(frozen=True, slots=True)
class Position:
    x: int
    y: int
    z: int


@dataclass(frozen=True, slots=True)
class Dimensions:
    length: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Placement:
    item_instance_id: str
    product_id: str
    position: Position
    dimensions: Dimensions
    orientation: Orientation
    step: int


@dataclass(frozen=True, slots=True)
class PackingInstructionStep:
    step: int
    action: Literal["prepare_box", "place_item", "close_box"]
    box_id: str
    message: str
    item_instance_id: str | None = None
    product_id: str | None = None
    position: Position | None = None
    dimensions: Dimensions | None = None
    orientation: Orientation | None = None


@dataclass(frozen=True, slots=True)
class PackedBox:
    id: str
    box_type_id: str
    name: str
    length: int
    width: int
    height: int
    max_weight: int
    total_weight: int
    used_volume: int
    fill_ratio: float
    placements: tuple[Placement, ...]
    instructions: tuple[PackingInstructionStep, ...] = ()


@dataclass(frozen=True, slots=True)
class PackingMetrics:
    total_items: int
    packed_items: int
    unpacked_items: int
    boxes_used: int
    boxes_by_type: dict[str, int]
    total_box_volume: int
    used_volume: int
    empty_volume: int
    fill_ratio: float
    total_weight: int


@dataclass(frozen=True, slots=True)
class PackingIssue:
    code: IssueCode
    severity: Literal["info", "warning", "error"]
    message: str
    item_instance_ids: tuple[str, ...] = ()
    box_type_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PackingAlternative:
    id: str
    description: str
    status: PackingStatus
    metrics: PackingMetrics
    packed_boxes: tuple[PackedBox, ...]
    unpacked_items: tuple[ItemInstance, ...]
    issues: tuple[PackingIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class PackingOptions:
    include_alternatives: bool = True
    max_alternatives: int = 3
    algorithm: PackingAlgorithm = "heuristic"
    # Deprecated input retained for existing saved orders; engines ignore it.
    solver_timeout_ms: int | None = None
    solver_workers: int = 4


@dataclass(frozen=True, slots=True)
class PackingRequest:
    boxes: tuple[BoxType, ...]
    products: tuple[Product, ...]
    options: PackingOptions = field(default_factory=PackingOptions)


@dataclass(frozen=True, slots=True)
class OptimizationInfo:
    status: Literal["optimal", "feasible", "fallback"]
    reason: Literal["completed", "time_limit", "size_limit", "resource_limit", "solver_error"]
    workers: int
    time_limit_ms: int | None
    support_ratio: float = 1.0


@dataclass(frozen=True, slots=True)
class PackingResult:
    status: PackingStatus
    metrics: PackingMetrics
    packed_boxes: tuple[PackedBox, ...]
    unpacked_items: tuple[ItemInstance, ...]
    issues: tuple[PackingIssue, ...] = ()
    alternatives: tuple[PackingAlternative, ...] = ()
    algorithm_version: str = "demo-stub-v1"
    optimization: OptimizationInfo | None = None
    calculation_seconds: float | None = None
