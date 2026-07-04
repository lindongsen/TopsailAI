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
    @patch("cli_topsailai.streaming._get_pid_from_stdout_path")
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
        mock_get_pid_from_path,
        mock_find_stdout,
        mock_stat,
    ):
        mock_find_stdout.return_value = "/tmp/s1.session.stdout"
        mock_get_pid_from_path.return_value = 1234
        mock_get_pid.return_value = 5678
        mock_exists.return_value = True
        mock_stat.return_value = MagicMock(st_mode=0o010000)
        mock_isfifo.return_value = True
        mock_open.return_value = 3
        result = send_message_to_session("s1", "hello", "/tmp/fake_task_dir")
        self.assertTrue(result)
        mock_get_pid_from_path.assert_called_once_with("/tmp/s1.session.stdout")
        mock_get_pid.assert_not_called()
        mock_open.assert_called_once()
        mock_write.assert_called_once()
        mock_close.assert_called_once()

    @patch("os.stat")
    @patch("cli_topsailai.streaming._find_session_stdout_file")
    @patch("cli_topsailai.streaming._get_pid_from_stdout_path")
    @patch("cli_topsailai.streaming.get_file_pid")
    @patch("os.path.exists")
    @patch("stat.S_ISFIFO")
    @patch("os.open")
    @patch("os.write")
    @patch("os.close")
    def test_send_message_to_session_fallback_to_file_pid(
        self,
        mock_close,
        mock_write,
        mock_open,
        mock_isfifo,
        mock_exists,
        mock_get_pid,
        mock_get_pid_from_path,
        mock_find_stdout,
        mock_stat,
    ):
        mock_find_stdout.return_value = "/tmp/s1.session.stdout"
        mock_get_pid_from_path.return_value = None
        mock_get_pid.return_value = 5678
        mock_exists.return_value = True
        mock_stat.return_value = MagicMock(st_mode=0o010000)
        mock_isfifo.return_value = True
        mock_open.return_value = 3
        result = send_message_to_session("s1", "hello", "/tmp/fake_task_dir")
        self.assertTrue(result)
        mock_get_pid_from_path.assert_called_once_with("/tmp/s1.session.stdout")
        mock_get_pid.assert_called_once_with("/tmp/s1.session.stdout")
        mock_open.assert_called_once()

    @patch("os.stat")
    @patch("cli_topsailai.streaming._find_session_stdout_file")
    @patch("cli_topsailai.streaming._get_pid_from_stdout_path")
    @patch("cli_topsailai.streaming.get_file_pid")
    @patch("os.path.exists")
    @patch("stat.S_ISFIFO")
    @patch("os.open")
    @patch("os.write")
    @patch("os.close")
    def test_send_message_to_session_fallback_when_filename_pid_pipe_missing(
        self,
        mock_close,
        mock_write,
        mock_open,
        mock_isfifo,
        mock_exists,
        mock_get_pid,
        mock_get_pid_from_path,
        mock_find_stdout,
        mock_stat,
    ):
        mock_find_stdout.return_value = "/tmp/s1.session.stdout"
        mock_get_pid_from_path.return_value = 1234
        mock_get_pid.return_value = 5678
        # Filename-derived pipe is missing; fuser-derived pipe exists.
        mock_exists.side_effect = lambda path: "s1.5678.session.pipe" in path
        mock_stat.return_value = MagicMock(st_mode=0o010000)
        mock_isfifo.return_value = True
        mock_open.return_value = 3
        result = send_message_to_session("s1", "hello", "/tmp/fake_task_dir")
        self.assertTrue(result)
        mock_get_pid_from_path.assert_called_once_with("/tmp/s1.session.stdout")
        mock_get_pid.assert_called_once_with("/tmp/s1.session.stdout")
        mock_open.assert_called_once()


    def test_send_message_to_session_uses_session_stdout_for_task_stdout(self):
        """When given a task stdout path, resolve the session stdout path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "s1.1000.session.stdout")
            task_path = os.path.join(tmpdir, "s1.topsailai.1234567890.2000.task.stdout")
            pipe_path = os.path.join(tmpdir, "s1.1000.session.pipe")
            with open(session_path, "w") as f:
                f.write("session log")
            with open(task_path, "w") as f:
                f.write("task log")
            os.mkfifo(pipe_path)

            def reader():
                with open(pipe_path, "rb") as f:
                    f.read()

            import threading

            t = threading.Thread(target=reader)
            t.start()
            try:
                result = send_message_to_session(
                    "s1", "hello", tmpdir, timeout=2.0, stdout_path=task_path
                )
            finally:
                t.join(timeout=3)
        self.assertTrue(result)

    def test_send_message_to_session_task_stdout_no_session_stdout(self):
        """When given a task stdout path without a matching session stdout, fail gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = os.path.join(tmpdir, "s1.topsailai.1234567890.2000.task.stdout")
            with open(task_path, "w") as f:
                f.write("task log")
            with patch("builtins.print") as mock_print:
                result = send_message_to_session(
                    "s1", "hello", tmpdir, timeout=2.0, stdout_path=task_path
                )
            printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertFalse(result)
        self.assertTrue(any("No session stdout file found" in str(p) for p in printed))

    def test_send_message_to_session_uses_session_stdout_for_standard_task_stdout(self):
        """When given a standard task stdout path with an extra identifier, resolve the session stdout path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "s1.1000.session.stdout")
            task_path = os.path.join(tmpdir, "s1.2000.step-1.task.stdout")
            pipe_path = os.path.join(tmpdir, "s1.1000.session.pipe")
            with open(session_path, "w") as f:
                f.write("session log")
            with open(task_path, "w") as f:
                f.write("task log")
            os.mkfifo(pipe_path)

            def reader():
                with open(pipe_path, "rb") as f:
                    f.read()

            import threading

            t = threading.Thread(target=reader)
            t.start()
            try:
                result = send_message_to_session(
                    "s1", "hello", tmpdir, timeout=2.0, stdout_path=task_path
                )
            finally:
                t.join(timeout=3)
        self.assertTrue(result)

    def test_send_message_to_session_prefers_task_list_pid(self):
        """When a pid is provided from the task list, use it before filename parsing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "s1.1000.session.stdout")
            task_path = os.path.join(tmpdir, "s1.topsailai.1234567890.2000.task.stdout")
            pipe_path = os.path.join(tmpdir, "s1.1000.session.pipe")
            with open(session_path, "w") as f:
                f.write("session log")
            with open(task_path, "w") as f:
                f.write("task log")
            os.mkfifo(pipe_path)

            def reader():
                with open(pipe_path, "rb") as f:
                    f.read()

            import threading

            t = threading.Thread(target=reader)
            t.start()
            try:
                result = send_message_to_session(
                    "s1", "hello", tmpdir, timeout=2.0, stdout_path=task_path, pid=1000
                )
            finally:
                t.join(timeout=3)
        self.assertTrue(result)

if __name__ == "__main__":
    unittest.main()
