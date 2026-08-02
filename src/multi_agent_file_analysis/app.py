"""Application composition — wires all services together."""

from dataclasses import dataclass

from multi_agent_file_analysis.agents import CriticAgent, ExplorerAgent, ReasonerAgent
from multi_agent_file_analysis.audit import JsonlAuditRecorder, MemoryAuditRecorder
from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import RunMode
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
    audit_recorder: MemoryAuditRecorder | JsonlAuditRecorder


class ApplicationFactory:
    """Creates the complete service graph from AppConfig."""

    def build(
        self,
        config: AppConfig,
        llm_client: LLMClient | None = None,
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
