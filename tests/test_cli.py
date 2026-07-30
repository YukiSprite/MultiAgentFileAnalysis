from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from multi_agent_file_analysis.cli import main


class CLITests(unittest.TestCase):
    def test_documented_shorthand_executes_dry_run(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(["--dry-run", "GW-004 错误是什么原因？"])
        self.assertEqual(0, status, errors.getvalue())
        self.assertIn("诊断摘要", output.getvalue())
        self.assertIn("GW-004", output.getvalue())

    def test_explicit_ask_command_executes(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["ask", "--dry-run", "RATE_LIMIT_RPS"])
        self.assertEqual(0, status)
        self.assertIn("RATE_LIMIT_RPS", output.getvalue())


if __name__ == "__main__":
    unittest.main()
