"""Integer AABB geometry in contract axes: x right, y back, z up."""

from collections.abc import Iterable
from fractions import Fraction

from app.domain.models import BoxType, Dimensions, PackedBox, Placement

Box = BoxType | PackedBox
Rectangle = tuple[int, int, int, int]


def fits_inside_box(dimensions: Dimensions, box: Box) -> bool:
    """Test one specific orientation against the box's internal dimensions."""
    return (
        0 < dimensions.length <= box.length
        and 0 < dimensions.width <= box.width
        and 0 < dimensions.height <= box.height
    )


def placement_inside_bounds(placement: Placement, box: Box) -> bool:
    p, d = placement.position, placement.dimensions
    return (
        fits_inside_box(d, box)
        and 0 <= p.x <= box.length - d.length
        and 0 <= p.y <= box.width - d.width
        and 0 <= p.z <= box.height - d.height
    )


def aabb_intersects(a: Placement, b: Placement) -> bool:
    """Only positive-volume intersection collides; touching faces/edges do not."""
    ap, ad, bp, bd = a.position, a.dimensions, b.position, b.dimensions
    return (
        ap.x < bp.x + bd.length
        and bp.x < ap.x + ad.length
        and ap.y < bp.y + bd.width
        and bp.y < ap.y + ad.width
        and ap.z < bp.z + bd.height
        and bp.z < ap.z + ad.height
        and ad.length > 0
        and ad.width > 0
        and ad.height > 0
        and bd.length > 0
        and bd.width > 0
        and bd.height > 0
    )


def supporting_rectangle(placement: Placement, below: Placement) -> Rectangle | None:
    """Positive contact rectangle if ``below`` ends exactly at the bottom face."""
    p, d, bp, bd = placement.position, placement.dimensions, below.position, below.dimensions
    if bp.z + bd.height != p.z:
        return None
    x0, x1 = max(p.x, bp.x), min(p.x + d.length, bp.x + bd.length)
    y0, y1 = max(p.y, bp.y), min(p.y + d.width, bp.y + bd.width)
    return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def _rectangle_union_area(rectangles: list[Rectangle]) -> int:
    """Sweep integer x strips and merge y intervals; shared support counts once."""
    if not rectangles:
        return 0
    if len(rectangles) == 1:
        x0, y0, x1, y1 = rectangles[0]
        return (x1 - x0) * (y1 - y0)
    xs = sorted({x for x0, _, x1, _ in rectangles for x in (x0, x1)})
    area = 0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted((y0, y1) for x0, y0, x1, y1 in rectangles if x0 < right and x1 > left)
        covered = 0
        end = 0
        for low, high in intervals:
            covered += max(0, high - max(low, end))
            end = max(end, high)
        area += (right - left) * covered
    return area


def support_area(placement: Placement, placements: Iterable[Placement]) -> int:
    """Return exact supported bottom area in mm², including the box floor."""
    if placement.position.z == 0:
        return placement.dimensions.length * placement.dimensions.width
    rectangles = [
        rectangle
        for below in placements
        if (rectangle := supporting_rectangle(placement, below)) is not None
    ]
    return _rectangle_union_area(rectangles)


def support_ratio(placement: Placement, placements: Iterable[Placement]) -> float:
    """A reporting value; hard constraints should use ``has_support`` instead."""
    bottom_area = placement.dimensions.length * placement.dimensions.width
    return support_area(placement, placements) / bottom_area if bottom_area > 0 else 0.0


def has_support(
    placement: Placement,
    placements: Iterable[Placement],
    min_support_ratio: Fraction = Fraction(4, 5),
) -> bool:
    """Compare integer areas without epsilon; even threshold zero forbids floating."""
    if not 0 <= min_support_ratio <= 1:
        raise ValueError("min_support_ratio must be between 0 and 1")
    bottom_area = placement.dimensions.length * placement.dimensions.width
    if bottom_area <= 0 or placement.position.z < 0:
        return False
    area = support_area(placement, placements)
    return area > 0 and (
        area * min_support_ratio.denominator >= bottom_area * min_support_ratio.numerator
    )
