"""Bounded, transient background calculations for a single API process.

Cancellation reaches the solver controller before the job process is reaped.
PostgreSQL remains the persistent store for the box catalog.
"""

import logging
import math
import multiprocessing
from dataclasses import dataclass, field
from fractions import Fraction
from multiprocessing.synchronize import Event as ProcessEvent
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException

from app.domain.models import PackingRequest
from app.packing.dispatcher import PackingEngineDispatcher
from app.packing.validation import validate_solution
from app.schemas.packing import PackingResultSchema
from app.services.packing import PackingService

logger = logging.getLogger(__name__)


def _calculate(request: PackingRequest, path: Path, cancel_event) -> None:
    result = PackingService(PackingEngineDispatcher(cancel_event=cancel_event)).pack(request)
    support = Fraction(1) if request.options.algorithm == "z3" else Fraction(4, 5)
    validate_solution(request, result, support)
    # The parent serves the file only after a successful process exit.
    path.write_text(PackingResultSchema.model_validate(result).model_dump_json(), encoding="utf-8")


@dataclass
class _Job:
    id: str
    directory: TemporaryDirectory
    started: float = field(default_factory=monotonic)
    finished: float | None = None
    status: str = "running"
    error: str | None = None
    cancel: Event = field(default_factory=Event)
    thread: Thread | None = None
    process_cancel: ProcessEvent = field(
        default_factory=lambda: multiprocessing.get_context("spawn").Event()
    )

    @property
    def path(self) -> Path:
        return Path(self.directory.name) / "result.json"


class PackingJobs:
    """One active calculation, three retained results, 15-minute retention.

    Workers are reaped on cancellation, deadline, failure and application exit.
    Result/status URLs are temporary and do not survive an API restart.
    """

    def __init__(self, timeout_seconds: float | None = None, *, worker=_calculate) -> None:
        if timeout_seconds is not None and (
            not math.isfinite(timeout_seconds) or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite, or None")
        self.timeout_seconds = timeout_seconds
        self._worker = worker
        self._jobs: dict[str, _Job] = {}
        self._lock = Lock()
        self._closed = False

    def submit(self, request: PackingRequest) -> dict:
        with self._lock:
            if self._closed:
                raise HTTPException(503, "Сервис расчёта остановлен.")
            if any(job.status == "running" for job in self._jobs.values()):
                raise HTTPException(
                    409, "Большой заказ уже рассчитывается. Дождитесь результата или отмените его."
                )
            self._prune()
            job = _Job(uuid4().hex, TemporaryDirectory(prefix="duncarbox-pack-"))
            self._jobs[job.id] = job
            job.thread = Thread(target=self._run, args=(job, request), daemon=True)
            job.thread.start()
            return self._snapshot(job)

    def _prune(self) -> None:
        # Called under the lock; only completed jobs can be removed.
        completed = [j for j in self._jobs.values() if j.status != "running"]
        for index, job in enumerate(completed):
            if index < len(completed) - 2 or monotonic() - job.finished > 900:
                job.directory.cleanup()
                del self._jobs[job.id]

    def _run(self, job: _Job, request: PackingRequest) -> None:
        process = multiprocessing.get_context("spawn").Process(
            target=self._worker,
            args=(request, job.path, job.process_cancel),
            name=f"packing-{job.id}",
        )
        status, error = "failed", "Расчёт завершился с ошибкой. Попробуйте ещё раз."
        try:
            process.start()
            while True:
                if job.cancel.is_set():
                    status, error = "cancelled", None
                    break
                if (
                    self.timeout_seconds is not None
                    and monotonic() - job.started >= self.timeout_seconds
                ):
                    status, error = "failed", "Превышено настроенное время фонового расчёта."
                    break
                process.join(timeout=0.1)
                if not process.is_alive():
                    if process.exitcode == 0 and job.path.is_file():
                        status, error = "completed", None
                    break
        except Exception:
            logger.exception("Background packing failed: %s", job.id)
        finally:
            if process.pid is not None:
                job.process_cancel.set()
                # Give the Z3 controller time to terminate and reap its own workers.
                # A heuristic job has no children and can be terminated afterwards.
                process.join(timeout=5 if request.options.algorithm == "z3" else 0)
                if process.is_alive():
                    process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
                process.close()
            if status != "completed":
                job.path.unlink(missing_ok=True)
            with self._lock:
                job.status, job.error, job.finished = status, error, monotonic()

    def _lookup(self, job_id: str) -> _Job:
        job = self._jobs.get(job_id)
        if job is None or (job.finished is not None and monotonic() - job.finished > 900):
            raise HTTPException(
                404, "Расчёт не найден или срок хранения истёк. Запустите его заново."
            )
        return job

    def _snapshot(self, job: _Job) -> dict:
        return {
            "id": job.id,
            "status": job.status,
            "error": job.error,
            "elapsed_seconds": round((job.finished or monotonic()) - job.started, 2),
            "timeout_seconds": self.timeout_seconds,
        }

    def status(self, job_id: str) -> dict:
        with self._lock:
            return self._snapshot(self._lookup(job_id))

    def result_path(self, job_id: str) -> Path:
        with self._lock:
            job = self._lookup(job_id)
            if job.status != "completed":
                raise HTTPException(409, job.error or "Результат расчёта ещё не готов.")
            return job.path

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = self._lookup(job_id)
            job.cancel.set()
        if job.thread:
            job.thread.join(timeout=10)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            jobs = list(self._jobs.values())
            for job in jobs:
                job.cancel.set()
        for job in jobs:
            if job.thread:
                job.thread.join(timeout=10)
            job.directory.cleanup()
