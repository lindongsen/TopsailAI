#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the top-level self_environs section in topsailai_launch_agent.

The ``self_environs`` section in ``.topsailai/settings.yaml`` is a flat mapping
of environment-variable name to value. Its variables are loaded into the
launcher's OWN process environment (``os.environ``) at startup as initial
settings, and are NOT merged into the launched driver's environment.
"""

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


class TestApplySelfEnvirons(unittest.TestCase):
    """Unit tests for the _apply_self_environs helper."""

    def test_applies_flat_mapping_to_os_environ(self):
        settings = {"self_environs": {"MY_FLAG": "1", "MY_PATH": "/opt/x"}}
        with mock.patch.dict(os.environ, {}, clear=False):
            launcher._apply_self_environs(settings)
            self.assertEqual(os.environ.get("MY_FLAG"), "1")
            self.assertEqual(os.environ.get("MY_PATH"), "/opt/x")

    def test_missing_self_environs_is_noop(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            launcher._apply_self_environs({})
            self.assertNotIn("MY_FLAG", os.environ)

    def test_none_self_environs_is_noop(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            launcher._apply_self_environs({"self_environs": None})
            self.assertNotIn("MY_FLAG", os.environ)

    def test_non_mapping_prints_warning_and_ignores(self):
        stderr = StringIO()
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch(
            "sys.stderr", stderr
        ):
            launcher._apply_self_environs({"self_environs": ["bad"]})
            self.assertIn("must be a mapping", stderr.getvalue())
            self.assertNotIn("MY_FLAG", os.environ)

    def test_values_converted_to_string(self):
        settings = {"self_environs": {"NUM": 42, "FLAG": True}}
        with mock.patch.dict(os.environ, {}, clear=False):
            launcher._apply_self_environs(settings)
            self.assertEqual(os.environ.get("NUM"), "42")
            self.assertEqual(os.environ.get("FLAG"), "True")


class TestSelfEnvironsViaMain(unittest.TestCase):
    """End-to-end verification that main() loads self_environs at startup."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _write_settings(self, workspace, extra=""):
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write('ai_agent_driver: "test-driver"\n')
            f.write('workspace: "."\n')
            f.write("context:\n")
            f.write("  _: []\n")
            f.write("environment:\n")
            f.write("  _: {}\n")
            f.write(extra)
        return settings_path

    def test_main_loads_self_environs_into_os_environ(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                extra='self_environs:\n  MY_INITIAL: "loaded"\n',
            )

            sys.argv = ["topsailai_launch_agent.py", "--dry-run"]
            with mock.patch("sys.stdout", self._stdout), mock.patch(
                "sys.stderr", self._stderr
            ), mock.patch.object(launcher, "_driver_exists", return_value=True):
                with self.assertRaises(SystemExit) as cm:
                    launcher.main()

            self.assertEqual(cm.exception.code, 0)
            self.assertEqual(os.environ.get("MY_INITIAL"), "loaded")

    def test_main_self_environs_not_printed_as_driver_env(self):
        """self_environs must NOT appear in the merged driver env output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                extra='self_environs:\n  MY_INITIAL: "loaded"\n',
            )

            sys.argv = ["topsailai_launch_agent.py", "--dry-run"]
            with mock.patch("sys.stdout", self._stdout), mock.patch(
                "sys.stderr", self._stderr
            ), mock.patch.object(launcher, "_driver_exists", return_value=True):
                with self.assertRaises(SystemExit) as cm:
                    launcher.main()

            self.assertEqual(cm.exception.code, 0)
            stdout_output = self._stdout.getvalue()
            # The dry-run "Environment variables (merged from base and item)"
            # section only lists base/item env keys; self_environs is absent.
            self.assertNotIn("MY_INITIAL=loaded", stdout_output)


if __name__ == "__main__":
    unittest.main()
