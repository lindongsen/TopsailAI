#!/usr/bin/env python3
"""
Unit tests for the raw runtime streaming mode in cli_topsailai.streaming.
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
from cli_topsailai.streaming import (
    _dispatch_input,
    _extract_session_id_from_path,
    _handle_stream_ctx_btw,
    _handle_stream_send,
    _read_input_line,
    _stream_file_raw,
    _tail_file,
)


class TestExtractSessionIdFromPath(unittest.TestCase):
    """Tests for _extract_session_id_from_path."""

    def test_named_session(self):
        result = _extract_session_id_from_path("/tmp/my-session.1234.session.stdout")
        self.assertEqual(result, "my-session")

    def test_temp_session(self):
        result = _extract_session_id_from_path("/tmp/topsailai.1234.session.stdout")
        self.assertIsNone(result)

    def test_generic_stdout(self):
        result = _extract_session_id_from_path("/tmp/some.1234.stdout")
        self.assertIsNone(result)


class TestTailFile(unittest.TestCase):
    """Tests for _tail_file."""

    @patch("cli_topsailai.streaming.subprocess.run")
    def test_uses_system_tail_when_available(self, mock_run):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            path = f.name
        try:
            _tail_file(path, 2)
            mock_run.assert_called_once_with(
                ["tail", "-n", "2", path], check=False
            )
        finally:
            os.unlink(path)

    @patch("cli_topsailai.streaming.subprocess.run")
    def test_falls_back_to_python_tail(self, mock_run):
        mock_run.side_effect = FileNotFoundError("tail not found")
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            for i in range(10):
                f.write(f"line{i}\n")
            path = f.name
        try:
            with patch("builtins.print") as mock_print:
                _tail_file(path, 3)
            printed = [call[0][0] for call in mock_print.call_args_list]
            self.assertEqual(printed, ["line7\n", "line8\n", "line9\n"])
        finally:
            os.unlink(path)


class TestReadInputLine(unittest.TestCase):
    """Tests for _read_input_line."""

    @patch("cli_topsailai.streaming.input", return_value="  hello  ")
    def test_strips_input(self, mock_input):
        self.assertEqual(_read_input_line(), "hello")

    @patch("cli_topsailai.streaming.input", side_effect=EOFError)
    def test_eof_returns_none(self, mock_input):
        self.assertIsNone(_read_input_line())

    @patch("cli_topsailai.streaming.input", side_effect=KeyboardInterrupt)
    def test_interrupt_returns_none(self, mock_input):
        self.assertIsNone(_read_input_line())


class TestDispatchRawInput(unittest.TestCase):
    """Tests for _dispatch_input."""

    def test_quit_exits(self):
        for cmd in ("q", "quit", "exit", "QUIT"):
            with self.subTest(cmd=cmd):
                result = _dispatch_input(
                    cmd, "/task", [], "s1", "/task/s.log"
                )
                self.assertFalse(result)

    def test_cd_exits(self):
        for cmd in ("cd", "/cd", "CD"):
            with self.subTest(cmd=cmd):
                result = _dispatch_input(
                    cmd, "/task", [], "s1", "/task/s.log"
                )
                self.assertFalse(result)

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_slash_command_delegates(self, mock_handle):
        result = _dispatch_input(
            "/send hello", "/task", [], "s1", "/task/s.log"
        )
        self.assertTrue(result)
        mock_handle.assert_called_once_with(
            "/send hello", "/task", [], "s1", "/task/s.log"
        )

    def test_unknown_command_prints_error(self):
        with patch("builtins.print") as mock_print:
            result = _dispatch_input(
                "what", "/task", [], "s1", "/task/s.log"
            )
        self.assertTrue(result)
        self.assertTrue(
            any(
                "Unknown streaming command" in str(call)
                for call in mock_print.call_args_list
            )
        )


class TestStreamFileRaw(unittest.TestCase):
    """Tests for _stream_file_raw end-to-end behavior."""

    def setUp(self):
        cli_state.running = True

    def tearDown(self):
        cli_state.running = True
        cli_state._child_processes.clear()

    @patch("cli_topsailai.streaming.subprocess.run")
    @patch("cli_topsailai.streaming.sys.stdin.isatty", return_value=True)
    @patch("cli_topsailai.streaming.select.select")
    @patch("cli_topsailai.streaming._read_input_line")
    def test_streams_and_quits(
        self,
        mock_read,
        mock_select,
        mock_isatty,
        mock_run,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "s1.1234.session.stdout")
            with open(path, "w") as f:
                f.write("existing line\n")

            mock_select.side_effect = [([sys.stdin], [], []), ([], [], [])]
            mock_read.return_value = "q"

            _stream_file_raw(path, tmpdir, [], "s1", path, tail_lines=1)

            mock_run.assert_called_once_with(
                ["tail", "-n", "1", path], check=False
            )

    @patch("cli_topsailai.streaming.subprocess.run")
    @patch("cli_topsailai.streaming.sys.stdin.isatty", return_value=True)
    @patch("cli_topsailai.streaming.select.select")
    @patch("cli_topsailai.streaming._read_input_line")
    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_send_command_in_raw_mode(
        self,
        mock_handle,
        mock_read,
        mock_select,
        mock_isatty,
        mock_run,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "s1.1234.session.stdout")
            with open(path, "w") as f:
                f.write("existing line\n")

            mock_select.side_effect = [([sys.stdin], [], []), ([], [], [])]
            mock_read.side_effect = ["/send hello", "q"]

            _stream_file_raw(path, tmpdir, [], "s1", path, tail_lines=1)

            mock_handle.assert_called_once_with(
                "/send hello", tmpdir, [], "s1", path
            )

    @patch("cli_topsailai.streaming.subprocess.run")
    @patch("cli_topsailai.streaming.sys.stdin.isatty", return_value=False)
    def test_non_tty_exits_when_running_becomes_false(
        self,
        mock_isatty,
        mock_run,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "s1.1234.session.stdout")
            with open(path, "w") as f:
                f.write("existing line\n")

            def stop_running(*args, **kwargs):
                cli_state.running = False
                return True

            with patch(
                "cli_topsailai.streaming.time.sleep", side_effect=stop_running
            ):
                _stream_file_raw(path, tmpdir, [], "s1", path, tail_lines=1)

            self.assertFalse(cli_state.running)

    def test_file_not_found_prints_error(self):
        with patch("builtins.print") as mock_print:
            _stream_file_raw(
                "/nonexistent/path.log", "/task", [], "s1", "/task/s.log"
            )
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(
            any("File not found" in str(p) for p in printed)
        )


class TestHandleStreamSendRestored(unittest.TestCase):
    """Tests that _handle_stream_send routes through the session pipe."""

    @patch("cli_topsailai.streaming.send_message_to_session")
    def test_inline_message_uses_session_pipe(self, mock_send):
        _handle_stream_send(
            "/send hello world",
            "/task",
            [],
            "s1",
            "/task/s1.1234.session.stdout",
        )
        mock_send.assert_called_once_with(
            "s1", "hello world", "/task",
            stdout_path="/task/s1.1234.session.stdout"
        )

    @patch("cli_topsailai.streaming.send_message_to_session")
    @patch("cli_topsailai.streaming._read_multiline_input_for_send", return_value="line1\nline2")
    def test_multiline_message_uses_session_pipe(self, mock_read, mock_send):
        _handle_stream_send(
            "/send",
            "/task",
            [],
            "s1",
            "/task/s1.1234.session.stdout",
        )
        mock_read.assert_called_once()
        mock_send.assert_called_once_with(
            "s1", "line1\nline2", "/task",
            stdout_path="/task/s1.1234.session.stdout"
        )

    def test_missing_session_prints_error(self):
        with patch("builtins.print") as mock_print:
            _handle_stream_send(
                "/send hello",
                "/task",
                [],
                None,
                "/task/s1.1234.session.stdout",
            )
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(
            any("No session associated" in str(p) for p in printed)
        )


class TestHandleStreamCtxBtwRestored(unittest.TestCase):
    """Tests that _handle_stream_ctx_btw delegates to yaml_commands."""

    @patch("cli_topsailai.streaming.yaml_commands.handle_yaml_command")
    @patch(
        "cli_topsailai.streaming.yaml_commands.match_yaml_command",
        return_value=({"shell": "echo hi"}, {"message": "hi"}),
    )
    def test_delegates_to_yaml_command(self, mock_match, mock_handle):
        _handle_stream_ctx_btw("/ctx.btw hi", "/task")
        mock_match.assert_called_once_with("/ctx.btw hi", "/task")
        mock_handle.assert_called_once_with({"shell": "echo hi"}, {"message": "hi"})

    @patch("cli_topsailai.streaming.yaml_commands.match_yaml_command", return_value=None)
    def test_unmatched_command_prints_error(self, mock_match):
        with patch("builtins.print") as mock_print:
            _handle_stream_ctx_btw("/ctx.btw hi", "/task")
        mock_match.assert_called_once_with("/ctx.btw hi", "/task")
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(
            any("Could not match /ctx.btw" in str(p) for p in printed)
        )


if __name__ == "__main__":
    unittest.main()
