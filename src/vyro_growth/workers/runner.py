from __future__ import annotations

from typing import Protocol

from vyro_growth.workers.base import Job


class UnknownJobError(LookupError):
    """Raised when no handler is registered for a job name."""


class JobHandler(Protocol):
    def handle(self, job: Job) -> None: ...


class WorkerRunner(Protocol):
    """Abstraction for synchronous or async worker execution backends."""

    def run(self, job: Job) -> None: ...


class InlineWorkerRunner:
    """Development runner that dispatches jobs in-process."""

    def __init__(self, handlers: dict[str, JobHandler]) -> None:
        self._handlers = handlers

    def run(self, job: Job) -> None:
        handler = self._handlers.get(job.name)
        if handler is None:
            raise UnknownJobError(f"No handler registered for job: {job.name}")
        handler.handle(job)
