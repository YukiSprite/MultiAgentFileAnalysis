"""Application configuration."""

from dataclasses import dataclass
from pathlib import Path

from multi_agent_file_analysis.core import ConfigError, RunMode


@dataclass(slots=True)
class AppConfig:
    """Runtime limits and paths used by the application."""

    page_index_path: Path
    knowledge_base_root: Path
    run_mode: RunMode = RunMode.INTERACTIVE
    env_file_path: Path | None = None
    audit_log_path: Path | None = None
    max_file_chars: int = 12_000
    max_read_lines: int = 240
    max_directory_entries: int = 100
    grep_context_lines: int = 3
    max_grep_hits: int = 50
    max_search_results: int = 20
    max_search_files: int = 20_000
    max_search_candidates: int = 750
    # Keep every accepted source file searchable.  A separate aggregate budget
    # bounds one catalog build/search across many files.
    max_search_file_chars: int = 5_000_000
    max_search_total_chars: int = 250_000_000
    max_source_file_bytes: int = 5_000_000
    max_explorer_turns: int = 12
    max_workflow_iterations: int = 16
    max_review_retries: int = 2
    max_human_input_chars: int = 20_000

    def validate(self) -> None:
        """Fail early when a limit or path would make execution unsafe."""
        if not self.page_index_path.exists():
            raise ConfigError(f"Page index not found: {self.page_index_path}")
        if not self.knowledge_base_root.exists():
            raise ConfigError(
                f"Knowledge-base root not found: {self.knowledge_base_root}"
            )
        if not self.knowledge_base_root.is_dir():
            raise ConfigError(
                f"Knowledge-base root is not a directory: {self.knowledge_base_root}"
            )

        positive_limits = {
            "max_file_chars": self.max_file_chars,
            "max_read_lines": self.max_read_lines,
            "max_directory_entries": self.max_directory_entries,
            "grep_context_lines": self.grep_context_lines,
            "max_grep_hits": self.max_grep_hits,
            "max_search_results": self.max_search_results,
            "max_search_files": self.max_search_files,
            "max_search_candidates": self.max_search_candidates,
            "max_search_file_chars": self.max_search_file_chars,
            "max_search_total_chars": self.max_search_total_chars,
            "max_source_file_bytes": self.max_source_file_bytes,
            "max_explorer_turns": self.max_explorer_turns,
            "max_workflow_iterations": self.max_workflow_iterations,
            "max_human_input_chars": self.max_human_input_chars,
        }
        for name, value in positive_limits.items():
            if value <= 0:
                raise ConfigError(f"{name} must be greater than zero")
        if self.max_review_retries < 0:
            raise ConfigError("max_review_retries must not be negative")
