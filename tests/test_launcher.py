from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_help_runs_without_install_or_pythonpath(self) -> None:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "mafa.py", "--help"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("web", result.stdout)
        self.assertIn("chat", result.stdout)

    def test_launcher_dispatches_dry_run(self) -> None:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [
                sys.executable,
                "mafa.py",
                "ask",
                "--dry-run",
                "--knowledge-base",
                str(ROOT / "knowledge_base"),
                "RATE_LIMIT_RPS",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("RATE_LIMIT_RPS", result.stdout)


if __name__ == "__main__":
    unittest.main()
