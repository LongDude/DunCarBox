"""Deterministic, stock-aware multi-start candidate-point bin packing."""

from collections import Counter, OrderedDict
from dataclasses import dataclass, replace
from fractions import Fraction

from app.domain.models import (
    BoxType,
    Dimensions,
    ItemInstance,
    Orientation,
    PackedBox,
    PackingAlternative,
    PackingMetrics,
    PackingRequest,
    PackingResult,
    Placement,
)
from app.packing.candidates import candidate_points
from app.packing.diagnostics import build_issues
from app.packing.geometry import (
    aabb_intersects,
    fits_inside_box,
    has_support,
    placement_inside_bounds,
)
from app.packing.options import EngineOptions
from app.packing.orientations import unique_orientations
from app.packing.scoring import (
    packing_complexity,
    placement_score,
    solution_score,
    solution_signature,
)
from app.packing.strategies import STRATEGIES, Strategy, expand_items, order_items, volume
from app.packing.validation import validate_solution


@dataclass(frozen=True, slots=True)
class _FilledBox:
    placements: tuple[Placement, ...]
    weight: int
    used_volume: int


def _fill_box(
    box: BoxType,
    items: tuple[ItemInstance, ...],
    orientations: dict[str, tuple[tuple[Orientation, Dimensions], ...]],
    options: EngineOptions,
) -> _FilledBox:
    placements: list[Placement] = []
    packed: set[str] = set()
    weight = used = 0
    occupied_bounds = (0, 0, 0)
    points = candidate_points(box, (), options.max_candidate_points)
    failures: set[tuple] = set()
    available = {
        pid: tuple((code, dims) for code, dims in values if fits_inside_box(dims, box))
        for pid, values in orientations.items()
    }
    for _ in range(options.max_fill_passes):
        count_before = len(placements)
        for item in items:
            if weight == box.max_weight or used == volume(box) or not points:
                break
            if item.id in packed or item.weight + weight > box.max_weight:
                continue
            if used + volume(item) > volume(box):
                continue
            variants = available[item.product_id]
            shape = (variants, item.weight)
            if not variants or shape in failures:
                continue
            best: Placement | None = None
            best_score: tuple | None = None
            for point in points:
                # Candidate order and primary score are both bottom first.
                if best is not None and point.z > best.position.z:
                    break
                for orientation_index, (orientation, dimensions) in enumerate(variants):
                    proposal = Placement(
                        item.id, item.product_id, point, dimensions, orientation, 0
                    )
                    if not placement_inside_bounds(proposal, box):
                        continue
                    if (
                        best_score is not None
                        and max(occupied_bounds[2], point.z + dimensions.height) > best_score[1]
                    ):
                        continue
                    if any(aabb_intersects(proposal, existing) for existing in placements):
                        continue
                    if not has_support(proposal, placements, options.min_support_ratio):
                        continue
                    score = placement_score(
                        proposal,
                        box,
                        placements,
                        orientation_index,
                        occupied_bounds=occupied_bounds,
                    )
                    if best_score is None or score < best_score:
                        best, best_score = proposal, score
            if best is None:
                failures.add(shape)
                continue
            placements.append(best)
            packed.add(item.id)
            weight += item.weight
            used += volume(item)
            occupied_bounds = (
                max(occupied_bounds[0], best.position.x + best.dimensions.length),
                max(occupied_bounds[1], best.position.y + best.dimensions.width),
                max(occupied_bounds[2], best.position.z + best.dimensions.height),
            )
            failures.clear()
            points = candidate_points(box, placements, options.max_candidate_points)
        if count_before == len(placements):
            break
    # Direct supports have a strictly smaller z; this is a topological order.
    ordered = sorted(
        placements,
        key=lambda p: (
            p.position.z,
            p.position.x,
            p.position.y,
            p.product_id,
            int(p.item_instance_id.rsplit(":", 1)[1]),
        ),
    )
    return _FilledBox(
        tuple(replace(p, step=index) for index, p in enumerate(ordered, 1)), weight, used
    )


def _box_score(
    box: BoxType,
    filled: _FilledBox,
    remaining: tuple[ItemInstance, ...],
    stock: dict[str, int],
    compatible: dict[str, tuple[str, ...]],
    policy: str,
) -> tuple:
    selected = {p.item_instance_id for p in filled.placements}
    # Optimistic one-item compatibility lookahead. Avoid spending the last versatile
    # carton on easy goods while leaving an item that only fits that carton behind.
    stranded = sum(
        not any(stock[bid] - (bid == box.id) > 0 for bid in compatible[item.product_id])
        for item in remaining
        if item.id not in selected
    )
    count = len(filled.placements)
    if policy == "count":
        choice = (-count, -filled.used_volume, volume(box))
    elif policy == "smallest":
        choice = (volume(box), -count, -filled.used_volume)
    elif policy == "fill":
        choice = (-Fraction(filled.used_volume, volume(box)), -count, volume(box))
    elif policy == "volume":
        choice = (-filled.used_volume, -count, volume(box))
    else:
        raise ValueError(f"Unknown box policy: {policy}")
    return stranded, *choice, box.id


def _metrics(boxes: tuple[PackedBox, ...], total_items: int) -> PackingMetrics:
    counts = Counter(box.box_type_id for box in boxes)
    total_volume = sum(volume(box) for box in boxes)
    used = sum(box.used_volume for box in boxes)
    packed = sum(len(box.placements) for box in boxes)
    return PackingMetrics(
        total_items=total_items,
        packed_items=packed,
        unpacked_items=total_items - packed,
        boxes_used=len(boxes),
        boxes_by_type=dict(sorted(counts.items())),
        total_box_volume=total_volume,
        used_volume=used,
        empty_volume=total_volume - used,
        fill_ratio=round(used / total_volume, 6) if total_volume else 0,
        total_weight=sum(box.total_weight for box in boxes),
    )


class DeterministicPackingEngine:
    """Implements PackingEngine using domain dataclasses, without HTTP or storage.

    Engine options are immutable and all search state belongs to one call, making
    the instance reentrant. The request's public options still control alternatives.
    """

    version = "candidate-packing-v1"

    def __init__(self, options: EngineOptions | None = None) -> None:
        self.options = options or EngineOptions()
        if self.options != EngineOptions():
            ratio = self.options.min_support_ratio
            self.version = (
                f"{type(self).version}-s{ratio.numerator}of{ratio.denominator}"
                f"-p{self.options.max_candidate_points}-r{self.options.max_strategies}"
                f"-a{self.options.max_alternatives}-f{self.options.max_fill_passes}"
            )

    def pack(self, request: PackingRequest) -> PackingResult:
        items = expand_items(request)
        boxes = {box.id: box for box in sorted(request.boxes, key=lambda box: box.id)}
        orientations = {
            product.id: unique_orientations(
                Dimensions(product.length, product.width, product.height), product.allow_rotation
            )
            for product in request.products
        }
        compatible = {
            product.id: tuple(
                box.id
                for box in boxes.values()
                if product.weight <= box.max_weight
                and any(fits_inside_box(dims, box) for _, dims in orientations[product.id])
            )
            for product in request.products
        }
        possible = tuple(
            item
            for item in items
            if any(boxes[bid].available_count for bid in compatible[item.product_id])
        )
        # Bounded, request-local LRU shares identical trials between starts and box types.
        cache: OrderedDict[tuple, _FilledBox] = OrderedDict()

        def fill(box: BoxType, remaining: tuple[ItemInstance, ...]) -> _FilledBox:
            useful = tuple(item for item in remaining if box.id in compatible[item.product_id])
            key = (
                box.length,
                box.width,
                box.height,
                box.max_weight,
                tuple(item.id for item in useful),
            )
            if key in cache:
                cache.move_to_end(key)
                return cache[key]
            result = _fill_box(box, useful, orientations, self.options)
            cache[key] = result
            if len(cache) > 128:
                cache.popitem(last=False)
            return result

        def search(strategy: Strategy, ordered: tuple[ItemInstance, ...]) -> PackingResult:
            remaining = ordered
            stock = {bid: box.available_count for bid, box in boxes.items()}
            packed_boxes: list[PackedBox] = []
            while remaining:
                best: tuple[BoxType, _FilledBox] | None = None
                best_score: tuple | None = None
                for box in boxes.values():
                    if not stock[box.id]:
                        continue
                    trial = fill(box, remaining)
                    if not trial.placements:
                        continue
                    score = _box_score(
                        box, trial, remaining, stock, compatible, strategy.box_policy
                    )
                    if best_score is None or score < best_score:
                        best, best_score = (box, trial), score
                if best is None:
                    break
                box, trial = best
                stock[box.id] -= 1
                packed_boxes.append(
                    PackedBox(
                        id=f"{box.id}:{box.available_count - stock[box.id]}",
                        box_type_id=box.id,
                        name=box.name,
                        length=box.length,
                        width=box.width,
                        height=box.height,
                        max_weight=box.max_weight,
                        total_weight=trial.weight,
                        used_volume=trial.used_volume,
                        fill_ratio=round(trial.used_volume / volume(box), 6),
                        placements=trial.placements,
                    )
                )
                chosen = {p.item_instance_id for p in trial.placements}
                remaining = tuple(item for item in remaining if item.id not in chosen)
            packed = tuple(packed_boxes)
            chosen = {p.item_instance_id for box in packed for p in box.placements}
            unpacked = tuple(item for item in items if item.id not in chosen)
            metrics = _metrics(packed, len(items))
            result = PackingResult(
                status="success" if not unpacked else "partial" if chosen else "impossible",
                metrics=metrics,
                packed_boxes=packed,
                unpacked_items=unpacked,
                issues=build_issues(request, packed, unpacked),
                algorithm_version=self.version,
            )
            # Every completed candidate is checked, not just the winner.
            validate_solution(request, result, self.options.min_support_ratio)
            return result

        solutions: dict[tuple, tuple[PackingResult, str]] = {}
        tried: set[tuple] = set()
        for strategy in STRATEGIES[: self.options.max_strategies]:
            ordered = order_items(possible, strategy.ordering, compatible, boxes)
            start_key = strategy.box_policy, tuple(item.id for item in ordered)
            if start_key in tried:
                continue
            tried.add(start_key)
            result = search(strategy, ordered)
            signature = solution_signature(result.packed_boxes)
            solutions.setdefault(signature, (result, strategy.name))
        ranked = sorted(solutions.values(), key=lambda pair: solution_score(pair[0], boxes))
        recommended, _ = ranked[0]
        alternatives = []
        limit = (
            min(request.options.max_alternatives, self.options.max_alternatives)
            if request.options.include_alternatives
            else 0
        )
        for result, _ in ranked[1:]:
            # Never offer a plan known to pack fewer units or less product volume.
            if (result.metrics.packed_items, result.metrics.used_volume) != (
                recommended.metrics.packed_items,
                recommended.metrics.used_volume,
            ):
                continue
            if len(alternatives) >= limit:
                break
            alternatives.append(
                PackingAlternative(
                    id=f"alternative-{len(alternatives) + 1}",
                    description=(
                        f"Коробок: {result.metrics.boxes_used}; "
                        f"заполнение: {result.metrics.fill_ratio:.1%}; "
                        f"товаров выше дна: {packing_complexity(result.packed_boxes).raised_items}."
                    ),
                    status=result.status,
                    metrics=result.metrics,
                    packed_boxes=result.packed_boxes,
                    unpacked_items=result.unpacked_items,
                    issues=result.issues,
                )
            )
        alternatives.sort(
            key=lambda alt: (
                alt.metrics.unpacked_items,
                alt.metrics.boxes_used,
                alt.metrics.empty_volume,
                alt.id,
            )
        )
        result = replace(recommended, alternatives=tuple(alternatives))
        validate_solution(request, result, self.options.min_support_ratio)
        return result
