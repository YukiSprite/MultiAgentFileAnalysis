"""Application configuration placeholders."""

from dataclasses import dataclass
from pathlib import Path

from multi_agent_file_analysis.core import RunMode


@dataclass(slots=True)
class AppConfig:
    """High-level paths used by the architecture."""

    page_index_path: Path
    knowledge_base_root: Path
    run_mode: RunMode = RunMode.INTERACTIVE
    model_name: str | None = None
    audit_log_path: Path | None = None
    max_file_chars: int = 12_000
    grep_context_lines: int = 3
    max_grep_hits: int = 50
