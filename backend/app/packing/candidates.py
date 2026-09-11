"""Bounded extreme points, projected toward walls and preceding item faces."""

from collections.abc import Sequence

from app.domain.models import BoxType, PackedBox, Placement, Position

Box = BoxType | PackedBox
Solid = tuple[int, int, int, int, int, int]


def _solid(placement: Placement) -> Solid:
    p, d = placement.position, placement.dimensions
    return p.x, p.y, p.z, p.x + d.length, p.y + d.width, p.z + d.height


def _inside_box(point: Position, box: Box) -> bool:
    # A positive-sized item cannot start at an outer maximum face.
    return 0 <= point.x < box.length and 0 <= point.y < box.width and 0 <= point.z < box.height


def _occupied(point: Position, solid: Solid) -> bool:
    x0, y0, z0, x1, y1, z1 = solid
    return x0 <= point.x < x1 and y0 <= point.y < y1 and z0 <= point.z < z1


def point_is_valid(point: Position, box: Box, placements: Sequence[Placement]) -> bool:
    """Reject points in half-open occupied solids, including their minimum faces."""
    return _inside_box(point, box) and not any(_occupied(point, _solid(p)) for p in placements)


def _point_order(point: Position) -> tuple[int, int, int, int]:
    return point.z, point.x + point.y, point.x, point.y


def _valid_points(points: set[Position], box: Box, solids: list[Solid]) -> list[Position]:
    """Sweep x so validity checks visit only solids that overlap the point's x."""
    ordered = sorted((p for p in points if _inside_box(p, box)), key=lambda p: (p.x, p.y, p.z))
    starts = sorted(solids)
    active: list[Solid] = []
    cursor = 0
    valid: list[Position] = []
    for point in ordered:
        while cursor < len(starts) and starts[cursor][0] <= point.x:
            active.append(starts[cursor])
            cursor += 1
        active = [solid for solid in active if solid[3] > point.x]
        if not any(_occupied(point, solid) for solid in active):
            valid.append(point)
    return sorted(valid, key=_point_order)


def _project(point: Position, axis: int, solids: list[Solid]) -> Position:
    target = 0
    x, y, z = point.x, point.y, point.z
    if axis == 0:
        if x == 0:
            return point
        for _, y0, z0, x1, y1, z1 in solids:
            if target < x1 <= x and y0 <= y < y1 and z0 <= z < z1:
                target = x1
        return point if target == x else Position(target, y, z)
    if axis == 1:
        if y == 0:
            return point
        for x0, _, z0, x1, y1, z1 in solids:
            if target < y1 <= y and x0 <= x < x1 and z0 <= z < z1:
                target = y1
        return point if target == y else Position(x, target, z)
    if z == 0:
        return point
    for x0, y0, _, x1, y1, z1 in solids:
        if target < z1 <= z and x0 <= x < x1 and y0 <= y < y1:
            target = z1
    return point if target == z else Position(x, y, target)


def candidate_points(
    box: Box, placements: Sequence[Placement], max_points: int = 128
) -> tuple[Position, ...]:
    """Return a stable, capped frontier, not an exhaustive coordinate grid.

    Every placed item contributes its three positive-face corners. For the first
    ``max_points`` valid corners, project toward each negative axis and both x/y
    projection orders to recover useful floor and wall intersections. Projections
    cannot cross an occupied solid at the point. Final AABB/support checks still
    decide whether an actual item fits there.

    Coordinate dominance alone is not safe: a farther point can access a cavity
    or a supporting face. Only duplicates, occupied points and bounds are pruned;
    the final deterministic cap is an explicit heuristic search limit.
    """
    if max_points < 1:
        raise ValueError("max_points must be positive")
    solids = [_solid(placement) for placement in placements]
    corners = {Position(0, 0, 0)}
    for x0, y0, z0, x1, y1, z1 in solids:
        corners.update((Position(x1, y0, z0), Position(x0, y1, z0), Position(x0, y0, z1)))
    frontier = _valid_points(corners, box, solids)
    projected: set[Position] = set()
    for point in frontier[:max_points]:
        px, py, pz = (_project(point, axis, solids) for axis in range(3))
        projected.update((px, py, pz, _project(px, 1, solids), _project(py, 0, solids)))
    valid = set(frontier)
    valid.update(_valid_points(projected, box, solids))
    return tuple(sorted(valid, key=_point_order)[:max_points])
