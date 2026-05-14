"""Application configuration placeholders."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    """High-level paths used by the architecture."""

    page_index_path: Path
    knowledge_base_root: Path
    max_file_chars: int = 12_000
    grep_context_lines: int = 3
