from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from multi_agent_file_analysis.agents import CriticAgent, ReasonerAgent
from multi_agent_file_analysis.agents.critic import CRITIC_SYSTEM_PROMPT
from multi_agent_file_analysis.agents.reasoner import REASONER_SYSTEM_PROMPT
from multi_agent_file_analysis.agents import AgentResult
from multi_agent_file_analysis.audit import MemoryAuditRecorder
from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import (
    AgentResultStatus,
    AgentRole,
    ConfigError,
    EvidenceKind,
    ReviewDecision,
    TrustLevel,
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
)
from multi_agent_file_analysis.graph.partial import render_partial_answer
from multi_agent_file_analysis.hitl import HITLSession
from multi_agent_file_analysis.llm import LLMMessage, LLMRequest, LLMResponse
from multi_agent_file_analysis.qa import QAResponse
from multi_agent_file_analysis.web.jobs import RunState
from multi_agent_file_analysis.web.serializers import run_payload


class RecordingLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            message=LLMMessage(role="assistant", content=self.content),
            model="test",
        )


class SequenceLLM:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            message=LLMMessage(role="assistant", content=self.contents.pop(0)),
            model="test",
        )


def evidence(summary: str, quote: str) -> EvidenceItem:
    return EvidenceItem(
        source_path="/docs/rule.md",
        summary=summary,
        kind=EvidenceKind.RULE,
        quote=quote,
        line_start=3,
        line_end=3,
        content_hash="abc",
        verified=True,
    )


class ConfigLimitTests(unittest.TestCase):
    def _config(self, tmp: str, resumes: int) -> AppConfig:
        root = Path(tmp)
        index = root / "index.yaml"
        index.write_text("version: '0.2'\n", encoding="utf-8")
        kb = root / "kb"
        kb.mkdir()
        return AppConfig(index, kb, max_hitl_resumes=resumes)

    def test_zero_resumes_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._config(tmp, 0).validate()

    def test_negative_resumes_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                self._config(tmp, -1).validate()


class ReasonerTrustTests(unittest.TestCase):
    def test_digest_is_labelled_in_prompt(self) -> None:
        llm = RecordingLLM(
            json.dumps({"action": "draft", "summary": "ok", "cited_evidence": []})
        )
        state = DiagnosisState(
            user_query="q",
            evidence=[evidence("Main unit is always", "Exact quote here.")],
        )
        ReasonerAgent(llm_client=llm).run(state)
        prompt = llm.requests[0].messages[1].content
        self.assertIn("Digest (model-written, not evidence", prompt)
        self.assertIn("Exact quote here.", prompt)

    def test_user_asserted_runtime_is_labelled(self) -> None:
        llm = RecordingLLM(
            json.dumps({"action": "draft", "summary": "ok", "cited_evidence": []})
        )
        state = DiagnosisState(
            user_query="q",
            evidence=[evidence("rule", "Exact quote here.")],
        )
        state.runtime_context.append(
            SimpleNamespace(
                request_id="r1",
                verified=False,
                trust=TrustLevel.USER_ASSERTED,
                label="端口",
                content="Port 22",
            )
        )
        ReasonerAgent(llm_client=llm).run(state)
        prompt = llm.requests[0].messages[1].content
        self.assertIn("trust=user_asserted", prompt)
        self.assertIn("user_asserted", REASONER_SYSTEM_PROMPT)

    def test_repeated_request_after_reply_is_repaired(self) -> None:
        human_request = json.dumps(
            {
                "action": "human_request",
                "prompt": "Need port",
                "expected_input": "port value",
            }
        )
        draft = json.dumps(
            {
                "action": "draft",
                "summary": "按用户提供的 Port 22 进行条件化判断。",
                "cited_evidence": [],
                "uncertainties": ["端口由用户提供，未验证。"],
            }
        )
        llm = SequenceLLM([human_request, draft])
        state = DiagnosisState(
            user_query="q",
            evidence=[evidence("rule", "Exact quote here.")],
            resume_count=1,
        )
        state.runtime_context.append(
            SimpleNamespace(
                request_id="r1",
                verified=False,
                trust=TrustLevel.USER_ASSERTED,
                label="端口",
                content="Port 22",
            )
        )
        result = ReasonerAgent(llm_client=llm).run(state)
        self.assertEqual(WorkflowStage.CRITIQUE, result.next_stage)
        self.assertEqual(2, len(llm.requests))
        assert state.diagnosis_draft is not None
        self.assertIn("Port 22", state.diagnosis_draft.summary)

    def test_repeated_request_falls_back_to_conditional_draft(self) -> None:
        human_request = json.dumps(
            {
                "action": "human_request",
                "prompt": "请提供 sshd -T 输出中的 port 行",
                "expected_input": "port value",
            }
        )
        llm = SequenceLLM([human_request, human_request])
        state = DiagnosisState(
            user_query="q",
            evidence=[evidence("rule", "Exact quote here.")],
            resume_count=1,
        )
        state.runtime_context.append(
            SimpleNamespace(
                request_id="r1",
                verified=False,
                trust=TrustLevel.USER_ASSERTED,
                label="请提供 current-lab 的 SSH 监听端口",
                content="Port 22",
            )
        )
        result = ReasonerAgent(llm_client=llm).run(state)
        self.assertEqual(WorkflowStage.CRITIQUE, result.next_stage)
        self.assertIsNone(state.human_request)
        assert state.diagnosis_draft is not None
        self.assertIn("Port 22", state.diagnosis_draft.summary)
        self.assertIn("条件化结论", state.diagnosis_draft.summary)

    def test_rejected_command_is_kept_as_preview(self) -> None:
        output = json.dumps(
            {
                "action": "human_request",
                "prompt": "Need port",
                "expected_input": "sshd -T output",
                "suggested_command": "sshd -T | grep -i port",
            }
        )
        state = DiagnosisState(user_query="q", resume_count=2)
        ReasonerAgent(llm_client=RecordingLLM(output)).run(state)
        request = state.human_request
        assert request is not None
        self.assertIsNone(request.suggested_command)
        self.assertEqual("sshd -T | grep -i port", request.rejected_command)
        self.assertIn("Shell composition", request.command_warning or "")
        self.assertEqual(3, request.attempt)


class CriticAttributionTests(unittest.TestCase):
    def _state(self) -> DiagnosisState:
        return DiagnosisState(
            user_query="q",
            evidence=[
                evidence(
                    "Main unit is Restart=always",
                    "drop-in sets Restart=on-failure",
                )
            ],
            diagnosis_draft=DiagnosisDraft(
                summary="Main unit is Restart=always",
                cited_evidence=["/docs/rule.md:L3"],
            ),
        )

    def test_digest_overreach_routes_back_to_explorer(self) -> None:
        output = json.dumps(
            {
                "decision": "needs_revision",
                "notes": ["unsupported"],
                "missing_evidence": [],
                "unsupported_claims": ["Main unit is Restart=always"],
            }
        )
        state = self._state()
        result = CriticAgent(llm_client=RecordingLLM(output)).run(state)
        self.assertEqual(WorkflowStage.EXPLORE, result.next_stage)
        assert state.critic_report is not None
        self.assertEqual(
            ReviewDecision.NEEDS_MORE_EVIDENCE,
            state.critic_report.decision,
        )

    def test_unrelated_claim_stays_on_revision(self) -> None:
        output = json.dumps(
            {
                "decision": "needs_revision",
                "notes": ["unsupported"],
                "missing_evidence": [],
                "unsupported_claims": ["The daemon must be restarted manually"],
            }
        )
        state = self._state()
        result = CriticAgent(llm_client=RecordingLLM(output)).run(state)
        self.assertEqual(WorkflowStage.REASON, result.next_stage)

    def test_final_answer_uses_quote_not_digest(self) -> None:
        state = DiagnosisState(
            user_query="q",
            evidence=[evidence("digest-only claim", "Exact source sentence.")],
            diagnosis_draft=DiagnosisDraft(
                summary="Supported summary",
                cited_evidence=["/docs/rule.md:L3"],
            ),
        )
        CriticAgent().run(state)
        self.assertIn("Exact source sentence.", state.final_answer or "")
        self.assertNotIn("digest-only claim", state.final_answer or "")

    def test_final_answer_separates_runtime_basis(self) -> None:
        state = DiagnosisState(
            user_query="q",
            evidence=[evidence("rule", "Exact source sentence.")],
            diagnosis_draft=DiagnosisDraft(
                summary="Supported summary",
                cited_evidence=["/docs/rule.md:L3"],
            ),
        )
        state.runtime_context.append(
            SimpleNamespace(
                request_id="req-9",
                verified=False,
                trust=TrustLevel.USER_ASSERTED,
                label="端口",
                content="Port 22",
            )
        )
        CriticAgent().run(state)
        self.assertIn("## 运行时依据（用户提供，未验证）", state.final_answer or "")
        self.assertIn("req-9", state.final_answer or "")
        self.assertIn("Port 22", state.final_answer or "")
        self.assertIn("user_asserted", CRITIC_SYSTEM_PROMPT)

    def test_partial_answer_separates_runtime_basis(self) -> None:
        state = DiagnosisState(
            user_query="q",
            evidence=[evidence("rule", "Exact source sentence.")],
        )
        state.runtime_context.append(
            SimpleNamespace(
                request_id="req-9",
                verified=False,
                trust=TrustLevel.USER_ASSERTED,
                label="端口",
                content="Port 22",
            )
        )
        partial = render_partial_answer(state)
        self.assertIn("## 已核验的阶段性事实", partial)
        self.assertIn("## 运行时依据（用户提供，未验证）", partial)
        self.assertLess(
            partial.index("## 已核验的阶段性事实"),
            partial.index("## 运行时依据（用户提供，未验证）"),
        )


class CountingExplorer:
    role = AgentRole.EXPLORER

    def run(self, state, context=None):
        if not state.evidence:
            state.evidence.append(evidence("rule", "Exact source sentence."))
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.SUCCEEDED,
            message="evidence",
            next_stage=WorkflowStage.REASON,
        )


class AlwaysHITLReasoner:
    role = AgentRole.REASONER

    def run(self, state, context=None):
        state.human_request = HumanRequest(
            prompt="Need status",
            expected_input="text",
            request_id="r1",
            rejected_command="sshd -T | grep -i port",
            command_warning="Shell composition",
            attempt=state.resume_count + 1,
        )
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.NEEDS_MORE_CONTEXT,
            message="need runtime",
            next_stage=WorkflowStage.REQUEST_HUMAN_INPUT,
        )


class ApprovingCritic:
    role = AgentRole.CRITIC

    def run(self, state, context=None):
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


class HitlBudgetTests(unittest.TestCase):
    def _workflow(self, resumes: int, *, audit=None) -> DiagnosisWorkflow:
        return DiagnosisWorkflow(
            explorer=CountingExplorer(),
            reasoner=AlwaysHITLReasoner(),
            critic=ApprovingCritic(),
            hitl_session=HITLSession(),
            audit_recorder=audit,
            max_hitl_resumes=resumes,
        )

    def test_zero_budget_never_suspends(self) -> None:
        state = self._workflow(0).run(DiagnosisState(user_query="q"))
        self.assertEqual(WorkflowStatus.ABSTAINED, state.status)
        self.assertTrue(
            any("HITL resume budget exhausted" in item for item in state.errors)
        )
        self.assertIsNone(state.human_request)
        self.assertIn(
            "HITL resume budget exhausted", state.partial_answer or ""
        )
        self.assertIsNotNone(state.metrics.ended_at)

    def test_budget_limits_repeated_resumes(self) -> None:
        workflow = self._workflow(2)
        state = workflow.run(DiagnosisState(user_query="q"))
        self.assertEqual(WorkflowStatus.WAITING_FOR_HUMAN, state.status)
        self.assertEqual(0, state.resume_count)
        state = workflow.resume(state, "first")
        self.assertEqual(WorkflowStatus.WAITING_FOR_HUMAN, state.status)
        self.assertEqual(1, state.resume_count)
        state = workflow.resume(state, "second")
        self.assertEqual(WorkflowStatus.ABSTAINED, state.status)
        self.assertEqual(2, state.resume_count)
        self.assertIn("阶段性回答", state.partial_answer or "")

    def test_rejected_command_preview_is_not_audited(self) -> None:
        audit = MemoryAuditRecorder()
        state = self._workflow(0, audit=audit).run(
            DiagnosisState(user_query="q")
        )
        self.assertEqual(WorkflowStatus.ABSTAINED, state.status)
        for event in audit.events:
            for value in event.payload.values():
                self.assertNotIn("grep", value)


class WebPayloadTests(unittest.TestCase):
    def test_console_renders_rejected_command(self) -> None:
        script = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "multi_agent_file_analysis"
            / "web"
            / "static"
            / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("rejected_command", script)
        self.assertIn("次追问", script)

    def test_human_request_exposes_command_state(self) -> None:
        state = DiagnosisState(user_query="q", run_id="r1")
        state.human_request = HumanRequest(
            prompt="need",
            expected_input="text",
            command_approved=False,
            command_warning="blocked",
            rejected_command="sshd -T | grep port",
            attempt=2,
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
        request = run_payload(session, job)["human_request"]
        self.assertFalse(request["command_approved"])
        self.assertEqual("blocked", request["command_warning"])
        self.assertEqual("sshd -T | grep port", request["rejected_command"])
        self.assertEqual(2, request["attempt"])
        self.assertIsNone(request["suggested_command"])


if __name__ == "__main__":
    unittest.main()
