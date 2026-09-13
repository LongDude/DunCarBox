"""Contract-ordered, unique orthogonal rotations; no geometric approximation."""

from app.domain.models import Dimensions, Orientation

ORIENTATION_ORDER: tuple[Orientation, ...] = ("LWH", "LHW", "WLH", "WHL", "HLW", "HWL")


def unique_orientations(
    dimensions: Dimensions, allow_rotation: bool = True
) -> tuple[tuple[Orientation, Dimensions], ...]:
    """Yaw is always allowed; allow_rotation additionally permits changing the base.

    Keep the first allowed contract label when equal sides duplicate geometry.
    """
    axes = {"L": dimensions.length, "W": dimensions.width, "H": dimensions.height}
    seen: set[Dimensions] = set()
    result: list[tuple[Orientation, Dimensions]] = []
    for orientation in ORIENTATION_ORDER if allow_rotation else ("LWH", "WLH"):
        rotated = Dimensions(*(axes[axis] for axis in orientation))
        if rotated not in seen:
            seen.add(rotated)
            result.append((orientation, rotated))
    return tuple(result)
