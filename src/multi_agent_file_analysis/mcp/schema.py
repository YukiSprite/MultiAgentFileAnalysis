"""Structured MCP output contracts for virtual filesystem tools."""

from __future__ import annotations

from typing_extensions import TypedDict


class DirectoryEntryOutput(TypedDict):
    path: str
    kind: str
    description: str
    title: str | None
    tags: list[str] | None
    metadata: dict[str, str]


class DirectoryListingOutput(TypedDict):
    path: str
    entries: list[DirectoryEntryOutput]
    truncated: bool
    total_entries: int
    offset: int
    next_offset: int | None


class FileReadOutput(TypedDict):
    path: str
    content: str
    truncated: bool
    total_chars: int | None
    source_path: str | None
    start_line: int
    end_line: int
    total_lines: int
    content_hash: str | None


class GrepHitOutput(TypedDict):
    path: str
    line_number: int
    line: str
    context: list[str]
    section: str | None
    excerpt: str
    context_start: int | None
    context_end: int | None


class GrepOutput(TypedDict):
    path: str
    pattern: str
    hits: list[GrepHitOutput]
    truncated: bool
    files_searched: int


class SearchHitOutput(TypedDict):
    path: str
    score: float
    description: str
    excerpt: str
    line_start: int | None
    line_end: int | None
    matched_terms: list[str]
    metadata: dict[str, str]


class SearchOutput(TypedDict):
    query: str
    scope: str
    hits: list[SearchHitOutput]
    truncated: bool
    files_searched: int


class FindEntryOutput(TypedDict):
    path: str
    kind: str
    description: str
    metadata: dict[str, str]


class FindOutput(TypedDict):
    path: str
    name: str
    entries: list[FindEntryOutput]
    truncated: bool
    nodes_searched: int


class StatOutput(TypedDict):
    path: str
    kind: str
    description: str
    title: str | None
    tags: list[str]
    metadata: dict[str, str]
    size_bytes: int | None


class EvidenceVerificationOutput(TypedDict):
    path: str
    quote: str
    line_start: int
    line_end: int
    section: str | None
    content_hash: str
    source_version: str | None
    metadata: dict[str, str]


class MetadataOutput(TypedDict):
    path: str
    metadata: dict[str, str]
