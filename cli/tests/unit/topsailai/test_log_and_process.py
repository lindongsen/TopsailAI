#!/usr/bin/env python3
"""
Unit tests for log discovery, process management, and file PID functions in topsailai.py.

Covers:
- discover_log_files()
- register_process(), unregister_process(), cleanup_children()
- get_file_pid()
"""

import sys
import os
import unittest
import tempfile
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai as cli


class TestDiscoverLogFiles(unittest.TestCase):
    """Tests for discover_log_files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_empty_dir(self):
        """Return empty list for empty directory."""
        result = cli.discover_log_files(self.tmpdir)
        self.assertEqual(result, [])

    def test_no_stdout_files(self):
        """Return empty list when no .stdout files exist."""
        with open(os.path.join(self.tmpdir, "other.txt"), "w") as f:
            f.write("test")
        result = cli.discover_log_files(self.tmpdir)
        self.assertEqual(result, [])

    def test_single_stdout_file(self):
        """Discover a single .stdout file."""
        path = os.path.join(self.tmpdir, "topsailai.1234.session.stdout")
        with open(path, "w") as f:
            f.write("log content")
        result = cli.discover_log_files(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filename"], "topsailai.1234.session.stdout")
        self.assertEqual(result[0]["session_id"], "(temp)")
        self.assertEqual(result[0]["pid"], 1234)
        self.assertEqual(result[0]["size"], len("log content"))
        self.assertTrue(os.path.isfile(result[0]["path"]))

    def test_session_stdout(self):
        """Handle topsailai.{pid}.session.stdout as temp session."""
        path = os.path.join(self.tmpdir, "topsailai.1234.session.stdout")
        with open(path, "w") as f:
            f.write("temp log")
        result = cli.discover_log_files(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["session_id"], "(temp)")

    def test_multiple_files_sorted_by_mtime(self):
        """Files are sorted by mtime descending."""
        path1 = os.path.join(self.tmpdir, "a.1234.session.stdout")
        path2 = os.path.join(self.tmpdir, "b.5678.session.stdout")
        with open(path1, "w") as f:
            f.write("a")
        time.sleep(0.05)
        with open(path2, "w") as f:
            f.write("b")
        result = cli.discover_log_files(self.tmpdir)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["filename"], "b.5678.session.stdout")
        self.assertEqual(result[0]["session_id"], "b")
        self.assertEqual(result[0]["pid"], 5678)
        self.assertEqual(result[1]["filename"], "a.1234.session.stdout")
        self.assertEqual(result[1]["session_id"], "a")
        self.assertEqual(result[1]["pid"], 1234)
    def test_nonexistent_dir(self):
        """Return empty list for nonexistent directory."""
        result = cli.discover_log_files("/nonexistent/path/12345")
        self.assertEqual(result, [])


class TestProcessManagement(unittest.TestCase):
    """Tests for register_process, unregister_process, cleanup_children."""

    def tearDown(self):
        cli._child_processes.clear()

    def test_register_process(self):
        """Register a process for tracking."""
        mock_proc = MagicMock()
        cli.register_process(mock_proc)
        self.assertIn(mock_proc, cli._child_processes)

    def test_unregister_process(self):
        """Unregister a process after completion."""
        mock_proc = MagicMock()
        cli.register_process(mock_proc)
        cli.unregister_process(mock_proc)
        self.assertNotIn(mock_proc, cli._child_processes)

    def test_unregister_unknown_process(self):
        """Unregister a process not in list does not raise."""
        mock_proc = MagicMock()
        cli.unregister_process(mock_proc)
        self.assertEqual(cli._child_processes, [])

    def test_register_none(self):
        """Register None does nothing."""
        cli.register_process(None)
        self.assertEqual(cli._child_processes, [])

    @patch("builtins.print")
    def test_cleanup_children_empty(self, mock_print):
        """Cleanup with no children does nothing."""
        cli.cleanup_children()
        self.assertEqual(cli._child_processes, [])

    @patch("builtins.print")
    def test_cleanup_children_terminates(self, mock_print):
        """Cleanup terminates running processes."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        cli.register_process(mock_proc)
        cli.cleanup_children()
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        self.assertEqual(cli._child_processes, [])

    @patch("builtins.print")
    def test_cleanup_children_skips_finished(self, mock_print):
        """Cleanup skips already finished processes."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        cli.register_process(mock_proc)
        cli.cleanup_children()
        mock_proc.terminate.assert_not_called()
        mock_proc.kill.assert_not_called()


class TestGetFilePid(unittest.TestCase):
    """Tests for get_file_pid."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.testfile = os.path.join(self.tmpdir, "test.stdout")
        with open(self.testfile, "w") as f:
            f.write("test")

    def tearDown(self):
        if os.path.exists(self.testfile):
            os.remove(self.testfile)
        os.rmdir(self.tmpdir)
        cli._child_processes.clear()

    @patch("topsailai.subprocess.Popen")
    def test_lsof_found(self, mock_popen):
        """Find PID via lsof."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("1234\n", "")
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        result = cli.get_file_pid(self.testfile)
        self.assertEqual(result, 1234)
        mock_popen.assert_called_once()
        args = mock_popen.call_args.args[0]
        self.assertEqual(args[:2], ["lsof", "-t"])

    @patch("topsailai.subprocess.Popen")
    def test_lsof_not_found(self, mock_popen):
        """lsof returns no output."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 1
        mock_proc.poll.return_value = 1
        mock_popen.return_value = mock_proc

        result = cli.get_file_pid(self.testfile)
        self.assertIsNone(result)

    @patch("topsailai.subprocess.Popen")
    def test_fuser_fallback(self, mock_popen):
        """Fallback to fuser when lsof fails."""
        def side_effect(cmd, **kwargs):
            mock_proc = MagicMock()
            if cmd[0] == "lsof":
                mock_proc.communicate.return_value = ("", "")
                mock_proc.returncode = 1
                mock_proc.poll.return_value = 1
            else:
                mock_proc.communicate.return_value = ("/path: 5678\n", "")
                mock_proc.returncode = 0
                mock_proc.poll.return_value = 0
            return mock_proc
        mock_popen.side_effect = side_effect

        result = cli.get_file_pid(self.testfile)
        self.assertEqual(result, 5678)

    @patch("topsailai.subprocess.Popen")
    def test_both_fail(self, mock_popen):
        """Return None when both lsof and fuser fail."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 1
        mock_proc.poll.return_value = 1
        mock_popen.return_value = mock_proc

        result = cli.get_file_pid(self.testfile)
        self.assertIsNone(result)

    @patch("topsailai.subprocess.Popen")
    def test_lsof_exception(self, mock_popen):
        """Handle exception from lsof."""
        mock_popen.side_effect = OSError("lsof not found")

        result = cli.get_file_pid(self.testfile)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
