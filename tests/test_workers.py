from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from vyro_growth.workers import InlineJobQueue, InlineWorkerRunner, Job, UnknownJobError


@dataclass
class EchoHandler:
    handled: list[Job] = field(default_factory=list)

    def handle(self, job: Job) -> None:
        self.handled.append(job)


def test_inline_job_queue_returns_job_reference() -> None:
    queue = InlineJobQueue()
    job = Job(name="discover_practices", payload={"region": "TX"})

    job_id = queue.enqueue(job)

    assert job_id == "inline:discover_practices"


def test_inline_worker_runner_dispatches_to_handler() -> None:
    handler = EchoHandler()
    runner = InlineWorkerRunner({"discover_practices": handler})
    job = Job(name="discover_practices", payload={"region": "TX"})

    runner.run(job)

    assert handler.handled == [job]


def test_inline_worker_runner_raises_for_unknown_job() -> None:
    runner = InlineWorkerRunner({})

    with pytest.raises(UnknownJobError, match="discover_practices"):
        runner.run(Job(name="discover_practices", payload={}))
