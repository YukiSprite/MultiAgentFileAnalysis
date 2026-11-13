"""Console session registry and its corpus mounts."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from multi_agent_file_analysis.app import CorpusMount, mount_corpus
from multi_agent_file_analysis.audit import AuditRecorder
from multi_agent_file_analysis.core import RunMode
from multi_agent_file_analysis.corpora import CorpusCatalog, CorpusDefinition

from .errors import ConsoleError
from .jobs import RunJob

MountFactory = Callable[..., CorpusMount]


@dataclass(slots=True)
class WebSettings:
    """Tunable console limits."""

    idle_ttl_seconds: float = 1800.0
    max_sessions: int = 8
    max_events_per_run: int = 200
    heartbeat_seconds: float = 15.0
    max_file_chars: int = 12_000


@dataclass(slots=True)
class WebSession:
    """One browser session bound to exactly one corpus."""

    session_id: str
    mount: CorpusMount
    dry_run: bool
    created_at: float
    last_seen: float
    lock: threading.Lock = field(default_factory=threading.Lock)
    runs_lock: threading.Lock = field(default_factory=threading.Lock)
    runs: dict[str, RunJob] = field(default_factory=dict)

    @property
    def corpus_id(self) -> str:
        return self.mount.corpus.corpus_id

    @property
    def corpus_name(self) -> str:
        return self.mount.corpus.name

    @property
    def document_count(self) -> int:
        return self.mount.document_count


class SessionRegistry:
    """Owns mounts, idle expiry, and the session table."""

    def __init__(
        self,
        knowledge_base_root: Path,
        settings: WebSettings | None = None,
        *,
        env_file_path: Path | None = None,
        mount_factory: MountFactory = mount_corpus,
        audit_recorder_factory: Callable[[], AuditRecorder] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._knowledge_base_root = knowledge_base_root.resolve()
        self._settings = settings or WebSettings()
        self._env_file_path = env_file_path
        self._mount_factory = mount_factory
        self._audit_recorder_factory = audit_recorder_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, WebSession] = {}

    @property
    def settings(self) -> WebSettings:
        return self._settings

    def list_corpora(self) -> list[CorpusDefinition]:
        return list(
            CorpusCatalog.discover(self._knowledge_base_root).corpora
        )

    def create(self, corpus_id: str, *, dry_run: bool) -> WebSession:
        self.sweep()
        corpus = self._find_corpus(corpus_id)
        self._assert_capacity()

        recorder = (
            self._audit_recorder_factory()
            if self._audit_recorder_factory is not None
            else None
        )
        try:
            mount = self._mount_factory(
                corpus,
                self._knowledge_base_root,
                run_mode=RunMode.DRY_RUN if dry_run else RunMode.INTERACTIVE,
                env_file_path=self._env_file_path,
                max_file_chars=self._settings.max_file_chars,
                audit_recorder=recorder,
            )
        except Exception as exc:
            raise ConsoleError(
                "mount_failed",
                f"Could not mount corpus {corpus_id}: {exc}",
                500,
            ) from exc

        now = self._clock()
        session = WebSession(
            session_id=uuid.uuid4().hex[:12],
            mount=mount,
            dry_run=dry_run,
            created_at=now,
            last_seen=now,
        )
        with self._lock:
            if len(self._sessions) >= self._settings.max_sessions:
                session.mount.close()
                raise ConsoleError(
                    "too_many_sessions",
                    "Maximum number of console sessions reached",
                    429,
                )
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str, *, touch: bool = True) -> WebSession:
        now = self._clock()
        expired = False
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                expired = (
                    now - session.last_seen
                    > self._settings.idle_ttl_seconds
                )
                if touch and not expired:
                    session.last_seen = now
        if session is None:
            raise ConsoleError(
                "session_not_found",
                f"Unknown session: {session_id}",
                404,
            )
        if expired:
            self.close(session_id)
            raise ConsoleError(
                "session_not_found",
                f"Session {session_id} has expired",
                404,
            )
        return session

    def close(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.mount.close()
        return True

    def sweep(self) -> int:
        now = self._clock()
        expired: list[WebSession] = []
        with self._lock:
            for session_id, session in list(self._sessions.items()):
                if now - session.last_seen > self._settings.idle_ttl_seconds:
                    expired.append(self._sessions.pop(session_id))
        for session in expired:
            session.mount.close()
        return len(expired)

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.mount.close()

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _find_corpus(self, corpus_id: str) -> CorpusDefinition:
        for corpus in self.list_corpora():
            if corpus.corpus_id == corpus_id:
                return corpus
        raise ConsoleError(
            "corpus_not_found",
            f"Unknown corpus: {corpus_id}",
            404,
        )

    def _assert_capacity(self) -> None:
        with self._lock:
            if len(self._sessions) >= self._settings.max_sessions:
                raise ConsoleError(
                    "too_many_sessions",
                    "Maximum number of console sessions reached",
                    429,
                )
