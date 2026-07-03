#!/usr/bin/env python3
"""
Unit tests for send/retrieve/stream prompt handling in cli_topsailai.
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
from cli_topsailai.core import prompt_selection
from cli_topsailai.streaming import send_message_to_session


class TestSendRetrieveStreamPrompt(unittest.TestCase):
    """Tests for send/retrieve/stream prompt handling."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    @patch("cli_topsailai.core.input")
    def test_send_prompt(self, mock_input):
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_input.return_value = "/send hello"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "send")
        self.assertEqual(value, "/send hello")

    @patch("cli_topsailai.core.input")
    def test_retrieve_prompt(self, mock_input):
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_input.return_value = "/retrieve"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "retrieve")

    @patch("os.stat")
    @patch("cli_topsailai.streaming._find_session_stdout_file")
    @patch("cli_topsailai.streaming.get_file_pid")
    @patch("os.path.exists")
    @patch("stat.S_ISFIFO")
    @patch("os.open")
    @patch("os.write")
    @patch("os.close")
    def test_send_message_to_session(
        self,
        mock_close,
        mock_write,
        mock_open,
        mock_isfifo,
        mock_exists,
        mock_get_pid,
        mock_find_stdout,
        mock_stat,
    ):
        mock_find_stdout.return_value = "/tmp/s1.session.stdout"
        mock_get_pid.return_value = 1234
        mock_exists.return_value = True
        mock_stat.return_value = MagicMock(st_mode=0o010000)
        mock_isfifo.return_value = True
        mock_open.return_value = 3
        result = send_message_to_session("s1", "hello", "/tmp/fake_task_dir")
        self.assertTrue(result)
        mock_open.assert_called_once()
        mock_write.assert_called_once()
        mock_close.assert_called_once()

if __name__ == "__main__":
    unittest.main()
