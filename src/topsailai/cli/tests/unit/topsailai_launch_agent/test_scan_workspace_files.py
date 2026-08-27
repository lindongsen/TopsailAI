#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for workspace file scanning in topsailai_launch_agent."""

import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

# Ensure the CLI source is importable.
CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

import topsailai_launch_agent as launcher


class TestScanWorkspaceFiles(unittest.TestCase):
    """Verify _scan_workspace_files behavior, including symlink handling."""

    def test_symlink_to_directory_is_not_recursed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "workspace")
            os.makedirs(workspace)

            real_dir = os.path.join(tmpdir, "real_dir")
            os.makedirs(real_dir)
            with open(os.path.join(real_dir, "inside.txt"), "w", encoding="utf-8") as f:
                f.write("inside\n")

            link_dir = os.path.join(workspace, "link_dir")
            os.symlink(real_dir, link_dir)

            tree = launcher._scan_workspace_files(workspace)
            self.assertIn("link_dir", tree)
            self.assertNotIn("inside.txt", tree)

    def test_symlink_to_file_is_listed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real_file = os.path.join(tmpdir, "real_file.txt")
            with open(real_file, "w", encoding="utf-8") as f:
                f.write("content\n")

            link_file = os.path.join(tmpdir, "link_file.txt")
            os.symlink(real_file, link_file)

            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertIn("link_file.txt", tree)
            self.assertIn("real_file.txt", tree)

    def test_regular_directory_is_recursed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub_dir = os.path.join(tmpdir, "sub")
            os.makedirs(sub_dir)
            with open(os.path.join(sub_dir, "nested.txt"), "w", encoding="utf-8") as f:
                f.write("nested\n")

            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertIn("sub", tree)
            self.assertIn("nested.txt", tree)

    def test_project_folder_child_restricts_scan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "workspace")
            project = os.path.join(workspace, "project-a")
            other = os.path.join(workspace, "project-b")
            os.makedirs(project)
            os.makedirs(other)
            with open(os.path.join(project, "in-project.txt"), "w", encoding="utf-8") as f:
                f.write("a\n")
            with open(os.path.join(other, "in-other.txt"), "w", encoding="utf-8") as f:
                f.write("b\n")

            tree = launcher._scan_workspace_files(workspace, project, include_files=True)
            self.assertIn("project-a", tree)
            self.assertIn("in-project.txt", tree)
            self.assertNotIn("project-b", tree)
            self.assertNotIn("in-other.txt", tree)
            self.assertIn("> " + project, tree)

    def test_project_folder_equal_to_workspace_scans_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, "sub")
            os.makedirs(sub)
            with open(os.path.join(sub, "nested.txt"), "w", encoding="utf-8") as f:
                f.write("nested\n")

            tree = launcher._scan_workspace_files(tmpdir, tmpdir, include_files=True)
            self.assertIn("sub", tree)
            self.assertIn("nested.txt", tree)
            self.assertIn("> " + tmpdir, tree)

    def test_project_folder_outside_workspace_scans_both(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "workspace")
            outside = os.path.join(tmpdir, "outside")
            os.makedirs(workspace)
            os.makedirs(outside)
            with open(os.path.join(workspace, "inside.txt"), "w", encoding="utf-8") as f:
                f.write("inside\n")
            with open(os.path.join(outside, "outside.txt"), "w", encoding="utf-8") as f:
                f.write("outside\n")

            tree = launcher._scan_workspace_files(workspace, outside, include_files=True)
            self.assertIn("inside.txt", tree)
            self.assertIn("outside.txt", tree)
            self.assertIn("> " + workspace, tree)
            self.assertIn("> " + outside, tree)

    def test_project_folder_none_scans_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, "sub")
            os.makedirs(sub)
            with open(os.path.join(sub, "nested.txt"), "w", encoding="utf-8") as f:
                f.write("nested\n")

            tree = launcher._scan_workspace_files(tmpdir, None, include_files=True)
            self.assertIn("sub", tree)
            self.assertIn("nested.txt", tree)

    def test_nested_gitignore_excludes_files_and_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deploy = os.path.join(tmpdir, "deploy")
            os.makedirs(deploy)
            with open(os.path.join(deploy, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("# protect secrets\nsecret.env\ncache_dir\npgdata/\n")
            with open(os.path.join(deploy, "keep.txt"), "w", encoding="utf-8") as f:
                f.write("keep\n")
            with open(os.path.join(deploy, "secret.env"), "w", encoding="utf-8") as f:
                f.write("SECRET\n")
            os.makedirs(os.path.join(deploy, "cache_dir"))
            os.makedirs(os.path.join(deploy, "pgdata"))

            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertIn("deploy", tree)
            self.assertIn("keep.txt", tree)
            self.assertNotIn("secret.env", tree)
            self.assertNotIn("cache_dir", tree)
            self.assertNotIn("pgdata", tree)

    def test_nested_gitignore_does_not_leak_to_parent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deploy = os.path.join(tmpdir, "deploy")
            os.makedirs(deploy)
            with open(os.path.join(deploy, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("secret.env\n")
            with open(os.path.join(deploy, "secret.env"), "w", encoding="utf-8") as f:
                f.write("SECRET\n")
            # Same-named file at the workspace root must NOT be ignored.
            with open(os.path.join(tmpdir, "secret.env"), "w", encoding="utf-8") as f:
                f.write("ROOT SECRET\n")

            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertEqual(tree.count("secret.env"), 1)

    def test_root_gitignore_still_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("build.out\n")
            with open(os.path.join(tmpdir, "build.out"), "w", encoding="utf-8") as f:
                f.write("artifact\n")
            with open(os.path.join(tmpdir, "keep.txt"), "w", encoding="utf-8") as f:
                f.write("keep\n")

            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertNotIn("build.out", tree)
            self.assertIn("keep.txt", tree)

    def test_nested_gitignore_negation_unignores_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deploy = os.path.join(tmpdir, "deploy")
            os.makedirs(deploy)
            with open(os.path.join(deploy, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("*.log\n!important.log\n")
            with open(os.path.join(deploy, "debug.log"), "w", encoding="utf-8") as f:
                f.write("debug\n")
            with open(os.path.join(deploy, "important.log"), "w", encoding="utf-8") as f:
                f.write("important\n")

            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertNotIn("debug.log", tree)
            self.assertIn("important.log", tree)

    def test_hidden_files_and_directories_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            visible_dir = os.path.join(tmpdir, "visible")
            hidden_dir = os.path.join(tmpdir, ".hidden")
            os.makedirs(visible_dir)
            os.makedirs(hidden_dir)
            with open(os.path.join(visible_dir, "visible.txt"), "w", encoding="utf-8") as f:
                f.write("visible\n")
            with open(os.path.join(hidden_dir, "hidden.txt"), "w", encoding="utf-8") as f:
                f.write("hidden\n")
            with open(os.path.join(tmpdir, ".hidden-file"), "w", encoding="utf-8") as f:
                f.write("hidden\n")

            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertIn("visible", tree)
            self.assertIn("visible.txt", tree)
            self.assertNotIn(".hidden", tree)
            self.assertNotIn("hidden.txt", tree)
            self.assertNotIn(".hidden-file", tree)


class TestScanFolder(unittest.TestCase):
    """Verify the --scan CLI helper behavior."""

    def test_scan_folder_prints_tree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, "sub")
            os.makedirs(sub)
            with open(os.path.join(sub, "nested.txt"), "w", encoding="utf-8") as f:
                f.write("nested\n")

            import io
            captured = io.StringIO()
            original_stdout = sys.stdout
            try:
                sys.stdout = captured
                launcher._scan_folder(tmpdir, include_files=True)
            finally:
                sys.stdout = original_stdout

            output = captured.getvalue()
            self.assertIn("> " + tmpdir, output)
            self.assertIn("sub", output)
            self.assertIn("nested.txt", output)

    def test_scan_folder_rejects_non_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            not_a_dir = os.path.join(tmpdir, "not-a-dir.txt")
            with open(not_a_dir, "w", encoding="utf-8") as f:
                f.write("content\n")

            with self.assertRaises(SystemExit) as ctx:
                launcher._scan_folder(not_a_dir)
            self.assertEqual(ctx.exception.code, 1)

if __name__ == "__main__":
    unittest.main()


class TestScanEnvExclusions(unittest.TestCase):
    """Verify env-var-driven name filtering in _scan_workspace_files."""

    EXCLUDE_ENV = [
        "TOPSAILAI_SCAN_EXCLUDE",
        "TOPSAILAI_SCAN_EXCLUDE_DIRS",
        "TOPSAILAI_SCAN_EXCLUDE_FILES",
    ]

    def setUp(self):
        self._saved = {}
        for key in self.EXCLUDE_ENV:
            self._saved[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key in self.EXCLUDE_ENV:
            if self._saved.get(key) is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = self._saved[key]

    def _make_tree(self, tmpdir):
        """Create a sample tree with a mix of files and directories."""
        keep_dir = os.path.join(tmpdir, "keep_dir")
        skip_dir = os.path.join(tmpdir, "skip_dir")
        os.makedirs(keep_dir)
        os.makedirs(skip_dir)
        with open(os.path.join(keep_dir, "keep.txt"), "w", encoding="utf-8") as f:
            f.write("keep\n")
        with open(os.path.join(skip_dir, "inner.txt"), "w", encoding="utf-8") as f:
            f.write("inner\n")
        with open(os.path.join(tmpdir, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("notes\n")
        with open(os.path.join(tmpdir, "report.log"), "w", encoding="utf-8") as f:
            f.write("log\n")
        return tmpdir

    def test_exclude_applies_to_files_and_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE"] = "skip_dir,report.log"
            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertIn("keep_dir", tree)
            self.assertIn("keep.txt", tree)
            self.assertIn("notes.txt", tree)
            self.assertNotIn("skip_dir", tree)
            self.assertNotIn("inner.txt", tree)
            self.assertNotIn("report.log", tree)

    def test_exclude_dirs_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE_DIRS"] = "skip_dir"
            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertNotIn("skip_dir", tree)
            self.assertNotIn("inner.txt", tree)
            self.assertIn("report.log", tree)
            self.assertIn("notes.txt", tree)

    def test_exclude_files_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE_FILES"] = "report.log"
            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertNotIn("report.log", tree)
            self.assertIn("skip_dir", tree)
            self.assertIn("inner.txt", tree)
            self.assertIn("notes.txt", tree)

    def test_wildcard_patterns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE_FILES"] = "*.log"
            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertNotIn("report.log", tree)
            self.assertIn("notes.txt", tree)
            self.assertIn("keep.txt", tree)

    def test_empty_values_filter_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE"] = ""
            os.environ["TOPSAILAI_SCAN_EXCLUDE_DIRS"] = ", ,"
            os.environ["TOPSAILAI_SCAN_EXCLUDE_FILES"] = ""
            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertIn("skip_dir", tree)
            self.assertIn("inner.txt", tree)
            self.assertIn("report.log", tree)
            self.assertIn("notes.txt", tree)

    def test_unset_env_filters_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertIn("skip_dir", tree)
            self.assertIn("report.log", tree)
            self.assertIn("notes.txt", tree)

    def test_helper_parse_csv_names(self):
        self.assertEqual(launcher._parse_csv_names(None), [])
        self.assertEqual(launcher._parse_csv_names(""), [])
        self.assertEqual(launcher._parse_csv_names("a,b,c"), ["a", "b", "c"])
        self.assertEqual(launcher._parse_csv_names(" a , b "), ["a", "b"])
        self.assertEqual(launcher._parse_csv_names(",,"), [])

    def test_helper_matches_any(self):
        self.assertTrue(launcher._matches_any("report.log", ["*.log"]))
        self.assertTrue(launcher._matches_any("node_modules", ["node_modules"]))
        self.assertFalse(launcher._matches_any("keep.txt", ["*.log"]))
        self.assertFalse(launcher._matches_any("anything", []))


class TestScanSelfEnvirons(unittest.TestCase):
    """Verify the --scan path honors self_environs from settings.yaml."""

    SCAN_EXCLUDE_ENVS = [
        "TOPSAILAI_SCAN_EXCLUDE",
        "TOPSAILAI_SCAN_EXCLUDE_DIRS",
        "TOPSAILAI_SCAN_EXCLUDE_FILES",
    ]

    def setUp(self):
        self._saved = {}
        for key in self.SCAN_EXCLUDE_ENVS:
            self._saved[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key in self.SCAN_EXCLUDE_ENVS:
            if self._saved.get(key) is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = self._saved[key]

    def _write_settings(self, tmpdir, content):
        cfg_dir = os.path.join(tmpdir, ".topsailai")
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_path = os.path.join(cfg_dir, "settings.yaml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(content)
        return cfg_path

    def test_load_settings_if_exists_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._write_settings(
                tmpdir, "self_environs:\n  TOPSAILAI_SCAN_EXCLUDE_DIRS: vendor\n"
            )
            settings = launcher._load_settings_if_exists(cfg_path)
            self.assertEqual(
                settings.get("self_environs", {}),
                {"TOPSAILAI_SCAN_EXCLUDE_DIRS": "vendor"},
            )

    def test_load_settings_if_exists_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, "nonexistent", "settings.yaml")
            self.assertEqual(launcher._load_settings_if_exists(missing), {})

    def test_scan_path_applies_self_environs_exclusion(self):
        """Reproduce the main() --scan branch: settings drive scan exclusions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._write_settings(
                tmpdir,
                "self_environs:\n  TOPSAILAI_SCAN_EXCLUDE_DIRS: \"vendor,dist\"\n",
            )
            # Build a tree with a vendor dir that must be excluded.
            os.makedirs(os.path.join(tmpdir, "vendor"))
            with open(os.path.join(tmpdir, "vendor", "x.js"), "w", encoding="utf-8") as f:
                f.write("// js\n")
            os.makedirs(os.path.join(tmpdir, "src"))
            with open(os.path.join(tmpdir, "src", "main.py"), "w", encoding="utf-8") as f:
                f.write("print('hi')\n")

            # Mirror the main() --scan dispatch.
            scan_settings = launcher._load_settings_if_exists(cfg_path)
            launcher._apply_self_environs(scan_settings)
            tree = launcher._scan_workspace_files(tmpdir, tmpdir, include_files=True)

            self.assertIn("src", tree)
            self.assertIn("main.py", tree)
            self.assertNotIn("vendor", tree)
            self.assertNotIn("x.js", tree)

    def test_scan_path_without_settings_filters_nothing(self):
        """With no settings.yaml, --scan leaves the tree unfiltered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "vendor"))
            with open(os.path.join(tmpdir, "vendor", "x.js"), "w", encoding="utf-8") as f:
                f.write("// js\n")

            missing = os.path.join(tmpdir, "absent", "settings.yaml")
            scan_settings = launcher._load_settings_if_exists(missing)
            launcher._apply_self_environs(scan_settings)
            tree = launcher._scan_workspace_files(tmpdir, tmpdir, include_files=True)

            self.assertIn("vendor", tree)
            self.assertIn("x.js", tree)


class TestExcludeOption(unittest.TestCase):
    """Verify the --exclude option filters names from the scanned tree."""

    EXCLUDE_ENV = [
        "TOPSAILAI_SCAN_EXCLUDE",
        "TOPSAILAI_SCAN_EXCLUDE_DIRS",
        "TOPSAILAI_SCAN_EXCLUDE_FILES",
    ]

    def setUp(self):
        self._saved = {}
        for key in self.EXCLUDE_ENV:
            self._saved[key] = os.environ.pop(key, None)
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv

    def tearDown(self):
        for key in self.EXCLUDE_ENV:
            if self._saved.get(key) is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = self._saved[key]
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _make_tree(self, tmpdir):
        """Create a sample tree with a mix of files and directories."""
        for name in ("keep_dir", "build", "dist"):
            os.makedirs(os.path.join(tmpdir, name), exist_ok=True)
        with open(os.path.join(tmpdir, "build", "out.o"), "w", encoding="utf-8") as f:
            f.write("obj\n")
        with open(os.path.join(tmpdir, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("notes\n")
        with open(os.path.join(tmpdir, "report.log"), "w", encoding="utf-8") as f:
            f.write("log\n")
        return tmpdir

    def test_exclude_names_list_filters_files_and_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(
                tmpdir, exclude_names=["build", "report.log"], include_files=True
            )
            self.assertNotIn("build", tree)
            self.assertNotIn("out.o", tree)
            self.assertNotIn("report.log", tree)
            self.assertIn("keep_dir", tree)
            self.assertIn("notes.txt", tree)
            self.assertIn("dist", tree)

    def test_exclude_names_single_string_is_csv_parsed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(
                tmpdir, exclude_names="build, dist", include_files=True
            )
            self.assertNotIn("build", tree)
            self.assertNotIn("dist", tree)
            self.assertIn("keep_dir", tree)
            self.assertIn("report.log", tree)

    def test_exclude_names_support_wildcards(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(tmpdir, exclude_names=["*.log"], include_files=True)
            self.assertNotIn("report.log", tree)
            self.assertIn("notes.txt", tree)
            self.assertIn("build", tree)

    def test_exclude_names_merge_with_env_exclusions(self):
        """CLI names extend (not replace) TOPSAILAI_SCAN_EXCLUDE."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE"] = "dist"
            tree = launcher._scan_workspace_files(tmpdir, exclude_names=["build"], include_files=True)
            self.assertNotIn("build", tree)
            self.assertNotIn("dist", tree)
            self.assertIn("keep_dir", tree)
            self.assertIn("report.log", tree)

    def test_exclude_names_none_keeps_env_behavior(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE_DIRS"] = "build"
            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertNotIn("build", tree)
            self.assertIn("dist", tree)

    def test_helper_merge_exclusions(self):
        self.assertEqual(launcher._merge_exclusions(["a"], None), ["a"])
        self.assertEqual(launcher._merge_exclusions([], "b,c"), ["b", "c"])
        self.assertEqual(launcher._merge_exclusions(["a"], ["a", "b"]), ["a", "b"])
        self.assertEqual(launcher._merge_exclusions(None, [" a ", ""]), ["a"])
        self.assertEqual(launcher._merge_exclusions(["x"], ["y", "x", "z"]), ["x", "y", "z"])

    def test_scan_folder_passes_exclude_names(self):
        """_scan_folder forwards exclude_names to the shared scanner."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            captured = {}

            def fake_scan(workspace, project_folder=None, exclude_names=None, include_files=None):
                captured["exclude_names"] = exclude_names
                captured["include_files"] = include_files
                return "tree"

            original = launcher._scan_workspace_files
            launcher._scan_workspace_files = fake_scan
            try:
                launcher._scan_folder(tmpdir, exclude_names=["build"])
            finally:
                launcher._scan_workspace_files = original
            self.assertEqual(captured["exclude_names"], ["build"])
            # The scan default stays folders-only unless files are requested.
            self.assertFalse(captured["include_files"])

    def test_scan_folder_passes_include_files(self):
        """_scan_folder forwards include_files to the shared scanner."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            captured = {}

            def fake_scan(workspace, project_folder=None, exclude_names=None, include_files=None):
                captured["include_files"] = include_files
                return "tree"

            original = launcher._scan_workspace_files
            launcher._scan_workspace_files = fake_scan
            try:
                launcher._scan_folder(tmpdir, include_files=True)
            finally:
                launcher._scan_workspace_files = original
            self.assertTrue(captured["include_files"])

    def test_main_scan_applies_exclude_option(self):
        """`--scan FOLDER --exclude NAMES` prints a filtered tree and exits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.chdir(tmpdir)
            sys.argv = [
                "topsailai_launch_agent.py",
                "--scan",
                tmpdir,
                "--include-files",
                "--exclude",
                "build,*.log",
            ]
            stdout = StringIO()
            original_stdout = sys.stdout
            sys.stdout = stdout
            try:
                launcher.main()
            finally:
                sys.stdout = original_stdout
            tree = stdout.getvalue()
            self.assertNotIn("build", tree)
            self.assertNotIn("report.log", tree)
            self.assertIn("keep_dir", tree)
            self.assertIn("notes.txt", tree)

    def test_main_scan_repeated_exclude_options_are_merged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.chdir(tmpdir)
            sys.argv = [
                "topsailai_launch_agent.py",
                "--exclude",
                "build",
                "--exclude",
                "dist,notes.txt",
                "--include-files",
                "--scan",
                tmpdir,
            ]
            stdout = StringIO()
            original_stdout = sys.stdout
            sys.stdout = stdout
            try:
                launcher.main()
            finally:
                sys.stdout = original_stdout
            tree = stdout.getvalue()
            self.assertNotIn("build", tree)
            self.assertNotIn("dist", tree)
            self.assertNotIn("notes.txt", tree)
            self.assertIn("report.log", tree)


class TestScanFoldersOnlyDefault(unittest.TestCase):
    """Verify the folders-only scan default and the opt-in file listing."""

    INCLUDE_FILES_ENV = "TOPSAILAI_SCAN_INCLUDE_FILES"

    def setUp(self):
        self._saved = os.environ.pop(self.INCLUDE_FILES_ENV, None)
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(self.INCLUDE_FILES_ENV, None)
        else:
            os.environ[self.INCLUDE_FILES_ENV] = self._saved
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _make_tree(self, tmpdir):
        """Create a folder tree with a file at every level."""
        nested = os.path.join(tmpdir, "src", "pkg")
        os.makedirs(nested)
        os.makedirs(os.path.join(tmpdir, "docs"))
        with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("readme\n")
        with open(os.path.join(tmpdir, "src", "main.py"), "w", encoding="utf-8") as handle:
            handle.write("print('hi')\n")
        with open(os.path.join(nested, "leaf.py"), "w", encoding="utf-8") as handle:
            handle.write("leaf\n")
        return tmpdir

    def test_default_lists_folders_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(tmpdir)
            self.assertIn("src", tree)
            self.assertIn("pkg", tree)
            self.assertIn("docs", tree)
            self.assertNotIn("README.md", tree)
            self.assertNotIn("main.py", tree)
            self.assertNotIn("leaf.py", tree)

    def test_include_files_lists_files_and_folders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertIn("src", tree)
            self.assertIn("pkg", tree)
            self.assertIn("README.md", tree)
            self.assertIn("main.py", tree)
            self.assertIn("leaf.py", tree)

    def test_default_hides_symlinked_file_but_keeps_symlinked_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real_dir = os.path.join(tmpdir, "real_dir")
            os.makedirs(real_dir)
            real_file = os.path.join(tmpdir, "real_file.txt")
            with open(real_file, "w", encoding="utf-8") as handle:
                handle.write("content\n")
            os.symlink(real_dir, os.path.join(tmpdir, "link_dir"))
            os.symlink(real_file, os.path.join(tmpdir, "link_file.txt"))

            tree = launcher._scan_workspace_files(tmpdir)
            self.assertIn("link_dir", tree)
            self.assertNotIn("link_file.txt", tree)

    def test_default_folder_tree_is_smaller_than_file_tree(self):
        """Folders-only is the compact mode requested for the agent context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            folders_only = launcher._scan_workspace_files(tmpdir)
            with_files = launcher._scan_workspace_files(tmpdir, include_files=True)
            self.assertLess(len(folders_only), len(with_files))

    def test_env_var_enables_file_listing(self):
        """A resolved True from the env var makes the scanner list files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ[self.INCLUDE_FILES_ENV] = "true"
            include_files = launcher._resolve_scan_include_files()
            tree = launcher._scan_workspace_files(tmpdir, include_files=include_files)
            self.assertIn("main.py", tree)

    def test_scan_folder_defaults_to_folders_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            stdout = StringIO()
            original_stdout = sys.stdout
            sys.stdout = stdout
            try:
                launcher._scan_folder(tmpdir)
            finally:
                sys.stdout = original_stdout
            output = stdout.getvalue()
            self.assertIn("> " + tmpdir, output)
            self.assertIn("src", output)
            self.assertNotIn("main.py", output)

    def test_scan_folder_include_files_prints_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            stdout = StringIO()
            original_stdout = sys.stdout
            sys.stdout = stdout
            try:
                launcher._scan_folder(tmpdir, include_files=True)
            finally:
                sys.stdout = original_stdout
            self.assertIn("main.py", stdout.getvalue())

    def test_main_scan_prints_folders_only_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.chdir(tmpdir)
            sys.argv = ["topsailai_launch_agent.py", "--scan", tmpdir]
            stdout = StringIO()
            original_stdout = sys.stdout
            sys.stdout = stdout
            try:
                launcher.main()
            finally:
                sys.stdout = original_stdout
            tree = stdout.getvalue()
            self.assertIn("src", tree)
            self.assertIn("pkg", tree)
            self.assertNotIn("main.py", tree)

    def test_main_scan_include_files_flag_prints_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.chdir(tmpdir)
            sys.argv = ["topsailai_launch_agent.py", "--scan", tmpdir, "--include-files"]
            stdout = StringIO()
            original_stdout = sys.stdout
            sys.stdout = stdout
            try:
                launcher.main()
            finally:
                sys.stdout = original_stdout
            self.assertIn("main.py", stdout.getvalue())

    def test_main_scan_folders_only_overrides_env(self):
        """An explicit --folders-only wins over TOPSAILAI_SCAN_INCLUDE_FILES."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.chdir(tmpdir)
            os.environ[self.INCLUDE_FILES_ENV] = "true"
            sys.argv = ["topsailai_launch_agent.py", "--scan", tmpdir, "--folders-only"]
            stdout = StringIO()
            original_stdout = sys.stdout
            sys.stdout = stdout
            try:
                launcher.main()
            finally:
                sys.stdout = original_stdout
            self.assertNotIn("main.py", stdout.getvalue())

    def test_main_scan_include_files_and_folders_only_are_mutually_exclusive(self):
        sys.argv = [
            "topsailai_launch_agent.py",
            "--scan",
            tempfile.gettempdir(),
            "--include-files",
            "--folders-only",
        ]
        stderr = StringIO()
        original_stderr = sys.stderr
        sys.stderr = stderr
        try:
            with self.assertRaises(SystemExit) as ctx:
                launcher.main()
        finally:
            sys.stderr = original_stderr
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_main_scan_env_var_enables_files_without_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.chdir(tmpdir)
            os.environ[self.INCLUDE_FILES_ENV] = "1"
            sys.argv = ["topsailai_launch_agent.py", "--scan", tmpdir]
            stdout = StringIO()
            original_stdout = sys.stdout
            sys.stdout = stdout
            try:
                launcher.main()
            finally:
                sys.stdout = original_stdout
            self.assertIn("main.py", stdout.getvalue())


class TestResolveScanIncludeFiles(unittest.TestCase):
    """Verify resolution of the scan include-files mode."""

    INCLUDE_FILES_ENV = "TOPSAILAI_SCAN_INCLUDE_FILES"

    def setUp(self):
        self._saved = os.environ.pop(self.INCLUDE_FILES_ENV, None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(self.INCLUDE_FILES_ENV, None)
        else:
            os.environ[self.INCLUDE_FILES_ENV] = self._saved

    def test_unset_defaults_to_folders_only(self):
        self.assertFalse(launcher._resolve_scan_include_files())

    def test_cli_flag_takes_precedence_over_env(self):
        environ = {self.INCLUDE_FILES_ENV: "true"}
        self.assertTrue(launcher._resolve_scan_include_files(True, environ))
        self.assertFalse(launcher._resolve_scan_include_files(False, environ))

    def test_truthy_spellings_enable_files(self):
        for value in ("1", "true", "TRUE", "Yes", "y", "on", " true "):
            with self.subTest(value=value):
                self.assertTrue(
                    launcher._resolve_scan_include_files(None, {self.INCLUDE_FILES_ENV: value})
                )

    def test_falsy_spellings_keep_folders_only(self):
        for value in ("", "0", "false", "FALSE", "no", "n", "off", " off "):
            with self.subTest(value=value):
                self.assertFalse(
                    launcher._resolve_scan_include_files(None, {self.INCLUDE_FILES_ENV: value})
                )

    def test_invalid_value_warns_and_uses_default(self):
        stderr = StringIO()
        with patch.object(sys, "stderr", stderr):
            value = launcher._resolve_scan_include_files(
                None, {self.INCLUDE_FILES_ENV: "maybe"}
            )
        self.assertFalse(value)
        self.assertIn("Invalid TOPSAILAI_SCAN_INCLUDE_FILES", stderr.getvalue())

    def test_reads_process_environment_when_mapping_omitted(self):
        os.environ[self.INCLUDE_FILES_ENV] = "yes"
        self.assertTrue(launcher._resolve_scan_include_files())
