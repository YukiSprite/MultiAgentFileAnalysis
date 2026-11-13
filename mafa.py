#!/usr/bin/env python3
"""Zero-install launcher for all platforms.

Run from the repository root with ``python mafa.py`` (or ``python3 mafa.py``).
It adds ``src/`` to ``sys.path`` so no editable install is required, then hands
control to the normal CLI. Without arguments it starts the browser console.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

EXPECTED_DEPENDENCIES = {
    "yaml",
    "dotenv",
    "openai",
    "bs4",
    "lxml",
    "fastapi",
    "uvicorn",
}


def _bootstrap() -> None:
    if SRC.is_dir() and str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))


def main() -> int:
    if sys.version_info < (3, 11):
        print(
            "需要 Python 3.11 或更高版本，当前为 "
            f"{sys.version.split()[0]}",
            file=sys.stderr,
        )
        return 1
    _bootstrap()
    try:
        from multi_agent_file_analysis.cli import main as cli_main
    except ModuleNotFoundError as exc:
        missing = exc.name or "unknown"
        if missing.split(".")[0] not in EXPECTED_DEPENDENCIES:
            raise
        print(f"缺少依赖：{missing}", file=sys.stderr)
        print(
            "请先安装：python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
