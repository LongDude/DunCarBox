from typing import Protocol

from app.domain.models import PackingRequest, PackingResult


class PackingEngine(Protocol):
    """A deterministic, side-effect-free packing operation; no HTTP or storage."""

    def pack(self, request: PackingRequest) -> PackingResult: ...
