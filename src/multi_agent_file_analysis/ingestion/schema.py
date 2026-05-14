"""Knowledge-base ingestion models."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class DocumentSource:
    """A source document that may be mapped into the virtual knowledge base."""

    uri: str
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class IngestedDocument:
    """A normalized document ready for page-index mapping."""

    source: DocumentSource
    virtual_path: str
    local_path: Path
    description: str


@dataclass(slots=True)
class IngestionPlan:
    """Declarative plan for building or refreshing the knowledge base."""

    sources: list[DocumentSource] = field(default_factory=list)
    output_root: Path | None = None
    page_index_path: Path | None = None
