"""Contract-ordered, unique orthogonal rotations; no geometric approximation."""

from app.domain.models import Dimensions, Orientation

ORIENTATION_ORDER: tuple[Orientation, ...] = ("LWH", "LHW", "WLH", "WHL", "HLW", "HWL")


def unique_orientations(
    dimensions: Dimensions, allow_rotation: bool = True
) -> tuple[tuple[Orientation, Dimensions], ...]:
    """Keep the first contract label when equal sides produce duplicate rotations."""
    if not allow_rotation:
        return (("LWH", dimensions),)
    axes = {"L": dimensions.length, "W": dimensions.width, "H": dimensions.height}
    seen: set[Dimensions] = set()
    result: list[tuple[Orientation, Dimensions]] = []
    for orientation in ORIENTATION_ORDER:
        rotated = Dimensions(*(axes[axis] for axis in orientation))
        if rotated not in seen:
            seen.add(rotated)
            result.append((orientation, rotated))
    return tuple(result)
