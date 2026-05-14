"""Knowledge-base ingestion boundaries."""

from .pipeline import KnowledgeBaseBuilder
from .schema import DocumentSource, IngestedDocument, IngestionPlan

__all__ = ["DocumentSource", "IngestedDocument", "IngestionPlan", "KnowledgeBaseBuilder"]
