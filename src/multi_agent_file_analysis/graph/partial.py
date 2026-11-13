"""Deterministic rendering for non-final, partially supported workflow output."""

from __future__ import annotations

from multi_agent_file_analysis.core import WorkflowStatus
from multi_agent_file_analysis.graph.state import DiagnosisState, EvidenceItem


def render_partial_answer(state: DiagnosisState) -> str:
    """Expose useful progress without presenting an unapproved draft as final."""
    review_status = (
        "尚未完成最终审查" if state.human_request is not None else "未通过最终审查"
    )
    sections = [
        f"## 阶段性回答（{review_status}）",
        (
            "以下内容保留了当前流程已经形成的断言和已核验原文，但尚未获得 "
            "Critic 最终批准，因此不能视为完整定论。"
        ),
    ]

    draft = state.diagnosis_draft
    if draft is not None:
        sections.extend(["## 当前暂定断言", draft.summary])
        if draft.root_cause:
            sections.extend(["## 暂定解释", draft.root_cause])
        if draft.cited_evidence:
            sections.extend(
                [
                    "## 暂定断言引用",
                    "\n".join(
                        f"- `{citation}`" for citation in draft.cited_evidence
                    ),
                ]
            )
    else:
        sections.extend(
            [
                "## 当前暂定断言",
                "尚未形成面向问题的完整推论；以下先列出已经逐字核验的来源片段。",
            ]
        )

    evidence = _ordered_verified_evidence(state)
    if evidence:
        sections.extend(
            [
                "## 已核验的阶段性事实",
                "\n\n".join(_render_evidence(item) for item in evidence[:8]),
            ]
        )

    if state.runtime_context:
        sections.extend(
            [
                "## 运行时依据（用户提供，未验证）",
                "\n".join(
                    f"- 请求 {item.request_id or 'unknown'}："
                    f"{' '.join(item.content.split())[:200]}"
                    for item in state.runtime_context
                ),
            ]
        )

    gaps = _remaining_gaps(state)
    if gaps:
        sections.extend(
            [
                "## 尚未解决的前提",
                "\n".join(f"- {item}" for item in gaps),
            ]
        )

    if (
        state.status == WorkflowStatus.WAITING_FOR_HUMAN
        and state.human_request is not None
    ):
        reason = f"等待补充现场信息：{state.human_request.prompt}"
    else:
        reason = (
            state.errors[-1]
            if state.errors
            else state.last_transition_reason or "工作流未获得最终批准"
        )
    sections.extend(["## 当前停止原因", reason])
    return "\n\n".join(sections)


def _ordered_verified_evidence(state: DiagnosisState) -> list[EvidenceItem]:
    verified = [item for item in state.evidence if item.verified and item.quote]
    if not verified:
        return []
    cited = set(state.diagnosis_draft.cited_evidence) if state.diagnosis_draft else set()
    return sorted(
        verified,
        key=lambda item: (
            0 if item.citation_key in cited or item.source_path in cited else 1,
            0 if item.supports_obligations else 1,
        ),
    )


def _render_evidence(item: EvidenceItem) -> str:
    obligations = (
        f"；对应检索义务：{'；'.join(item.supports_obligations)}"
        if item.supports_obligations
        else ""
    )
    quote = " ".join((item.quote or "").split())
    if len(quote) > 600:
        quote = quote[:600].rstrip() + "……"
    return f"- `{item.citation_key}`{obligations}\n\n  > {quote}"


def _remaining_gaps(state: DiagnosisState) -> list[str]:
    candidates: list[str] = list(state.uncovered_evidence_obligations)
    if state.critic_report:
        candidates.extend(state.critic_report.missing_evidence)
        candidates.extend(
            f"尚无依据的主张：{item}"
            for item in state.critic_report.unsupported_claims
        )
    if state.diagnosis_draft:
        candidates.extend(state.diagnosis_draft.uncertainties)
    if state.human_request:
        candidates.append(
            state.human_request.reason
            or f"需要现场信息：{state.human_request.expected_input}"
        )
    return list(dict.fromkeys(item.strip() for item in candidates if item.strip()))
