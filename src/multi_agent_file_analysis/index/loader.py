"""Page-index loading boundary."""

from pathlib import Path

from .schema import PageIndex


class PageIndexLoader:
    """Loads and validates the static page index."""

    def load(self, path: Path) -> PageIndex:
        """Load a page index from disk."""
        raise NotImplementedError
