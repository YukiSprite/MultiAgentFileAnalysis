"""Knowledge-base ingestion boundaries."""

from .chm import (
    ChmExtractor,
    ChmImporter,
    ChmImportLimits,
    ChmImportResult,
    ChmTocEntry,
    decode_chm_text,
    parse_chm_toc,
)
from .html_markdown import HtmlToMarkdownConverter
from .pipeline import KnowledgeBaseBuilder
from .schema import DocumentSource, IngestedDocument, IngestionPlan

__all__ = [
    "ChmExtractor",
    "ChmImporter",
    "ChmImportLimits",
    "ChmImportResult",
    "ChmTocEntry",
    "DocumentSource",
    "HtmlToMarkdownConverter",
    "IngestedDocument",
    "IngestionPlan",
    "KnowledgeBaseBuilder",
    "decode_chm_text",
    "parse_chm_toc",
]
