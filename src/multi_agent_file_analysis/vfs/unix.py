"""Unix-style, read-only tool facade backed by the controlled VFS."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from multi_agent_file_analysis.core.errors import VirtualFileSystemError

from .protocol import VirtualFileSystem


@dataclass(slots=True)
class UnixToolResult:
    """Shell-shaped result without executing a real shell command."""

    tool: str
    cwd: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> str:
        return json.dumps(
            {
                "tool": self.tool,
                "cwd": self.cwd,
                "exit_code": self.exit_code,
                "stdout": self.stdout,
                "stderr": self.stderr,
                "truncated": self.truncated,
                "data": self.data,
            },
            ensure_ascii=False,
        )


class UnixFileSystemSession:
    """Per-agent POSIX-like session rooted at the virtual ``/`` directory."""

    def __init__(self, vfs: VirtualFileSystem) -> None:
        self._vfs = vfs
        self._cwd = "/"
        self._handlers: dict[str, Callable[..., UnixToolResult]] = {
            "pwd": self._pwd,
            "cd": self._cd,
            "ls": self._ls,
            "find": self._find,
            "stat": self._stat,
            "cat": self._cat,
            "head": self._head,
            "tail": self._tail,
            "grep": self._grep,
            "search": self._search,
        }

    @property
    def cwd(self) -> str:
        return self._cwd

    def execute(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
    ) -> UnixToolResult:
        """Execute an allowlisted virtual tool with structured arguments."""
        handler = self._handlers.get(tool)
        if handler is None:
            return UnixToolResult(
                tool=tool,
                cwd=self._cwd,
                exit_code=127,
                stderr=f"{tool}: command not found in the read-only workspace",
            )
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return UnixToolResult(
                tool=tool,
                cwd=self._cwd,
                exit_code=2,
                stderr=f"{tool}: arguments must be an object",
            )
        try:
            return handler(**arguments)
        except (TypeError, ValueError, VirtualFileSystemError) as exc:
            return UnixToolResult(
                tool=tool,
                cwd=self._cwd,
                exit_code=2,
                stderr=f"{tool}: {exc}",
            )
        except Exception:
            return UnixToolResult(
                tool=tool,
                cwd=self._cwd,
                exit_code=1,
                stderr=f"{tool}: virtual filesystem operation failed",
            )

    def _pwd(self) -> UnixToolResult:
        return UnixToolResult(
            tool="pwd",
            cwd=self._cwd,
            exit_code=0,
            stdout=self._cwd,
        )

    def _cd(self, path: str = "/") -> UnixToolResult:
        resolved = self._resolve(path)
        stat = self._vfs.v_stat(resolved)
        if stat.kind != "directory":
            raise VirtualFileSystemError(f"not a directory: {resolved}")
        self._cwd = resolved
        return UnixToolResult(
            tool="cd",
            cwd=self._cwd,
            exit_code=0,
            stdout=self._cwd,
        )

    def _ls(
        self,
        path: str = ".",
        offset: int = 0,
        limit: int | None = None,
        query: str | None = None,
        long: bool = False,
    ) -> UnixToolResult:
        resolved = self._resolve(path)
        result = self._vfs.v_ls(
            resolved,
            offset=offset,
            limit=limit,
            query=query,
        )
        lines: list[str] = []
        for entry in result.entries:
            suffix = "/" if entry.kind == "directory" else ""
            if long:
                metadata = " ".join(
                    f"{key}={value}" for key, value in sorted(entry.metadata.items())
                )
                detail = f" — {entry.description}" if entry.description else ""
                if metadata:
                    detail += f" [{metadata}]"
                lines.append(f"{entry.kind[0]}-- {entry.path}{suffix}{detail}")
            else:
                lines.append(f"{entry.path}{suffix}")
        return UnixToolResult(
            tool="ls",
            cwd=self._cwd,
            exit_code=0,
            stdout="\n".join(lines),
            truncated=result.truncated,
            data={
                "path": resolved,
                "total_entries": result.total_entries,
                "offset": result.offset,
                "next_offset": result.next_offset,
            },
        )

    def _find(
        self,
        path: str = ".",
        name: str = "*",
        type: str | None = None,
        limit: int | None = None,
        filters: dict[str, str] | None = None,
    ) -> UnixToolResult:
        resolved = self._resolve(path)
        result = self._vfs.v_find(
            resolved,
            name=name,
            kind=type,
            limit=limit,
            filters=filters,
        )
        lines = [
            entry.path + ("/" if entry.kind == "directory" else "")
            for entry in result.entries
        ]
        return UnixToolResult(
            tool="find",
            cwd=self._cwd,
            exit_code=0,
            stdout="\n".join(lines),
            truncated=result.truncated,
            data={
                "path": resolved,
                "name": name,
                "nodes_searched": result.nodes_searched,
            },
        )

    def _stat(self, path: str) -> UnixToolResult:
        resolved = self._resolve(path)
        result = self._vfs.v_stat(resolved)
        payload = {
            "path": result.path,
            "type": result.kind,
            "size_bytes": result.size_bytes,
            "title": result.title,
            "description": result.description,
            "tags": result.tags,
            "metadata": result.metadata,
        }
        return UnixToolResult(
            tool="stat",
            cwd=self._cwd,
            exit_code=0,
            stdout=json.dumps(payload, ensure_ascii=False, indent=2),
            data=payload,
        )

    def _cat(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> UnixToolResult:
        resolved = self._resolve(path)
        result = self._vfs.v_cat(
            resolved,
            start_line=start_line,
            end_line=end_line,
        )
        return self._file_result("cat", result)

    def _head(self, path: str, lines: int = 40) -> UnixToolResult:
        if lines <= 0:
            raise VirtualFileSystemError("line count must be greater than zero")
        resolved = self._resolve(path)
        result = self._vfs.v_cat(resolved, start_line=1, end_line=lines)
        return self._file_result("head", result)

    def _tail(self, path: str, lines: int = 40) -> UnixToolResult:
        if lines <= 0:
            raise VirtualFileSystemError("line count must be greater than zero")
        resolved = self._resolve(path)
        probe = self._vfs.v_cat(resolved, start_line=1, end_line=1)
        start_line = max(1, probe.total_lines - lines + 1)
        result = self._vfs.v_cat(
            resolved,
            start_line=start_line,
            end_line=probe.total_lines,
        )
        return self._file_result("tail", result)

    def _grep(
        self,
        pattern: str,
        path: str = ".",
        recursive: bool = True,
        ignore_case: bool = True,
        whole_word: bool = False,
        context: int | None = None,
        limit: int | None = None,
    ) -> UnixToolResult:
        del recursive  # Indexed directories are recursively searched by design.
        resolved = self._resolve(path)
        result = self._vfs.v_grep(
            resolved,
            pattern,
            case_sensitive=not ignore_case,
            whole_word=whole_word,
            context_lines=context,
            limit=limit,
        )
        blocks: list[str] = []
        for hit in result.hits:
            if hit.context:
                blocks.append(
                    f"{hit.path}:{hit.line_number}:{hit.line}\n"
                    + "\n".join(f"{hit.path}-{line}" for line in hit.context)
                )
            else:
                blocks.append(f"{hit.path}:{hit.line_number}:{hit.line}")
        return UnixToolResult(
            tool="grep",
            cwd=self._cwd,
            exit_code=0 if result.hits else 1,
            stdout="\n--\n".join(blocks),
            truncated=result.truncated,
            data={
                "path": resolved,
                "pattern": pattern,
                "matches": len(result.hits),
                "files_searched": result.files_searched,
            },
        )

    def _search(
        self,
        query: str,
        path: str = ".",
        limit: int | None = None,
        filters: dict[str, str] | None = None,
    ) -> UnixToolResult:
        resolved = self._resolve(path)
        result = self._vfs.v_search(
            query,
            scope=resolved,
            limit=limit,
            filters=filters,
        )
        blocks = [
            f"{hit.path}:{hit.line_start}-{hit.line_end} score={hit.score:.1f}\n"
            f"{hit.excerpt}"
            for hit in result.hits
        ]
        return UnixToolResult(
            tool="search",
            cwd=self._cwd,
            exit_code=0 if result.hits else 1,
            stdout="\n--\n".join(blocks),
            truncated=result.truncated,
            data={
                "path": resolved,
                "query": query,
                "matches": len(result.hits),
                "files_searched": result.files_searched,
            },
        )

    def _file_result(self, tool: str, result: Any) -> UnixToolResult:
        return UnixToolResult(
            tool=tool,
            cwd=self._cwd,
            exit_code=0,
            stdout=result.content,
            truncated=result.truncated,
            data={
                "path": result.path,
                "start_line": result.start_line,
                "end_line": result.end_line,
                "total_lines": result.total_lines,
                "content_hash": result.content_hash,
            },
        )

    def _resolve(self, path: str) -> str:
        if not isinstance(path, str) or not path:
            raise VirtualFileSystemError("path must be a non-empty string")
        if "\\" in path or "\x00" in path:
            raise VirtualFileSystemError(f"invalid virtual path: {path}")

        parts = [] if path.startswith("/") else self._path_parts(self._cwd)
        for part in path.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        return "/" + "/".join(parts) if parts else "/"

    @staticmethod
    def _path_parts(path: str) -> list[str]:
        return [part for part in path.split("/") if part]


_UNIX_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "pwd",
        "description": "Print the current directory in the read-only virtual workspace.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "cd",
        "description": "Change the current virtual directory. Relative and absolute POSIX paths are supported.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "/"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "ls",
        "description": "List one virtual directory level with bounded pagination.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1},
                "query": {"type": "string"},
                "long": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "find",
        "description": "Find indexed virtual paths using a POSIX-style glob and optional metadata filters.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "name": {"type": "string", "default": "*"},
                "type": {"type": "string", "enum": ["file", "directory"]},
                "limit": {"type": "integer", "minimum": 1},
                "filters": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "stat",
        "description": "Show type, size, tags, version, authority, and other metadata for one virtual path.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cat",
        "description": "Read a bounded line range from a virtual text file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1, "default": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "head",
        "description": "Read the first N lines of a virtual text file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "lines": {"type": "integer", "minimum": 1, "default": 40},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "tail",
        "description": "Read the last N lines of a virtual text file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "lines": {"type": "integer", "minimum": 1, "default": 40},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "grep",
        "description": "Recursively grep indexed files for a literal string; no shell or regular expression is executed.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "recursive": {"type": "boolean", "default": True},
                "ignore_case": {"type": "boolean", "default": True},
                "whole_word": {"type": "boolean", "default": False},
                "context": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search",
        "description": "Run metadata-aware ranked lexical search for a natural-language query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "limit": {"type": "integer", "minimum": 1},
                "filters": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
)


def unix_tool_schemas() -> list[dict[str, Any]]:
    """Return independent JSON Schema definitions for native tool calling."""
    return deepcopy(list(_UNIX_TOOL_SCHEMAS))
