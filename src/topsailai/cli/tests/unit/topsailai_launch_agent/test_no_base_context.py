#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the --no-base-context option in topsailai_launch_agent.

``--no-base-context`` drops the shared base context sources configured under
``context._`` (and the legacy ``context._default``) so only the selected item's
own sources are injected. Base environment variables are still merged.
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


class TestResolveBaseContext(unittest.TestCase):
    """Verify the base-context resolver honors the ignore switch."""

    def test_returns_merged_base_sources_by_default(self):
        context_map = {"_default": ["legacy.md"], "_": ["base.md"], "memo": ["memo.md"]}

        self.assertEqual(
            launcher._resolve_base_context(context_map),
            ["legacy.md", "base.md"],
        )

    def test_returns_empty_list_when_base_is_ignored(self):
        context_map = {"_default": ["legacy.md"], "_": ["base.md"], "memo": ["memo.md"]}

        self.assertEqual(
            launcher._resolve_base_context(context_map, ignore_base_context=True),
            [],
        )

    def test_missing_base_keys_return_empty_list(self):
        self.assertEqual(launcher._resolve_base_context({"memo": ["memo.md"]}), [])


class TestFormatItemConfigBaseContext(unittest.TestCase):
    """Verify the selection summary reflects the effective context sources."""

    def setUp(self):
        self.context_map = {
            "_": ["base.md"],
            "memo": ["memo.md"],
        }
        self.env_map = {
            "_": {"SHARED": "base"},
            "memo": {"MEMO_ONLY": "x"},
        }

    def test_summary_lists_base_sources_by_default(self):
        output = launcher._format_item_config("memo", self.context_map, self.env_map)

        self.assertIn("[base] - base.md", output)
        self.assertIn("- memo.md", output)

    def test_summary_omits_base_sources_when_ignored(self):
        output = launcher._format_item_config(
            "memo", self.context_map, self.env_map, ignore_base_context=True
        )

        self.assertNotIn("base.md", output)
        self.assertIn("- memo.md", output)

    def test_summary_keeps_base_environment_when_context_is_ignored(self):
        output = launcher._format_item_config(
            "memo", self.context_map, self.env_map, ignore_base_context=True
        )

        self.assertIn("[base] SHARED=base", output)
        self.assertIn("[item] MEMO_ONLY=x", output)


class TestSelectContextItemForwardsFlag(unittest.TestCase):
    """Verify the interactive selector forwards the ignore switch."""

    def test_selector_forwards_ignore_base_context(self):
        context_map = {"_": ["base.md"], "default": [], "memo": []}
        env_map = {}
        captured = {}

        def fake_format(item_name, ctx_map, env_map_arg, ignore_base_context=False):
            captured["ignore_base_context"] = ignore_base_context
            return item_name

        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch.object(
            launcher, "_format_item_config", fake_format
        ), mock.patch("topsailai_launch_agent._timed_prompt", return_value="memo"):
            result = launcher._select_context_item(
                context_map, env_map, timeout=10.0, ignore_base_context=True
            )

        self.assertEqual(result, "memo")
        self.assertTrue(captured["ignore_base_context"])


class TestMainNoBaseContext(unittest.TestCase):
    """Verify main() context assembly with and without --no-base-context."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _write_settings(self, workspace, context, environment=None):
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write('ai_agent_driver: "test-driver"\n')
            f.write('workspace: "."\n')
            f.write("context:\n")
            for key, value in context.items():
                if not value:
                    f.write(f"  {key}: []\n")
                else:
                    f.write(f"  {key}:\n")
                    for path in value:
                        f.write(f'    - "{path}"\n')
            f.write("environment:\n")
            if environment:
                for key, value in environment.items():
                    if not value:
                        f.write(f"  {key}: {{}}\n")
                    else:
                        f.write(f"  {key}:\n")
                        for env_key, env_value in value.items():
                            f.write(f'    {env_key}: "{env_value}"\n')
            else:
                f.write("  _: {}\n")
        return settings_path

    def _run_main(self, argv):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ), mock.patch.object(launcher, "_driver_exists", return_value=True):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def test_base_and_item_sources_are_injected_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_": ["base.md"], "memo": ["memo.md"]},
                environment={"_": {"BASE_FLAG": "1"}},
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--item", "memo", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("base.md", stdout_output)
            self.assertIn("memo.md", stdout_output)
            self.assertIn("BASE_FLAG=1", stdout_output)
            self.assertNotIn("Base context ignored", stdout_output)

    def test_flag_injects_only_item_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_": ["base.md"], "memo": ["memo.md"]},
                environment={"_": {"BASE_FLAG": "1"}},
            )

            exit_code = self._run_main(
                [
                    "topsailai_launch_agent.py",
                    "--item",
                    "memo",
                    "--no-base-context",
                    "--dry-run",
                ]
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertNotIn("base.md", stdout_output)
            self.assertIn("memo.md", stdout_output)
            # Base environment variables are still merged.
            self.assertIn("BASE_FLAG=1", stdout_output)
            self.assertIn("Base context ignored", stdout_output)
            self.assertIn("selected item only; base ignored", stdout_output)

    def test_flag_ignores_legacy_default_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_default": ["legacy.md"], "memo": ["memo.md"]},
            )

            exit_code = self._run_main(
                [
                    "topsailai_launch_agent.py",
                    "--item",
                    "memo",
                    "--no-base-context",
                    "--dry-run",
                ]
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertNotIn("legacy.md", stdout_output)
            self.assertIn("memo.md", stdout_output)

    def test_flag_with_only_base_context_injects_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(tmpdir, context={"_": ["base.md"]})

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--no-base-context", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertNotIn("base.md", stdout_output)
            self.assertIn("(none)", stdout_output)
            self.assertIn("Base context ignored", stdout_output)

    def test_flag_does_not_change_driver_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_": ["base.md"], "memo": ["memo.md"]},
                environment={
                    "_": {"TOPSAILAI_AGENT_DRIVER": "base-driver"},
                    "memo": {"TOPSAILAI_AGENT_DRIVER": "memo-driver"},
                },
            )

            exit_code = self._run_main(
                [
                    "topsailai_launch_agent.py",
                    "--item",
                    "memo",
                    "--no-base-context",
                    "--dry-run",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("memo-driver", self._stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
