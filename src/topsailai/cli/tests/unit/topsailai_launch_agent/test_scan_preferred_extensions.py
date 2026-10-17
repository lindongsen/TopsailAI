#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the settings.yaml scan controls in topsailai_launch_agent.

Covers the top-level ``scan`` section:

- ``scan.include_files`` enables listing files as well as folders.
- ``scan.preferred_extensions`` keeps selected files in folders-only mode,
  matched case-insensitively.

author: DawsonLin
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


class TestNormalizePreferredExtensions(unittest.TestCase):
    """Verify normalization of the preferred-extension list."""

    def test_none_and_empty_return_empty(self):
        self.assertEqual(launcher._normalize_preferred_extensions(None), [])
        self.assertEqual(launcher._normalize_preferred_extensions([]), [])

    def test_leading_dot_is_added_and_lowercased(self):
        self.assertEqual(
            launcher._normalize_preferred_extensions(["PY", ".Md"]),
            [".py", ".md"],
        )

    def test_duplicates_and_blanks_are_dropped(self):
        self.assertEqual(
            launcher._normalize_preferred_extensions(["py", ".py", "", "  ", "md"]),
            [".py", ".md"],
        )

    def test_comma_separated_string_is_accepted(self):
        self.assertEqual(
            launcher._normalize_preferred_extensions("py, .md ,txt"),
            [".py", ".md", ".txt"],
        )

    def test_invalid_type_warns_and_returns_empty(self):
        stderr = StringIO()
        with mock.patch.object(sys, "stderr", stderr):
            result = launcher._normalize_preferred_extensions(123)
        self.assertEqual(result, [])
        self.assertIn("preferred_extensions", stderr.getvalue())


class TestResolveScanSettings(unittest.TestCase):
    """Verify parsing of the top-level ``scan`` section."""

    def test_absent_section_returns_none_and_empty(self):
        self.assertEqual(launcher._resolve_scan_settings({}), (None, []))

    def test_include_files_true_is_parsed(self):
        include, preferred = launcher._resolve_scan_settings(
            {"scan": {"include_files": True}}
        )
        self.assertTrue(include)
        self.assertEqual(preferred, [])

    def test_include_files_false_is_parsed(self):
        include, _ = launcher._resolve_scan_settings({"scan": {"include_files": False}})
        self.assertFalse(include)

    def test_preferred_extensions_are_normalized(self):
        _, preferred = launcher._resolve_scan_settings(
            {"scan": {"preferred_extensions": ["PY", "md"]}}
        )
        self.assertEqual(preferred, [".py", ".md"])

    def test_non_mapping_scan_warns_and_is_ignored(self):
        stderr = StringIO()
        with mock.patch.object(sys, "stderr", stderr):
            result = launcher._resolve_scan_settings({"scan": ["bad"]})
        self.assertEqual(result, (None, []))
        self.assertIn("'scan' must be a mapping", stderr.getvalue())

    def test_non_boolean_include_files_warns_and_is_ignored(self):
        stderr = StringIO()
        with mock.patch.object(sys, "stderr", stderr):
            include, _ = launcher._resolve_scan_settings(
                {"scan": {"include_files": "yes"}}
            )
        self.assertIsNone(include)
        self.assertIn("scan.include_files", stderr.getvalue())


class TestResolveScanIncludeFilesSettings(unittest.TestCase):
    """Verify settings.yaml participates in the include-files priority chain."""

    ENV_KEY = "TOPSAILAI_SCAN_INCLUDE_FILES"

    def setUp(self):
        self._saved = os.environ.pop(self.ENV_KEY, None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(self.ENV_KEY, None)
        else:
            os.environ[self.ENV_KEY] = self._saved

    def test_settings_enables_files_when_env_unset(self):
        self.assertTrue(
            launcher._resolve_scan_include_files(None, {}, settings_flag=True)
        )

    def test_settings_false_keeps_folders_only(self):
        self.assertFalse(
            launcher._resolve_scan_include_files(None, {}, settings_flag=False)
        )

    def test_cli_flag_wins_over_settings(self):
        self.assertFalse(
            launcher._resolve_scan_include_files(False, {}, settings_flag=True)
        )
        self.assertTrue(
            launcher._resolve_scan_include_files(True, {}, settings_flag=False)
        )

    def test_env_var_wins_over_settings(self):
        self.assertTrue(
            launcher._resolve_scan_include_files(
                None, {self.ENV_KEY: "true"}, settings_flag=False
            )
        )
        self.assertFalse(
            launcher._resolve_scan_include_files(
                None, {self.ENV_KEY: "false"}, settings_flag=True
            )
        )

    def test_absent_settings_falls_back_to_folders_only(self):
        self.assertFalse(launcher._resolve_scan_include_files(None, {}))


class TestPreferredExtensionsScan(unittest.TestCase):
    """Verify preferred extensions keep selected files in folders-only mode."""

    def _make_tree(self, tmpdir):
        nested = os.path.join(tmpdir, "src", "pkg")
        os.makedirs(nested)
        os.makedirs(os.path.join(tmpdir, "docs"))
        for path, content in (
            (os.path.join(tmpdir, "README.md"), "readme\n"),
            (os.path.join(tmpdir, "notes.txt"), "notes\n"),
            (os.path.join(tmpdir, "src", "main.py"), "print('hi')\n"),
            (os.path.join(nested, "leaf.PY"), "leaf\n"),
            (os.path.join(tmpdir, "docs", "guide.md"), "guide\n"),
        ):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
        return tmpdir

    def test_default_still_lists_folders_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(tmpdir)
            self.assertIn("src", tree)
            self.assertNotIn("main.py", tree)
            self.assertNotIn("README.md", tree)

    def test_preferred_extension_keeps_matching_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(
                tmpdir, preferred_extensions=[".py"]
            )
            self.assertIn("src", tree)
            self.assertIn("main.py", tree)
            self.assertIn("leaf.PY", tree)
            self.assertNotIn("README.md", tree)
            self.assertNotIn("notes.txt", tree)

    def test_preferred_extension_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(
                tmpdir, preferred_extensions=["MD"]
            )
            self.assertIn("README.md", tree)
            self.assertIn("guide.md", tree)
            self.assertNotIn("main.py", tree)

    def test_include_files_overrides_preferred_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(
                tmpdir, include_files=True, preferred_extensions=[".py"]
            )
            self.assertIn("main.py", tree)
            self.assertIn("README.md", tree)
            self.assertIn("notes.txt", tree)

    def test_preferred_extension_respects_gitignore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("secret.py\n")
            with open(os.path.join(tmpdir, "secret.py"), "w", encoding="utf-8") as f:
                f.write("SECRET\n")
            with open(os.path.join(tmpdir, "keep.py"), "w", encoding="utf-8") as f:
                f.write("keep\n")

            tree = launcher._scan_workspace_files(
                tmpdir, preferred_extensions=[".py"]
            )
            self.assertIn("keep.py", tree)
            self.assertNotIn("secret.py", tree)

    def test_preferred_extension_respects_exclusions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "keep.py"), "w", encoding="utf-8") as f:
                f.write("keep\n")
            with open(os.path.join(tmpdir, "drop.py"), "w", encoding="utf-8") as f:
                f.write("drop\n")

            tree = launcher._scan_workspace_files(
                tmpdir, exclude_names=["drop.py"], preferred_extensions=[".py"]
            )
            self.assertIn("keep.py", tree)
            self.assertNotIn("drop.py", tree)


class TestScanFolderPreferredExtensions(unittest.TestCase):
    """Verify _scan_folder forwards preferred_extensions."""

    def test_scan_folder_forwards_preferred_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            captured = {}

            def fake_scan(
                workspace,
                project_folder=None,
                exclude_names=None,
                include_files=None,
                preferred_extensions=None,
            ):
                captured["preferred_extensions"] = preferred_extensions
                return "tree"

            original = launcher._scan_workspace_files
            launcher._scan_workspace_files = fake_scan
            try:
                launcher._scan_folder(tmpdir, preferred_extensions=[".py"])
            finally:
                launcher._scan_workspace_files = original
            self.assertEqual(captured["preferred_extensions"], [".py"])


class TestMainScanSettings(unittest.TestCase):
    """Verify main() honors the scan section for --scan and the context tree."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._saved_env = os.environ.pop("TOPSAILAI_SCAN_INCLUDE_FILES", None)

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv
        if self._saved_env is None:
            os.environ.pop("TOPSAILAI_SCAN_INCLUDE_FILES", None)
        else:
            os.environ["TOPSAILAI_SCAN_INCLUDE_FILES"] = self._saved_env

    def _write_settings(self, workspace, scan_block):
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write('ai_agent_driver: "test-driver"\n')
            f.write('workspace: "."\n')
            f.write(scan_block)
            f.write("context:\n")
            f.write("  _: []\n")
            f.write("environment:\n")
            f.write("  _: {}\n")
        return settings_path

    def _make_tree(self, tmpdir):
        os.makedirs(os.path.join(tmpdir, "src"))
        with open(os.path.join(tmpdir, "src", "main.py"), "w", encoding="utf-8") as f:
            f.write("print('hi')\n")
        with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as f:
            f.write("readme\n")
        return tmpdir

    def test_scan_command_uses_preferred_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            self._write_settings(
                tmpdir,
                "scan:\n  include_files: false\n  preferred_extensions: ['.py']\n",
            )
            os.chdir(tmpdir)
            sys.argv = ["topsailai_launch_agent.py", "--scan", tmpdir]
            stdout = StringIO()
            with mock.patch("sys.stdout", stdout):
                launcher.main()
            output = stdout.getvalue()
            self.assertIn("main.py", output)
            self.assertNotIn("README.md", output)

    def test_scan_command_uses_include_files_setting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            self._write_settings(tmpdir, "scan:\n  include_files: true\n")
            os.chdir(tmpdir)
            sys.argv = ["topsailai_launch_agent.py", "--scan", tmpdir]
            stdout = StringIO()
            with mock.patch("sys.stdout", stdout):
                launcher.main()
            output = stdout.getvalue()
            self.assertIn("main.py", output)
            self.assertIn("README.md", output)

    def test_context_tree_uses_preferred_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            self._write_settings(
                tmpdir,
                "scan:\n  include_files: false\n  preferred_extensions: ['md']\n",
            )
            os.chdir(tmpdir)
            captured = {}

            def fake_scan(
                workspace,
                project_folder=None,
                exclude_names=None,
                include_files=None,
                preferred_extensions=None,
            ):
                captured["include_files"] = include_files
                captured["preferred_extensions"] = preferred_extensions
                return "fake-tree"

            sys.argv = ["topsailai_launch_agent.py", "--dry-run"]
            with mock.patch.object(launcher, "_scan_workspace_files", fake_scan):
                with self.assertRaises(SystemExit) as ctx:
                    launcher.main()
            self.assertEqual(ctx.exception.code, 0)
            self.assertFalse(captured["include_files"])
            self.assertEqual(captured["preferred_extensions"], [".md"])


if __name__ == "__main__":
    unittest.main()
