#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for behavior when .topsailai/settings.yaml is missing."""

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

    def test_missing_settings_does_not_create_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            self.assertFalse(os.path.isfile(settings_path))

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(os.path.isfile(settings_path))

    def test_missing_settings_uses_default_agent_driver(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn(
                launcher.DEFAULT_CONFIG["ai_agent_driver"], stdout_output
            )

    def test_missing_settings_warns_and_continues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            stderr_output = self._stderr.getvalue()
            self.assertIn("Settings file not found", stderr_output)
            self.assertIn("Using default configuration", stderr_output)
            self.assertNotIn("Interactive Setup", stderr_output)
            self.assertNotIn("Configuration saved to", stderr_output)

    def test_missing_settings_in_tty_chooses_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            # Empty answer accepts the default "r" (run with default driver).
            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"],
                inputs=[""],
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(os.path.isfile(settings_path))
            stderr_output = self._stderr.getvalue()
            self.assertIn("Choose how to proceed", stderr_output)
            self.assertNotIn("Interactive Setup", stderr_output)
            self.assertNotIn("Configuration saved to", stderr_output)
            stdout_output = self._stdout.getvalue()
            self.assertIn(
                launcher.DEFAULT_CONFIG["ai_agent_driver"], stdout_output
            )

    def test_missing_settings_in_tty_chooses_setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            # "s" chooses setup, then accept all defaults and skip extras.
            inputs = [
                "s",  # choose guided setup
                "",   # accept default driver
                "",   # accept default workspace
                "n",  # do not add context files
                "n",  # do not add extra environment variables
            ]

            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--dry-run"],
                inputs=inputs,
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.isfile(settings_path))
            stderr_output = self._stderr.getvalue()
            self.assertIn("Interactive Setup", stderr_output)
            self.assertIn("Configuration saved to", stderr_output)
            settings = launcher.load_yaml(settings_path)
            self.assertEqual(
                settings["ai_agent_driver"],
                launcher.DEFAULT_CONFIG["ai_agent_driver"],
            )

    def test_missing_settings_setup_flag_forces_setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            # --setup should launch guided setup even though TTY is not mocked.
            inputs = [
                "",   # accept default driver
                "",   # accept default workspace
                "n",  # do not add context files
                "n",  # do not add extra environment variables
            ]

            exit_code = self._run_main_interactive(
                ["topsailai_launch_agent.py", "--setup", "--dry-run"],
                inputs=inputs,
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.isfile(settings_path))
            stderr_output = self._stderr.getvalue()
            self.assertIn("--setup requested", stderr_output)
            self.assertIn("Interactive Setup", stderr_output)
            self.assertIn("Configuration saved to", stderr_output)

    def test_missing_settings_with_explicit_item_uses_default_config_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            exit_code = self._run_main(
                [
                    "topsailai_launch_agent.py",
                    "--item",
                    "memo",
                    "--dry-run",
                ]
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("topsailai_agent_chats", stdout_output)

    def test_missing_settings_driver_override_still_works(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            exit_code = self._run_main(
                [
                    "topsailai_launch_agent.py",
                    "--driver",
                    "override-driver",
                    "--dry-run",
                ]
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("override-driver", stdout_output)
            self.assertNotIn(
                launcher.DEFAULT_CONFIG["ai_agent_driver"], stdout_output
            )

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


if __name__ == "__main__":
    unittest.main()
