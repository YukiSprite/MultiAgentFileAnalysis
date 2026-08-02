from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multi_agent_file_analysis.app import ApplicationFactory
from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import RunMode
from multi_agent_file_analysis.environment import load_project_environment


class EnvironmentLoadingTests(unittest.TestCase):
    def test_defaults_to_env_in_current_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("OPENAI_MODEL=cwd-model\n", encoding="utf-8")

            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "multi_agent_file_analysis.environment.Path.cwd",
                    return_value=Path(tmp),
                ),
            ):
                loaded = load_project_environment()

                self.assertEqual(env_file.resolve(), loaded)
                self.assertEqual("cwd-model", os.environ["OPENAI_MODEL"])

    def test_loads_values_from_explicit_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "OPENAI_API_KEY=from-file\nOPENAI_MODEL=test-model\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                loaded = load_project_environment(env_file)

                self.assertEqual(env_file.resolve(), loaded)
                self.assertEqual("from-file", os.environ["OPENAI_API_KEY"])
                self.assertEqual("test-model", os.environ["OPENAI_MODEL"])

    def test_existing_process_environment_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "OPENAI_API_KEY=from-file\nOPENAI_MODEL=file-model\n",
                encoding="utf-8",
            )

            initial = {
                "OPENAI_API_KEY": "from-shell",
                "OPENAI_MODEL": "shell-model",
            }
            with patch.dict(os.environ, initial, clear=True):
                load_project_environment(env_file)

                self.assertEqual("from-shell", os.environ["OPENAI_API_KEY"])
                self.assertEqual("shell-model", os.environ["OPENAI_MODEL"])

    def test_missing_env_file_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / ".env"
            self.assertIsNone(load_project_environment(missing))

    def test_application_factory_loads_configured_env_file(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("OPENAI_API_KEY=factory-test\n", encoding="utf-8")
            config = AppConfig(
                page_index_path=project_root / "configs/page_index.example.yaml",
                knowledge_base_root=project_root / "knowledge_base",
                run_mode=RunMode.DRY_RUN,
                env_file_path=env_file,
            )

            with patch.dict(os.environ, {}, clear=True):
                ApplicationFactory().build(config)
                self.assertEqual("factory-test", os.environ["OPENAI_API_KEY"])


if __name__ == "__main__":
    unittest.main()
