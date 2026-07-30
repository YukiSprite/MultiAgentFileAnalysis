"""Human-in-the-loop session — suspend and resume workflow."""

from dataclasses import dataclass
from typing import Protocol

from multi_agent_file_analysis.core.errors import HITLError
from multi_agent_file_analysis.graph.state import (
    DiagnosisState,
    HumanRequest,
    RuntimeContextItem,
    WorkflowStatus,
)


@dataclass(slots=True)
class HumanResponse:
    """User response that resumes a suspended workflow."""

    content: str
    source_hint: str | None = None


class HumanChannel(Protocol):
    """Boundary for delivering requests to a user."""

    def send_request(self, request: HumanRequest) -> None: ...


class HITLSession:
    """Creates and consumes user-facing information requests."""

    def __init__(
        self,
        channel: HumanChannel | None = None,
        max_response_chars: int = 20_000,
    ) -> None:
        self._channel = channel
        self._max_response_chars = max_response_chars

    @property
    def channel(self) -> HumanChannel | None:
        return self._channel

    def create_request(self, state: DiagnosisState) -> HumanRequest:
        req = state.human_request
        if req is None:
            raise HITLError("No human request in state")
        return req

    def suspend(self, state: DiagnosisState) -> DiagnosisState:
        if state.human_request is None:
            raise HITLError("Cannot suspend: no human_request in state")
        state.status = WorkflowStatus.WAITING_FOR_HUMAN
        return state

    def apply_response(
        self,
        state: DiagnosisState,
        response: HumanResponse,
    ) -> DiagnosisState:
        if state.status != WorkflowStatus.WAITING_FOR_HUMAN:
            raise HITLError("Cannot apply response: workflow is not waiting for human input")
        content = response.content.strip()
        if not content:
            raise HITLError("Human response must not be empty")
        if len(content) > self._max_response_chars:
            raise HITLError(
                f"Human response exceeds {self._max_response_chars} characters"
            )

        label = state.human_request.prompt[:80] if state.human_request else "user_input"
        request_id = state.human_request.request_id if state.human_request else None
        state.runtime_context.append(
            RuntimeContextItem(
                label=label,
                content=content,
                source_hint=response.source_hint,
                request_id=request_id,
                verified=False,
            )
        )
        state.human_request = None
        return state
