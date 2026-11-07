#!/usr/bin/env python3
"""
Unit tests for file-holder detection and PID resolution in log_files.

These pin two rules: a filename without a PID must never be resolved by
guessing which process holds the file, and the Linux process table must answer
"is this file in use" before any external tool is spawned.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai.log_files import get_file_pid, is_file_in_use


class TestGetFilePidDoesNotGuess(unittest.TestCase):
    """A filename without a PID must not be resolved by scanning holders."""

    @patch("cli_topsailai.log_files.subprocess.Popen")
    def test_unparseable_filename_returns_none_without_subprocess(self, mock_popen):
        """An unparseable name has no PID, and no tool may invent one."""
        self.assertIsNone(get_file_pid("/tmp/s1.session.stdout"))
        mock_popen.assert_not_called()

    @patch("cli_topsailai.log_files.subprocess.Popen")
    def test_parseable_filename_returns_pid_without_subprocess(self, mock_popen):
        """The filename PID is authoritative and needs no external tool."""
        self.assertEqual(get_file_pid("/tmp/s1.1234.session.stdout"), 1234)
        mock_popen.assert_not_called()

    def test_empty_path_returns_none(self):
        """An empty path has no PID to resolve."""
        self.assertIsNone(get_file_pid(""))


class TestIsFileInUsePrefersProc(unittest.TestCase):
    """The Linux process table answers before any external tool is spawned."""

    def test_detects_a_real_holder_through_proc(self):
        """A file this process holds open is reported as in use."""
        with tempfile.NamedTemporaryFile() as handle:
            self.assertTrue(is_file_in_use(handle.name))

    @patch("cli_topsailai.log_files.subprocess.Popen")
    def test_no_holder_does_not_spawn_a_tool(self, mock_popen):
        """An unheld file is answered by the process table alone.

        The file must be closed before probing: an open handle in this very
        process is a real holder, so keeping it open would test the opposite
        case.
        """
        handle = tempfile.NamedTemporaryFile(delete=False)
        path = handle.name
        handle.close()
        try:
            self.assertFalse(is_file_in_use(path))
        finally:
            os.unlink(path)
        mock_popen.assert_not_called()

    def test_missing_file_is_not_in_use(self):
        """A path that does not exist cannot be in use."""
        self.assertFalse(is_file_in_use("/tmp/topsailai-absent-file-xyz"))

    @patch("cli_topsailai.log_files.subprocess.Popen")
    def test_falls_back_to_lsof_without_proc(self, mock_popen):
        """A host without /proc still gets a portable answer."""
        proc = MagicMock()
        proc.communicate.return_value = ("1234\n", "")
        proc.returncode = 0
        proc.poll.return_value = 0
        mock_popen.return_value = proc
        handle = tempfile.NamedTemporaryFile(delete=False)
        path = handle.name
        handle.close()
        try:
            with patch("cli_topsailai.log_files._proc_available", return_value=False):
                self.assertTrue(is_file_in_use(path))
        finally:
            os.unlink(path)
        mock_popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
