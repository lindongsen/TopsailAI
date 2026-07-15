#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for context item auto-selection in topsailai_launch_agent."""

import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest import mock

# Ensure the CLI source is importable.
CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

import topsailai_launch_agent as launcher


class TestContextSelection(unittest.TestCase):
    """Verify auto-selection behavior when --item is omitted."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _write_settings(
        self,
        workspace,
        context=None,
        environment=None,
        driver="test-driver",
    ):
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(f'ai_agent_driver: "{driver}"\n')
            f.write('workspace: "."\n')
            f.write('context:\n')
            if context is None:
                f.write('  _default: []\n')
            else:
                for key, value in context.items():
                    if not value:
                        f.write(f'  {key}: []\n')
                    else:
                        f.write(f'  {key}:\n')
                        for path in value:
                            f.write(f'    - "{path}"\n')
            f.write('environment:\n')
            if environment is None:
                f.write('  _default: {}\n')
            else:
                for key, value in environment.items():
                    if not value:
                        f.write(f'  {key}: {{}}\n')
                    else:
                        f.write(f'  {key}:\n')
                        for env_key, env_value in value.items():
                            f.write(f'    {env_key}: "{env_value}"\n')
        return settings_path

    def _run_main(self, argv):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def _run_main_interactive(self, argv, inputs):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ), mock.patch("sys.stdin.isatty", return_value=True), mock.patch(
            "builtins.input", side_effect=inputs
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def test_only_default_item_uses_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_default": ["project.yaml"]},
                environment={"_default": {"TOPSAILAI_INTERACTIVE_MODE": "1"}},
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            stderr_output = self._stderr.getvalue()
            self.assertNotIn("Multiple context items", stderr_output)
            stdout_output = self._stdout.getvalue()
            self.assertIn("test-driver", stdout_output)

    def test_single_non_default_item_uses_it_automatically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={
                    "_default": ["project.yaml"],
                    "memo": ["memo.yaml"],
                },
                environment={
                    "_default": {"TOPSAILAI_INTERACTIVE_MODE": "1"},
                    "memo": {"TOPSAILAI_AGENT_DRIVER": "memo-driver"},
                },
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            stderr_output = self._stderr.getvalue()
            self.assertNotIn("Multiple context items", stderr_output)
            stdout_output = self._stdout.getvalue()
            self.assertIn("memo-driver", stdout_output)
            self.assertNotIn("test-driver", stdout_output)

    def test_multiple_items_prompts_and_selects_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={
                    "_default": ["project.yaml"],
                    "default": ["default.yaml"],
                    "memo": ["memo.yaml"],
                },
                environment={
                    "_default": {"TOPSAILAI_INTERACTIVE_MODE": "1"},
                    "default": {"TOPSAILAI_AGENT_DRIVER": "default-driver"},
                    "memo": {"TOPSAILAI_AGENT_DRIVER": "memo-driver"},
                },
            )

            # Empty answer accepts the default item "default".
            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"],
                inputs=[""],
            )

            self.assertEqual(exit_code, 0)
            stderr_output = self._stderr.getvalue()
            self.assertIn("Multiple context items", stderr_output)
            self.assertIn("default", stderr_output)
            self.assertIn("memo", stderr_output)
            self.assertIn("project.yaml", stderr_output)
            stdout_output = self._stdout.getvalue()
            self.assertIn("default-driver", stdout_output)

    def test_multiple_items_prompts_and_selects_by_number(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={
                    "_default": ["project.yaml"],
                    "default": ["default.yaml"],
                    "memo": ["memo.yaml"],
                },
                environment={
                    "_default": {"TOPSAILAI_INTERACTIVE_MODE": "1"},
                    "default": {"TOPSAILAI_AGENT_DRIVER": "default-driver"},
                    "memo": {"TOPSAILAI_AGENT_DRIVER": "memo-driver"},
                },
            )

            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"],
                inputs=["2"],
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("memo-driver", stdout_output)
            self.assertNotIn("default-driver", stdout_output)

    def test_multiple_items_prompts_and_selects_by_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={
                    "_default": ["project.yaml"],
                    "default": ["default.yaml"],
                    "memo": ["memo.yaml"],
                },
                environment={
                    "_default": {"TOPSAILAI_INTERACTIVE_MODE": "1"},
                    "default": {"TOPSAILAI_AGENT_DRIVER": "default-driver"},
                    "memo": {"TOPSAILAI_AGENT_DRIVER": "memo-driver"},
                },
            )

            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"],
                inputs=["memo"],
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("memo-driver", stdout_output)

    def test_multiple_items_without_default_in_non_tty_exits_with_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={
                    "_default": ["project.yaml"],
                    "memo": ["memo.yaml"],
                    "test": ["test.yaml"],
                },
                environment={
                    "_default": {"TOPSAILAI_INTERACTIVE_MODE": "1"},
                    "memo": {"TOPSAILAI_AGENT_DRIVER": "memo-driver"},
                    "test": {"TOPSAILAI_AGENT_DRIVER": "test-driver"},
                },
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 1)
            stderr_output = self._stderr.getvalue()
            self.assertIn("Multiple context items", stderr_output)
            self.assertIn("Use --item", stderr_output)

    def test_multiple_items_with_default_in_non_tty_uses_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={
                    "_default": ["project.yaml"],
                    "default": ["default.yaml"],
                    "memo": ["memo.yaml"],
                },
                environment={
                    "_default": {"TOPSAILAI_INTERACTIVE_MODE": "1"},
                    "default": {"TOPSAILAI_AGENT_DRIVER": "default-driver"},
                    "memo": {"TOPSAILAI_AGENT_DRIVER": "memo-driver"},
                },
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("default-driver", stdout_output)

    def test_empty_context_in_tty_prompts_for_setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = self._write_settings(
                tmpdir,
                context={},
                environment={},
            )
            project_path = os.path.join(tmpdir, "project.yaml")
            with open(project_path, "w", encoding="utf-8") as f:
                f.write("# dummy project file\n")

            inputs = [
                "y",              # Configure context now?
                "",               # Accept default for _default context prompt
                "project.yaml",   # _default context file
                "",               # Finish context files
                "n",              # Add another item?
            ]

            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"],
                inputs,
            )

            self.assertEqual(exit_code, 0)
            stderr_output = self._stderr.getvalue()
            self.assertIn("Context Setup", stderr_output)
            settings = launcher.load_yaml(settings_path)
            self.assertEqual(settings["context"]["_default"], ["project.yaml"])

    def test_empty_context_in_non_tty_warns_and_continues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={},
                environment={},
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            stderr_output = self._stderr.getvalue()
            self.assertIn("context is empty", stderr_output)

    def test_format_item_config_shows_merged_default_and_item_values(self):
        context_map = {
            "_default": ["project.yaml"],
            "memo": ["memo.yaml"],
        }
        env_map = {
            "_default": {"TOPSAILAI_INTERACTIVE_MODE": "1", "SHARED": "default"},
            "memo": {"SHARED": "memo", "MEMO_ONLY": "x"},
        }
        output = launcher._format_item_config("memo", context_map, env_map)

        self.assertIn("project.yaml", output)
        self.assertIn("memo.yaml", output)
        self.assertIn("TOPSAILAI_INTERACTIVE_MODE", output)
        self.assertIn("SHARED", output)
        self.assertIn("MEMO_ONLY", output)
        # The merged value of SHARED should come from the item.
        self.assertIn("[item] SHARED=memo", output)
        self.assertIn("[default] TOPSAILAI_INTERACTIVE_MODE=1", output)


if __name__ == "__main__":
    unittest.main()
