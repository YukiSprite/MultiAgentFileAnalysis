"""Controlled virtual file-system browsing and lexical retrieval."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import ToolName
from multi_agent_file_analysis.core.errors import VirtualFileSystemError
from multi_agent_file_analysis.index import IndexNode, NodeKind, PageIndexRepository

from .policy import VfsAccessPolicy


@dataclass(slots=True)
class DirectoryEntry:
    path: str
    kind: str
    description: str
    title: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class DirectoryListing:
    path: str
    entries: list[DirectoryEntry]
    truncated: bool = False
    total_entries: int = 0
    offset: int = 0
    next_offset: int | None = None


@dataclass(slots=True)
class FileReadResult:
    path: str
    content: str
    truncated: bool
    total_chars: int | None = None
    source_path: str | None = None
    start_line: int = 1
    end_line: int = 1
    total_lines: int = 0
    content_hash: str | None = None


@dataclass(slots=True)
class GrepHit:
    path: str
    line_number: int
    line: str
    context: list[str]
    section: str | None = None
    excerpt: str = ""
    context_start: int | None = None
    context_end: int | None = None


@dataclass(slots=True)
class GrepResult:
    path: str
    pattern: str
    hits: list[GrepHit]
    truncated: bool = False
    files_searched: int = 0


@dataclass(slots=True)
class SearchHit:
    path: str
    score: float
    description: str
    excerpt: str
    line_start: int | None = None
    line_end: int | None = None
    matched_terms: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SearchResult:
    query: str
    scope: str
    hits: list[SearchHit]
    truncated: bool = False
    files_searched: int = 0


@dataclass(slots=True)
class EvidenceVerification:
    path: str
    quote: str
    line_start: int
    line_end: int
    section: str | None
    content_hash: str
    source_version: str | None
    metadata: dict[str, str]


@dataclass(slots=True)
class VfsToolCall:
    tool_name: ToolName
    path: str
    pattern: str | None = None


class VirtualFileSystem:
    """Read-only, bounded access to documents registered in Page Index."""

    def __init__(
        self,
        repository: PageIndexRepository,
        config: AppConfig,
        policy: VfsAccessPolicy | None = None,
    ) -> None:
        self._repo = repository
        self._config = config
        self._policy = policy or VfsAccessPolicy()

    def v_ls(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        query: str | None = None,
    ) -> DirectoryListing:
        """List one directory level with pagination and optional filtering."""
        self._policy.assert_can_list(path)
        effective_limit = min(
            limit or self._config.max_directory_entries,
            self._config.max_directory_entries,
        )
        self._policy.assert_can_paginate(offset, effective_limit)

        children = self._repo.list_children(path)
        if query:
            needle = query.casefold()
            children = [
                child
                for child in children
                if needle in self._node_search_text(child).casefold()
            ]

        total = len(children)
        page = children[offset : offset + effective_limit]
        next_offset = offset + len(page) if offset + len(page) < total else None
        entries = [
            DirectoryEntry(
                path=child.path,
                kind=str(child.kind),
                description=child.description,
                title=child.title,
                tags=list(child.tags) if child.tags else None,
                metadata=dict(child.metadata),
            )
            for child in page
        ]
        return DirectoryListing(
            path=path,
            entries=entries,
            truncated=next_offset is not None,
            total_entries=total,
            offset=offset,
            next_offset=next_offset,
        )

    def v_cat(
        self,
        path: str,
        *,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> FileReadResult:
        """Read a bounded line range; callers can continue with the next line."""
        self._policy.assert_can_read(path)
        if start_line < 1:
            raise VirtualFileSystemError("start_line must be at least 1")
        if end_line is not None and end_line < start_line:
            raise VirtualFileSystemError("end_line must not precede start_line")

        source_path, content = self._read_file(path)
        lines = content.splitlines()
        total_lines = len(lines)
        requested_end = end_line or (start_line + self._config.max_read_lines - 1)
        requested_end = min(
            requested_end,
            start_line + self._config.max_read_lines - 1,
        )
        start_index = min(start_line - 1, total_lines)
        end_index = min(requested_end, total_lines)
        selected = lines[start_index:end_index]
        rendered = "\n".join(selected)
        char_truncated = len(rendered) > self._config.max_file_chars
        if char_truncated:
            rendered = rendered[: self._config.max_file_chars]

        actual_end = start_index + len(selected)
        truncated = char_truncated or actual_end < total_lines
        return FileReadResult(
            path=path,
            content=rendered,
            truncated=truncated,
            total_chars=len(content),
            source_path=str(source_path),
            start_line=start_line,
            end_line=max(start_line, actual_end),
            total_lines=total_lines,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    def v_read_range(
        self,
        path: str,
        start_line: int,
        end_line: int,
    ) -> FileReadResult:
        """Explicit line-range alias used by Explorer tool calls."""
        if end_line - start_line + 1 > self._config.max_read_lines:
            raise VirtualFileSystemError(
                f"Requested range exceeds {self._config.max_read_lines} lines"
            )
        return self.v_cat(path, start_line=start_line, end_line=end_line)

    def v_grep(
        self,
        path: str,
        pattern: str,
        *,
        case_sensitive: bool = False,
        whole_word: bool = False,
    ) -> GrepResult:
        """Search a file or an indexed directory scope using a literal string."""
        self._policy.assert_can_search(path, pattern)
        flags = 0 if case_sensitive else re.IGNORECASE
        expression = re.escape(pattern)
        if whole_word:
            expression = rf"(?<!\w){expression}(?!\w)"
        matcher = re.compile(expression, flags)

        hits: list[GrepHit] = []
        files_searched = 0
        truncated = False
        for node in self._repo.iter_files(path):
            if files_searched >= self._config.max_search_files:
                truncated = True
                break
            files_searched += 1
            _, content = self._read_file(node.path)
            if len(content) > self._config.max_search_file_chars:
                content = content[: self._config.max_search_file_chars]
                truncated = True
            lines = content.splitlines()
            for index, line in enumerate(lines):
                if not matcher.search(line):
                    continue
                if len(hits) >= self._config.max_grep_hits:
                    truncated = True
                    break
                start = max(0, index - self._config.grep_context_lines)
                end = min(
                    len(lines),
                    index + self._config.grep_context_lines + 1,
                )
                context = [f"{i + 1}: {lines[i]}" for i in range(start, end)]
                hits.append(
                    GrepHit(
                        path=node.path,
                        line_number=index + 1,
                        line=line,
                        context=context,
                        section=self._nearest_heading(lines, index),
                        excerpt="\n".join(lines[start:end]),
                        context_start=start + 1,
                        context_end=end,
                    )
                )
            if len(hits) >= self._config.max_grep_hits:
                break

        return GrepResult(
            path=path,
            pattern=pattern,
            hits=hits,
            truncated=truncated,
            files_searched=files_searched,
        )

    def v_search(
        self,
        query: str,
        *,
        scope: str = "/",
        limit: int | None = None,
        filters: dict[str, str] | None = None,
    ) -> SearchResult:
        """Rank indexed files with metadata-aware lexical search."""
        self._policy.assert_can_search(scope, query)
        effective_limit = min(
            limit or self._config.max_search_results,
            self._config.max_search_results,
        )
        terms = self._query_terms(query)
        if not terms:
            raise VirtualFileSystemError("Search query has no usable terms")

        candidates: list[SearchHit] = []
        files_searched = 0
        any_truncated = False
        for node in self._repo.iter_files(scope):
            if files_searched >= self._config.max_search_files:
                any_truncated = True
                break
            if filters and not self._matches_filters(node, filters):
                continue
            files_searched += 1
            _, content = self._read_file(node.path)
            if len(content) > self._config.max_search_file_chars:
                content = content[: self._config.max_search_file_chars]
                any_truncated = True

            metadata_text = self._node_search_text(node).casefold()
            content_folded = content.casefold()
            score = 0.0
            matched: list[str] = []
            first_position: int | None = None
            for term in terms:
                folded = term.casefold()
                metadata_count = metadata_text.count(folded)
                content_count = content_folded.count(folded)
                if metadata_count or content_count:
                    matched.append(term)
                    score += min(metadata_count, 3) * 4.0
                    score += min(content_count, 8) * 1.5
                    if node.path.casefold().find(folded) >= 0:
                        score += 5.0
                    position = content_folded.find(folded)
                    if position >= 0 and (
                        first_position is None or position < first_position
                    ):
                        first_position = position
            if not matched:
                continue

            excerpt, line_start, line_end = self._excerpt(
                content,
                first_position,
            )
            candidates.append(
                SearchHit(
                    path=node.path,
                    score=score,
                    description=node.description,
                    excerpt=excerpt,
                    line_start=line_start,
                    line_end=line_end,
                    matched_terms=matched,
                    metadata=dict(node.metadata),
                )
            )

        candidates.sort(key=lambda hit: (-hit.score, hit.path))
        truncated = len(candidates) > effective_limit or any_truncated
        return SearchResult(
            query=query,
            scope=scope,
            hits=candidates[:effective_limit],
            truncated=truncated,
            files_searched=files_searched,
        )

    def verify_quote(self, path: str, quote: str) -> EvidenceVerification:
        """Bind a model-proposed quote to an indexed source or reject it."""
        self._policy.assert_can_read(path)
        normalized_quote = quote.strip()
        if len(normalized_quote) < 4:
            raise VirtualFileSystemError("Evidence quote is too short to verify")
        _, content = self._read_file(path)
        position = content.find(normalized_quote)
        if position < 0:
            raise VirtualFileSystemError(
                f"Evidence quote does not occur verbatim in {path}"
            )

        line_start = content.count("\n", 0, position) + 1
        line_end = line_start + normalized_quote.count("\n")
        lines = content.splitlines()
        node = self._repo.get_node(path)
        return EvidenceVerification(
            path=node.path,
            quote=normalized_quote,
            line_start=line_start,
            line_end=line_end,
            section=self._nearest_heading(lines, max(0, line_start - 1)),
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_version=node.metadata.get("version"),
            metadata=dict(node.metadata),
        )

    def get_metadata(self, path: str) -> dict[str, str]:
        return dict(self._repo.get_node(path).metadata)

    def _read_file(self, virtual_path: str) -> tuple[Path, str]:
        node = self._repo.get_node(virtual_path)
        if node.kind != NodeKind.FILE:
            raise VirtualFileSystemError(f"Not a virtual file: {virtual_path}")
        source_path = self._repo.resolve_source_path(virtual_path)
        if not source_path.exists():
            raise VirtualFileSystemError(f"Source file not found: {source_path}")
        if not source_path.is_file():
            raise VirtualFileSystemError(f"Source is not a file: {source_path}")
        if source_path.stat().st_size > self._config.max_source_file_bytes:
            raise VirtualFileSystemError(
                f"Source exceeds {self._config.max_source_file_bytes} bytes: "
                f"{virtual_path}"
            )
        try:
            return source_path, source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return source_path, source_path.read_text(
                encoding="utf-8",
                errors="replace",
            )

    @staticmethod
    def _node_search_text(node: IndexNode) -> str:
        values = [
            node.path,
            node.title or "",
            node.description,
            " ".join(node.tags),
            " ".join(node.aliases),
            " ".join(f"{key} {value}" for key, value in node.metadata.items()),
        ]
        return "\n".join(values)

    @staticmethod
    def _matches_filters(node: IndexNode, filters: dict[str, str]) -> bool:
        for key, expected in filters.items():
            if key == "tag":
                if expected not in node.tags:
                    return False
            elif node.metadata.get(key) != expected:
                return False
        return True

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        ascii_terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", query)
        cjk_chunks = re.findall(r"[\u3400-\u9fff]{2,}", query)
        stopwords = {"the", "and", "what", "why", "how", "是什么", "怎么", "如何"}
        terms: list[str] = []
        for term in ascii_terms:
            if term.casefold() not in stopwords:
                terms.append(term)
        for chunk in cjk_chunks:
            if chunk not in stopwords:
                terms.append(chunk)
            if len(chunk) > 2:
                terms.extend(
                    chunk[index : index + 2]
                    for index in range(len(chunk) - 1)
                    if chunk[index : index + 2] not in stopwords
                )
        return list(dict.fromkeys(terms))

    @staticmethod
    def _nearest_heading(lines: list[str], index: int) -> str | None:
        for candidate in range(min(index, len(lines) - 1), -1, -1):
            stripped = lines[candidate].strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or None
        return None

    @staticmethod
    def _excerpt(
        content: str,
        position: int | None,
        context_lines: int = 2,
    ) -> tuple[str, int | None, int | None]:
        lines = content.splitlines()
        if not lines:
            return "", None, None
        if position is None:
            start = 0
        else:
            line_index = content.count("\n", 0, position)
            start = max(0, line_index - context_lines)
        end = min(len(lines), start + context_lines * 2 + 1)
        return "\n".join(lines[start:end]), start + 1, end
