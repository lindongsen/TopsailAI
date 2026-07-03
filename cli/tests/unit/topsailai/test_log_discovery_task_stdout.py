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


if __name__ == "__main__":
    unittest.main()
