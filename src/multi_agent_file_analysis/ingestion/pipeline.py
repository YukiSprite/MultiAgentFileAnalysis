"""Knowledge-base ingestion pipeline boundary."""

from multi_agent_file_analysis.index import PageIndex

from .schema import DocumentSource, IngestedDocument, IngestionPlan


class KnowledgeBaseBuilder:
    """Builds Markdown documents and a page index from source materials."""

    def plan(self, sources: list[DocumentSource]) -> IngestionPlan:
        """Create an ingestion plan from source documents."""
        raise NotImplementedError

    def ingest(self, plan: IngestionPlan) -> list[IngestedDocument]:
        """Normalize source documents into knowledge-base files."""
        raise NotImplementedError

    def build_index(self, documents: list[IngestedDocument]) -> PageIndex:
        """Build a page index for ingested documents."""
        raise NotImplementedError
