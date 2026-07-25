#!/usr/bin/env python3
"""
Unit tests for managed project persistence in cli_topsailai/projects.py.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_topsailai import projects


class TestLoadProjects(unittest.TestCase):
    """Tests for load_projects."""

    @patch("cli_topsailai.projects._get_projects_path")
    def test_missing_file_returns_empty(self, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            self.assertEqual(projects.load_projects(), [])

    @patch("cli_topsailai.projects._get_projects_path")
    def test_loads_and_sorts_oldest_first(self, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".projects.jsonl")
            mock_path.return_value = path
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"name": "b", "path": "/work/b", "created_at": "2026-07-25T10:00:00"}) + "\n")
                fh.write(json.dumps({"name": "a", "path": "/work/a", "created_at": "2026-07-25T08:00:00"}) + "\n")
            loaded = projects.load_projects()
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["name"], "a")
            self.assertEqual(loaded[1]["name"], "b")

    @patch("cli_topsailai.projects._get_projects_path")
    def test_skips_invalid_lines(self, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".projects.jsonl")
            mock_path.return_value = path
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("not-json\n")
                fh.write(json.dumps({"name": "a", "path": "/work/a", "created_at": "2026-07-25T08:00:00"}) + "\n")
                fh.write("\n")
            loaded = projects.load_projects()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["name"], "a")

    @patch("cli_topsailai.projects._get_projects_path")
    def test_skips_entries_without_path(self, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".projects.jsonl")
            mock_path.return_value = path
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"name": "a", "created_at": "2026-07-25T08:00:00"}) + "\n")
            self.assertEqual(projects.load_projects(), [])


class TestSaveProjects(unittest.TestCase):
    """Tests for save_projects."""

    @patch("cli_topsailai.projects._get_projects_path")
    def test_saves_projects_atomically(self, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".projects.jsonl")
            mock_path.return_value = path
            project_list = [
                {"name": "a", "path": "/work/a", "created_at": "2026-07-25T08:00:00"},
            ]
            self.assertTrue(projects.save_projects(project_list))
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.read().strip().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["name"], "a")

    @patch("cli_topsailai.projects._get_projects_path")
    def test_save_creates_directory(self, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", ".projects.jsonl")
            mock_path.return_value = path
            self.assertTrue(projects.save_projects([]))
            self.assertTrue(os.path.isdir(os.path.dirname(path)))


class TestAddProject(unittest.TestCase):
    """Tests for add_project."""

    @patch("cli_topsailai.projects._get_projects_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_add_valid_project(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = os.path.join(tmp, "my-project")
            os.makedirs(project_dir)
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            result = projects.add_project(project_dir, name="My Project")
            self.assertTrue(result)
            loaded = projects.load_projects()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["name"], "My Project")
            self.assertTrue(os.path.isabs(loaded[0]["path"]))

    @patch("cli_topsailai.projects._get_projects_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_add_with_tilde_expansion(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            with patch.dict(os.environ, {"HOME": tmp}):
                result = projects.add_project("~/project", name="proj")
            self.assertTrue(result)
            loaded = projects.load_projects()
            self.assertEqual(loaded[0]["path"], project_dir)

    @patch("cli_topsailai.projects._get_projects_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_add_rejects_missing_path(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            result = projects.add_project("/does/not/exist")
            self.assertFalse(result)
            self.assertIn("does not exist", mock_stdout.getvalue())

    @patch("cli_topsailai.projects._get_projects_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_add_rejects_file_path(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "not-a-dir")
            with open(file_path, "w") as fh:
                fh.write("x")
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            result = projects.add_project(file_path)
            self.assertFalse(result)
            self.assertIn("not a directory", mock_stdout.getvalue())

    @patch("cli_topsailai.projects._get_projects_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_add_rejects_duplicate_path(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = os.path.join(tmp, "dup")
            os.makedirs(project_dir)
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            self.assertTrue(projects.add_project(project_dir))
            result = projects.add_project(project_dir, name="Other")
            self.assertFalse(result)
            self.assertIn("already exists", mock_stdout.getvalue())


class TestDeleteProjectByIndex(unittest.TestCase):
    """Tests for delete_project_by_index."""

    @patch("cli_topsailai.projects._get_projects_path")
    @patch("builtins.input", side_effect=["y"])
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_delete_confirmed(self, mock_stdout, mock_input, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            projects.save_projects([
                {"name": "a", "path": "/work/a", "created_at": "2026-07-25T08:00:00"},
                {"name": "b", "path": "/work/b", "created_at": "2026-07-25T09:00:00"},
            ])
            result = projects.delete_project_by_index(2)
            self.assertTrue(result)
            loaded = projects.load_projects()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["name"], "a")

    @patch("cli_topsailai.projects._get_projects_path")
    @patch("builtins.input", side_effect=["n"])
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_delete_cancelled(self, mock_stdout, mock_input, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            projects.save_projects([
                {"name": "a", "path": "/work/a", "created_at": "2026-07-25T08:00:00"},
            ])
            result = projects.delete_project_by_index(1)
            self.assertFalse(result)
            self.assertEqual(len(projects.load_projects()), 1)

    @patch("cli_topsailai.projects._get_projects_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_delete_invalid_index(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            projects.save_projects([
                {"name": "a", "path": "/work/a", "created_at": "2026-07-25T08:00:00"},
            ])
            result = projects.delete_project_by_index(5)
            self.assertFalse(result)


class TestBuildManagedProjectList(unittest.TestCase):
    """Tests for build_managed_project_list."""

    @patch("cli_topsailai.projects._get_projects_path")
    def test_assigns_row_numbers(self, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            mock_path.return_value = os.path.join(tmp, ".projects.jsonl")
            projects.save_projects([
                {"name": "a", "path": "/work/a", "created_at": "2026-07-25T08:00:00"},
                {"name": "b", "path": "/work/b", "created_at": "2026-07-25T09:00:00"},
            ])
            entries = projects.build_managed_project_list()
            self.assertEqual(entries[0]["no"], 1)
            self.assertEqual(entries[1]["no"], 2)


class TestPrintProjectTable(unittest.TestCase):
    """Tests for print_project_table."""

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_empty_list(self, mock_stdout):
        projects.print_project_table([])
        output = mock_stdout.getvalue()
        self.assertIn("No managed projects", output)
        self.assertIn("p add", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_renders_entries(self, mock_stdout):
        entries = projects.build_managed_project_list()
        # build_managed_project_list reads from disk; use a manual entry.
        entries = [
            {"no": 1, "name": "My Project", "path": "/work/my-project", "created_at": "2026-07-25T08:15:00"},
        ]
        projects.print_project_table(entries)
        output = mock_stdout.getvalue()
        self.assertIn("My Project", output)
        self.assertIn("/work/my-project", output)
        self.assertIn("07-25 08:15", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_truncates_long_path(self, mock_stdout):
        entries = [
            {"no": 1, "name": "x", "path": "/work/" + "a" * 80, "created_at": "2026-07-25T08:15:00"},
        ]
        projects.print_project_table(entries)
        output = mock_stdout.getvalue()
        self.assertIn("...", output)


if __name__ == "__main__":
    unittest.main()
