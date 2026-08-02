"""Safe loading of local environment configuration."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_project_environment(env_file: Path | None = None) -> Path | None:
    """Load a local ``.env`` file without overriding process variables.

    The default is deliberately limited to ``.env`` in the current working
    directory.  This avoids unexpectedly loading configuration from a parent
    directory while still matching normal CLI usage from the project root.
    """
    candidate = (env_file or (Path.cwd() / ".env")).expanduser()
    if not candidate.is_file():
        return None

    load_dotenv(dotenv_path=candidate, override=False)
    return candidate.resolve()
