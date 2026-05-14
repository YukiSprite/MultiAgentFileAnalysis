"""Virtual file-system access policy boundary.

The policy layer is where future implementations should enforce path safety,
tool-level permissions, and query limits before any real file is touched.
"""


class VfsAccessPolicy:
    """Guards what virtual paths and tools an agent may use.

    Keep this separate from VirtualFileSystem so security checks can be tested
    independently from file reading and grep behavior.
    """

    def assert_can_list(self, path: str) -> None:
        """Validate that a virtual directory can be listed."""
        raise NotImplementedError

    def assert_can_read(self, path: str) -> None:
        """Validate that a virtual file can be read."""
        raise NotImplementedError

    def assert_can_search(self, path: str, pattern: str) -> None:
        """Validate that a virtual path can be searched for an exact pattern."""
        raise NotImplementedError
