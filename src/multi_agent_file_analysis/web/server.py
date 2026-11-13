"""FastAPI application for the H5 console."""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from multi_agent_file_analysis.audit import MemoryAuditRecorder

from .errors import ConsoleError
from .events import (
    EventBus,
    EventBusRecorder,
    FanoutAuditRecorder,
    RunEvent,
)
from .jobs import JobRunner
from .serializers import run_payload, session_payload
from .sessions import MountFactory, SessionRegistry, WebSettings

STATIC_DIR = Path(__file__).parent / "static"


class CreateSessionRequest(BaseModel):
    corpus_id: str
    dry_run: bool = False


class AskRequest(BaseModel):
    query: str


class ResumeRequest(BaseModel):
    content: str


def create_app(
    knowledge_root: Path,
    *,
    env_file_path: Path | None = None,
    settings: WebSettings | None = None,
    mount_factory: MountFactory | None = None,
    max_workers: int = 4,
) -> FastAPI:
    resolved_settings = settings or WebSettings()
    bus = EventBus(max_events_per_run=resolved_settings.max_events_per_run)

    registry_kwargs: dict[str, Any] = {
        "settings": resolved_settings,
        "env_file_path": env_file_path,
        "audit_recorder_factory": lambda: FanoutAuditRecorder(
            [MemoryAuditRecorder(), EventBusRecorder(bus)]
        ),
    }
    if mount_factory is not None:
        registry_kwargs["mount_factory"] = mount_factory
    registry = SessionRegistry(knowledge_root, **registry_kwargs)
    runner = JobRunner(bus, max_workers=max_workers)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        bus.bind_loop(asyncio.get_running_loop())
        try:
            yield
        finally:
            runner.shutdown()
            registry.close_all()

    app = FastAPI(
        title="MultiAgentFileAnalysis Console",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.bus = bus
    app.state.registry = registry
    app.state.runner = runner
    app.state.settings = resolved_settings

    @app.exception_handler(ConsoleError)
    async def _console_error(
        request: Request,
        exc: ConsoleError,
    ) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status_code,
        )

    @app.get("/api/corpora")
    async def list_corpora() -> dict[str, Any]:
        corpora = await run_in_threadpool(registry.list_corpora)
        return {
            "corpora": [
                {
                    "id": corpus.corpus_id,
                    "name": corpus.name,
                    "description": corpus.description,
                    "discovery_source": corpus.discovery_source,
                }
                for corpus in corpora
            ]
        }

    @app.post("/api/sessions", status_code=201)
    async def create_session(body: CreateSessionRequest) -> dict[str, Any]:
        session = await run_in_threadpool(
            registry.create,
            body.corpus_id,
            dry_run=body.dry_run,
        )
        return session_payload(session)

    @app.delete("/api/sessions/{session_id}")
    async def close_session(session_id: str) -> dict[str, Any]:
        registry.get(session_id, touch=False)
        registry.close(session_id)
        return {"closed": True}

    @app.post("/api/sessions/{session_id}/ask", status_code=202)
    async def ask(session_id: str, body: AskRequest) -> dict[str, Any]:
        session = registry.get(session_id)
        job = runner.submit(session, body.query)
        return run_payload(session, job)

    @app.post(
        "/api/sessions/{session_id}/runs/{run_id}/resume",
        status_code=202,
    )
    async def resume(
        session_id: str,
        run_id: str,
        body: ResumeRequest,
    ) -> dict[str, Any]:
        session = registry.get(session_id)
        job = runner.resume(session, run_id, body.content)
        return run_payload(session, job)

    @app.get("/api/sessions/{session_id}/runs/{run_id}")
    async def get_run(session_id: str, run_id: str) -> dict[str, Any]:
        session = registry.get(session_id)
        job = runner.get_job(session, run_id)
        return run_payload(session, job)

    @app.get("/api/sessions/{session_id}/runs/{run_id}/events")
    async def stream_events(
        session_id: str,
        run_id: str,
    ) -> StreamingResponse:
        session = registry.get(session_id)
        runner.get_job(session, run_id)
        return StreamingResponse(
            _event_stream(bus, run_id, resolved_settings.heartbeat_seconds),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if STATIC_DIR.is_dir():
        app.mount(
            "/static",
            StaticFiles(directory=STATIC_DIR),
            name="static",
        )

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


async def _event_stream(
    bus: EventBus,
    run_id: str,
    heartbeat_seconds: float,
) -> AsyncIterator[str]:
    subscription = bus.subscribe(run_id)
    try:
        last_index = len(subscription.events) - 1
        for index, event in enumerate(subscription.events):
            yield _format_sse(event)
            if event.type == "terminal":
                return
            # A pause ends the stream only while it is still the latest state.
            # After a resume the replay ends with later events instead.
            if event.type == "pause" and index == last_index:
                return
        if subscription.closed or subscription.queue is None:
            return
        while True:
            try:
                event = await asyncio.wait_for(
                    subscription.queue.get(),
                    timeout=heartbeat_seconds,
                )
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            yield _format_sse(event)
            if event.type in {"terminal", "pause"}:
                return
    finally:
        bus.unsubscribe(run_id, subscription.queue)


def _format_sse(event: RunEvent) -> str:
    payload = json.dumps(
        {
            "seq": event.seq,
            "type": event.type,
            "run_id": event.run_id,
            "data": event.data,
        },
        ensure_ascii=False,
    )
    return f"id: {event.seq}\nevent: {event.type}\ndata: {payload}\n\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve the MultiAgentFileAnalysis H5 console"
    )
    parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=Path("knowledge_base"),
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-sessions", type=int, default=8)
    parser.add_argument("--idle-minutes", type=float, default=30.0)
    parser.add_argument("--max-events", type=int, default=200)
    args = parser.parse_args(argv)

    import uvicorn

    settings = WebSettings(
        idle_ttl_seconds=max(1.0, args.idle_minutes * 60.0),
        max_sessions=max(1, args.max_sessions),
        max_events_per_run=max(1, args.max_events),
    )
    app = create_app(
        args.knowledge_base,
        env_file_path=args.env_file,
        settings=settings,
    )
    print(
        "Console sessions live in this process only; run a single worker.",
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
