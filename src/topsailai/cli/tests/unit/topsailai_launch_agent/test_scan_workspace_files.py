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

    def test_project_folder_outside_workspace_falls_back(self):
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
            self.assertNotIn("outside.txt", tree)
            self.assertIn("> " + workspace, tree)

    def test_project_folder_none_scans_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, "sub")
            os.makedirs(sub)
            with open(os.path.join(sub, "nested.txt"), "w", encoding="utf-8") as f:
                f.write("nested\n")

            tree = launcher._scan_workspace_files(tmpdir, None)
            self.assertIn("sub", tree)
            self.assertIn("nested.txt", tree)


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
