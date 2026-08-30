from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Job:
    name: str
    payload: dict[str, object]


class JobQueue(Protocol):
    def enqueue(self, job: Job) -> str: ...


class InlineJobQueue:
    """Development-only queue stub. Replace with a durable worker backend in production."""

    def enqueue(self, job: Job) -> str:
        return f"inline:{job.name}"
