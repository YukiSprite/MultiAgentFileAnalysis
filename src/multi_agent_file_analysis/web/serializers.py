"""JSON rendering for sessions and runs (no unapproved content)."""

from __future__ import annotations

from typing import Any

from multi_agent_file_analysis.graph import DiagnosisState

from .jobs import RunJob
from .sessions import WebSession

MAX_TRACE_STEPS = 50


def session_payload(session: WebSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "corpus": {
            "id": session.corpus_id,
            "name": session.corpus_name,
            "description": session.mount.corpus.description,
        },
        "document_count": session.document_count,
        "dry_run": session.dry_run,
        "created_at": session.created_at,
    }


def run_payload(session: WebSession, job: RunJob) -> dict[str, Any]:
    response = job.response
    state = response.state if response is not None else None
    payload: dict[str, Any] = {
        "run_id": job.run_id,
        "session_id": session.session_id,
        "query": job.query,
        "status": str(job.status),
        "dry_run": session.dry_run,
        "answer": response.answer if response is not None else None,
        "is_partial": (
            bool(response.is_partial)
            if response is not None
            else job.error is not None
        ),
        "needs_human_input": (
            bool(response.needs_human_input) if response is not None else False
        ),
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "workflow_status": str(state.status) if state is not None else None,
        "stage": str(state.stage) if state is not None else None,
        "attempts": _attempts(state),
        "errors": list(state.errors) if state is not None else [],
        "human_request": _human_request(state),
        "evidence": _evidence(state),
        "plan": _plan(state),
        "critic": _critic(state),
        "trace": _trace(state),
        "runtime_context": _runtime_context(state),
    }
    return payload


def _attempts(state: DiagnosisState | None) -> dict[str, int]:
    if state is None:
        return {}
    return {
        "explorer": state.exploration_attempts,
        "reasoner": state.reasoning_attempts,
        "critic": state.review_attempts,
        "workflow": state.workflow_iterations,
    }


def _human_request(state: DiagnosisState | None) -> dict[str, Any] | None:
    if state is None or state.human_request is None:
        return None
    request = state.human_request
    return {
        "prompt": request.prompt,
        "expected_input": request.expected_input,
        "reason": request.reason,
        "suggested_command": (
            request.suggested_command if request.command_approved else None
        ),
        "request_id": request.request_id,
    }


def _evidence(state: DiagnosisState | None) -> list[dict[str, Any]]:
    if state is None:
        return []
    cited = (
        set(state.diagnosis_draft.cited_evidence)
        if state.diagnosis_draft is not None
        else set()
    )
    items: list[dict[str, Any]] = []
    for item in state.evidence:
        if not item.verified or not item.quote:
            continue
        items.append(
            {
                "citation_key": item.citation_key,
                "path": item.source_path,
                "line_start": item.line_start,
                "line_end": item.line_end,
                "section": item.section,
                "version": item.source_version,
                "summary": item.summary,
                "quote": item.quote,
                "supports_obligations": list(item.supports_obligations),
                "cited": (
                    item.citation_key in cited or item.source_path in cited
                ),
            }
        )
    return items


def _plan(state: DiagnosisState | None) -> dict[str, Any] | None:
    if state is None or state.retrieval_plan is None:
        return None
    plan = state.retrieval_plan
    uncovered = {
        " ".join(value.split()).casefold()
        for value in state.uncovered_evidence_obligations
    }
    return {
        "obligations": [
            {
                "text": obligation,
                "covered": " ".join(obligation.split()).casefold()
                not in uncovered,
            }
            for obligation in plan.evidence_obligations
        ],
        "exact_literals": list(plan.exact_literals),
        "search_queries": list(plan.search_queries),
    }


def _critic(state: DiagnosisState | None) -> dict[str, Any] | None:
    if state is None or state.critic_report is None:
        return None
    report = state.critic_report
    return {
        "decision": str(report.decision),
        "notes": list(report.notes),
        "missing_evidence": list(report.missing_evidence),
        "unsupported_claims": list(report.unsupported_claims),
    }


def _trace(state: DiagnosisState | None) -> list[dict[str, Any]]:
    if state is None:
        return []
    recent = state.exploration_log[-MAX_TRACE_STEPS:]
    return [
        {
            "tool": str(step.tool_name),
            "path": step.path,
            "query": step.query,
            "summary": step.result_summary,
        }
        for step in recent
    ]


def _runtime_context(state: DiagnosisState | None) -> list[dict[str, Any]]:
    if state is None:
        return []
    return [
        {
            "label": item.label,
            "content": item.content,
            "source_hint": item.source_hint,
            "verified": item.verified,
        }
        for item in state.runtime_context
    ]
