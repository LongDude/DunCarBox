"""Cooperative deadlines/cancellation inside the Python placement loops."""

from collections.abc import Callable
from time import monotonic

ProgressCallback = Callable[[str, float | None], None]


class SearchControl:
    def __init__(
        self, *, deadline: float | None = None, cancel_event=None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.deadline = deadline
        self.cancel_event = cancel_event
        self.progress = progress

    def expired(self) -> bool:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RuntimeError("Packing cancelled")
        return self.deadline is not None and monotonic() >= self.deadline

    def report(self, stage: str, fraction: float | None) -> None:
        if self.progress is not None:
            self.progress(stage, fraction)
