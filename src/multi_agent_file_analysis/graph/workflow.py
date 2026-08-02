"""Bounded workflow for retrieval, reasoning, review, and HITL."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from multi_agent_file_analysis.agents.base import AgentContext
from multi_agent_file_analysis.audit import AuditEvent, AuditEventType, AuditRecorder
from multi_agent_file_analysis.core import (
    ReviewDecision,
    WorkflowStage,
    WorkflowStatus,
)
from multi_agent_file_analysis.core.errors import WorkflowError
from multi_agent_file_analysis.graph.nodes import (
    CriticNode,
    ExplorerNode,
    HITLNode,
    NodeResult,
    ReasonerNode,
)
from multi_agent_file_analysis.graph.plan import WorkflowEdge, WorkflowPlan
from multi_agent_file_analysis.graph.partial import render_partial_answer
from multi_agent_file_analysis.graph.state import DiagnosisState, RuntimeContextItem
from multi_agent_file_analysis.llm import LLMClient

if TYPE_CHECKING:
    from multi_agent_file_analysis.agents import (
        CriticAgent,
        ExplorerAgent,
        ReasonerAgent,
    )
    from multi_agent_file_analysis.hitl import HITLSession


class DiagnosisWorkflow:
    """Coordinate agent execution with explicit budgets and terminal states."""

    def __init__(
        self,
        explorer: ExplorerAgent,
        reasoner: ReasonerAgent,
        critic: CriticAgent,
        hitl_session: "HITLSession | None" = None,
        audit_recorder: AuditRecorder | None = None,
        llm_client: LLMClient | None = None,
        max_iterations: int = 16,
        max_review_retries: int = 2,
    ) -> None:
        self._explorer_node = ExplorerNode(explorer)
        self._reasoner_node = ReasonerNode(reasoner)
        self._critic_node = CriticNode(critic)
        self._hitl_node = HITLNode(hitl_session) if hitl_session else None
        self._hitl_session = hitl_session
        self._audit_recorder = audit_recorder
        self._llm_client = llm_client
        self._max_iterations = max_iterations
        self._max_review_retries = max_review_retries

    def plan(self) -> WorkflowPlan:
        stages = [
            WorkflowStage.INTAKE,
            WorkflowStage.EXPLORE,
            WorkflowStage.REASON,
            WorkflowStage.REQUEST_HUMAN_INPUT,
            WorkflowStage.CRITIQUE,
            WorkflowStage.FINALIZE,
        ]
        edges = [
            WorkflowEdge(WorkflowStage.INTAKE, WorkflowStage.EXPLORE),
            WorkflowEdge(WorkflowStage.EXPLORE, WorkflowStage.REASON),
            WorkflowEdge(WorkflowStage.REASON, WorkflowStage.CRITIQUE),
            WorkflowEdge(
                WorkflowStage.REASON,
                WorkflowStage.REQUEST_HUMAN_INPUT,
            ),
            WorkflowEdge(
                WorkflowStage.REQUEST_HUMAN_INPUT,
                WorkflowStage.REASON,
            ),
            WorkflowEdge(WorkflowStage.CRITIQUE, WorkflowStage.FINALIZE),
            WorkflowEdge(
                WorkflowStage.CRITIQUE,
                WorkflowStage.EXPLORE,
                "needs_more_evidence",
            ),
            WorkflowEdge(
                WorkflowStage.CRITIQUE,
                WorkflowStage.REASON,
                "needs_revision",
            ),
        ]
        return WorkflowPlan(stages=stages, edges=edges)

    def run(
        self,
        state: DiagnosisState,
        context: AgentContext | None = None,
        *,
        start_stage: WorkflowStage | None = None,
    ) -> DiagnosisState:
        if state.status == WorkflowStatus.WAITING_FOR_HUMAN:
            raise WorkflowError("Use resume() for a workflow awaiting human input")
        if not state.run_id:
            state.run_id = uuid.uuid4().hex[:12]
        context = context or self._context(state)
        event = (
            AuditEventType.WORKFLOW_STARTED
            if state.workflow_iterations == 0
            else AuditEventType.WORKFLOW_RESUMED
        )
        self._emit(context, event, f"Workflow active: {state.run_id}")
        state.status = WorkflowStatus.RUNNING
        stage = start_stage or state.next_stage or WorkflowStage.EXPLORE
        return self._execute(state, stage, context)

    def resume(
        self,
        state: DiagnosisState,
        user_input: str,
        context: AgentContext | None = None,
    ) -> DiagnosisState:
        if state.status != WorkflowStatus.WAITING_FOR_HUMAN:
            raise WorkflowError("Cannot resume: workflow is not waiting for input")
        context = context or self._context(state)

        if self._hitl_session:
            from multi_agent_file_analysis.hitl import HumanResponse

            self._hitl_session.apply_response(
                state,
                HumanResponse(content=user_input),
            )
        else:
            content = user_input.strip()
            if not content:
                raise WorkflowError("Human response must not be empty")
            state.runtime_context.append(
                RuntimeContextItem(label="user_input", content=content)
            )

        state.resume_count += 1
        state.human_request = None
        state.partial_answer = None
        state.next_stage = WorkflowStage.REASON
        state.status = WorkflowStatus.RUNNING
        self._emit(
            context,
            AuditEventType.HUMAN_INPUT_RECEIVED,
            "Human input received; resuming at reasoner",
        )
        return self.run(
            state,
            context,
            start_stage=WorkflowStage.REASON,
        )

    def _execute(
        self,
        state: DiagnosisState,
        stage: WorkflowStage,
        context: AgentContext,
    ) -> DiagnosisState:
        while state.workflow_iterations < self._max_iterations:
            state.workflow_iterations += 1
            state.stage = stage
            state.next_stage = None
            if stage == WorkflowStage.EXPLORE:
                state.exploration_attempts += 1
            elif stage == WorkflowStage.REASON:
                state.reasoning_attempts += 1
            elif stage == WorkflowStage.CRITIQUE:
                state.review_attempts += 1

            self._emit(
                context,
                AuditEventType.WORKFLOW_STAGE_CHANGED,
                f"Entering stage: {stage}",
            )
            result = self._run_stage(stage, state, context)

            if state.status == WorkflowStatus.WAITING_FOR_HUMAN:
                state.next_stage = WorkflowStage.REASON
                state.partial_answer = render_partial_answer(state)
                return state
            if state.status == WorkflowStatus.FAILED:
                return self._finish_failed(state, context)
            if result is None:
                state.errors.append(f"No executable node for stage {stage}")
                return self._finish_failed(state, context)

            next_stage = result.next_stage
            if next_stage == WorkflowStage.FINALIZE:
                return self._finalize(state, context)
            if next_stage is None:
                state.errors.append(
                    result.message or f"Stage {stage} returned no transition"
                )
                return self._finish_failed(state, context)

            if stage == WorkflowStage.CRITIQUE:
                report = state.critic_report
                if (
                    report
                    and report.decision != ReviewDecision.APPROVED
                    and state.review_attempts > self._max_review_retries
                ):
                    state.status = WorkflowStatus.ABSTAINED
                    state.last_transition_reason = (
                        "Critic retry budget exhausted"
                    )
                    state.errors.append(state.last_transition_reason)
                    self._emit(
                        context,
                        AuditEventType.WORKFLOW_FAILED,
                        state.last_transition_reason,
                    )
                    state.partial_answer = render_partial_answer(state)
                    return state

            state.last_transition_reason = result.message
            state.next_stage = next_stage
            stage = next_stage

        state.errors.append(
            f"Workflow exceeded {self._max_iterations} stage iterations"
        )
        return self._finish_failed(state, context)

    def _run_stage(
        self,
        stage: WorkflowStage,
        state: DiagnosisState,
        context: AgentContext,
    ) -> NodeResult | None:
        if stage == WorkflowStage.EXPLORE:
            return self._explorer_node.run(state, context)
        if stage == WorkflowStage.REASON:
            result = self._reasoner_node.run(state, context)
            if result.next_stage == WorkflowStage.REQUEST_HUMAN_INPUT:
                if self._hitl_node is None:
                    state.errors.append("HITL requested but not configured")
                    state.status = WorkflowStatus.FAILED
                    return None
                return self._hitl_node.run(state, context)
            return result
        if stage == WorkflowStage.CRITIQUE:
            return self._critic_node.run(state, context)
        return None

    def _finalize(
        self,
        state: DiagnosisState,
        context: AgentContext,
    ) -> DiagnosisState:
        report = state.critic_report
        if (
            report is None
            or report.decision != ReviewDecision.APPROVED
            or not state.final_answer
        ):
            state.errors.append(
                "Finalization blocked: no approved, rendered answer exists"
            )
            return self._finish_failed(state, context)
        state.stage = WorkflowStage.FINALIZE
        state.next_stage = None
        state.status = WorkflowStatus.COMPLETED
        state.partial_answer = None
        self._emit(
            context,
            AuditEventType.WORKFLOW_FINISHED,
            "Workflow completed with an approved answer",
        )
        return state

    def _finish_failed(
        self,
        state: DiagnosisState,
        context: AgentContext,
    ) -> DiagnosisState:
        state.status = WorkflowStatus.FAILED
        state.next_stage = None
        state.partial_answer = render_partial_answer(state)
        self._emit(
            context,
            AuditEventType.WORKFLOW_FAILED,
            state.errors[-1] if state.errors else "Workflow failed",
        )
        return state

    def _context(self, state: DiagnosisState) -> AgentContext:
        return AgentContext(
            run_id=state.run_id,
            llm_client=self._llm_client,
            audit_recorder=self._audit_recorder,
        )

    @staticmethod
    def _emit(
        context: AgentContext,
        event_type: AuditEventType,
        message: str,
    ) -> None:
        if context.audit_recorder:
            context.audit_recorder.record(
                AuditEvent(
                    event_type=event_type,
                    run_id=context.run_id,
                    message=message,
                )
            )
