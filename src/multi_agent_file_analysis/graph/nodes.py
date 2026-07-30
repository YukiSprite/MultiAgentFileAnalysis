"""Graph node implementations — thin adapters wrapping agents and HITL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from multi_agent_file_analysis.agents.base import AgentContext, AgentResult
from multi_agent_file_analysis.audit import AuditEvent, AuditEventType
from multi_agent_file_analysis.core import (
    AgentResultStatus,
    WorkflowStage,
    WorkflowStatus,
)
from multi_agent_file_analysis.graph.state import DiagnosisState

if TYPE_CHECKING:
    from multi_agent_file_analysis.agents import CriticAgent, ExplorerAgent, ReasonerAgent
    from multi_agent_file_analysis.hitl import HITLSession


@dataclass(slots=True)
class NodeResult:
    status: WorkflowStatus
    current_stage: WorkflowStage
    next_stage: WorkflowStage | None = None
    message: str | None = None
    agent_status: AgentResultStatus | None = None


class WorkflowNode(Protocol):
    stage: WorkflowStage

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult: ...


def _emit(
    context: AgentContext | None,
    event_type: AuditEventType,
    message: str,
    payload: dict | None = None,
) -> None:
    if context and context.audit_recorder:
        context.audit_recorder.record(
            AuditEvent(
                event_type=event_type,
                run_id=context.run_id,
                message=message,
                payload=payload or {},
            )
        )


class ExplorerNode:
    stage = WorkflowStage.EXPLORE

    def __init__(self, agent: ExplorerAgent) -> None:
        self._agent = agent

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult:
        _emit(context, AuditEventType.AGENT_STARTED, "Explorer started")
        state.stage = WorkflowStage.EXPLORE
        state.status = WorkflowStatus.RUNNING

        result: AgentResult = self._agent.run(state, context)
        _emit(context, AuditEventType.AGENT_FINISHED, f"Explorer: {result.message}")
        if result.status == AgentResultStatus.FAILED:
            state.status = WorkflowStatus.FAILED
            state.errors.append(result.message)

        return NodeResult(
            status=state.status,
            current_stage=WorkflowStage.EXPLORE,
            next_stage=(
                result.next_stage
                if result.status != AgentResultStatus.FAILED
                else None
            ),
            message=result.message,
            agent_status=result.status,
        )


class ReasonerNode:
    stage = WorkflowStage.REASON

    def __init__(self, agent: ReasonerAgent) -> None:
        self._agent = agent

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult:
        _emit(context, AuditEventType.AGENT_STARTED, "Reasoner started")
        state.stage = WorkflowStage.REASON

        result: AgentResult = self._agent.run(state, context)
        _emit(context, AuditEventType.AGENT_FINISHED, f"Reasoner: {result.message}")
        if result.status == AgentResultStatus.FAILED:
            state.status = WorkflowStatus.FAILED
            state.errors.append(result.message)

        return NodeResult(
            status=state.status,
            current_stage=WorkflowStage.REASON,
            next_stage=(
                result.next_stage
                if result.status != AgentResultStatus.FAILED
                else None
            ),
            message=result.message,
            agent_status=result.status,
        )


class CriticNode:
    stage = WorkflowStage.CRITIQUE

    def __init__(self, agent: CriticAgent) -> None:
        self._agent = agent

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult:
        _emit(context, AuditEventType.AGENT_STARTED, "Critic started")
        state.stage = WorkflowStage.CRITIQUE

        result: AgentResult = self._agent.run(state, context)
        _emit(context, AuditEventType.AGENT_FINISHED, f"Critic: {result.message}")
        if (
            result.status == AgentResultStatus.FAILED
            and result.next_stage is None
        ):
            state.status = WorkflowStatus.FAILED
            state.errors.append(result.message)

        return NodeResult(
            status=state.status,
            current_stage=WorkflowStage.CRITIQUE,
            next_stage=result.next_stage,
            message=result.message,
            agent_status=result.status,
        )


class HITLNode:
    stage = WorkflowStage.REQUEST_HUMAN_INPUT

    def __init__(self, session: "HITLSession") -> None:
        self._session = session

    def run(self, state: DiagnosisState, context: AgentContext | None = None) -> NodeResult:
        _emit(context, AuditEventType.HUMAN_INPUT_REQUESTED, "Requesting human input")
        state.stage = WorkflowStage.REQUEST_HUMAN_INPUT
        self._session.suspend(state)

        if state.human_request and self._session.channel:
            self._session.channel.send_request(state.human_request)

        return NodeResult(
            status=WorkflowStatus.WAITING_FOR_HUMAN,
            current_stage=WorkflowStage.REQUEST_HUMAN_INPUT,
            next_stage=None,
            message="Waiting for user to provide runtime context",
        )
