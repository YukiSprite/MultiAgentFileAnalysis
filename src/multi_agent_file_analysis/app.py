"""Application composition boundary.

This module is the only place that should know how concrete services are wired
together. Future CLI or API entry points should ask ApplicationFactory for a
ready-to-use service graph instead of manually constructing agents, VFS, and
workflow objects in multiple places.
"""

from dataclasses import dataclass

from multi_agent_file_analysis.agents import CriticAgent, ExplorerAgent, ReasonerAgent
from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.graph import DiagnosisWorkflow
from multi_agent_file_analysis.index import PageIndexRepository
from multi_agent_file_analysis.qa import QAService
from multi_agent_file_analysis.vfs import VirtualFileSystem


@dataclass(slots=True)
class ApplicationServices:
    """Top-level services wired by the application factory.

    Keeping these objects together makes smoke tests and application startup
    easier: a caller can build once, then use qa_service as the public entry
    point while still having access to lower-level services for diagnostics.
    """

    config: AppConfig
    page_index_repository: PageIndexRepository
    vfs: VirtualFileSystem
    explorer: ExplorerAgent
    reasoner: ReasonerAgent
    critic: CriticAgent
    workflow: DiagnosisWorkflow
    qa_service: QAService


class ApplicationFactory:
    """Creates the service graph from AppConfig.

    Expected future responsibilities:
    - load and validate the Page Index;
    - create the repository and virtual file-system implementation;
    - create concrete LLM and audit adapters;
    - wire Explorer, Reasoner, Critic, HITL, Workflow, and QAService.

    Business algorithms should stay out of this class. It is an assembly layer,
    not a retrieval or reasoning engine.
    """

    def build(self, config: AppConfig) -> ApplicationServices:
        """Wire application services together."""
        raise NotImplementedError
