"""Critic agent boundary."""

from multi_agent_file_analysis.agents.base import AgentResult
from multi_agent_file_analysis.graph.state import DiagnosisState


class CriticAgent:
    """Reviews diagnosis drafts against collected evidence."""

    def run(self, state: DiagnosisState) -> AgentResult:
        """Approve the draft or request another pass."""
        raise NotImplementedError
