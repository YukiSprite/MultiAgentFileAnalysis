"""Graph workflow boundary."""

from multi_agent_file_analysis.graph.state import DiagnosisState


class DiagnosisWorkflow:
    """Coordinates agent execution and HITL suspension/resume."""

    def run(self, state: DiagnosisState) -> DiagnosisState:
        """Run the diagnosis workflow until it finishes or needs user input."""
        raise NotImplementedError

    def resume(self, state: DiagnosisState, user_input: str) -> DiagnosisState:
        """Resume a suspended workflow with user-provided context."""
        raise NotImplementedError
