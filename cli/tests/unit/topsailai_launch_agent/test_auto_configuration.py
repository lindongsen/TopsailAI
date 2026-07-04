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


if __name__ == "__main__":
    unittest.main()
