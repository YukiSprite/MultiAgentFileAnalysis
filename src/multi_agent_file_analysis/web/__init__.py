"""Browser console: FastAPI server, session registry, and event bus."""

from .errors import ConsoleError
from .events import EventBus, EventBusRecorder, FanoutAuditRecorder
from .jobs import JobRunner, RunJob, RunState
from .serializers import run_payload, session_payload
from .server import create_app, main
from .sessions import SessionRegistry, WebSession, WebSettings

__all__ = [
    "ConsoleError",
    "EventBus",
    "EventBusRecorder",
    "FanoutAuditRecorder",
    "JobRunner",
    "RunJob",
    "RunState",
    "SessionRegistry",
    "WebSession",
    "WebSettings",
    "create_app",
    "main",
    "run_payload",
    "session_payload",
]
