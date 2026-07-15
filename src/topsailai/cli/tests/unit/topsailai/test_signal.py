#!/usr/bin/env python3
"""
Unit tests for signal handling in cli_topsailai.
"""

import os
import signal
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
from cli_topsailai.process import cleanup_child_processes


class TestSignalHandling(unittest.TestCase):
    """Tests for signal handling."""

    def tearDown(self):
        cli_state._child_processes.clear()

    @patch("cli_topsailai.process.print_info")
    def test_cleanup_child_processes(self, mock_print_info):
        proc = MagicMock()
        proc.poll.return_value = None
        cli_state._child_processes.add(proc)
        cleanup_child_processes()
        proc.terminate.assert_called_once()
        self.assertNotIn(proc, cli_state._child_processes)

    def test_signal_handler_registration(self):
        from cli_topsailai.core import setup_signal_handlers

        with patch("signal.signal") as mock_signal:
            setup_signal_handlers()
            mock_signal.assert_any_call(signal.SIGINT, unittest.mock.ANY)
            mock_signal.assert_any_call(signal.SIGTERM, unittest.mock.ANY)


if __name__ == "__main__":
    unittest.main()
