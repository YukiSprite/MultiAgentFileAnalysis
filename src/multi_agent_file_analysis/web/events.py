"""Run event bus and audit fan-out used by the console."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

from multi_agent_file_analysis.audit.events import AuditEvent


@dataclass(slots=True)
class RunEvent:
    """One progress event belonging to a single run."""

    seq: int
    type: str
    run_id: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Subscription:
    """A replay snapshot plus the live queue that follows it."""

    events: list[RunEvent]
    queue: asyncio.Queue[RunEvent] | None
    closed: bool


class EventBus:
    """Per-run bounded event buffer with fan-out to live subscribers.

    ``publish`` is called from worker threads, so subscriber delivery goes
    through ``loop.call_soon_threadsafe`` whenever a loop is bound.
    """

    def __init__(self, max_events_per_run: int = 200) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[RunEvent]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[RunEvent]]] = {}
        self._closed: set[str] = set()
        self._seq = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max_events = max_events_per_run

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(
        self,
        run_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> RunEvent | None:
        """Append one event unless the run already published its terminal."""
        with self._lock:
            if run_id in self._closed:
                return None
            self._seq += 1
            event = RunEvent(
                seq=self._seq,
                type=event_type,
                run_id=run_id,
                data=dict(data or {}),
            )
            self._events.setdefault(
                run_id, deque(maxlen=self._max_events)
            ).append(event)
            queues = list(self._subscribers.get(run_id, ()))
        self._dispatch(queues, event)
        return event

    def publish_terminal(
        self,
        run_id: str,
        data: dict[str, Any],
    ) -> bool:
        """Publish the single terminal event for a run."""
        with self._lock:
            if run_id in self._closed:
                return False
            self._closed.add(run_id)
            self._seq += 1
            event = RunEvent(
                seq=self._seq,
                type="terminal",
                run_id=run_id,
                data=dict(data),
            )
            self._events.setdefault(
                run_id, deque(maxlen=self._max_events)
            ).append(event)
            queues = list(self._subscribers.get(run_id, ()))
        self._dispatch(queues, event)
        return True

    def subscribe(self, run_id: str) -> Subscription:
        """Atomically snapshot replay events and register a live queue."""
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        with self._lock:
            events = list(self._events.get(run_id, ()))
            closed = run_id in self._closed
            if closed:
                return Subscription(events=events, queue=None, closed=True)
            queue: asyncio.Queue[RunEvent] = asyncio.Queue()
            self._subscribers.setdefault(run_id, []).append(queue)
            return Subscription(events=events, queue=queue, closed=False)

    def unsubscribe(
        self,
        run_id: str,
        queue: asyncio.Queue[RunEvent] | None,
    ) -> None:
        if queue is None:
            return
        with self._lock:
            queues = self._subscribers.get(run_id)
            if not queues:
                return
            if queue in queues:
                queues.remove(queue)
            if not queues:
                self._subscribers.pop(run_id, None)

    def events(self, run_id: str) -> list[RunEvent]:
        with self._lock:
            return list(self._events.get(run_id, ()))

    def is_closed(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._closed

    def forget(self, run_id: str) -> None:
        with self._lock:
            self._events.pop(run_id, None)
            self._subscribers.pop(run_id, None)
            self._closed.discard(run_id)

    def _dispatch(
        self,
        queues: list[asyncio.Queue[RunEvent]],
        event: RunEvent,
    ) -> None:
        for queue in queues:
            loop = self._loop
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(self._offer, queue, event)
                    continue
                except RuntimeError:
                    pass
            self._offer(queue, event)

    @staticmethod
    def _offer(queue: asyncio.Queue[RunEvent], event: RunEvent) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


class EventBusRecorder:
    """Audit sink that forwards workflow events to the bus."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def record(self, event: AuditEvent) -> None:
        self._bus.publish(
            event.run_id,
            str(event.event_type),
            {"message": event.message, **event.payload},
        )


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class FanoutAuditRecorder:
    """Writes one audit event to several sinks without letting one break."""

    def __init__(self, recorders: list[AuditSink]) -> None:
        self._recorders = list(recorders)
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        with self._lock:
            for recorder in self._recorders:
                try:
                    recorder.record(event)
                except Exception:
                    continue
