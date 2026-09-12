from typing import Protocol

from app.domain.models import PackingRequest, PackingResult


class PackingEngine(Protocol):
    """Packing without mutating the request or inventory; no HTTP or storage."""

    def pack(self, request: PackingRequest) -> PackingResult: ...
