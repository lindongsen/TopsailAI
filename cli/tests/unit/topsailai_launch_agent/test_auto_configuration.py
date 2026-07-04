#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for auto-configuration when .topsailai/settings.yaml is missing."""

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


class TestAutoConfiguration(unittest.TestCase):
    """Verify behavior when .topsailai/settings.yaml does not exist."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _run_main(self, argv):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def test_missing_settings_creates_default_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            self.assertFalse(os.path.isfile(settings_path))

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.isfile(settings_path))

            settings = launcher.load_yaml(settings_path)
            self.assertEqual(settings, launcher.DEFAULT_CONFIG)

    def test_missing_settings_prompts_for_default_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            stderr_output = self._stderr.getvalue()
            self.assertIn("context._default", stderr_output)
            self.assertIn("Creating a default configuration file", stderr_output)

    def test_existing_settings_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_dir = os.path.join(tmpdir, ".topsailai")
            os.makedirs(settings_dir, exist_ok=True)
            settings_path = os.path.join(settings_dir, "settings.yaml")
            with open(settings_path, "w", encoding="utf-8") as f:
                f.write("ai_agent_driver: existing-driver\n")
                f.write('workspace: "."\n')
                f.write("context:\n")
                f.write("  _default: []\n")
                f.write("  default: []\n")
                f.write("environment:\n")
                f.write("  _default: {}\n")
                f.write("  default: {}\n")

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            settings = launcher.load_yaml(settings_path)
            self.assertEqual(settings["ai_agent_driver"], "existing-driver")


    def _run_main_interactive(self, argv, inputs):
        """Run main() with mocked TTY stdin and a sequence of input() responses."""
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ), mock.patch("sys.stdin.isatty", return_value=True), mock.patch(
            "builtins.input", side_effect=inputs
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def test_interactive_setup_creates_config_with_user_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            # Create a dummy context file so reading it during dry-run succeeds.
            project_path = os.path.join(tmpdir, "project.yaml")
            with open(project_path, "w", encoding="utf-8") as f:
                f.write("# dummy project file\n")

            inputs = [
                "custom-driver",       # AI agent driver command
                ".",                   # Working directory
                "y",                   # Add context files?
                "project.yaml",        # Context file path
                "",                    # Finish context files
                "y",                   # Add environment variables?
                "TOPSAILAI_API_KEY=secret",  # Env var
                "",                    # Finish env vars
            ]

            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"], inputs
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.isfile(settings_path))

            settings = launcher.load_yaml(settings_path)
            self.assertEqual(settings["ai_agent_driver"], "custom-driver")
            self.assertEqual(settings["workspace"], ".")
            self.assertEqual(settings["context"]["_default"], ["project.yaml"])
            self.assertEqual(
                settings["environment"]["_default"],
                {"TOPSAILAI_INTERACTIVE_MODE": "1", "TOPSAILAI_API_KEY": "secret"},
            )

            stderr_output = self._stderr.getvalue()
            self.assertIn("Interactive Setup", stderr_output)
            self.assertIn("Configuration saved to", stderr_output)

    def test_interactive_setup_uses_defaults_when_user_presses_enter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            # Empty answers accept defaults; "n" skips optional sections.
            inputs = ["", "", "n", "n"]

            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"], inputs
            )

            self.assertEqual(exit_code, 0)
            settings = launcher.load_yaml(settings_path)
            self.assertEqual(
                settings["ai_agent_driver"], launcher.DEFAULT_CONFIG["ai_agent_driver"]
            )
            self.assertEqual(settings["workspace"], ".")
            self.assertEqual(settings["context"]["_default"], [])
            self.assertEqual(
                settings["environment"]["_default"],
                {"TOPSAILAI_INTERACTIVE_MODE": "1"},
            )

    def test_interactive_setup_skips_invalid_env_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            inputs = [
                "custom-driver",
                ".",
                "n",                   # No context files
                "y",                   # Add environment variables
                "INVALID_LINE",        # Should be ignored with a warning
                "KEY=VALUE",           # Valid env var
                "",                    # Finish env vars
            ]

            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"], inputs
            )

            self.assertEqual(exit_code, 0)
            settings = launcher.load_yaml(settings_path)
            self.assertEqual(
                settings["environment"]["_default"],
                {"TOPSAILAI_INTERACTIVE_MODE": "1", "KEY": "VALUE"},
            )
            self.assertIn(
                "Ignoring invalid env line",
                self._stderr.getvalue(),
            )

    def test_generated_config_includes_comments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            with open(settings_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("# AI Agent TopsailAI-Launcher Configuration", content)
            self.assertIn("# Resolution order", content)
            self.assertIn("TOPSAILAI_INTERACTIVE_MODE", content)

    def test_interactive_generated_config_includes_comments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            inputs = ["", "", "n", "n"]
            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"], inputs
            )

            self.assertEqual(exit_code, 0)
            with open(settings_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("# AI Agent TopsailAI-Launcher Configuration", content)
            self.assertIn("# TOPSAILAI_INTERACTIVE_MODE enables", content)
            self.assertIn("TOPSAILAI_INTERACTIVE_MODE: \"1\"", content)


if __name__ == "__main__":
    unittest.main()
