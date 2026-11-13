from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from multi_agent_file_analysis.core import RunMode, WorkflowStatus
from multi_agent_file_analysis.corpora import CorpusCatalog
from multi_agent_file_analysis.graph import (
    CriticReport,
    DiagnosisDraft,
    DiagnosisState,
    EvidenceItem,
    ExplorationStep,
    RetrievalPlan,
)
from multi_agent_file_analysis.core import ReviewDecision, ToolName
from multi_agent_file_analysis.qa import QAResponse
from multi_agent_file_analysis.web import (
    EventBus,
    FanoutAuditRecorder,
    RunState,
    SessionRegistry,
    WebSettings,
    create_app,
    run_payload,
)
from multi_agent_file_analysis.audit import AuditEvent, AuditEventType

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_corpus(root: Path, name: str, corpus_id: str, body: str) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "rules.md").write_text(body, encoding="utf-8")
    (directory / ".mafa-corpus.yaml").write_text(
        f"id: {corpus_id}\nname: {name}\n",
        encoding="utf-8",
    )


class StubQAService:
    """Stand-in QA facade that records calls and returns canned responses."""

    def __init__(self, ask=None, resume=None) -> None:
        self._ask = ask
        self._resume = resume
        self.ask_calls: list = []
        self.resume_calls: list = []

    def ask(self, request):
        self.ask_calls.append(request)
        if self._ask is None:
            return self._completed(request)
        return self._ask(request)

    def resume_by_id(self, run_id, content):
        self.resume_calls.append((run_id, content))
        if self._resume is None:
            return self._completed(SimpleNamespace(run_id=run_id))
        return self._resume(run_id, content)

    @staticmethod
    def _completed(request) -> QAResponse:
        state = DiagnosisState(
            user_query="q",
            run_id=request.run_id,
            status=WorkflowStatus.COMPLETED,
        )
        state.final_answer = "approved"
        return QAResponse(state=state, answer="approved", is_partial=False)


class StubMount:
    def __init__(self, corpus, qa_service, document_count=1) -> None:
        self.corpus = corpus
        self.services = SimpleNamespace(qa_service=qa_service)
        self.document_count = document_count
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _waiting_response(run_id: str) -> QAResponse:
    state = DiagnosisState(
        user_query="q",
        run_id=run_id,
        status=WorkflowStatus.WAITING_FOR_HUMAN,
    )
    from multi_agent_file_analysis.graph import HumanRequest

    state.human_request = HumanRequest(
        prompt="请提供 sshd -T 输出",
        expected_input="命令输出",
        request_id="req-1",
    )
    state.partial_answer = "阶段性回答（尚未完成最终审查）"
    return QAResponse(
        state=state,
        answer=state.partial_answer,
        needs_human_input=True,
        is_partial=True,
    )


class ConsoleTestBase(unittest.TestCase):
    mount_factory = None

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.base = Path(self._temporary.name)
        self.knowledge_base = self.base / "knowledge_base"
        self.knowledge_base.mkdir()
        _write_corpus(
            self.knowledge_base,
            "dnd",
            "dnd",
            "# DND Rules\n\nDND_ALPHA is one.\n",
        )
        _write_corpus(
            self.knowledge_base,
            "openssh",
            "openssh",
            "# SSH Rules\n\nSSH_SECRET must stay isolated.\n",
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def make_client(self, settings: WebSettings | None = None, mount_factory=None):
        app = create_app(
            self.knowledge_base,
            env_file_path=self.base / "missing.env",
            settings=settings
            or WebSettings(
                idle_ttl_seconds=60,
                max_sessions=8,
                heartbeat_seconds=0.05,
            ),
            mount_factory=mount_factory or self.mount_factory,
            max_workers=2,
        )
        return app, TestClient(app)

    def create_dry_session(self, client: TestClient, corpus_id="dnd"):
        response = client.post(
            "/api/sessions",
            json={"corpus_id": corpus_id, "dry_run": True},
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()


def _parse_sse(lines, stop_types=("terminal",), max_lines=400):
    events = []
    current: dict[str, str] = {}
    count = 0
    for line in lines:
        count += 1
        if count > max_lines:
            break
        if line == "":
            if "event" in current:
                payload = json.loads(current.get("data") or "{}")
                events.append(
                    {
                        "event": current.get("event"),
                        "seq": payload.get("seq"),
                        "data": payload.get("data", payload),
                    }
                )
                if current.get("event") in stop_types:
                    break
            current = {}
            continue
        if line.startswith(":"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            current[key.strip()] = value.strip()
    return events


def _wait_for_run(client, session_id, run_id, states, timeout=8.0):
    deadline = time.time() + timeout
    payload = {}
    while time.time() < deadline:
        payload = client.get(
            f"/api/sessions/{session_id}/runs/{run_id}"
        ).json()
        if payload.get("status") in states:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"run stayed {payload.get('status')!r}: {payload}")


class CorpusAndSessionTests(ConsoleTestBase):
    def test_corpora_list(self) -> None:
        app, client = self.make_client()
        with client:
            response = client.get("/api/corpora")
            self.assertEqual(200, response.status_code)
            ids = {item["id"] for item in response.json()["corpora"]}
            self.assertEqual({"dnd", "openssh"}, ids)

    def test_unknown_corpus_is_rejected(self) -> None:
        app, client = self.make_client()
        with client:
            response = client.post(
                "/api/sessions",
                json={"corpus_id": "nope", "dry_run": True},
            )
            self.assertEqual(404, response.status_code)
            self.assertEqual("corpus_not_found", response.json()["error"]["code"])

    def test_session_close_removes_index(self) -> None:
        app, client = self.make_client()
        with client:
            session = self.create_dry_session(client)
            index_dir = app.state.registry.get(
                session["session_id"]
            ).mount.index_dir
            self.assertTrue(index_dir.exists())
            response = client.delete(f"/api/sessions/{session['session_id']}")
            self.assertEqual(200, response.status_code)
            self.assertFalse(index_dir.exists())
            response = client.get(
                f"/api/sessions/{session['session_id']}/runs/whatever"
            )
            self.assertEqual(404, response.status_code)

    def test_session_binds_one_corpus_and_isolates_it(self) -> None:
        app, client = self.make_client()
        with client:
            first = self.create_dry_session(client, "dnd")
            second = self.create_dry_session(client, "openssh")
            dnd_mount = app.state.registry.get(first["session_id"]).mount
            ssh_mount = app.state.registry.get(second["session_id"]).mount
            self.assertEqual("dnd", dnd_mount.corpus.corpus_id)
            self.assertEqual("openssh", ssh_mount.corpus.corpus_id)
            self.assertEqual(1, len(dnd_mount.services.vfs.v_grep("/", "DND_ALPHA").hits))
            self.assertEqual(0, len(dnd_mount.services.vfs.v_grep("/", "SSH_SECRET").hits))
            self.assertEqual(1, len(ssh_mount.services.vfs.v_grep("/", "SSH_SECRET").hits))

    def test_idle_sessions_are_swept(self) -> None:
        catalog = CorpusCatalog.discover(self.knowledge_base)
        corpus = catalog.corpora[0]
        closed: list[StubMount] = []

        def factory(c, root, **kwargs):
            mount = StubMount(c, StubQAService())
            mount.close = lambda: closed.append(mount)
            return mount

        clock = [0.0]
        registry = SessionRegistry(
            self.knowledge_base,
            WebSettings(idle_ttl_seconds=10, max_sessions=2),
            mount_factory=factory,
            clock=lambda: clock[0],
        )
        session = registry.create(corpus.corpus_id, dry_run=True)
        clock[0] = 11.0
        self.assertEqual(1, registry.sweep())
        self.assertEqual(0, registry.session_count)
        self.assertEqual(1, len(closed))

    def test_expired_session_is_not_reachable(self) -> None:
        catalog = CorpusCatalog.discover(self.knowledge_base)
        corpus = catalog.corpora[0]

        def factory(c, root, **kwargs):
            return StubMount(c, StubQAService())

        clock = [0.0]
        registry = SessionRegistry(
            self.knowledge_base,
            WebSettings(idle_ttl_seconds=5, max_sessions=2),
            mount_factory=factory,
            clock=lambda: clock[0],
        )
        session = registry.create(corpus.corpus_id, dry_run=True)
        clock[0] = 6.0
        with self.assertRaises(Exception) as caught:
            registry.get(session.session_id)
        self.assertEqual("session_not_found", caught.exception.code)

    def test_max_sessions_is_enforced(self) -> None:
        catalog = CorpusCatalog.discover(self.knowledge_base)
        corpus = catalog.corpora[0]
        created: list[StubMount] = []

        def factory(c, root, **kwargs):
            mount = StubMount(c, StubQAService())
            created.append(mount)
            return mount

        registry = SessionRegistry(
            self.knowledge_base,
            WebSettings(max_sessions=1),
            mount_factory=factory,
        )
        registry.create(corpus.corpus_id, dry_run=True)
        with self.assertRaises(Exception) as caught:
            registry.create(corpus.corpus_id, dry_run=True)
        self.assertEqual("too_many_sessions", caught.exception.code)
        self.assertEqual(1, len(created))


class RunLifecycleTests(ConsoleTestBase):
    def test_ask_returns_before_diagnosis_finishes(self) -> None:
        gate = threading.Event()
        qa = StubQAService(
            ask=lambda request: (
                gate.wait(5),
                StubQAService._completed(request),
            )[1]
        )

        def factory(c, root, **kwargs):
            return StubMount(c, qa)

        app, client = self.make_client(mount_factory=factory)
        with client:
            session = self.create_dry_session(client)
            started = time.time()
            response = client.post(
                f"/api/sessions/{session['session_id']}/ask",
                json={"query": "why"},
            )
            elapsed = time.time() - started
            self.assertEqual(202, response.status_code, response.text)
            run_id = response.json()["run_id"]
            self.assertLess(elapsed, 1.5)
            self.assertIn(
                response.json()["status"], {"queued", "running"}
            )
            gate.set()
            payload = _wait_for_run(
                client,
                session["session_id"],
                run_id,
                {"completed", "failed", "abstained"},
            )
            self.assertEqual("completed", payload["status"])
            self.assertEqual("approved", payload["answer"])

    def test_same_session_runs_are_serial(self) -> None:
        lock = threading.Lock()
        active = {"now": 0, "max": 0}

        def ask(request):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            time.sleep(0.1)
            with lock:
                active["now"] -= 1
            return StubQAService._completed(request)

        qa = StubQAService(ask=ask)

        def factory(c, root, **kwargs):
            return StubMount(c, qa)

        app, client = self.make_client(mount_factory=factory)
        with client:
            session = self.create_dry_session(client)
            sid = session["session_id"]
            first = client.post(f"/api/sessions/{sid}/ask", json={"query": "one"})
            second = client.post(f"/api/sessions/{sid}/ask", json={"query": "two"})
            self.assertEqual(202, first.status_code)
            self.assertEqual(202, second.status_code)
            _wait_for_run(client, sid, first.json()["run_id"], {"completed"})
            _wait_for_run(client, sid, second.json()["run_id"], {"completed"})
            self.assertEqual(1, active["max"])

    def test_different_sessions_run_in_parallel(self) -> None:
        barrier = threading.Barrier(2, timeout=5)

        def ask(request):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                return StubQAService._completed(request)
            return StubQAService._completed(request)

        qa = StubQAService(ask=ask)

        def factory(c, root, **kwargs):
            return StubMount(c, qa)

        app, client = self.make_client(mount_factory=factory)
        with client:
            first = self.create_dry_session(client, "dnd")
            second = self.create_dry_session(client, "openssh")
            one = client.post(
                f"/api/sessions/{first['session_id']}/ask", json={"query": "one"}
            )
            two = client.post(
                f"/api/sessions/{second['session_id']}/ask", json={"query": "two"}
            )
            _wait_for_run(
                client, first["session_id"], one.json()["run_id"], {"completed"}
            )
            _wait_for_run(
                client, second["session_id"], two.json()["run_id"], {"completed"}
            )

    def test_empty_query_is_rejected(self) -> None:
        app, client = self.make_client()
        with client:
            session = self.create_dry_session(client)
            response = client.post(
                f"/api/sessions/{session['session_id']}/ask",
                json={"query": "   "},
            )
            self.assertEqual(400, response.status_code)
            self.assertEqual("empty_query", response.json()["error"]["code"])

    def test_unknown_session_and_run(self) -> None:
        app, client = self.make_client()
        with client:
            response = client.post("/api/sessions/missing/ask", json={"query": "x"})
            self.assertEqual(404, response.status_code)
            self.assertEqual(
                "session_not_found", response.json()["error"]["code"]
            )
            session = self.create_dry_session(client)
            response = client.get(
                f"/api/sessions/{session['session_id']}/runs/missing"
            )
            self.assertEqual(404, response.status_code)
            self.assertEqual("run_not_found", response.json()["error"]["code"])

    def test_resume_continues_from_reasoning_phase(self) -> None:
        app, client = self.make_client()
        with client:
            session = self.create_dry_session(client)
            sid = session["session_id"]
            submitted = client.post(
                f"/api/sessions/{sid}/ask", json={"query": "unknown-thing"}
            ).json()
            before = _wait_for_run(
                client, sid, submitted["run_id"], {"waiting_for_human"}
            )
            response = client.post(
                f"/api/sessions/{sid}/runs/{submitted['run_id']}/resume",
                json={"content": "现场信息：设备是 legacy-lab"},
            )
            self.assertEqual(202, response.status_code)
            after = _wait_for_run(
                client,
                sid,
                submitted["run_id"],
                {"waiting_for_human", "completed", "abstained", "failed"},
            )
            self.assertGreater(
                after["attempts"]["reasoner"], before["attempts"]["reasoner"]
            )
            self.assertEqual(
                before["attempts"]["explorer"], after["attempts"]["explorer"]
            )

    def test_resume_requires_waiting_state(self) -> None:
        app, client = self.make_client()
        with client:
            session = self.create_dry_session(client)
            submitted = client.post(
                f"/api/sessions/{session['session_id']}/ask",
                json={"query": "DND_ALPHA"},
            ).json()
            _wait_for_run(
                client,
                session["session_id"],
                submitted["run_id"],
                {"completed", "failed", "abstained"},
            )
            response = client.post(
                f"/api/sessions/{session['session_id']}/runs/"
                f"{submitted['run_id']}/resume",
                json={"content": "more"},
            )
            self.assertEqual(409, response.status_code)
            self.assertEqual("run_not_waiting", response.json()["error"]["code"])

    def test_dry_run_session_never_builds_a_model_client(self) -> None:
        app, client = self.make_client()
        with client:
            session = self.create_dry_session(client)
            mount = app.state.registry.get(session["session_id"]).mount
            self.assertEqual(RunMode.DRY_RUN, mount.services.config.run_mode)
            self.assertIsNone(mount.services.explorer._llm_client)

    def test_hitl_resume_completes_the_same_run(self) -> None:
        qa = StubQAService(
            ask=lambda request: _waiting_response(request.run_id),
            resume=lambda run_id, content: StubQAService._completed(
                SimpleNamespace(run_id=run_id)
            ),
        )

        def factory(c, root, **kwargs):
            return StubMount(c, qa)

        app, client = self.make_client(mount_factory=factory)
        with client:
            session = self.create_dry_session(client)
            sid = session["session_id"]
            submitted = client.post(
                f"/api/sessions/{sid}/ask", json={"query": "x"}
            ).json()
            waiting = _wait_for_run(
                client, sid, submitted["run_id"], {"waiting_for_human"}
            )
            self.assertTrue(waiting["is_partial"])
            self.assertTrue(waiting["needs_human_input"])
            self.assertEqual(
                "请提供 sshd -T 输出", waiting["human_request"]["prompt"]
            )
            resumed = client.post(
                f"/api/sessions/{sid}/runs/{submitted['run_id']}/resume",
                json={"content": "输出如下…"},
            )
            self.assertEqual(202, resumed.status_code)
            done = _wait_for_run(client, sid, submitted["run_id"], {"completed"})
            self.assertEqual("approved", done["answer"])
            self.assertEqual(1, len(qa.resume_calls))
            self.assertEqual("输出如下…", qa.resume_calls[0][1])


class EventStreamTests(ConsoleTestBase):
    def test_fanout_writes_every_sink_and_isolates_failure(self) -> None:
        class Broken:
            def record(self, event):
                raise RuntimeError("sink down")

        class Collector:
            def __init__(self):
                self.events = []

            def record(self, event):
                self.events.append(event)

        collector = Collector()
        recorder = FanoutAuditRecorder([Broken(), collector])
        recorder.record(
            AuditEvent(
                event_type=AuditEventType.WORKFLOW_STARTED,
                run_id="r1",
                message="started",
            )
        )
        self.assertEqual(1, len(collector.events))

    def test_event_bus_is_bounded_and_keeps_terminal(self) -> None:
        bus = EventBus(max_events_per_run=3)
        for index in range(5):
            bus.publish("r1", "tool_called", {"index": index})
        self.assertEqual(3, len(bus.events("r1")))
        self.assertTrue(bus.publish_terminal("r1", {"status": "completed"}))
        self.assertFalse(bus.publish_terminal("r1", {"status": "completed"}))
        replay = bus.subscribe("r1")
        self.assertTrue(replay.closed)
        self.assertEqual("terminal", replay.events[-1].type)
        self.assertLessEqual(len(replay.events), 3)

    def test_bus_publishes_nothing_after_terminal(self) -> None:
        bus = EventBus()
        bus.publish_terminal("r1", {"status": "completed"})
        self.assertIsNone(bus.publish("r1", "tool_called", {}))

    def test_stream_replays_terminal_after_completion(self) -> None:
        app, client = self.make_client()
        with client:
            session = self.create_dry_session(client)
            sid = session["session_id"]
            submitted = client.post(
                f"/api/sessions/{sid}/ask", json={"query": "DND_ALPHA"}
            ).json()
            _wait_for_run(client, sid, submitted["run_id"], {"completed", "failed", "abstained"})
            with client.stream(
                "GET",
                f"/api/sessions/{sid}/runs/{submitted['run_id']}/events",
            ) as response:
                self.assertEqual(200, response.status_code)
                events = _parse_sse(response.iter_lines())
            self.assertTrue(events)
            self.assertEqual("terminal", events[-1]["event"])
            self.assertIn("status", events[-1]["data"])

    def test_stream_emits_progress_and_one_terminal(self) -> None:
        app, client = self.make_client()
        with client:
            session = self.create_dry_session(client)
            sid = session["session_id"]
            submitted = client.post(
                f"/api/sessions/{sid}/ask", json={"query": "DND_ALPHA"}
            ).json()
            with client.stream(
                "GET",
                f"/api/sessions/{sid}/runs/{submitted['run_id']}/events",
            ) as response:
                events = _parse_sse(response.iter_lines())
            types = [event["event"] for event in events]
            self.assertIn("workflow_started", types)
            self.assertEqual(1, types.count("terminal"))
            self.assertEqual("terminal", types[-1])

    def test_waiting_run_emits_pause_then_terminal_after_resume(self) -> None:
        qa = StubQAService(
            ask=lambda request: _waiting_response(request.run_id),
            resume=lambda run_id, content: StubQAService._completed(
                SimpleNamespace(run_id=run_id)
            ),
        )

        def factory(c, root, **kwargs):
            return StubMount(c, qa)

        app, client = self.make_client(mount_factory=factory)
        with client:
            session = self.create_dry_session(client)
            sid = session["session_id"]
            submitted = client.post(
                f"/api/sessions/{sid}/ask", json={"query": "x"}
            ).json()
            run_id = submitted["run_id"]
            _wait_for_run(client, sid, run_id, {"waiting_for_human"})
            with client.stream(
                "GET", f"/api/sessions/{sid}/runs/{run_id}/events"
            ) as response:
                first = _parse_sse(response.iter_lines(), stop_types=("pause", "terminal"))
            self.assertEqual("pause", first[-1]["event"])
            self.assertTrue(first[-1]["data"]["is_partial"])

            client.post(
                f"/api/sessions/{sid}/runs/{run_id}/resume",
                json={"content": "输出"},
            )
            _wait_for_run(client, sid, run_id, {"completed"})
            with client.stream(
                "GET", f"/api/sessions/{sid}/runs/{run_id}/events"
            ) as response:
                second = _parse_sse(response.iter_lines())
            terminals = [event for event in second if event["event"] == "terminal"]
            self.assertEqual(1, len(terminals))
            self.assertEqual("completed", terminals[0]["data"]["status"])


class PresentationTests(unittest.TestCase):
    def _payload(self, status: WorkflowStatus, partial_text: str = "阶段性"):
        state = DiagnosisState(
            user_query="q",
            run_id="r1",
            status=status,
            retrieval_plan=RetrievalPlan(
                evidence_obligations=["规则 A", "规则 B"],
                exact_literals=["Rule"],
                search_queries=["rule"],
            ),
            uncovered_evidence_obligations=["规则 B"],
            critic_report=CriticReport(
                decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
                notes=["missing"],
                missing_evidence=["规则 B"],
            ),
            exploration_log=[
                ExplorationStep(
                    tool_name=ToolName.GREP,
                    path="/",
                    query="Rule",
                    result_summary="1 hit",
                )
            ],
        )
        state.evidence = [
            EvidenceItem(
                source_path="/rule.md",
                summary="rule",
                quote="Rule A applies.",
                line_start=1,
                line_end=1,
                verified=True,
                supports_obligations=["规则 A"],
            ),
            EvidenceItem(
                source_path="/other.md",
                summary="other",
                quote="Unrelated.",
                line_start=2,
                line_end=2,
                verified=True,
            ),
        ]
        state.diagnosis_draft = DiagnosisDraft(
            summary="暂定断言",
            recommended_actions=["危险操作：重启 sshd"],
            cited_evidence=["/rule.md:L1"],
        )
        state.partial_answer = partial_text
        job = SimpleNamespace(
            run_id="r1",
            query="q",
            status=RunState.ABSTAINED,
            response=QAResponse(
                state=state,
                answer=partial_text,
                is_partial=True,
            ),
            error=None,
            created_at=1.0,
            updated_at=2.0,
        )
        session = SimpleNamespace(session_id="s1", dry_run=True)
        return run_payload(session, job), state

    def test_partial_runs_are_flagged_and_omit_actions(self) -> None:
        payload, _ = self._payload(WorkflowStatus.ABSTAINED)
        self.assertTrue(payload["is_partial"])
        self.assertNotIn("recommended_actions", payload)
        self.assertNotIn("危险操作", json.dumps(payload, ensure_ascii=False))

    def test_evidence_marks_cited_and_uncited(self) -> None:
        payload, _ = self._payload(WorkflowStatus.ABSTAINED)
        cited = {item["citation_key"]: item["cited"] for item in payload["evidence"]}
        self.assertTrue(cited["/rule.md:L1"])
        self.assertFalse(cited["/other.md:L2"])

    def test_plan_reports_coverage(self) -> None:
        payload, _ = self._payload(WorkflowStatus.ABSTAINED)
        coverage = {
            item["text"]: item["covered"]
            for item in payload["plan"]["obligations"]
        }
        self.assertTrue(coverage["规则 A"])
        self.assertFalse(coverage["规则 B"])

    def test_trace_and_critic_are_exposed(self) -> None:
        payload, _ = self._payload(WorkflowStatus.ABSTAINED)
        self.assertEqual("needs_more_evidence", payload["critic"]["decision"])
        self.assertEqual("grep", payload["trace"][0]["tool"])
        self.assertEqual(1, len(payload["trace"]))

    def test_unapproved_command_is_not_exposed(self) -> None:
        from multi_agent_file_analysis.graph import HumanRequest

        state = DiagnosisState(user_query="q", run_id="r1")
        state.human_request = HumanRequest(
            prompt="need",
            expected_input="text",
            suggested_command="systemctl restart sshd",
            command_approved=False,
            command_warning="blocked",
        )
        job = SimpleNamespace(
            run_id="r1",
            query="q",
            status=RunState.WAITING_FOR_HUMAN,
            response=QAResponse(
                state=state,
                answer="partial",
                needs_human_input=True,
                is_partial=True,
            ),
            error=None,
            created_at=1.0,
            updated_at=2.0,
        )
        session = SimpleNamespace(session_id="s1", dry_run=False)
        payload = run_payload(session, job)
        self.assertIsNone(payload["human_request"]["suggested_command"])


class StaticAndIntegrationTests(ConsoleTestBase):
    def test_index_page_is_served(self) -> None:
        app, client = self.make_client()
        with client:
            response = client.get("/")
            self.assertEqual(200, response.status_code)
            self.assertIn("MAFA", response.text)
            response = client.get("/static/app.js")
            self.assertEqual(200, response.status_code)

    def test_console_assets_render_metrics_panel(self) -> None:
        app, client = self.make_client()
        with client:
            script = client.get("/static/app.js").text
        self.assertIn("用量与耗时", script)
        self.assertIn("total_tokens", script)

    def test_ops_demo_full_cycle_with_dry_run(self) -> None:
        app = create_app(
            PROJECT_ROOT / "knowledge_base",
            env_file_path=self.base / "missing.env",
            settings=WebSettings(
                idle_ttl_seconds=60,
                max_sessions=4,
                heartbeat_seconds=0.05,
            ),
            max_workers=2,
        )
        with TestClient(app) as client:
            corpora = client.get("/api/corpora").json()["corpora"]
            ids = {corpus["id"] for corpus in corpora}
            self.assertIn("openssh", ids)
            session = client.post(
                "/api/sessions",
                json={"corpus_id": "openssh", "dry_run": True},
            )
            self.assertEqual(201, session.status_code, session.text)
            sid = session.json()["session_id"]
            started = time.time()
            submitted = client.post(
                f"/api/sessions/{sid}/ask",
                json={
                    "query": (
                        "current-lab 中 alice 属于 contractors，"
                        "为什么全局允许转发但隧道仍被拒绝？"
                    )
                },
            )
            self.assertEqual(202, submitted.status_code)
            payload = _wait_for_run(
                client,
                sid,
                submitted.json()["run_id"],
                {"completed", "abstained", "failed"},
                timeout=20,
            )
            elapsed = time.time() - started
            self.assertTrue(payload["evidence"], "expected verified evidence")
            self.assertGreater(elapsed, 0.0)
            self.assertIn(payload["status"], {"completed", "abstained", "failed"})


if __name__ == "__main__":
    unittest.main()
