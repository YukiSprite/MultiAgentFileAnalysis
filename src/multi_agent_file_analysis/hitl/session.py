"""Human-in-the-loop session boundary."""

from dataclasses import dataclass
from typing import Protocol

from multi_agent_file_analysis.graph.state import DiagnosisState, HumanRequest


@dataclass(slots=True)
class HumanResponse:
    """User response that resumes a suspended workflow."""

    content: str
    source_hint: str | None = None


class HumanChannel(Protocol):
    """Boundary for delivering requests to a user."""

    def send_request(self, request: HumanRequest) -> None:
        """Send a request for user-provided runtime information."""
        ...


class HITLSession:
    """Creates and consumes user-facing information requests."""

    def __init__(self, channel: HumanChannel | None = None) -> None:
        self._channel = channel

    def create_request(self, state: DiagnosisState) -> HumanRequest:
        """Create a request for missing runtime context."""
        raise NotImplementedError

    def suspend(self, state: DiagnosisState) -> DiagnosisState:
        """Mark the workflow as waiting for human input."""
        raise NotImplementedError

    def apply_response(
        self,
        state: DiagnosisState,
        response: HumanResponse,
    ) -> DiagnosisState:
        """Attach a user response to the workflow state."""
        raise NotImplementedError
