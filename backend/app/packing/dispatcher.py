"""Select a packing engine without changing the service or placement contract."""

from app.domain.models import PackingRequest, PackingResult
from app.packing.engine import DeterministicPackingEngine
from app.packing.parallel import pack_parallel
from app.packing.z3_engine import Z3PackingEngine


class PackingEngineDispatcher:
    # Health retains the version of the backwards-compatible default algorithm.
    version = DeterministicPackingEngine.version

    def __init__(self, cancel_event=None, progress=None) -> None:
        self._cancel_event = cancel_event
        self._progress = progress
        self._z3 = Z3PackingEngine(cancel_event=cancel_event, progress=progress)

    def pack(self, request: PackingRequest) -> PackingResult:
        if request.options.algorithm == "heuristic":
            return pack_parallel(request, cancel_event=self._cancel_event, progress=self._progress)
        if request.options.algorithm == "z3":
            return self._z3.pack(request)
        raise ValueError(f"Unknown packing algorithm: {request.options.algorithm}")
