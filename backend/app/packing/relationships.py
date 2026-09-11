"""Structured spatial relationships for the existing service instruction layer."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models import Placement
from app.packing.geometry import supporting_rectangle


@dataclass(frozen=True, slots=True)
class PlacementRelationships:
    """Internal metadata derived from placements; does not extend the v1 DTO."""

    item_instance_id: str
    on_floor: bool
    supported_by: tuple[str, ...]
    right_of: tuple[str, ...]
    behind: tuple[str, ...]


def placement_relationships(
    placements: Sequence[Placement],
) -> tuple[PlacementRelationships, ...]:
    """Describe direct positive-area face contacts, in packing-step order."""
    relationships = []
    for placement in sorted(placements, key=lambda p: (p.step, p.item_instance_id)):
        p, d = placement.position, placement.dimensions
        supported_by, right_of, behind = [], [], []
        for neighbor in placements:
            if neighbor.item_instance_id == placement.item_instance_id:
                continue
            np, nd = neighbor.position, neighbor.dimensions
            if supporting_rectangle(placement, neighbor) is not None:
                supported_by.append(neighbor.item_instance_id)
            vertical_contact = max(p.z, np.z) < min(p.z + d.height, np.z + nd.height)
            if not vertical_contact:
                continue
            if np.x + nd.length == p.x and max(p.y, np.y) < min(p.y + d.width, np.y + nd.width):
                right_of.append(neighbor.item_instance_id)
            if np.y + nd.width == p.y and max(p.x, np.x) < min(p.x + d.length, np.x + nd.length):
                behind.append(neighbor.item_instance_id)
        relationships.append(
            PlacementRelationships(
                placement.item_instance_id,
                p.z == 0,
                tuple(sorted(supported_by)),
                tuple(sorted(right_of)),
                tuple(sorted(behind)),
            )
        )
    return tuple(relationships)
