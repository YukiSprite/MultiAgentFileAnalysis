"""Critic agent — fail-closed review against verified evidence."""

from __future__ import annotations

import json
from typing import Any

from multi_agent_file_analysis.agents.base import AgentContext, AgentResult
from multi_agent_file_analysis.core import (
    AgentResultStatus,
    AgentRole,
    ReviewDecision,
    WorkflowStage,
)
from multi_agent_file_analysis.graph.state import CriticReport, DiagnosisState
from multi_agent_file_analysis.hitl import action_requires_explicit_warning
from multi_agent_file_analysis.llm import LLMClient, LLMMessage, LLMRequest


CRITIC_SYSTEM_PROMPT = """You are an evidence and safety critic. Evidence excerpts
have already been bound verbatim to indexed sources. Review whether the draft's
claims, applicability, version scope, and actions are supported.

Return one JSON object:
{"decision":"approved|needs_more_evidence|needs_revision|rejected",
 "notes":["..."],"missing_evidence":["..."],"unsupported_claims":["..."]}

Fail closed. Do not approve merely because a parameter name appears in a source.
Check conditions, exceptions, version, and command safety.
"""


class CriticAgent:
    role = AgentRole.CRITIC

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    def run(
        self,
        state: DiagnosisState,
        context: AgentContext | None = None,
    ) -> AgentResult:
        preflight = self._deterministic_preflight(state)
        if preflight is not None:
            return preflight

        llm = self._llm_client or (context.llm_client if context else None)
        if llm is None:
            return self._approve(state, ["Deterministic evidence checks passed"])
        return self._llm_critique(state, llm)

    def _deterministic_preflight(
        self,
        state: DiagnosisState,
    ) -> AgentResult | None:
        draft = state.diagnosis_draft
        if draft is None:
            return self._report(
                state,
                ReviewDecision.REJECTED,
                ["No diagnosis draft exists"],
                next_stage=None,
            )

        verified = [item for item in state.evidence if item.verified and item.quote]
        if not verified:
            return self._report(
                state,
                ReviewDecision.NEEDS_MORE_EVIDENCE,
                ["No source-bound evidence is available"],
                missing=["Verbatim evidence from an indexed source"],
                next_stage=WorkflowStage.EXPLORE,
            )

        valid_citations = {
            key
            for item in verified
            for key in (item.source_path, item.citation_key)
        }
        if not draft.cited_evidence:
            return self._report(
                state,
                ReviewDecision.NEEDS_REVISION,
                ["Draft does not cite any verified evidence"],
                next_stage=WorkflowStage.REASON,
            )
        invalid = [
            citation
            for citation in draft.cited_evidence
            if citation not in valid_citations
        ]
        if invalid:
            return self._report(
                state,
                ReviewDecision.NEEDS_MORE_EVIDENCE,
                [f"Unknown or unverified citation: {item}" for item in invalid],
                missing=invalid,
                next_stage=WorkflowStage.EXPLORE,
            )

        unsafe = [
            action
            for action in draft.recommended_actions
            if action_requires_explicit_warning(action)
        ]
        if unsafe:
            return self._report(
                state,
                ReviewDecision.NEEDS_REVISION,
                [
                    "Potentially mutating action lacks an explicit risk, backup, "
                    "confirmation, or rollback warning"
                ],
                unsupported=unsafe,
                next_stage=WorkflowStage.REASON,
            )
        return None

    def _llm_critique(
        self,
        state: DiagnosisState,
        llm: LLMClient,
    ) -> AgentResult:
        draft = state.diagnosis_draft
        assert draft is not None
        messages = [
            LLMMessage(role="system", content=CRITIC_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=(
                    f"Question: {state.user_query}\n"
                    f"Evidence:\n{self._format_evidence(state)}\n\n"
                    f"Summary: {draft.summary}\n"
                    f"Root cause: {draft.root_cause or 'none'}\n"
                    f"Actions: {'; '.join(draft.recommended_actions) or 'none'}\n"
                    f"Citations: {'; '.join(draft.cited_evidence)}\n"
                    f"Uncertainties: {'; '.join(draft.uncertainties) or 'none'}"
                ),
            ),
        ]
        response = llm.complete(LLMRequest(messages=messages, temperature=0.0))
        parsed = self._parse_action(response.message.content)
        if parsed is None:
            return self._report(
                state,
                ReviewDecision.NEEDS_REVISION,
                ["Critic returned invalid JSON; approval withheld"],
                next_stage=WorkflowStage.REASON,
            )
        try:
            decision = ReviewDecision(str(parsed.get("decision")))
        except ValueError:
            return self._report(
                state,
                ReviewDecision.REJECTED,
                ["Critic returned an unknown decision; approval withheld"],
                next_stage=None,
            )

        notes = self._string_list(parsed.get("notes"))
        missing = self._string_list(parsed.get("missing_evidence"))
        unsupported = self._string_list(parsed.get("unsupported_claims"))
        if decision == ReviewDecision.APPROVED:
            return self._approve(state, notes or ["Critic approved the draft"])
        if decision == ReviewDecision.NEEDS_MORE_EVIDENCE:
            return self._report(
                state,
                decision,
                notes,
                missing=missing,
                unsupported=unsupported,
                next_stage=WorkflowStage.EXPLORE,
            )
        if decision == ReviewDecision.NEEDS_REVISION:
            return self._report(
                state,
                decision,
                notes,
                missing=missing,
                unsupported=unsupported,
                next_stage=WorkflowStage.REASON,
            )
        return self._report(
            state,
            ReviewDecision.REJECTED,
            notes or ["Critic rejected the draft"],
            missing=missing,
            unsupported=unsupported,
            next_stage=None,
        )

    def _approve(
        self,
        state: DiagnosisState,
        notes: list[str],
    ) -> AgentResult:
        state.critic_report = CriticReport(
            decision=ReviewDecision.APPROVED,
            notes=notes,
        )
        state.critic_notes = list(notes)
        state.final_answer = self._render_final_answer(state)
        return AgentResult(
            role=self.role,
            status=AgentResultStatus.SUCCEEDED,
            message="Draft approved after evidence and safety checks",
            next_stage=WorkflowStage.FINALIZE,
        )

    def _report(
        self,
        state: DiagnosisState,
        decision: ReviewDecision,
        notes: list[str],
        *,
        missing: list[str] | None = None,
        unsupported: list[str] | None = None,
        next_stage: WorkflowStage | None,
    ) -> AgentResult:
        report = CriticReport(
            decision=decision,
            notes=notes,
            missing_evidence=missing or [],
            unsupported_claims=unsupported or [],
        )
        state.critic_report = report
        state.critic_notes = list(notes)
        status = (
            AgentResultStatus.FAILED
            if decision == ReviewDecision.REJECTED
            else AgentResultStatus.REJECTED
        )
        return AgentResult(
            role=self.role,
            status=status,
            message=f"Critic decision: {decision}",
            next_stage=next_stage,
        )

    @staticmethod
    def _render_final_answer(state: DiagnosisState) -> str:
        draft = state.diagnosis_draft
        assert draft is not None
        sections = ["## 诊断摘要", draft.summary]
        if draft.root_cause:
            sections.extend(["## 可能根因", draft.root_cause])
        if draft.recommended_actions:
            actions = "\n".join(
                f"{index}. {action}"
                for index, action in enumerate(draft.recommended_actions, 1)
            )
            sections.extend(["## 建议操作", actions])
        if draft.uncertainties:
            sections.extend(
                [
                    "## 尚不确定的信息",
                    "\n".join(f"- {item}" for item in draft.uncertainties),
                ]
            )
        cited = set(draft.cited_evidence)
        evidence_lines = []
        for item in state.evidence:
            if item.source_path in cited or item.citation_key in cited:
                evidence_lines.append(
                    f"- `{item.citation_key}`：{item.summary}"
                )
        sections.extend(
            [
                "## 证据来源",
                "\n".join(evidence_lines) or "- 未找到可显示的证据",
            ]
        )
        if draft.confidence:
            sections.extend(["## 置信度", draft.confidence])
        return "\n\n".join(sections)

    @staticmethod
    def _format_evidence(state: DiagnosisState) -> str:
        return "\n".join(
            f"- {item.citation_key} version={item.source_version or 'unknown'} "
            f"section={item.section or 'unknown'}\n"
            f"  {item.quote}"
            for item in state.evidence
            if item.verified and item.quote
        )

    @staticmethod
    def _parse_action(content: str) -> dict[str, Any] | None:
        candidate = content.strip()
        if "```" in candidate:
            first = candidate.find("```")
            second = candidate.find("```", first + 3)
            if second >= 0:
                candidate = candidate[first + 3 : second].strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].lstrip()
        brace = candidate.find("{")
        if brace > 0:
            candidate = candidate[brace:]
        try:
            value, _ = json.JSONDecoder().raw_decode(candidate)
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
