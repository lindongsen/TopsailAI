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
from cli_topsailai.streaming import (
    _handle_stream_ctx_btw,
    send_message_to_session,
    stream_file,
)
from cli_topsailai.yaml_commands import handle_yaml_command, match_yaml_command


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

    def test_send_message_to_session(self):
        """Keep legacy PID discovery while delegating exact byte delivery."""
        from cli_topsailai.runtime_pipe import PipeDeliveryResult
        from pathlib import Path

        with patch("cli_topsailai.streaming._find_session_stdout_file", return_value="/fixture/s1.session.stdout"), \
             patch("cli_topsailai.streaming._get_pid_from_stdout_path", return_value=1234) as parsed_pid, \
             patch("cli_topsailai.streaming.get_file_pid", return_value=5678) as fallback_pid, \
             patch("cli_topsailai.streaming.os.path.exists", side_effect=lambda path: True), \
             patch("cli_topsailai.streaming.send_to_pipe", return_value=PipeDeliveryResult(10)) as send:
            self.assertTrue(send_message_to_session("s1", "hello", "/fixture"))
        parsed_pid.assert_called_once_with("/fixture/s1.session.stdout")
        fallback_pid.assert_not_called()
        send.assert_called_once_with(Path("/fixture/s1.1234.session.pipe"), "hello", timeout=5.0)

    def test_multiline_send_stages_payload_and_removes_temporary_file(self):
        """Multi-line runtime payloads are staged, sent intact, and removed."""
        import threading

        workspace = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        temporary_dir = os.path.join(workspace, ".tmp")
        os.makedirs(temporary_dir, exist_ok=True)
        before = set(os.listdir(temporary_dir))
        received = []
        with tempfile.TemporaryDirectory(dir=temporary_dir) as task_dir:
            stdout_path = os.path.join(task_dir, "s1.1234.session.stdout")
            pipe_path = os.path.join(task_dir, "s1.1234.session.pipe")
            with open(stdout_path, "w", encoding="utf-8") as stdout_file:
                stdout_file.write("running")
            os.mkfifo(pipe_path)

            def reader():
                with open(pipe_path, "rb") as pipe_file:
                    received.append(pipe_file.read())

            thread = threading.Thread(target=reader)
            thread.start()
            try:
                result = send_message_to_session(
                    "s1",
                    "line one\nline two",
                    task_dir,
                    timeout=2.0,
                    stdout_path=stdout_path,
                    pid=1234,
                )
            finally:
                thread.join(timeout=3)

        self.assertTrue(result)
        self.assertEqual(received, [b"line one\nline two\nEOF\n"])
        self.assertEqual(set(os.listdir(temporary_dir)), before)

    def test_send_rejects_embedded_eof_marker_before_pipe_write(self):
        """A protocol marker in message content must not cause silent truncation."""
        with tempfile.TemporaryDirectory() as task_dir:
            stdout_path = os.path.join(task_dir, "s1.1234.session.stdout")
            pipe_path = os.path.join(task_dir, "s1.1234.session.pipe")
            with open(stdout_path, "w", encoding="utf-8") as stdout_file:
                stdout_file.write("running")
            os.mkfifo(pipe_path)

            with patch("cli_topsailai.runtime_pipe._open") as mock_open:
                result = send_message_to_session(
                    "s1",
                    "before\nEOF\nafter",
                    task_dir,
                    timeout=0.1,
                    stdout_path=stdout_path,
                    pid=1234,
                )

        self.assertFalse(result)
        mock_open.assert_not_called()

    def test_multiline_send_removes_temporary_file_after_write_failure(self):
        """A failed pipe write does not leave the staged payload behind."""
        import threading

        workspace = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        temporary_dir = os.path.join(workspace, ".tmp")
        os.makedirs(temporary_dir, exist_ok=True)
        before = set(os.listdir(temporary_dir))
        with tempfile.TemporaryDirectory(dir=temporary_dir) as task_dir:
            stdout_path = os.path.join(task_dir, "s1.1234.session.stdout")
            pipe_path = os.path.join(task_dir, "s1.1234.session.pipe")
            with open(stdout_path, "w", encoding="utf-8") as stdout_file:
                stdout_file.write("running")
            os.mkfifo(pipe_path)

            def reader():
                with open(pipe_path, "rb") as pipe_file:
                    pipe_file.read()

            thread = threading.Thread(target=reader)
            thread.start()
            try:
                with patch(
                    "cli_topsailai.runtime_pipe._write",
                    side_effect=OSError("write failed"),
                ):
                    result = send_message_to_session(
                        "s1",
                        "line one\nline two",
                        task_dir,
                        timeout=2.0,
                        stdout_path=stdout_path,
                        pid=1234,
                    )
            finally:
                thread.join(timeout=3)

        self.assertFalse(result)
        self.assertEqual(set(os.listdir(temporary_dir)), before)

    def test_send_message_to_session_fallback_to_file_pid(self):
        """Keep legacy PID discovery while delegating exact byte delivery."""
        from cli_topsailai.runtime_pipe import PipeDeliveryResult
        from pathlib import Path

        with patch("cli_topsailai.streaming._find_session_stdout_file", return_value="/fixture/s1.session.stdout"), \
             patch("cli_topsailai.streaming._get_pid_from_stdout_path", return_value=None) as parsed_pid, \
             patch("cli_topsailai.streaming.get_file_pid", return_value=5678) as fallback_pid, \
             patch("cli_topsailai.streaming.os.path.exists", side_effect=lambda path: "5678" in path), \
             patch("cli_topsailai.streaming.send_to_pipe", return_value=PipeDeliveryResult(10)) as send:
            self.assertTrue(send_message_to_session("s1", "hello", "/fixture"))
        parsed_pid.assert_called_once_with("/fixture/s1.session.stdout")
        fallback_pid.assert_called_once_with("/fixture/s1.session.stdout")
        send.assert_called_once_with(Path("/fixture/s1.5678.session.pipe"), "hello", timeout=5.0)


    def test_send_message_to_session_fallback_when_filename_pid_pipe_missing(self):
        """Keep legacy PID discovery while delegating exact byte delivery."""
        from cli_topsailai.runtime_pipe import PipeDeliveryResult
        from pathlib import Path

        with patch("cli_topsailai.streaming._find_session_stdout_file", return_value="/fixture/s1.session.stdout"), \
             patch("cli_topsailai.streaming._get_pid_from_stdout_path", return_value=1234) as parsed_pid, \
             patch("cli_topsailai.streaming.get_file_pid", return_value=5678) as fallback_pid, \
             patch("cli_topsailai.streaming.os.path.exists", side_effect=lambda path: "5678" in path), \
             patch("cli_topsailai.streaming.send_to_pipe", return_value=PipeDeliveryResult(10)) as send:
            self.assertTrue(send_message_to_session("s1", "hello", "/fixture"))
        parsed_pid.assert_called_once_with("/fixture/s1.session.stdout")
        fallback_pid.assert_called_once_with("/fixture/s1.session.stdout")
        send.assert_called_once_with(Path("/fixture/s1.5678.session.pipe"), "hello", timeout=5.0)



    def test_send_message_to_session_task_stdout_uses_filename_pid(self):
        """When given a task stdout path, use the PID embedded in the filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = os.path.join(tmpdir, "s1.2000.step-1.task.stdout")
            pipe_path = os.path.join(tmpdir, "s1.2000.session.pipe")
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

    def test_send_message_to_session_task_stdout_no_pipe(self):
        """When the filename-PID pipe is missing, report that the session is not running."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = os.path.join(tmpdir, "s1.2000.step-1.task.stdout")
            with open(task_path, "w") as f:
                f.write("task log")
            with patch("builtins.print") as mock_print:
                result = send_message_to_session(
                    "s1", "hello", tmpdir, timeout=0.5, stdout_path=task_path
                )
            printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertFalse(result)
        self.assertTrue(
            any("does not appear to be running" in str(p) for p in printed)
        )
        self.assertTrue(
            any("s1.2000.session.pipe" in str(p) for p in printed)
        )

    def test_send_message_to_session_task_stdout_pipe_timeout_includes_path(self):
        """Regression: timeout error for an existing but unread pipe must include the path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = os.path.join(tmpdir, "20260722T100956.1412638.step-1.task.stdout")
            pipe_path = os.path.join(tmpdir, "20260722T100956.1412638.session.pipe")
            with open(task_path, "w") as f:
                f.write("task log")
            os.mkfifo(pipe_path)
            with patch("builtins.print") as mock_print:
                result = send_message_to_session(
                    "20260722T100956", "yes", tmpdir, timeout=0.2, stdout_path=task_path
                )
            printed = [str(call[0][0]) for call in mock_print.call_args_list]
        self.assertFalse(result)
        timeout_msg = " ".join(printed)
        self.assertIn("Timed out waiting for session to open the pipe for reading", timeout_msg)
        self.assertIn("20260722T100956.1412638.session.pipe", timeout_msg)

    def test_send_message_to_session_prefers_task_list_pid(self):
        """When a pid is provided from the task list, use it before filename parsing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = os.path.join(tmpdir, "s1.2000.step-1.task.stdout")
            pipe_path = os.path.join(tmpdir, "s1.1000.session.pipe")
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
class TestStreamingCtxBtw(unittest.TestCase):
    """Tests for /ctx.btw in streaming/runtime scope."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    @patch("cli_topsailai.streaming.print_header")
    @patch("cli_topsailai.streaming.subprocess.run")
    @patch("cli_topsailai.state.running", False)
    def test_stream_file_sets_runtime_scope_while_streaming(
        self, mock_run, mock_header
    ):
        """stream_file should switch to runtime scope while streaming."""
        captured = {}

        def capture_header(title):
            captured["scope"] = cli_state.current_scope
            captured["session_id"] = cli_state.current_session_id

        mock_header.side_effect = capture_header

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("log line\n")
            path = f.name
        try:
            stream_file(path, default_session_id="s1")
        finally:
            os.unlink(path)

        self.assertEqual(captured.get("scope"), "runtime")
        self.assertEqual(captured.get("session_id"), "s1")
        self.assertEqual(cli_state.current_scope, "workspace")
        self.assertIsNone(cli_state.current_session_id)

    @patch("cli_topsailai.streaming._can_use_curses", return_value=False)
    @patch("cli_topsailai.streaming.subprocess.run")
    def test_stream_file_cd_restores_workspace_scope(
        self, mock_run, mock_can_use_curses
    ):
        """stream_file with cd input should restore workspace scope."""
        cli_state.running = True
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("log line\n")
            path = f.name
        try:
            with patch("sys.stdin.isatty", return_value=True):
                with patch(
                    "cli_topsailai.streaming.select.select",
                    return_value=([sys.stdin], [], []),
                ):
                    with patch("builtins.input", return_value="cd"):
                        stream_file(path, default_session_id="s1")
        finally:
            os.unlink(path)

        self.assertEqual(cli_state.current_scope, "workspace")
        self.assertIsNone(cli_state.current_session_id)
        mock_can_use_curses.assert_called_once_with()

    def test_match_ctx_btw_in_runtime_scope(self):
        """/ctx.btw should match in runtime scope and extract message."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session", "runtime"],
                "shell": "topsailai_session_add_agent2llm_message -s '{session_id}' -m '{message}'",
            }
        ]
        matched = match_yaml_command("/ctx.btw hello world!", "/tmp/task")
        self.assertIsNotNone(matched)
        instruction, variables = matched
        self.assertEqual(variables.get("session_id"), "s1")
        self.assertEqual(variables.get("message"), "hello world!")

    def test_match_ctx_btw_without_args_in_runtime_scope(self):
        """/ctx.btw without args should match with empty message."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session", "runtime"],
                "shell": "topsailai_session_add_agent2llm_message -s '{session_id}' -m '{message}'",
            }
        ]
        matched = match_yaml_command("/ctx.btw", "/tmp/task")
        self.assertIsNotNone(matched)
        instruction, variables = matched
        self.assertEqual(variables.get("session_id"), "s1")
        self.assertEqual(variables.get("message"), "")

    @patch("cli_topsailai.process.run_external_command")
    @patch("builtins.input", side_effect=["line one", "line two", "", EOFError])
    def test_handle_ctx_btw_multiline_in_runtime_scope(
        self, mock_input, mock_run
    ):
        """/ctx.btw without args should read multi-line input until EOF."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = []
        instruction = {
            "cmd": "/ctx.btw",
            "scopes": ["session", "runtime"],
            "shell": "topsailai_session_add_agent2llm_message -s '{session_id}' -m '{message}'",
        }
        variables = {"session_id": "s1", "message": "", "task_dir": "/tmp/task"}
        handle_yaml_command(instruction, variables)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd_list = call_args[0][0]
        self.assertIn("topsailai_session_add_agent2llm_message", cmd_list)
        # The message should be quoted and contain both lines.
        joined = " ".join(cmd_list)
        self.assertIn("line one", joined)
        self.assertIn("line two", joined)

    @patch("cli_topsailai.process.run_external_command")
    def test_handle_ctx_btw_inline_args_in_runtime_scope(self, mock_run):
        """/ctx.btw with inline args should pass them as the message."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = []
        instruction = {
            "cmd": "/ctx.btw",
            "scopes": ["session", "runtime"],
            "shell": "topsailai_session_add_agent2llm_message -s '{session_id}' -m '{message}'",
        }
        variables = {
            "session_id": "s1",
            "message": "hello world!",
            "task_dir": "/tmp/task",
        }
        handle_yaml_command(instruction, variables)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd_list = call_args[0][0]
        joined = " ".join(cmd_list)
        self.assertIn("hello world!", joined)

    @patch("cli_topsailai.process.run_external_command")
    def test_handle_stream_ctx_btw_delegates_to_yaml_command(self, mock_run):
        """_handle_stream_ctx_btw should delegate to the YAML command handler."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session", "runtime"],
                "shell": "topsailai_session_add_agent2llm_message -s '{session_id}' -m '{message}'",
            }
        ]
        _handle_stream_ctx_btw("/ctx.btw remember to check logs", "/tmp/task")

        mock_run.assert_called_once()
        cmd_list = mock_run.call_args[0][0]
        joined = " ".join(cmd_list)
        self.assertIn("remember to check logs", joined)

    @patch("cli_topsailai.process.run_external_command")
    def test_handle_stream_ctx_btw_forwards_watched_pid(self, mock_run):
        """Runtime /ctx.btw must pass the watched PID so delivery is single-PID."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session", "runtime"],
                "shell": (
                    "topsailai_session_add_agent2llm_message "
                    "-s '{session_id}' -m '{message}' -p '{pid}'"
                ),
            }
        ]
        _handle_stream_ctx_btw(
            "/ctx.btw remember to check logs",
            "/tmp/task",
            default_pid=424242,
        )

        mock_run.assert_called_once()
        cmd_list = mock_run.call_args[0][0]
        joined = " ".join(cmd_list)
        self.assertIn("-p 424242", joined)

    @patch("cli_topsailai.process.run_external_command")
    def test_handle_stream_ctx_btw_without_pid_leaves_no_flag(self, mock_run):
        """Without a watched PID no -p flag should be emitted (session scope)."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session", "runtime"],
                "shell": (
                    "topsailai_session_add_agent2llm_message "
                    "-s '{session_id}' -m '{message}' -p '{pid}'"
                ),
            }
        ]
        _handle_stream_ctx_btw("/ctx.btw hello world!", "/tmp/task")

        mock_run.assert_called_once()
        cmd_list = mock_run.call_args[0][0]
        joined = " ".join(cmd_list)
        # The {pid} placeholder resolves to an empty value; the shell template
        # still contains '-p' but with nothing after it.
        self.assertNotRegex(joined, r"-p\s+\d+")

if __name__ == "__main__":
    unittest.main()
