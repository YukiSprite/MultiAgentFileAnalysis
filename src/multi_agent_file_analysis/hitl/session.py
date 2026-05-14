"""Human-in-the-loop session boundary."""

from multi_agent_file_analysis.graph.state import DiagnosisState, HumanRequest


class HITLSession:
    """Creates and consumes user-facing information requests."""

    def create_request(self, state: DiagnosisState) -> HumanRequest:
        """Create a request for missing runtime context."""
        raise NotImplementedError

    def apply_response(self, state: DiagnosisState, response: str) -> DiagnosisState:
        """Attach a user response to the workflow state."""
        raise NotImplementedError
