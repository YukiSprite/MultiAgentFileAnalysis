"""Background execution of diagnosis runs for the console."""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from multi_agent_file_analysis.core import WorkflowStatus
from multi_agent_file_analysis.qa import QARequest, QAResponse

from .errors import ConsoleError
from .events import EventBus

if TYPE_CHECKING:
    from .sessions import WebSession


class RunState(StrEnum):
    """Console-facing lifecycle of one run."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    FAILED = "failed"


TERMINAL_STATES = frozenset(
    {RunState.COMPLETED, RunState.ABSTAINED, RunState.FAILED}
)


@dataclass(slots=True)
class RunJob:
    """One submitted question and its latest result."""

    run_id: str
    query: str
    status: RunState = RunState.QUEUED
    response: QAResponse | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES


class JobRunner:
    """Runs blocking diagnosis work off the request thread."""

    def __init__(
        self,
        bus: EventBus,
        *,
        max_workers: int = 4,
    ) -> None:
        self._bus = bus
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="mafa-run",
        )

    def submit(self, session: "WebSession", query: str) -> RunJob:
        if not query.strip():
            raise ConsoleError("empty_query", "Question must not be empty", 400)
        job = RunJob(run_id=uuid.uuid4().hex[:12], query=query.strip())
        with session.runs_lock:
            session.runs[job.run_id] = job
        self._executor.submit(self._run_ask, session, job)
        return job

    def resume(
        self,
        session: "WebSession",
        run_id: str,
        content: str,
    ) -> RunJob:
        job = self.get_job(session, run_id)
        if job.status != RunState.WAITING_FOR_HUMAN:
            raise ConsoleError(
                "run_not_waiting",
                f"Run {run_id} is not waiting for human input",
                409,
            )
        if not content.strip():
            raise ConsoleError("empty_input", "Input must not be empty", 400)
        job.status = RunState.RUNNING
        job.updated_at = time.time()
        # Marks the start of a new phase so a replayed stream can tell an old
        # pause apart from the current state.
        self._bus.publish(
            job.run_id,
            "run_resumed",
            {"status": str(job.status)},
        )
        self._executor.submit(self._run_resume, session, job, content.strip())
        return job

    def get_job(self, session: "WebSession", run_id: str) -> RunJob:
        with session.runs_lock:
            job = session.runs.get(run_id)
        if job is None:
            raise ConsoleError("run_not_found", f"Unknown run: {run_id}", 404)
        return job

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run_ask(self, session: "WebSession", job: RunJob) -> None:
        with session.lock:
            job.status = RunState.RUNNING
            job.updated_at = time.time()
            try:
                response = session.mount.services.qa_service.ask(
                    QARequest(query=job.query, run_id=job.run_id)
                )
            except Exception as exc:
                self._fail(job, exc)
                return
            self._apply(job, response)

    def _run_resume(
        self,
        session: "WebSession",
        job: RunJob,
        content: str,
    ) -> None:
        with session.lock:
            job.status = RunState.RUNNING
            job.updated_at = time.time()
            try:
                response = session.mount.services.qa_service.resume_by_id(
                    job.run_id,
                    content,
                )
            except Exception as exc:
                self._fail(job, exc)
                return
            self._apply(job, response)

    def _fail(self, job: RunJob, exc: Exception) -> None:
        job.error = f"{type(exc).__name__}: {exc}"
        job.status = RunState.FAILED
        job.updated_at = time.time()
        self._publish_terminal(job)

    def _apply(self, job: RunJob, response: QAResponse) -> None:
        job.response = response
        if response.needs_human_input:
            job.status = RunState.WAITING_FOR_HUMAN
            job.updated_at = time.time()
            # A pause is not the end of the run: resume continues the same run
            # and only the real end publishes the terminal event.
            self._bus.publish(
                job.run_id,
                "pause",
                {
                    "status": str(job.status),
                    "answer": response.answer,
                    "is_partial": bool(response.is_partial),
                    "needs_human_input": True,
                },
            )
            return
        if response.state.status == WorkflowStatus.COMPLETED:
            job.status = RunState.COMPLETED
        elif response.state.status == WorkflowStatus.ABSTAINED:
            job.status = RunState.ABSTAINED
        else:
            job.status = RunState.FAILED
        job.updated_at = time.time()
        self._publish_terminal(job)

    def _publish_terminal(self, job: RunJob) -> None:
        response = job.response
        self._bus.publish_terminal(
            job.run_id,
            {
                "status": str(job.status),
                "answer": response.answer if response else None,
                "is_partial": (
                    bool(response.is_partial)
                    if response is not None
                    else job.error is not None
                ),
                "needs_human_input": (
                    bool(response.needs_human_input)
                    if response is not None
                    else False
                ),
                "error": job.error,
            },
        )
