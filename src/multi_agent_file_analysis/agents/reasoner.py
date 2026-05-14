"""Reasoner agent boundary."""

from multi_agent_file_analysis.agents.base import AgentResult
from multi_agent_file_analysis.graph.state import DiagnosisState


class ReasonerAgent:
    """Builds a diagnosis from user context and collected evidence."""

    def run(self, state: DiagnosisState) -> AgentResult:
        """Produce a diagnosis draft or request more user-provided context."""
        raise NotImplementedError
