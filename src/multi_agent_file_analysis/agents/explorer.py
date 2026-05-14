"""Explorer agent boundary."""

from multi_agent_file_analysis.agents.base import AgentResult
from multi_agent_file_analysis.graph.state import DiagnosisState
from multi_agent_file_analysis.vfs import VirtualFileSystem


class ExplorerAgent:
    """Collects rules and evidence from the virtual file system."""

    def __init__(self, vfs: VirtualFileSystem) -> None:
        self._vfs = vfs

    def run(self, state: DiagnosisState) -> AgentResult:
        """Explore the knowledge base and update diagnosis evidence."""
        raise NotImplementedError
