"""Knowledge-base ingestion pipeline boundary.

Ingestion is the offline half of the project. It prepares Markdown documents
and Page Index metadata before any online QA run starts.
"""

from multi_agent_file_analysis.index import PageIndex

from .schema import DocumentSource, IngestedDocument, IngestionPlan


class KnowledgeBaseBuilder:
    """Builds Markdown documents and a page index from source materials.

    Keep expensive parsing, PDF conversion, normalization, and index generation
    here. Online agents should consume the resulting knowledge base through VFS.
    """

    def plan(self, sources: list[DocumentSource]) -> IngestionPlan:
        """Create an ingestion plan from source documents."""
        raise NotImplementedError

    def ingest(self, plan: IngestionPlan) -> list[IngestedDocument]:
        """Normalize source documents into knowledge-base files."""
        raise NotImplementedError

    def build_index(self, documents: list[IngestedDocument]) -> PageIndex:
        """Build a page index for ingested documents."""
        raise NotImplementedError
