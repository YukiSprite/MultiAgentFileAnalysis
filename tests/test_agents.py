from __future__ import annotations

import json
import unittest

from multi_agent_file_analysis.agents import CriticAgent, ReasonerAgent
from multi_agent_file_analysis.core import (
    EvidenceKind,
    ReviewDecision,
    WorkflowStage,
)
from multi_agent_file_analysis.graph import (
    DiagnosisDraft,
    DiagnosisState,
    EvidenceItem,
)
from multi_agent_file_analysis.llm import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
)


class StaticLLM:
    def __init__(self, content: str) -> None:
        self.content = content

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            message=LLMMessage(role="assistant", content=self.content),
            model="test",
        )


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


class AgentSafetyTests(unittest.TestCase):
    def test_unsafe_human_command_is_removed(self) -> None:
        output = json.dumps(
            {
                "action": "human_request",
                "prompt": "Check the state",
                "expected_input": "command output",
                "reason": "Runtime state is missing",
                "suggested_command": "rm -rf /",
            }
        )
        state = DiagnosisState(user_query="why")
        result = ReasonerAgent(llm_client=StaticLLM(output)).run(state)
        self.assertEqual(WorkflowStage.REQUEST_HUMAN_INPUT, result.next_stage)
        self.assertIsNotNone(state.human_request)
        assert state.human_request is not None
        self.assertIsNone(state.human_request.suggested_command)
        self.assertFalse(state.human_request.command_approved)
        self.assertIn("not in", state.human_request.command_warning or "")

    def test_critic_parse_failure_does_not_approve(self) -> None:
        state = DiagnosisState(
            user_query="why",
            evidence=[verified_evidence()],
            diagnosis_draft=DiagnosisDraft(
                summary="A diagnosis",
                cited_evidence=["/docs/rule.md:L3"],
            ),
        )
        result = CriticAgent(llm_client=StaticLLM("not-json")).run(state)
        self.assertEqual(WorkflowStage.REASON, result.next_stage)
        self.assertIsNotNone(state.critic_report)
        assert state.critic_report is not None
        self.assertEqual(
            ReviewDecision.NEEDS_REVISION,
            state.critic_report.decision,
        )
        self.assertIsNone(state.final_answer)

    def test_rule_based_critic_renders_only_approved_draft(self) -> None:
        state = DiagnosisState(
            user_query="why",
            evidence=[verified_evidence()],
            diagnosis_draft=DiagnosisDraft(
                summary="Supported summary",
                root_cause="Supported cause",
                recommended_actions=["Inspect the current state."],
                cited_evidence=["/docs/rule.md:L3"],
                confidence="medium",
            ),
        )
        result = CriticAgent().run(state)
        self.assertEqual(WorkflowStage.FINALIZE, result.next_stage)
        self.assertIn("Supported summary", state.final_answer or "")
        self.assertIn("/docs/rule.md:L3", state.final_answer or "")


if __name__ == "__main__":
    unittest.main()
