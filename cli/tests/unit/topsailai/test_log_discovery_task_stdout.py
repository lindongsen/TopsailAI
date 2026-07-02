#!/usr/bin/env python3
"""
Unit tests for the new .task.stdout filename format in topsailai.py.

Covers:
- _parse_stdout_filename() for .task.stdout
- discover_log_files() including .task.stdout files
- _find_session_stdout_file() matching .task.stdout files
"""

import sys
import os
import unittest
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai as cli


class TestParseTaskStdoutFilename(unittest.TestCase):
    """Tests for _parse_stdout_filename with .task.stdout files."""

    def test_task_stdout_full_format(self):
        """Parse {session_id}.topsailai.{timestamp}.{pid}.task.stdout."""
        filename = "20260702T091956.topsailai.1782990987.5236263.task.stdout"
        session_id, pid = cli._parse_stdout_filename(filename)
        self.assertEqual(session_id, "20260702T091956")
        self.assertEqual(pid, 5236263)

    def test_task_stdout_session_id_with_dots(self):
        """Parse task stdout when session_id itself contains dots."""
        filename = "my.session.id.topsailai.1782990987.5236263.task.stdout"
        session_id, pid = cli._parse_stdout_filename(filename)
        self.assertEqual(session_id, "my.session.id")
        self.assertEqual(pid, 5236263)

    def test_task_stdout_invalid_pid(self):
        """Return None for invalid pid in task stdout."""
        filename = "20260702T091956.topsailai.1782990987.notapid.task.stdout"
        session_id, pid = cli._parse_stdout_filename(filename)
        self.assertIsNone(session_id)
        self.assertIsNone(pid)

    def test_task_stdout_missing_topsailai_marker(self):
        """Return None when topsailai marker is missing."""
        filename = "20260702T091956.1782990987.5236263.task.stdout"
        session_id, pid = cli._parse_stdout_filename(filename)
        self.assertIsNone(session_id)
        self.assertIsNone(pid)

    def test_task_stdout_empty_base(self):
        """Return None for empty base name."""
        session_id, pid = cli._parse_stdout_filename(".task.stdout")
        self.assertIsNone(session_id)
        self.assertIsNone(pid)


    def test_task_stdout_temp_invalid_pid(self):
        """Return None for invalid pid in temp task stdout."""
        filename = "topsailai.1782990987.notapid.task.stdout"
        session_id, pid = cli._parse_stdout_filename(filename)
        self.assertIsNone(session_id)
        self.assertIsNone(pid)

    def test_session_stdout_still_works(self):
        """Existing session.stdout parsing remains functional."""
        session_id, pid = cli._parse_stdout_filename("20260702T091956.1234.session.stdout")
        self.assertEqual(session_id, "20260702T091956")
        self.assertEqual(pid, 1234)

    def test_temp_session_stdout_still_works(self):
        """Existing temp session stdout parsing remains functional."""
        session_id, pid = cli._parse_stdout_filename("topsailai.1234.session.stdout")
        self.assertIsNone(session_id)
        self.assertEqual(pid, 1234)


class TestDiscoverTaskStdoutFiles(unittest.TestCase):
    """Tests for discover_log_files with .task.stdout files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_discovers_task_stdout(self):
        """Discover .task.stdout files alongside .session.stdout."""
        path = os.path.join(self.tmpdir, "20260702T091956.topsailai.1782990987.5236263.task.stdout")
        with open(path, "w") as f:
            f.write("task log")

        result = cli.discover_log_files(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filename"], "20260702T091956.topsailai.1782990987.5236263.task.stdout")
        self.assertEqual(result[0]["session_id"], "20260702T091956")
        self.assertEqual(result[0]["pid"], 5236263)
        self.assertEqual(result[0]["size"], len("task log"))

    def test_discovers_mixed_stdout_files(self):
        """Discover both .session.stdout and .task.stdout files."""
        session_path = os.path.join(self.tmpdir, "20260702T150608.2906377.session.stdout")
        task_path = os.path.join(self.tmpdir, "20260702T091956.topsailai.1782990987.5236263.task.stdout")
        with open(session_path, "w") as f:
            f.write("session")
        time.sleep(0.05)
        with open(task_path, "w") as f:
            f.write("task")

        result = cli.discover_log_files(self.tmpdir)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["filename"], os.path.basename(task_path))
        self.assertEqual(result[1]["filename"], os.path.basename(session_path))

    def test_ignores_non_stdout_files(self):
        """Ignore files without .stdout extension."""
        path = os.path.join(self.tmpdir, "20260702T091956.topsailai.1782990987.5236263.task")
        with open(path, "w") as f:
            f.write("not stdout")
        result = cli.discover_log_files(self.tmpdir)
        self.assertEqual(result, [])


class TestFindSessionStdoutFileTaskStdout(unittest.TestCase):
    """Tests for _find_session_stdout_file with .task.stdout files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_find_task_stdout_by_session_id(self):
        """Resolve session_id to the most recent .task.stdout file."""
        old_path = os.path.join(self.tmpdir, "20260702T091956.topsailai.1782990987.5236263.task.stdout")
        new_path = os.path.join(self.tmpdir, "20260702T091956.topsailai.1782990988.5236264.task.stdout")
        with open(old_path, "w") as f:
            f.write("old")
        time.sleep(0.05)
        with open(new_path, "w") as f:
            f.write("new")

        result = cli._find_session_stdout_file(self.tmpdir, "20260702T091956")
        self.assertEqual(result, new_path)

    def test_find_session_stdout_by_session_id(self):
        """Resolve session_id to the most recent .session.stdout file."""
        path = os.path.join(self.tmpdir, "20260702T150608.2906377.session.stdout")
        with open(path, "w") as f:
            f.write("session")

        result = cli._find_session_stdout_file(self.tmpdir, "20260702T150608")
        self.assertEqual(result, path)

    def test_no_match_returns_none(self):
        """Return None when no stdout file matches the session id."""
        path = os.path.join(self.tmpdir, "20260702T091956.topsailai.1782990987.5236263.task.stdout")
        with open(path, "w") as f:
            f.write("task")

        result = cli._find_session_stdout_file(self.tmpdir, "nonexistent")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
