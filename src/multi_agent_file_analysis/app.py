"""Application composition — wires all services together."""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from multi_agent_file_analysis.agents import CriticAgent, ExplorerAgent, ReasonerAgent
from multi_agent_file_analysis.audit import (
    AuditRecorder,
    JsonlAuditRecorder,
    MemoryAuditRecorder,
)
from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import ConfigError, RunMode
from multi_agent_file_analysis.corpora import CorpusDefinition
from multi_agent_file_analysis.environment import load_project_environment
from multi_agent_file_analysis.graph import DiagnosisWorkflow
from multi_agent_file_analysis.hitl import HITLSession, SafeCommandBroker
from multi_agent_file_analysis.index import PageIndexLoader, PageIndexRepository
from multi_agent_file_analysis.llm import LLMClient, OpenAICompatibleClient
from multi_agent_file_analysis.qa import QAService
from multi_agent_file_analysis.vfs import VirtualFileSystem


@dataclass(slots=True)
class ApplicationServices:
    config: AppConfig
    page_index_repository: PageIndexRepository
    vfs: VirtualFileSystem
    explorer: ExplorerAgent
    reasoner: ReasonerAgent
    critic: CriticAgent
    workflow: DiagnosisWorkflow
    qa_service: QAService
    audit_recorder: AuditRecorder


class ApplicationFactory:
    """Creates the complete service graph from AppConfig."""

    def build(
        self,
        config: AppConfig,
        llm_client: LLMClient | None = None,
        audit_recorder: AuditRecorder | None = None,
    ) -> ApplicationServices:
        load_project_environment(config.env_file_path)
        config.validate()
        # 1. Load page index
        loader = PageIndexLoader()
        page_index = loader.load(config.page_index_path)

        # 2. Create repository
        repository = PageIndexRepository(page_index, config.knowledge_base_root)

        # 3. Create VFS
        vfs = VirtualFileSystem(repository, config)

        # 4. Create LLM client (None for dry-run so agents use rule-based fallbacks)
        if config.run_mode != RunMode.DRY_RUN and llm_client is None:
            llm_client = OpenAICompatibleClient()

        # 5. Create audit recorder
        if audit_recorder is None:
            if config.audit_log_path:
                audit_recorder = JsonlAuditRecorder(config.audit_log_path)
            else:
                audit_recorder = MemoryAuditRecorder()

        # 6. Create agents
        command_broker = SafeCommandBroker()
        explorer = ExplorerAgent(
            vfs=vfs,
            llm_client=llm_client,
            max_turns=config.max_explorer_turns,
        )
        reasoner = ReasonerAgent(
            llm_client=llm_client,
            command_broker=command_broker,
        )
        critic = CriticAgent(llm_client=llm_client)

        # 7. Create HITL session
        hitl_session = HITLSession(
            max_response_chars=config.max_human_input_chars
        )

        # 8. Create workflow
        workflow = DiagnosisWorkflow(
            explorer=explorer,
            reasoner=reasoner,
            critic=critic,
            hitl_session=hitl_session,
            audit_recorder=audit_recorder,
            llm_client=llm_client,
            max_iterations=config.max_workflow_iterations,
            max_review_retries=config.max_review_retries,
        )

        # 9. Create QA service
        qa_service = QAService(workflow=workflow)

        return ApplicationServices(
            config=config,
            page_index_repository=repository,
            vfs=vfs,
            explorer=explorer,
            reasoner=reasoner,
            critic=critic,
            workflow=workflow,
            qa_service=qa_service,
            audit_recorder=audit_recorder,
        )


@dataclass(slots=True)
class CorpusMount:
    """One corpus mounted as an isolated virtual root.

    The mount owns its generated Page Index directory. Callers must keep the
    mount alive for as long as the corpus is used and call ``close()`` when the
    corpus is no longer needed.
    """

    corpus: CorpusDefinition
    corpus_root: Path
    index_dir: Path
    index_path: Path
    document_count: int
    services: ApplicationServices
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        shutil.rmtree(self.index_dir, ignore_errors=True)

    def __enter__(self) -> "CorpusMount":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def mount_corpus(
    corpus: CorpusDefinition,
    knowledge_base_root: Path,
    *,
    run_mode: RunMode,
    env_file_path: Path | None = None,
    audit_log_path: Path | None = None,
    max_file_chars: int = 12_000,
    llm_client: LLMClient | None = None,
    audit_recorder: AuditRecorder | None = None,
) -> CorpusMount:
    """Scan one corpus, build its Page Index, and assemble the service graph."""
    corpus_root = corpus.resolve_root(knowledge_base_root)
    index_dir = Path(tempfile.mkdtemp(prefix="mafa-corpus-index-"))
    index_path = index_dir / "page_index.yaml"
    try:
        index = PageIndexLoader.scan_directory(corpus_root, index_path)
        if not index.documents:
            raise ConfigError("selected corpus contains no Markdown documents")
        config = AppConfig(
            page_index_path=index_path,
            knowledge_base_root=corpus_root,
            run_mode=run_mode,
            env_file_path=env_file_path,
            audit_log_path=audit_log_path,
            max_file_chars=max_file_chars,
        )
        services = ApplicationFactory().build(
            config,
            llm_client=llm_client,
            audit_recorder=audit_recorder,
        )
    except BaseException:
        shutil.rmtree(index_dir, ignore_errors=True)
        raise
    return CorpusMount(
        corpus=corpus,
        corpus_root=corpus_root,
        index_dir=index_dir,
        index_path=index_path,
        document_count=len(index.documents),
        services=services,
    )
