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


if __name__ == "__main__":
    unittest.main()
