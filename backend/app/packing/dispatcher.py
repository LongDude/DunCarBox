"""Select a packing engine without changing the service or placement contract."""

from app.domain.models import PackingRequest, PackingResult
from app.packing.engine import DeterministicPackingEngine
from app.packing.z3_engine import Z3PackingEngine


class PackingEngineDispatcher:
    # Health retains the version of the backwards-compatible default algorithm.
    version = DeterministicPackingEngine.version

    def __init__(self, cancel_event=None) -> None:
        self._heuristic = DeterministicPackingEngine()
        self._z3 = Z3PackingEngine(cancel_event=cancel_event)

    def pack(self, request: PackingRequest) -> PackingResult:
        if request.options.algorithm == "heuristic":
            return self._heuristic.pack(request)
        if request.options.algorithm == "z3":
            return self._z3.pack(request)
        raise ValueError(f"Unknown packing algorithm: {request.options.algorithm}")
