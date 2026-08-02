from __future__ import annotations

import unittest

from multi_agent_file_analysis.agents import AgentResult
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
)
from multi_agent_file_analysis.hitl import HITLSession
from multi_agent_file_analysis.qa import QARequest, QAService


def evidence() -> EvidenceItem:
    return EvidenceItem(
        source_path="/rule.md",
        summary="rule",
        kind=EvidenceKind.RULE,
        quote="Verified rule.",
        line_start=1,
        line_end=1,
        content_hash="abc",
        verified=True,
    )


class CountingExplorer:
    role = AgentRole.EXPLORER

    def __init__(self) -> None:
        self.calls = 0

    def run(self, state, context=None):
        self.calls += 1
        if not state.evidence:
            state.evidence.append(evidence())
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.SUCCEEDED,
            message="evidence",
            next_stage=WorkflowStage.REASON,
        )


class HITLThenDraftReasoner:
    role = AgentRole.REASONER

    def run(self, state, context=None):
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
            cited_evidence=["/rule.md:L1"],
        )
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.SUCCEEDED,
            message="draft",
            next_stage=WorkflowStage.CRITIQUE,
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


class FailingReasoner:
    role = AgentRole.REASONER

    def run(self, state, context=None):
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.FAILED,
            message="reasoning failed",
            next_stage=None,
        )


class RevisionCritic:
    role = AgentRole.CRITIC

    def run(self, state, context=None):
        state.critic_report = CriticReport(
            decision=ReviewDecision.NEEDS_REVISION,
            notes=["revise"],
        )
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.REJECTED,
            message="revise",
            next_stage=WorkflowStage.REASON,
        )


class WorkflowTests(unittest.TestCase):
    def test_resume_continues_at_reasoner_without_reexploring(self) -> None:
        explorer = CountingExplorer()
        workflow = DiagnosisWorkflow(
            explorer=explorer,
            reasoner=HITLThenDraftReasoner(),
            critic=ApprovingCritic(),
            hitl_session=HITLSession(),
        )
        state = workflow.run(DiagnosisState(user_query="question"))
        self.assertEqual(WorkflowStatus.WAITING_FOR_HUMAN, state.status)
        self.assertEqual(1, explorer.calls)
        self.assertIn("阶段性回答（尚未完成最终审查）", state.partial_answer or "")
        self.assertIn("Verified rule.", state.partial_answer or "")
        self.assertIn("等待补充现场信息", state.partial_answer or "")
        state = workflow.resume(state, "service is active")
        self.assertEqual(WorkflowStatus.COMPLETED, state.status)
        self.assertEqual(1, explorer.calls)
        self.assertEqual("approved answer", state.final_answer)

    def test_failure_is_not_overwritten_as_completed(self) -> None:
        workflow = DiagnosisWorkflow(
            explorer=CountingExplorer(),
            reasoner=FailingReasoner(),
            critic=ApprovingCritic(),
        )
        state = workflow.run(DiagnosisState(user_query="question"))
        self.assertEqual(WorkflowStatus.FAILED, state.status)
        self.assertIn("reasoning failed", state.errors)
        self.assertIn("阶段性回答", state.partial_answer or "")
        self.assertIn("Verified rule.", state.partial_answer or "")
        self.assertIn("reasoning failed", state.partial_answer or "")

    def test_qa_service_returns_partial_answer_for_terminal_failure(self) -> None:
        workflow = DiagnosisWorkflow(
            explorer=CountingExplorer(),
            reasoner=FailingReasoner(),
            critic=ApprovingCritic(),
        )

        response = QAService(workflow).ask(QARequest(query="question"))

        self.assertTrue(response.is_partial)
        self.assertIn("阶段性回答", response.answer or "")
        self.assertIsNone(response.state.final_answer)

    def test_review_retry_budget_ends_in_abstention(self) -> None:
        class DraftReasoner:
            role = AgentRole.REASONER

            def run(self, state, context=None):
                state.diagnosis_draft = DiagnosisDraft(
                    summary="draft",
                    cited_evidence=["/rule.md:L1"],
                )
                return AgentResult(
                    role=self.role,
                    status=AgentResultStatus.SUCCEEDED,
                    message="draft",
                    next_stage=WorkflowStage.CRITIQUE,
                )

        workflow = DiagnosisWorkflow(
            explorer=CountingExplorer(),
            reasoner=DraftReasoner(),
            critic=RevisionCritic(),
            max_review_retries=1,
            max_iterations=10,
        )
        state = workflow.run(DiagnosisState(user_query="question"))
        self.assertEqual(WorkflowStatus.ABSTAINED, state.status)
        self.assertEqual(2, state.review_attempts)
        self.assertIn("当前暂定断言", state.partial_answer or "")
        self.assertIn("draft", state.partial_answer or "")
        self.assertIn("Critic retry budget exhausted", state.partial_answer or "")


if __name__ == "__main__":
    unittest.main()
