#!/usr/bin/env python3
"""
Unit tests for task stdout log discovery in cli_topsailai.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai.log_files import discover_log_files


class TestLogDiscoveryTaskStdout(unittest.TestCase):
    """Tests for discovering task stdout log files."""

    def test_no_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            files = discover_log_files(tmpdir)
            self.assertEqual(files, [])

    def test_discovers_task_stdout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "task.1234.stdout"), "w").close()
            open(os.path.join(tmpdir, "task.1234.stderr"), "w").close()
            files = discover_log_files(tmpdir)
            self.assertEqual(len(files), 2)

    def test_ignores_non_matching_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "notes.txt"), "w").close()
            files = discover_log_files(tmpdir)
            self.assertEqual(files, [])

    def test_temp_task_stdout_with_extra_identifier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "topsailai.1234.step-1.task.stdout"), "w").close()
            files = discover_log_files(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["session_id"], "(temp)")
            self.assertEqual(files[0]["pid"], 1234)
            self.assertTrue(files[0]["is_task"])

    def test_named_session_task_stdout_with_extra_identifier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "my-session.1234.step-1.task.stdout"), "w").close()
            files = discover_log_files(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["session_id"], "my-session")
            self.assertEqual(files[0]["pid"], 1234)
            self.assertTrue(files[0]["is_task"])

    def test_temp_task_stdout_with_numeric_extra(self):
        """Extra identifier may be a plain number."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "topsailai.1234.5678.task.stdout"), "w").close()
            files = discover_log_files(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["session_id"], "(temp)")
            self.assertEqual(files[0]["pid"], 1234)
            self.assertTrue(files[0]["is_task"])

    def test_temp_task_stdout_with_dotted_extra(self):
        """Extra identifier may contain dots."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "topsailai.1234.abc.123.task.stdout"), "w").close()
            files = discover_log_files(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["session_id"], "(temp)")
            self.assertEqual(files[0]["pid"], 1234)
            self.assertTrue(files[0]["is_task"])


if __name__ == "__main__":
    unittest.main()
