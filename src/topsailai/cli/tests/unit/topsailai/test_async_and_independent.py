#!/usr/bin/env python3
"""
Unit tests for async and independent process handling in cli_topsailai.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

import cli_topsailai.state as cli_state
from cli_topsailai.process import (
    is_async_command,
    is_independent_process,
    is_use_os_system,
    launch_independent_process,
    run_external_command,
)


class TestAsyncAndIndependent(unittest.TestCase):
    """Tests for async/independent command detection and execution."""

    def tearDown(self):
        cli_state._child_processes.clear()

    def test_async_command_detection(self):
        self.assertTrue(is_async_command({"async": True}))
        self.assertFalse(is_async_command({"async": False}))

    def test_independent_process_detection(self):
        self.assertTrue(is_independent_process({"independent_process": True}))
        self.assertFalse(is_independent_process({"independent_process": False}))

    def test_os_system_detection(self):
        self.assertTrue(is_use_os_system({"use_os_system": True}))
        self.assertFalse(is_use_os_system({"use_os_system": False}))

    @patch("cli_topsailai.process.subprocess.Popen")
    def test_launch_independent_process(self, mock_popen):
        """launch_independent_process starts a detached subprocess."""
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        result = launch_independent_process(["sleep", "1", "&"])
        self.assertEqual(result, mock_proc)
        mock_popen.assert_called_once()

    @patch("cli_topsailai.process.subprocess.Popen")
    def test_run_external_command_sync(self, mock_popen):
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
