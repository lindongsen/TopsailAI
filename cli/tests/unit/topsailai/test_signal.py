#!/usr/bin/env python3
"""
Unit tests for signal handling in topsailai.py.

Covers:
- signal_handler()
- cleanup_children integration
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai as cli


class TestSignalHandler(unittest.TestCase):
    """Tests for signal_handler."""

    def setUp(self):
        cli.running = True
        cli._child_processes.clear()

    def tearDown(self):
        cli.running = True
        cli._child_processes.clear()

    @patch("builtins.print")
    @patch("topsailai.cleanup_children")
    @patch("sys.exit")
    def test_sigint(self, mock_exit, mock_cleanup, mock_print):
        """Handle SIGINT signal."""
        cli.signal_handler(2, None)
        self.assertFalse(cli.running)
        mock_cleanup.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("builtins.print")
    @patch("topsailai.cleanup_children")
    @patch("sys.exit")
    def test_sigterm(self, mock_exit, mock_cleanup, mock_print):
        """Handle SIGTERM signal."""
        cli.signal_handler(15, None)
        self.assertFalse(cli.running)
        mock_cleanup.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("builtins.print")
    def test_prints_signal_info(self, mock_print):
        """Print signal information."""
        with patch("topsailai.cleanup_children"):
            with patch("sys.exit"):
                cli.signal_handler(2, None)
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("Received signal 2" in p for p in printed))


if __name__ == "__main__":
    unittest.main()
