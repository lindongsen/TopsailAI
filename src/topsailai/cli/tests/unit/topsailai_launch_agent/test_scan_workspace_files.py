#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for workspace file scanning in topsailai_launch_agent."""

import os
import sys
import tempfile
import unittest

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

            tree = launcher._scan_workspace_files(tmpdir)
            self.assertIn("link_file.txt", tree)
            self.assertIn("real_file.txt", tree)

    def test_regular_directory_is_recursed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub_dir = os.path.join(tmpdir, "sub")
            os.makedirs(sub_dir)
            with open(os.path.join(sub_dir, "nested.txt"), "w", encoding="utf-8") as f:
                f.write("nested\n")

            tree = launcher._scan_workspace_files(tmpdir)
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

            tree = launcher._scan_workspace_files(workspace, project)
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

            tree = launcher._scan_workspace_files(tmpdir, tmpdir)
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

            tree = launcher._scan_workspace_files(workspace, outside)
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

            tree = launcher._scan_workspace_files(tmpdir, None)
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

            tree = launcher._scan_workspace_files(tmpdir)
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

            tree = launcher._scan_workspace_files(tmpdir)
            self.assertEqual(tree.count("secret.env"), 1)

    def test_root_gitignore_still_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("build.out\n")
            with open(os.path.join(tmpdir, "build.out"), "w", encoding="utf-8") as f:
                f.write("artifact\n")
            with open(os.path.join(tmpdir, "keep.txt"), "w", encoding="utf-8") as f:
                f.write("keep\n")

            tree = launcher._scan_workspace_files(tmpdir)
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

            tree = launcher._scan_workspace_files(tmpdir)
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

            tree = launcher._scan_workspace_files(tmpdir)
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
                launcher._scan_folder(tmpdir)
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
            tree = launcher._scan_workspace_files(tmpdir)
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
            tree = launcher._scan_workspace_files(tmpdir)
            self.assertNotIn("skip_dir", tree)
            self.assertNotIn("inner.txt", tree)
            self.assertIn("report.log", tree)
            self.assertIn("notes.txt", tree)

    def test_exclude_files_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE_FILES"] = "report.log"
            tree = launcher._scan_workspace_files(tmpdir)
            self.assertNotIn("report.log", tree)
            self.assertIn("skip_dir", tree)
            self.assertIn("inner.txt", tree)
            self.assertIn("notes.txt", tree)

    def test_wildcard_patterns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE_FILES"] = "*.log"
            tree = launcher._scan_workspace_files(tmpdir)
            self.assertNotIn("report.log", tree)
            self.assertIn("notes.txt", tree)
            self.assertIn("keep.txt", tree)

    def test_empty_values_filter_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ["TOPSAILAI_SCAN_EXCLUDE"] = ""
            os.environ["TOPSAILAI_SCAN_EXCLUDE_DIRS"] = ", ,"
            os.environ["TOPSAILAI_SCAN_EXCLUDE_FILES"] = ""
            tree = launcher._scan_workspace_files(tmpdir)
            self.assertIn("skip_dir", tree)
            self.assertIn("inner.txt", tree)
            self.assertIn("report.log", tree)
            self.assertIn("notes.txt", tree)

    def test_unset_env_filters_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = launcher._scan_workspace_files(tmpdir)
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
