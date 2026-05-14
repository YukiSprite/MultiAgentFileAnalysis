"""Virtual file-system access policy boundary."""


class VfsAccessPolicy:
    """Guards what virtual paths and tools an agent may use."""

    def assert_can_list(self, path: str) -> None:
        """Validate that a virtual directory can be listed."""
        raise NotImplementedError

    def assert_can_read(self, path: str) -> None:
        """Validate that a virtual file can be read."""
        raise NotImplementedError

    def assert_can_search(self, path: str, pattern: str) -> None:
        """Validate that a virtual path can be searched for an exact pattern."""
        raise NotImplementedError
