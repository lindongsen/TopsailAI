#!/usr/bin/env python3
"""
Unit tests for log discovery and process management in cli_topsailai.
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

import cli_topsailai.state as cli_state
from cli_topsailai.log_files import (
    _resolve_literal_session_id,
    _resolve_send_target_from_arg,
    discover_log_files,
    get_file_pid,
)
from cli_topsailai.process import (
    is_async_command,
    is_independent_process,
    is_use_os_system,
    launch_independent_process,
    register_process,
    run_external_command,
    unregister_process,
)


class TestDiscoverLogFiles(unittest.TestCase):
    """Tests for discover_log_files."""

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            files = discover_log_files(tmpdir)
            self.assertEqual(files, [])

    def test_discovers_session_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "s1.1234.session.stdout"), "w").close()
            open(os.path.join(tmpdir, "other.txt"), "w").close()
            files = discover_log_files(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["session_id"], "s1")

    def test_sorted_by_creation_time_ascending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = os.path.join(tmpdir, "s1.1000.session.stdout")
            f2 = os.path.join(tmpdir, "s2.2000.session.stdout")
            f3 = os.path.join(tmpdir, "s3.3000.session.stdout")
            open(f1, "w").close()
            open(f2, "w").close()
            open(f3, "w").close()

            def fake_stat(path):
                m = MagicMock()
                m.st_size = 0
                m.st_mtime = 0
                m.st_ctime = 0
                if path == tmpdir:
                    m.st_mode = 0o40755
                    return m
                base = os.path.basename(path)
                times = {
                    "s1.1000.session.stdout": 3000,
                    "s2.2000.session.stdout": 1000,
                    "s3.3000.session.stdout": 2000,
                }
                m.st_mtime = times.get(base, 0)
                m.st_ctime = times.get(base, 0)
                m.st_mode = 0o100644
                return m

            with patch("cli_topsailai.log_files.os.stat", side_effect=fake_stat):
                files = discover_log_files(tmpdir)

            self.assertEqual([f["session_id"] for f in files], ["s2", "s3", "s1"])

    @patch("cli_topsailai.log_files.subprocess.Popen")
    def test_from_lsof(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("1234\n", "")
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc
        pid = get_file_pid("/tmp/s1.1234.session.stdout")
        self.assertEqual(pid, 1234)

    def test_no_pid(self):
        with patch("cli_topsailai.log_files.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("", "")
            mock_proc.returncode = 0
            mock_proc.poll.return_value = 0
            mock_popen.return_value = mock_proc
            pid = get_file_pid("/tmp/s1.session.stdout")
        self.assertIsNone(pid)


class TestResolveLiteralSessionId(unittest.TestCase):
    """Tests for _resolve_literal_session_id."""

    def test_match(self):
        result = _resolve_literal_session_id("s1")
        self.assertEqual(result, "s1")

    def test_temp_marker(self):
        result = _resolve_literal_session_id("(temp)")
        self.assertEqual(result, "topsailai")


class TestResolveSendTargetFromArg(unittest.TestCase):
    """Tests for _resolve_send_target_from_arg."""

    def test_numeric(self):
        files = [
            {
                "filename": "s1.1234.session.stdout",
                "session_id": "s1",
                "path": "/tmp/s1.1234.session.stdout",
                "pid": 1234,
            },
        ]
        result = _resolve_send_target_from_arg("1", files)
        self.assertIsNotNone(result)
        session_id, path, pid = result
        self.assertEqual(session_id, "s1")
        self.assertEqual(path, "/tmp/s1.1234.session.stdout")
        self.assertEqual(pid, 1234)

    def test_literal(self):
        files = [
            {
                "filename": "s1.1234.session.stdout",
                "session_id": "s1",
                "path": "/tmp/s1.1234.session.stdout",
                "pid": 1234,
            },
        ]
        result = _resolve_send_target_from_arg("s1", files)
        self.assertIsNotNone(result)
        session_id, path, pid = result
        self.assertEqual(session_id, "s1")
        self.assertIsNone(path)
        self.assertIsNone(pid)

class TestProcessManagement(unittest.TestCase):
    """Tests for process management functions."""

    def tearDown(self):
        cli_state._child_processes.clear()

    def test_register_unregister_process(self):
        proc = MagicMock()
        register_process(proc)
        self.assertIn(proc, cli_state._child_processes)
        unregister_process(proc)
        self.assertNotIn(proc, cli_state._child_processes)

    def test_is_independent_process(self):
        self.assertTrue(is_independent_process({"independent_process": True}))
        self.assertFalse(is_independent_process({"independent_process": False}))

    def test_is_async_command(self):
        self.assertTrue(is_async_command({"async": True}))
        self.assertFalse(is_async_command({"async": False}))

    def test_is_use_os_system(self):
        self.assertTrue(is_use_os_system({"use_os_system": True}))
        self.assertFalse(is_use_os_system({"use_os_system": False}))

    @patch("cli_topsailai.process.subprocess.Popen")
    def test_launch_independent_process(self, mock_popen):
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        result = launch_independent_process(["echo", "test"])
        self.assertEqual(result, mock_proc)
        mock_popen.assert_called_once()

    @patch("cli_topsailai.process.subprocess.Popen")
    def test_run_external_command(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc
        result = run_external_command(
            ["echo", "test"], os.environ.copy(), independent=False
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
