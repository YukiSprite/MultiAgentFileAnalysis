"""Page-index loading boundary."""

from pathlib import Path

from .schema import PageIndex


class PageIndexLoader:
    """Loads and validates the static page index."""

    def load(self, path: Path) -> PageIndex:
        """Load a page index from disk."""
        raise NotImplementedError

    def validate(self, index: PageIndex) -> None:
        """Validate a loaded page index before it is used by VFS."""
        raise NotImplementedError

    def dump_example(self, path: Path) -> None:
        """Write an example page index for project bootstrapping."""
        raise NotImplementedError
