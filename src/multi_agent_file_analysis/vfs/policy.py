"""Virtual file-system access policy."""

from multi_agent_file_analysis.core.errors import VirtualFileSystemError


class VfsAccessPolicy:
    """Guards what virtual paths and tools an agent may use."""

    def assert_can_list(self, path: str) -> None:
        self._assert_virtual_path(path, "listing")

    def assert_can_read(self, path: str) -> None:
        self._assert_virtual_path(path, "reading")

    def assert_can_search(self, path: str, pattern: str) -> None:
        self._assert_virtual_path(path, "search")
        if not pattern or not pattern.strip():
            raise VirtualFileSystemError("Search pattern must not be empty")
        if len(pattern) > 500:
            raise VirtualFileSystemError("Search pattern is too long")

    def assert_can_paginate(self, offset: int, limit: int) -> None:
        if offset < 0:
            raise VirtualFileSystemError("Offset must not be negative")
        if limit <= 0:
            raise VirtualFileSystemError("Limit must be greater than zero")

    @staticmethod
    def _assert_virtual_path(path: str, operation: str) -> None:
        if not path or not path.startswith("/") or "\\" in path or "\x00" in path:
            raise VirtualFileSystemError(
                f"Invalid virtual path for {operation}: {path}"
            )
        parts = [part for part in path.split("/") if part]
        if any(part in {".", ".."} for part in parts):
            raise VirtualFileSystemError(f"Path traversal denied: {path}")
