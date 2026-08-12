"""Controlled virtual file-system browsing and lexical retrieval."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
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
class FindEntry:
    path: str
    kind: str
    description: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class FindResult:
    path: str
    name: str
    entries: list[FindEntry]
    truncated: bool = False
    nodes_searched: int = 0


@dataclass(slots=True)
class StatResult:
    path: str
    kind: str
    description: str
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    size_bytes: int | None = None


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
        self._catalog: dict[str, list[int]] | None = None
        self._catalog_nodes: list[IndexNode] = []
        self._catalog_truncated = False

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

        _, content = self._read_file(path)
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
            # MCP and agent callers may receive this value.  Keep it inside the
            # virtual namespace instead of leaking the host filesystem path.
            source_path=path,
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
        context_lines: int | None = None,
        limit: int | None = None,
    ) -> GrepResult:
        """Search a file or an indexed directory scope using a literal string."""
        self._policy.assert_can_search(path, pattern)
        flags = 0 if case_sensitive else re.IGNORECASE
        expression = re.escape(pattern)
        if whole_word:
            expression = rf"(?<!\w){expression}(?!\w)"
        matcher = re.compile(expression, flags)
        effective_context = min(
            self._config.grep_context_lines
            if context_lines is None
            else max(0, context_lines),
            self._config.grep_context_lines,
        )
        requested_limit = self._config.max_grep_hits if limit is None else limit
        effective_limit = min(requested_limit, self._config.max_grep_hits)
        if effective_limit <= 0:
            raise VirtualFileSystemError("grep limit must be greater than zero")

        hits: list[GrepHit] = []
        files_searched = 0
        chars_searched = 0
        truncated = False
        for node in self._repo.iter_files(path):
            if files_searched >= self._config.max_search_files:
                truncated = True
                break
            files_searched += 1
            _, content = self._read_file(node.path)
            content = self._mask_frontmatter(content)
            remaining = self._config.max_search_total_chars - chars_searched
            searchable_chars = min(
                self._config.max_search_file_chars,
                max(0, remaining),
            )
            if searchable_chars == 0:
                truncated = True
                break
            if len(content) > searchable_chars:
                content = content[:searchable_chars]
                truncated = True
            chars_searched += len(content)
            lines = content.splitlines()
            for index, line in enumerate(lines):
                if not matcher.search(line):
                    continue
                if len(hits) >= effective_limit:
                    truncated = True
                    break
                start = max(0, index - effective_context)
                end = min(
                    len(lines),
                    index + effective_context + 1,
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
            if len(hits) >= effective_limit:
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

        hits: list[SearchHit] = []
        files_searched = 0
        chars_searched = 0
        any_truncated = False
        candidate_nodes, candidates_truncated = self._catalog_candidates(
            query,
            scope=scope,
            filters=filters,
        )
        nodes = (
            candidate_nodes
            if candidate_nodes is not None
            else self._repo.iter_files(scope)
        )
        for node in nodes:
            if files_searched >= self._config.max_search_files:
                any_truncated = True
                break
            if filters and not self._matches_filters(node, filters):
                continue
            files_searched += 1
            _, content = self._read_file(node.path)
            content = self._mask_frontmatter(content)
            remaining = self._config.max_search_total_chars - chars_searched
            searchable_chars = min(
                self._config.max_search_file_chars,
                max(0, remaining),
            )
            if searchable_chars == 0:
                any_truncated = True
                break
            if len(content) > searchable_chars:
                content = content[:searchable_chars]
                any_truncated = True
            chars_searched += len(content)

            metadata_text = self._node_search_text(node).casefold()
            content_folded = content.casefold()
            term_matches: list[tuple[float, float, str, int | None]] = []
            for term in terms:
                folded = term.casefold()
                metadata_count = metadata_text.count(folded)
                content_count = content_folded.count(folded)
                if metadata_count or content_count:
                    specificity = self._term_specificity(term)
                    contribution = (
                        min(metadata_count, 3) * 4.0 * specificity
                        + min(content_count, 8) * 1.5 * specificity
                    )
                    if node.path.casefold().find(folded) >= 0:
                        contribution += 5.0 * specificity
                    position = content_folded.find(folded)
                    term_matches.append(
                        (
                            specificity,
                            contribution,
                            term,
                            position if position >= 0 else None,
                        )
                    )
            if not term_matches:
                continue

            # Long natural-language questions generate overlapping CJK n-grams.
            # Score only the most specific matches so dozens of generic pairs do
            # not overwhelm one distinctive named rule.
            term_matches.sort(
                key=lambda item: (item[0], item[1], len(item[2])),
                reverse=True,
            )
            selected_matches = term_matches[:12]
            score = sum(item[1] for item in selected_matches)
            matched = [item[2] for item in selected_matches]
            content_matches = [
                item for item in selected_matches if item[3] is not None
            ]
            best_position = self._best_excerpt_position(
                content_folded,
                content_matches,
            )
            excerpt, line_start, line_end = self._excerpt(
                content,
                best_position,
            )
            hits.append(
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

        hits.sort(key=lambda hit: (-hit.score, hit.path))
        truncated = (
            len(hits) > effective_limit
            or any_truncated
            or candidates_truncated
            or self._catalog_truncated
        )
        return SearchResult(
            query=query,
            scope=scope,
            hits=hits[:effective_limit],
            truncated=truncated,
            files_searched=files_searched,
        )

    def v_find(
        self,
        path: str = "/",
        *,
        name: str = "*",
        kind: str | None = None,
        limit: int | None = None,
        filters: dict[str, str] | None = None,
    ) -> FindResult:
        """Find indexed nodes by POSIX-style glob and optional metadata."""
        self._policy.assert_can_list(path)
        if not name or len(name) > 256:
            raise VirtualFileSystemError("Find name must contain 1-256 characters")
        if kind not in {None, "file", "directory"}:
            raise VirtualFileSystemError("Find kind must be file or directory")
        effective_limit = min(
            limit or self._config.max_search_results,
            self._config.max_search_results,
        )
        self._policy.assert_can_paginate(0, effective_limit)

        entries: list[FindEntry] = []
        nodes_searched = 0
        truncated = False
        for node in self._repo.iter_nodes(path):
            if nodes_searched >= self._config.max_search_files:
                truncated = True
                break
            nodes_searched += 1
            node_kind = str(node.kind)
            if kind and node_kind != kind:
                continue
            if filters and not self._matches_filters(node, filters):
                continue
            basename = node.path.rstrip("/").rsplit("/", 1)[-1] or "/"
            if not (
                fnmatchcase(basename.casefold(), name.casefold())
                or fnmatchcase(node.path.casefold(), name.casefold())
            ):
                continue
            if len(entries) >= effective_limit:
                truncated = True
                break
            entries.append(
                FindEntry(
                    path=node.path,
                    kind=node_kind,
                    description=node.description,
                    metadata=dict(node.metadata),
                )
            )

        return FindResult(
            path=path,
            name=name,
            entries=entries,
            truncated=truncated,
            nodes_searched=nodes_searched,
        )

    def v_stat(self, path: str) -> StatResult:
        """Return metadata for one indexed virtual path without exposing host paths."""
        self._policy.assert_can_list(path)
        node = self._repo.get_node(path)
        size_bytes = None
        if node.kind == NodeKind.FILE:
            source_path = self._repo.resolve_source_path(path)
            try:
                if not source_path.exists() or not source_path.is_file():
                    raise VirtualFileSystemError(f"Source file not found for {path}")
                size_bytes = source_path.stat().st_size
            except OSError as exc:
                raise VirtualFileSystemError(
                    f"Unable to stat virtual file: {path}"
                ) from exc
        return StatResult(
            path=node.path,
            kind=str(node.kind),
            description=node.description,
            title=node.title,
            tags=list(node.tags),
            metadata=dict(node.metadata),
            size_bytes=size_bytes,
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
            raise VirtualFileSystemError(
                f"Source file not found for virtual path: {virtual_path}"
            )
        if not source_path.is_file():
            raise VirtualFileSystemError(
                f"Source is not a file for virtual path: {virtual_path}"
            )
        try:
            if source_path.stat().st_size > self._config.max_source_file_bytes:
                raise VirtualFileSystemError(
                    f"Source exceeds {self._config.max_source_file_bytes} bytes: "
                    f"{virtual_path}"
                )
            return source_path, source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return source_path, source_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                raise VirtualFileSystemError(
                    f"Unable to read virtual file: {virtual_path}"
                ) from exc
        except OSError as exc:
            raise VirtualFileSystemError(
                f"Unable to read virtual file: {virtual_path}"
            ) from exc

    def _catalog_candidates(
        self,
        query: str,
        *,
        scope: str,
        filters: dict[str, str] | None = None,
    ) -> tuple[list[IndexNode] | None, bool]:
        """Rank a bounded candidate set with the lazy inverted token catalog."""
        self._ensure_catalog()
        if self._catalog is None:
            return None, False
        query_terms = self._catalog_query_terms(query)
        if not query_terms:
            return None, False

        match_scores: dict[int, float] = {}
        had_usable_key = False
        key_weights: dict[str, float] = {}
        for term in query_terms:
            for key in self._catalog_term_keys(term):
                # Exact ASCII tokens carry more signal than their trigrams. CJK
                # text is represented by bigrams, so pages matching several
                # query bigrams naturally rise above incidental one-key matches.
                weight = 4.0 if key.startswith("a:") else 1.0
                key_weights[key] = max(key_weights.get(key, 0.0), weight)
        for key, weight in key_weights.items():
            postings = self._catalog.get(key)
            if not postings:
                continue
            had_usable_key = True
            for identifier in postings:
                match_scores[identifier] = (
                    match_scores.get(identifier, 0.0) + weight
                )
        if not had_usable_key:
            return [], False

        normalized_scope = scope.rstrip("/") or "/"
        prefix = normalized_scope + "/" if normalized_scope != "/" else "/"
        ranked: list[tuple[float, IndexNode]] = []
        for identifier, score in match_scores.items():
            node = self._catalog_nodes[identifier]
            if not (
                normalized_scope == "/"
                or node.path == normalized_scope
                or node.path.startswith(prefix)
            ):
                continue
            if filters and not self._matches_filters(node, filters):
                continue
            ranked.append((score, node))
        ranked.sort(key=lambda item: (-item[0], item[1].path))
        truncated = len(ranked) > self._config.max_search_candidates
        return (
            [node for _, node in ranked[: self._config.max_search_candidates]],
            truncated,
        )

    def _ensure_catalog(self) -> None:
        if self._catalog is not None:
            return
        catalog: dict[str, list[int]] = {}
        nodes: list[IndexNode] = []
        chars_indexed = 0
        for node in self._repo.iter_files("/"):
            if len(nodes) >= self._config.max_search_files:
                self._catalog_truncated = True
                break
            try:
                _, content = self._read_file(node.path)
            except VirtualFileSystemError:
                self._catalog_truncated = True
                continue
            content = self._mask_frontmatter(content)
            remaining = self._config.max_search_total_chars - chars_indexed
            searchable_chars = min(
                self._config.max_search_file_chars,
                max(0, remaining),
            )
            if searchable_chars == 0:
                self._catalog_truncated = True
                break
            if len(content) > searchable_chars:
                content = content[:searchable_chars]
                self._catalog_truncated = True
            chars_indexed += len(content)
            searchable = self._node_search_text(node) + "\n" + content
            identifier = len(nodes)
            nodes.append(node)
            for key in self._catalog_text_keys(searchable):
                catalog.setdefault(key, []).append(identifier)
        self._catalog = catalog
        self._catalog_nodes = nodes

    @staticmethod
    def _catalog_query_terms(query: str) -> list[str]:
        ascii_terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", query)
        cjk_terms = re.findall(r"[\u3400-\u9fff]{2,}", query)
        return list(dict.fromkeys([*ascii_terms, *cjk_terms]))

    @classmethod
    def _catalog_text_keys(cls, text: str) -> set[str]:
        keys: set[str] = set()
        for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", text.casefold()):
            keys.update(cls._catalog_term_keys(term))
        for chunk in re.findall(r"[\u3400-\u9fff]+", text):
            keys.update(cls._catalog_term_keys(chunk))
        return keys

    @staticmethod
    def _catalog_term_keys(term: str) -> list[str]:
        folded = term.casefold()
        cjk = re.sub(r"[^\u3400-\u9fff]", "", folded)
        if cjk:
            if len(cjk) == 1:
                return ["c:" + cjk]
            return [
                "c:" + cjk[index : index + 2]
                for index in range(len(cjk) - 1)
            ]
        if len(folded) < 3:
            return ["a:" + folded]
        return [
            "a:" + folded,
            *(
                "g:" + folded[index : index + 3]
                for index in range(len(folded) - 2)
            ),
        ]

    @staticmethod
    def _mask_frontmatter(content: str) -> str:
        """Blank YAML frontmatter while preserving downstream line numbers."""
        lines = content.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            return content
        closing = next(
            (
                index
                for index, line in enumerate(lines[1:501], start=1)
                if line.strip() in {"---", "..."}
            ),
            None,
        )
        if closing is None:
            return content
        masked = ["\n" if line.endswith("\n") else "" for line in lines[: closing + 1]]
        return "".join([*masked, *lines[closing + 1 :]])

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
        cjk_chunks = list(
            dict.fromkeys(re.findall(r"[\u3400-\u9fff]{2,}", query))
        )
        stopwords = {"the", "and", "what", "why", "how", "是什么", "怎么", "如何"}
        terms: list[str] = []
        for term in ascii_terms:
            if term.casefold() not in stopwords:
                terms.append(term)
        for chunk in cjk_chunks:
            if chunk not in stopwords:
                terms.append(chunk)
        for width in (3, 2):
            for chunk in cjk_chunks:
                if len(chunk) < width:
                    continue
                positions = range(len(chunk) - width + 1)
                # Bound pathological long user input while sampling the whole
                # phrase rather than indexing only its beginning.
                if len(positions) > 16:
                    last = len(positions) - 1
                    positions = sorted({round(last * index / 15) for index in range(16)})
                terms.extend(
                    chunk[index : index + width]
                    for index in positions
                    if chunk[index : index + width] not in stopwords
                )
        return list(dict.fromkeys(terms))[:128]

    @staticmethod
    def _term_specificity(term: str) -> float:
        cjk = re.sub(r"[^\u3400-\u9fff]", "", term)
        if cjk:
            functional = set("的一是了个该会不受于在内有和或与及其这那")
            informative = sum(character not in functional for character in cjk)
            return float(min(len(cjk), 6)) / 2.0 + informative / 4.0
        return 1.0

    @staticmethod
    def _best_excerpt_position(
        content_folded: str,
        matches: list[tuple[float, float, str, int | None]],
    ) -> int | None:
        """Choose the passage where the most distinct query terms co-occur."""
        searchable = [
            (specificity, term.casefold())
            for specificity, _, term, position in matches
            if position is not None
        ]
        if not searchable:
            return None

        occurrences: list[tuple[float, str, list[int]]] = []
        anchors: list[int] = []
        for specificity, term in searchable:
            term_positions: list[int] = []
            start = 0
            for _ in range(16):
                position = content_folded.find(term, start)
                if position < 0:
                    break
                term_positions.append(position)
                anchors.append(position)
                start = position + max(1, len(term))
            occurrences.append((specificity, term, term_positions))
        if not anchors:
            return None

        radius = 900
        best_position = min(anchors)
        best_rank: tuple[float, int, int, int, int] | None = None
        for anchor in anchors:
            start = max(0, anchor - radius)
            end = min(len(content_folded), anchor + radius)
            present: list[tuple[float, str, int]] = []
            for specificity, term, positions in occurrences:
                nearby = [position for position in positions if start <= position < end]
                if nearby:
                    present.append(
                        (
                            specificity,
                            term,
                            min(nearby, key=lambda position: abs(position - anchor)),
                        )
                    )
            absolute_positions = [item[2] for item in present]
            span = (
                max(absolute_positions) - min(absolute_positions)
                if absolute_positions
                else len(content_folded)
            )
            rank = (
                sum(item[0] for item in present),
                len(present),
                -span,
                -sum(abs(item[2] - anchor) for item in present),
                -anchor,
            )
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_position = anchor
        return best_position

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
        context_lines: int = 5,
    ) -> tuple[str, int | None, int | None]:
        lines = content.splitlines()
        if not lines:
            return "", None, None
        if position is None:
            first_content = next(
                (index for index, line in enumerate(lines) if line.strip()),
                0,
            )
            start = max(0, first_content - context_lines)
        else:
            line_index = content.count("\n", 0, position)
            start = max(0, line_index - context_lines)
        end = min(len(lines), start + context_lines * 2 + 1)
        return "\n".join(lines[start:end]), start + 1, end
