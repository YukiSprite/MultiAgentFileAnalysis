from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from multi_agent_file_analysis.agents import (
    AgentResult,
    CriticAgent,
    ExplorerAgent,
    ReasonerAgent,
)
from multi_agent_file_analysis.agents.base import call_llm
from multi_agent_file_analysis.audit import (
    AuditEventType,
    JsonlAuditRecorder,
    MemoryAuditRecorder,
)
from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import (
    AgentResultStatus,
    AgentRole,
    EvidenceKind,
    ReviewDecision,
    WorkflowStage,
    WorkflowStatus,
)
from multi_agent_file_analysis.graph import (
    CriticReport,
    DiagnosisDraft,
    DiagnosisState,
    DiagnosisWorkflow,
    EvidenceItem,
    HumanRequest,
    RoleUsage,
    RunMetrics,
    StageTiming,
)
from multi_agent_file_analysis.hitl import HITLSession
from multi_agent_file_analysis.index import (
    IndexNode,
    NodeKind,
    PageIndex,
    PageIndexRepository,
)
from multi_agent_file_analysis.llm import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    TokenUsage,
)
from multi_agent_file_analysis.qa import QARequest, QAResponse, QAService
from multi_agent_file_analysis.vfs import VirtualFileSystem
from multi_agent_file_analysis.web.events import EventBus
from multi_agent_file_analysis.web.jobs import JobRunner, RunJob, RunState
from multi_agent_file_analysis.web.serializers import run_payload


def assert_json_basic(test: unittest.TestCase, value: object) -> None:
    """Fail if value contains anything json.dumps cannot round-trip."""

    if isinstance(value, dict):
        for key, item in value.items():
            test.assertIsInstance(key, str)
            assert_json_basic(test, item)
    elif isinstance(value, list):
        for item in value:
            assert_json_basic(test, item)
    else:
        test.assertIn(
            type(value),
            {str, int, float, bool, type(None)},
            f"non-JSON type {type(value)!r}",
        )


class RunMetricsTests(unittest.TestCase):
    def test_empty_ledger_has_full_shape(self) -> None:
        payload = RunMetrics().to_dict()
        self.assertEqual({}, payload["roles"])
        self.assertEqual({}, payload["stages"])
        self.assertIsNone(payload["started_at"])
        self.assertIsNone(payload["ended_at"])
        self.assertEqual(0, payload["total_tokens"])
        assert_json_basic(self, payload)

    def test_single_role_accumulates_tokens_and_calls(self) -> None:
        metrics = RunMetrics()
        usage = metrics.role(AgentRole.EXPLORER)
        usage.add_tokens(10, 5, 15)
        usage.record_call()
        usage.add_tokens(20, 7, 27)
        usage.record_call()

        payload = metrics.to_dict()
        self.assertEqual(
            {
                "prompt_tokens": 30,
                "completion_tokens": 12,
                "total_tokens": 42,
                "calls": 2,
                "failures": 0,
                "calls_without_usage": 0,
            },
            payload["roles"]["explorer"],
        )
        self.assertEqual(42, payload["total_tokens"])
        assert_json_basic(self, payload)

    def test_single_stage_accumulates_and_clamps_negative(self) -> None:
        metrics = RunMetrics()
        stage = metrics.stage(WorkflowStage.EXPLORE)
        stage.add(1.5)
        stage.add(-3.0)
        stage.add(0.25)

        payload = metrics.to_dict()
        self.assertAlmostEqual(1.75, payload["stages"]["explore"]["seconds"])
        self.assertEqual(3, payload["stages"]["explore"]["entries"])
        assert_json_basic(self, payload)

    def test_calls_without_usage_are_counted(self) -> None:
        usage = RoleUsage()
        usage.record_missing_usage()
        usage.record_missing_usage()
        usage.record_call()

        self.assertEqual(3, usage.calls)
        self.assertEqual(2, usage.calls_without_usage)
        self.assertEqual(0, usage.total_tokens)

    def test_failure_increments_failures_and_keeps_tokens(self) -> None:
        usage = RoleUsage()
        usage.add_tokens(5, 1, 6)
        usage.record_call()
        usage.record_failure()

        self.assertEqual(6, usage.total_tokens)
        self.assertEqual(2, usage.calls)
        self.assertEqual(1, usage.failures)

    def test_stage_timing_default_is_zero(self) -> None:
        self.assertEqual({"seconds": 0.0, "entries": 0}, StageTiming().to_dict())


class StaticUsageLLM:
    """LLM stub with configurable content and usage, or one that raises."""

    def __init__(
        self,
        usage: TokenUsage | None = None,
        error: Exception | None = None,
        content: str = "ok",
    ) -> None:
        self.usage = usage
        self.error = error
        self.content = content
        self.calls = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMResponse(
            message=LLMMessage(role="assistant", content=self.content),
            model="test",
            usage=self.usage,
        )


def make_request() -> LLMRequest:
    return LLMRequest(messages=[LLMMessage(role="user", content="q")])


def verified_evidence() -> EvidenceItem:
    return EvidenceItem(
        source_path="/docs/rule.md",
        summary="A verified rule",
        kind=EvidenceKind.RULE,
        quote="The setting must be yes.",
        line_start=3,
        line_end=3,
        content_hash="abc",
        verified=True,
    )


class ManualClock:
    """Controllable monotonic clock so stage timings are deterministic."""

    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TimedExplorer:
    role = AgentRole.EXPLORER

    def __init__(self, clock: ManualClock, seconds: float) -> None:
        self._clock = clock
        self._seconds = seconds
        self.calls = 0

    def run(self, state, context=None):
        self.calls += 1
        self._clock.advance(self._seconds)
        if not state.evidence:
            state.evidence.append(verified_evidence())
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.SUCCEEDED,
            message="evidence",
            next_stage=WorkflowStage.REASON,
        )


class TimedReasoner:
    role = AgentRole.REASONER

    def __init__(self, clock: ManualClock, seconds: float) -> None:
        self._clock = clock
        self._seconds = seconds

    def run(self, state, context=None):
        self._clock.advance(self._seconds)
        state.diagnosis_draft = DiagnosisDraft(
            summary="diagnosis",
            cited_evidence=["/docs/rule.md:L3"],
        )
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.SUCCEEDED,
            message="draft",
            next_stage=WorkflowStage.CRITIQUE,
        )


class TimedHITLReasoner:
    role = AgentRole.REASONER

    def __init__(self, clock: ManualClock, seconds: float) -> None:
        self._clock = clock
        self._seconds = seconds

    def run(self, state, context=None):
        self._clock.advance(self._seconds)
        if not state.runtime_context:
            state.human_request = HumanRequest(
                prompt="Provide status",
                expected_input="text",
                request_id="request-1",
            )
            return AgentResult(
                role=self.role,
                status=AgentResultStatus.NEEDS_MORE_CONTEXT,
                message="need runtime",
                next_stage=WorkflowStage.REQUEST_HUMAN_INPUT,
            )
        state.diagnosis_draft = DiagnosisDraft(
            summary="diagnosis",
            cited_evidence=["/docs/rule.md:L3"],
        )
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.SUCCEEDED,
            message="draft",
            next_stage=WorkflowStage.CRITIQUE,
        )


class TimedCritic:
    role = AgentRole.CRITIC

    def __init__(self, clock: ManualClock, seconds: float) -> None:
        self._clock = clock
        self._seconds = seconds

    def run(self, state, context=None):
        self._clock.advance(self._seconds)
        state.critic_report = CriticReport(
            decision=ReviewDecision.APPROVED,
            notes=["ok"],
        )
        state.final_answer = "approved answer"
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.SUCCEEDED,
            message="approved",
            next_stage=WorkflowStage.FINALIZE,
        )


class StageTimingTests(unittest.TestCase):
    def test_stage_durations_accumulate_with_entries(self) -> None:
        clock = ManualClock()
        workflow = DiagnosisWorkflow(
            explorer=TimedExplorer(clock, 2.0),
            reasoner=TimedReasoner(clock, 0.5),
            critic=TimedCritic(clock, 1.5),
            clock=clock,
        )
        state = workflow.run(DiagnosisState(user_query="q"))

        stages = state.metrics.stages
        self.assertAlmostEqual(2.0, stages["explore"].seconds)
        self.assertAlmostEqual(0.5, stages["reason"].seconds)
        self.assertAlmostEqual(1.5, stages["critique"].seconds)
        self.assertEqual(1, stages["explore"].entries)
        self.assertIsNotNone(state.metrics.started_at)
        self.assertIsNotNone(state.metrics.ended_at)
        assert state.metrics.started_at is not None
        assert state.metrics.ended_at is not None
        self.assertGreaterEqual(state.metrics.ended_at, state.metrics.started_at)

    def test_backwards_clock_is_clamped_to_zero(self) -> None:
        clock = ManualClock()
        workflow = DiagnosisWorkflow(
            explorer=TimedExplorer(clock, -5.0),
            reasoner=TimedReasoner(clock, 0.0),
            critic=TimedCritic(clock, 0.0),
            clock=clock,
        )
        state = workflow.run(DiagnosisState(user_query="q"))

        self.assertEqual(0.0, state.metrics.stages["explore"].seconds)
        self.assertEqual(1, state.metrics.stages["explore"].entries)

    def test_human_wait_is_excluded_from_stage_durations(self) -> None:
        clock = ManualClock()
        workflow = DiagnosisWorkflow(
            explorer=TimedExplorer(clock, 0.25),
            reasoner=TimedHITLReasoner(clock, 0.5),
            critic=TimedCritic(clock, 0.75),
            hitl_session=HITLSession(),
            clock=clock,
        )
        state = workflow.run(DiagnosisState(user_query="q"))
        self.assertEqual(WorkflowStatus.WAITING_FOR_HUMAN, state.status)
        self.assertIsNone(state.metrics.ended_at)
        paused_reason = state.metrics.stages["reason"].seconds

        clock.advance(3600.0)
        state = workflow.resume(state, "service is active")

        self.assertEqual(WorkflowStatus.COMPLETED, state.status)
        self.assertAlmostEqual(
            paused_reason + 0.5,
            state.metrics.stages["reason"].seconds,
        )
        self.assertLess(state.metrics.stages["request_human_input"].seconds, 1.0)
        self.assertIsNotNone(state.metrics.ended_at)


class CallLlmAccountingTests(unittest.TestCase):
    def test_successful_call_adds_usage(self) -> None:
        state = DiagnosisState(user_query="q")
        llm = StaticUsageLLM(TokenUsage(prompt_tokens=11, completion_tokens=4, total_tokens=15))

        call_llm(state, AgentRole.EXPLORER, llm, make_request())

        usage = state.metrics.roles["explorer"]
        self.assertEqual(1, usage.calls)
        self.assertEqual(15, usage.total_tokens)
        self.assertEqual(0, usage.calls_without_usage)

    def test_missing_usage_is_counted_not_guessed(self) -> None:
        state = DiagnosisState(user_query="q")
        llm = StaticUsageLLM(usage=None)

        call_llm(state, AgentRole.CRITIC, llm, make_request())

        usage = state.metrics.roles["critic"]
        self.assertEqual(1, usage.calls)
        self.assertEqual(1, usage.calls_without_usage)
        self.assertEqual(0, usage.total_tokens)

    def test_exception_is_recorded_and_reraised(self) -> None:
        state = DiagnosisState(user_query="q")
        llm = StaticUsageLLM(error=RuntimeError("provider down"))

        with self.assertRaises(RuntimeError):
            call_llm(state, AgentRole.REASONER, llm, make_request())

        usage = state.metrics.roles["reasoner"]
        self.assertEqual(1, usage.calls)
        self.assertEqual(1, usage.failures)

    def test_failure_keeps_previously_counted_tokens(self) -> None:
        state = DiagnosisState(user_query="q")
        call_llm(
            state,
            AgentRole.REASONER,
            StaticUsageLLM(TokenUsage(3, 2, 5)),
            make_request(),
        )
        with self.assertRaises(RuntimeError):
            call_llm(
                state,
                AgentRole.REASONER,
                StaticUsageLLM(error=RuntimeError("boom")),
                make_request(),
            )

        usage = state.metrics.roles["reasoner"]
        self.assertEqual(5, usage.total_tokens)
        self.assertEqual(2, usage.calls)
        self.assertEqual(1, usage.failures)


class SequenceUsageLLM:
    """Replays scripted responses, each with its own reported usage."""

    def __init__(self, responses: list[tuple[LLMResponse, TokenUsage]]) -> None:
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        response, usage = self.responses.pop(0)
        response.usage = usage
        return response


def build_rule_vfs(base: Path) -> VirtualFileSystem:
    root = base / "kb"
    root.mkdir()
    (root / "rule.md").write_text(
        "# Rule\n\nAllowTcpForwarding yes\n",
        encoding="utf-8",
    )
    index_path = base / "index.yaml"
    index_path.write_text("version: '0.2'\nroot:\n  path: /\n", encoding="utf-8")
    index = PageIndex(
        version="0.2",
        root=IndexNode(
            path="/",
            kind=NodeKind.DIRECTORY,
            description="root",
            children=[
                IndexNode(
                    path="/rule.md",
                    kind=NodeKind.FILE,
                    description="OpenSSH rule",
                    source="rule.md",
                )
            ],
        ),
    )
    return VirtualFileSystem(
        PageIndexRepository(index, root),
        AppConfig(page_index_path=index_path, knowledge_base_root=root),
    )


class ExplorerMetricsTests(unittest.TestCase):
    def test_multi_turn_explorer_sums_calls_and_tokens(self) -> None:
        messages = [
            LLMMessage(
                role="assistant",
                content=(
                    '{"evidence_obligations":["forwarding rule"],'
                    '"exact_literals":["AllowTcpForwarding"],'
                    '"search_queries":["TCP forwarding"]}'
                ),
            ),
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="grep-1",
                        name="grep",
                        arguments={"pattern": "AllowTcpForwarding", "path": "/"},
                    )
                ],
            ),
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="evidence-1",
                        name="record_evidence",
                        arguments={
                            "source_path": "/rule.md",
                            "summary": "TCP forwarding is enabled",
                            "kind": "config_reference",
                            "quote": "AllowTcpForwarding yes",
                            "retrieval_query": "AllowTcpForwarding",
                            "supports_obligations": ["forwarding rule"],
                        },
                    )
                ],
            ),
            LLMMessage(role="assistant", content="Evidence collection complete."),
        ]
        usages = [TokenUsage(10, 1, 11), TokenUsage(20, 2, 22), TokenUsage(30, 3, 33)]
        usages.append(TokenUsage(40, 4, 44))
        llm = SequenceUsageLLM(
            [(LLMResponse(message=message), usage) for message, usage in zip(messages, usages)]
        )

        with tempfile.TemporaryDirectory() as tmp:
            state = DiagnosisState(user_query="Is TCP forwarding enabled?")
            ExplorerAgent(vfs=build_rule_vfs(Path(tmp)), llm_client=llm).run(state)

        usage = state.metrics.roles["explorer"]
        self.assertEqual(4, usage.calls)
        self.assertEqual(11 + 22 + 33 + 44, usage.total_tokens)
        self.assertEqual(100, usage.prompt_tokens)
        self.assertEqual(10, usage.completion_tokens)
        self.assertEqual(0, usage.calls_without_usage)


class AgentRoleMetricsTests(unittest.TestCase):
    def test_three_roles_are_counted_separately(self) -> None:
        state = DiagnosisState(
            user_query="why",
            evidence=[verified_evidence()],
        )
        ReasonerAgent(
            llm_client=StaticUsageLLM(
                usage=TokenUsage(10, 5, 15),
                content=json.dumps(
                    {
                        "action": "draft",
                        "summary": "A diagnosis",
                        "cited_evidence": ["/docs/rule.md:L3"],
                    }
                ),
            )
        ).run(state)
        CriticAgent(
            llm_client=StaticUsageLLM(
                usage=TokenUsage(20, 5, 25),
                content=json.dumps({"decision": "approved", "notes": ["ok"]}),
            )
        ).run(state)

        roles = state.metrics.roles
        self.assertEqual(15, roles["reasoner"].total_tokens)
        self.assertEqual(25, roles["critic"].total_tokens)
        self.assertEqual(1, roles["reasoner"].calls)
        self.assertEqual(1, roles["critic"].calls)
        self.assertEqual(
            sum(usage.total_tokens for usage in roles.values()),
            state.metrics.total_tokens,
        )

    def test_revision_round_appends_instead_of_overwriting(self) -> None:
        state = DiagnosisState(user_query="why", evidence=[verified_evidence()])
        content = json.dumps(
            {
                "action": "draft",
                "summary": "A diagnosis",
                "cited_evidence": ["/docs/rule.md:L3"],
            }
        )
        reasoner = ReasonerAgent(
            llm_client=StaticUsageLLM(
                usage=TokenUsage(10, 5, 15),
                content=content,
            )
        )
        reasoner.run(state)
        reasoner.run(state)

        usage = state.metrics.roles["reasoner"]
        self.assertEqual(2, usage.calls)
        self.assertEqual(30, usage.total_tokens)


class QaServiceMetricsTests(unittest.TestCase):
    def test_paused_response_carries_ledger_structure(self) -> None:
        clock = ManualClock()
        workflow = DiagnosisWorkflow(
            explorer=TimedExplorer(clock, 0.1),
            reasoner=TimedHITLReasoner(clock, 0.2),
            critic=TimedCritic(clock, 0.1),
            hitl_session=HITLSession(),
            clock=clock,
        )

        response = QAService(workflow).ask(QARequest(query="q"))

        self.assertTrue(response.needs_human_input)
        payload = response.state.metrics.to_dict()
        self.assertIn("explore", payload["stages"])
        self.assertIn("request_human_input", payload["stages"])
        self.assertEqual(0, payload["total_tokens"])
        self.assertIsNone(payload["ended_at"])


class AuditMetricsTests(unittest.TestCase):
    def _completed_run(self, recorder):
        clock = ManualClock()
        workflow = DiagnosisWorkflow(
            explorer=TimedExplorer(clock, 0.2),
            reasoner=TimedReasoner(clock, 0.3),
            critic=TimedCritic(clock, 0.1),
            audit_recorder=recorder,
            clock=clock,
        )
        return workflow.run(DiagnosisState(user_query="q"))

    def test_terminal_event_carries_metrics_payload(self) -> None:
        recorder = MemoryAuditRecorder()
        state = self._completed_run(recorder)

        terminal = [
            event
            for event in recorder.events
            if event.event_type == AuditEventType.WORKFLOW_FINISHED
        ]
        self.assertEqual(1, len(terminal))
        payload = terminal[0].payload
        self.assertEqual(
            state.metrics.to_dict(),
            json.loads(payload["metrics"]),
        )
        self.assertEqual(
            str(state.metrics.total_tokens),
            payload["metrics_total_tokens"],
        )

    def test_jsonl_terminal_record_is_self_sufficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "run.jsonl"
            state = self._completed_run(JsonlAuditRecorder(log_path))

            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
            ]

        terminal = [r for r in records if r["event_type"] == "workflow_finished"]
        self.assertEqual(1, len(terminal))
        metrics = json.loads(terminal[0]["metrics"])
        self.assertEqual(state.metrics.to_dict(), metrics)
        self.assertIn("explore", metrics["stages"])
        self.assertEqual(
            str(state.metrics.total_tokens),
            terminal[0]["metrics_total_tokens"],
        )


class MetricsCompatibilityTests(unittest.TestCase):
    def test_state_without_explicit_metrics_still_works(self) -> None:
        state = DiagnosisState(user_query="q")
        self.assertIsInstance(state.metrics, RunMetrics)
        self.assertEqual(0, state.metrics.total_tokens)

    def test_run_payload_serializes_state_with_metrics(self) -> None:
        state = DiagnosisState(user_query="q", run_id="r1")
        usage = state.metrics.role(AgentRole.REASONER)
        usage.add_tokens(3, 4, 7)
        usage.record_call()
        state.metrics.stage(WorkflowStage.REASON).add(0.5)

        job = SimpleNamespace(
            run_id="r1",
            query="q",
            status=RunState.COMPLETED,
            response=QAResponse(state=state, answer="done"),
            error=None,
            created_at=1.0,
            updated_at=2.0,
        )
        session = SimpleNamespace(session_id="s1", dry_run=False)
        payload = run_payload(session, job)

        json.dumps(payload)
        self.assertEqual("completed", payload["status"])
        self.assertEqual(7, payload["metrics"]["total_tokens"])
        self.assertEqual(1, payload["metrics"]["roles"]["reasoner"]["calls"])
        self.assertAlmostEqual(
            0.5,
            payload["metrics"]["stages"]["reason"]["seconds"],
        )

    def test_terminal_event_metrics_match_run_payload(self) -> None:
        state = DiagnosisState(
            user_query="q",
            run_id="r1",
            status=WorkflowStatus.COMPLETED,
        )
        state.metrics.role(AgentRole.CRITIC).add_tokens(5, 5, 10)
        state.metrics.stage(WorkflowStage.CRITIQUE).add(1.25)

        bus = EventBus()
        runner = JobRunner(bus, max_workers=1)
        job = RunJob(run_id="r1", query="q")
        try:
            runner._apply(job, QAResponse(state=state, answer="done"))
        finally:
            runner.shutdown()

        session = SimpleNamespace(session_id="s1", dry_run=False)
        payload = run_payload(session, job)
        terminal = bus.events("r1")[-1]
        self.assertEqual("terminal", terminal.type)
        self.assertEqual(payload["metrics"], terminal.data["metrics"])
        self.assertEqual(10, terminal.data["metrics"]["total_tokens"])


if __name__ == "__main__":
    unittest.main()
