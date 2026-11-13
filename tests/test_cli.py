from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from multi_agent_file_analysis.cli import _normalize_argv, _print_response, main
from multi_agent_file_analysis.core import ReviewDecision, ToolName, WorkflowStatus
from multi_agent_file_analysis.graph import (
    CriticReport,
    DiagnosisState,
    ExplorationStep,
    render_partial_answer,
)
from multi_agent_file_analysis.qa import QAResponse


class CLITests(unittest.TestCase):
    def test_abstained_response_prints_last_critic_report(self) -> None:
        state = DiagnosisState(
            user_query="question",
            run_id="run-123",
            status=WorkflowStatus.ABSTAINED,
            critic_report=CriticReport(
                decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
                notes=["The inference needs another premise"],
                missing_evidence=["Definition of the affected scope"],
            ),
            exploration_attempts=3,
            reasoning_attempts=3,
            review_attempts=3,
            exploration_log=[
                ExplorationStep(
                    tool_name=ToolName.GREP,
                    path="/",
                    query="RuleName",
                    result_summary="2 exact hits",
                )
            ],
        )
        state.partial_answer = render_partial_answer(state)
        output = io.StringIO()

        with redirect_stdout(output):
            status = _print_response(QAResponse(state=state))

        rendered = output.getvalue()
        self.assertEqual(1, status)
        self.assertIn("阶段性回答（未通过最终审查）", rendered)
        self.assertIn("尚未解决的前提", rendered)
        self.assertIn("The inference needs another premise", rendered)
        self.assertIn("Definition of the affected scope", rendered)
        self.assertIn("Explorer 3 / Reasoner 3 / Critic 3", rendered)
        self.assertIn("grep / query='RuleName' -> 2 exact hits", rendered)
        self.assertIn("Run ID: run-123", rendered)

    def test_documented_shorthand_executes_dry_run(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(["--dry-run", "GW-004 错误是什么原因？"])
        self.assertEqual(0, status, errors.getvalue())
        self.assertIn("诊断摘要", output.getvalue())
        self.assertIn("GW-004", output.getvalue())
        self.assertIn("[metrics]", output.getvalue())
        self.assertIn("total=0", output.getvalue())
        self.assertIn("no-usage calls=0", output.getvalue())

    def test_explicit_ask_command_executes(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["ask", "--dry-run", "RATE_LIMIT_RPS"])
        self.assertEqual(0, status)
        self.assertIn("RATE_LIMIT_RPS", output.getvalue())

    def test_web_command_reports_missing_dependencies(self) -> None:
        from multi_agent_file_analysis.cli import _missing_web_dependency

        self.assertIsNone(_missing_web_dependency(lambda name: object()))
        self.assertEqual(
            "fastapi",
            _missing_web_dependency(
                lambda name: None if name == "fastapi" else object()
            ),
        )
        errors = io.StringIO()
        with (
            patch(
                "multi_agent_file_analysis.cli._missing_web_dependency",
                return_value="fastapi",
            ),
            redirect_stderr(errors),
        ):
            status = main(["web"])
        self.assertEqual(1, status)
        self.assertIn("fastapi", errors.getvalue())
        self.assertIn("pip install -r requirements.txt", errors.getvalue())

    def test_empty_entrypoint_opens_web_console(self) -> None:
        self.assertEqual(["web"], _normalize_argv([]))
        self.assertEqual(["web", "--port", "9000"], _normalize_argv(["web", "--port", "9000"]))

    def test_web_command_forwards_flags_to_server(self) -> None:
        with patch("multi_agent_file_analysis.web.serve") as serve:
            serve.return_value = 0
            status = main(
                [
                    "web",
                    "--port",
                    "9100",
                    "--host",
                    "0.0.0.0",
                    "--max-sessions",
                    "3",
                    "--idle-minutes",
                    "5",
                    "--knowledge-base",
                    "knowledge_base",
                    "--env-file",
                    ".env.example",
                ]
            )
        self.assertEqual(0, status)
        kwargs = serve.call_args.kwargs
        self.assertEqual(9100, kwargs["port"])
        self.assertEqual("0.0.0.0", kwargs["host"])
        self.assertEqual(3, kwargs["settings"].max_sessions)
        self.assertEqual(300.0, kwargs["settings"].idle_ttl_seconds)
        self.assertEqual(Path("knowledge_base"), kwargs["knowledge_root"])

    def test_chat_locks_selected_corpus_and_accepts_multiple_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            knowledge_base = base / "knowledge_base"
            dnd = knowledge_base / "dnd"
            openssh = knowledge_base / "openssh"
            dnd.mkdir(parents=True)
            openssh.mkdir(parents=True)
            (dnd / "rules.md").write_text(
                "# DND Rules\n\nDND_ALPHA is one.\n\nDND_BETA is two.\n",
                encoding="utf-8",
            )
            (openssh / "rules.md").write_text(
                "# SSH Rules\n\nSSH_SECRET must stay isolated.\n",
                encoding="utf-8",
            )
            (dnd / ".mafa-corpus.yaml").write_text(
                "id: dnd\nname: DND\n",
                encoding="utf-8",
            )
            (openssh / ".mafa-corpus.yaml").write_text(
                "id: openssh\nname: OpenSSH\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            errors = io.StringIO()
            answers = ["1", "DND_ALPHA", "DND_BETA", "/quit"]

            with (
                patch("builtins.input", side_effect=answers),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                status = main(
                    [
                        "chat",
                        "--dry-run",
                        "--knowledge-base",
                        str(knowledge_base),
                        "--env-file",
                        str(base / "missing.env"),
                    ]
                )

            self.assertEqual(0, status, errors.getvalue())
            rendered = output.getvalue()
            self.assertIn("已选择：DND", rendered)
            self.assertIn("DND_ALPHA", rendered)
            self.assertIn("DND_BETA", rendered)
            self.assertNotIn("SSH_SECRET", rendered)


if __name__ == "__main__":
    unittest.main()
