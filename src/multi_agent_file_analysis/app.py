"""Application composition boundary."""

from dataclasses import dataclass

from multi_agent_file_analysis.agents import CriticAgent, ExplorerAgent, ReasonerAgent
from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.graph import DiagnosisWorkflow
from multi_agent_file_analysis.index import PageIndexRepository
from multi_agent_file_analysis.qa import QAService
from multi_agent_file_analysis.vfs import VirtualFileSystem


@dataclass(slots=True)
class ApplicationServices:
    """Top-level services wired by the application factory."""

    config: AppConfig
    page_index_repository: PageIndexRepository
    vfs: VirtualFileSystem
    explorer: ExplorerAgent
    reasoner: ReasonerAgent
    critic: CriticAgent
    workflow: DiagnosisWorkflow
    qa_service: QAService


class ApplicationFactory:
    """Creates the service graph from AppConfig."""

    def build(self, config: AppConfig) -> ApplicationServices:
        """Wire application services together."""
        raise NotImplementedError
