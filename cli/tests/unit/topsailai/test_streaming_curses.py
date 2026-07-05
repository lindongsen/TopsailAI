#!/usr/bin/env python3
"""
Unit tests for the curses-based streaming UI path in cli_topsailai.streaming.
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
    _CursesOutputCapture,
    _build_stream_command_handler,
    _can_use_curses,
    _run_curses_ui,
    stream_file,
)


class TestCanUseCurses(unittest.TestCase):
    """Tests for _can_use_curses delegation."""

    @patch("cli_topsailai.tui.is_curses_available", return_value=True)
    def test_returns_true_when_available(self, mock_available):
        self.assertTrue(_can_use_curses())
        mock_available.assert_called_once_with()

    @patch("cli_topsailai.tui.is_curses_available", return_value=False)
    def test_returns_false_when_unavailable(self, mock_available):
        self.assertFalse(_can_use_curses())
        mock_available.assert_called_once_with()


class TestStreamFileCursesPath(unittest.TestCase):
    """Tests for stream_file choosing the curses or legacy path."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    @patch("cli_topsailai.streaming._run_curses_ui")
    @patch("cli_topsailai.streaming._can_use_curses", return_value=True)
    def test_uses_curses_when_available(
        self, mock_can_use, mock_run_curses
    ):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("log line\n")
            path = f.name
        try:
            stream_file(
                path,
                task_dir="/tmp/tasks",
                log_files=[],
                default_session_id="s1",
                default_stdout_path="/tmp/tasks/s1.123.session.stdout",
            )
        finally:
            os.unlink(path)

        mock_can_use.assert_called_once_with()
        mock_run_curses.assert_called_once_with(
            path,
            "/tmp/tasks",
            [],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
        )
        self.assertEqual(cli_state.current_scope, "workspace")
        self.assertIsNone(cli_state.current_session_id)

    @patch("cli_topsailai.streaming._stream_file_legacy")
    @patch("cli_topsailai.streaming._can_use_curses", return_value=False)
    def test_falls_back_to_legacy_when_unavailable(
        self, mock_can_use, mock_legacy
    ):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("log line\n")
            path = f.name
        try:
            stream_file(
                path,
                task_dir="/tmp/tasks",
                log_files=[],
                default_session_id="s1",
                default_stdout_path="/tmp/tasks/s1.123.session.stdout",
            )
        finally:
            os.unlink(path)

        mock_can_use.assert_called_once_with()
        mock_legacy.assert_called_once_with(
            path,
            "/tmp/tasks",
            [],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
        )
        self.assertEqual(cli_state.current_scope, "workspace")
        self.assertIsNone(cli_state.current_session_id)


class TestRunCursesUi(unittest.TestCase):
    """Tests for _run_curses_ui construction and wiring."""

    @patch("cli_topsailai.tui.CursesStreamUI")
    @patch("cli_topsailai.streaming._build_stream_command_handler")
    def test_builds_ui_and_runs(self, mock_build_handler, mock_ui_cls):
        mock_ui = MagicMock()
        mock_ui_cls.return_value = mock_ui
        mock_handler = MagicMock()
        mock_build_handler.return_value = mock_handler

        _run_curses_ui(
            "/tmp/test.log",
            "/tmp/tasks",
            [{"filename": "s1.stdout"}],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
        )

        mock_ui_cls.assert_called_once()
        call_kwargs = mock_ui_cls.call_args.kwargs
        self.assertEqual(call_kwargs["filepath"], "/tmp/test.log")
        self.assertEqual(call_kwargs["task_dir"], "/tmp/tasks")
        self.assertEqual(call_kwargs["log_files"], [{"filename": "s1.stdout"}])
        self.assertEqual(call_kwargs["default_session_id"], "s1")
        self.assertEqual(
            call_kwargs["default_stdout_path"], "/tmp/tasks/s1.123.session.stdout"
        )
        self.assertTrue(callable(call_kwargs["command_handler"]))
        mock_build_handler.assert_called_once_with(
            mock_ui,
            "/tmp/tasks",
            [{"filename": "s1.stdout"}],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
        )
        mock_ui.run.assert_called_once_with()

    @patch("cli_topsailai.tui.CursesStreamUI")
    @patch("cli_topsailai.streaming._build_stream_command_handler")
    def test_command_handler_delegates_to_built_handler(
        self, mock_build_handler, mock_ui_cls
    ):
        mock_ui = MagicMock()
        mock_ui_cls.return_value = mock_ui
        mock_handler = MagicMock(return_value=True)
        mock_build_handler.return_value = mock_handler

        _run_curses_ui(
            "/tmp/test.log",
            "/tmp/tasks",
            [],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
        )

        command_handler = mock_ui_cls.call_args.kwargs["command_handler"]
        result = command_handler("/send hello")

        mock_handler.assert_called_once_with("/send hello")
        self.assertTrue(result)


class TestCursesOutputCapture(unittest.TestCase):
    """Tests for _CursesOutputCapture stdout/stderr redirection."""

    def setUp(self):
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.ui = MagicMock()

    def tearDown(self):
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

    def test_write_buffers_until_newline(self):
        capture = _CursesOutputCapture(self.ui)
        capture.write("hello")
        self.assertEqual(capture._buffer, ["hello"])
        self.ui.append_status.assert_not_called()
        capture.write(" world\n")
        self.ui.append_status.assert_called_once_with("hello world")

    def test_write_multiple_newlines(self):
        capture = _CursesOutputCapture(self.ui)
        capture.write("line1\nline2\n")
        self.assertEqual(
            self.ui.append_status.call_args_list,
            [(("line1",),), (("line2",),)],
        )

    def test_flush_calls_original_flush(self):
        mock_stdout = MagicMock()
        mock_stdout.flush = MagicMock()
        sys.stdout = mock_stdout
        sys.stderr = mock_stdout

        capture = _CursesOutputCapture(self.ui)
        capture.write("status\n")
        capture.flush()

        mock_stdout.flush.assert_called_once()
        self.ui.append_status.assert_called_once_with("status")

    def test_flush_empty_buffer_does_nothing(self):
        capture = _CursesOutputCapture(self.ui)
        capture.flush()
        self.ui.append_status.assert_not_called()

    def test_context_manager_redirects_stdout_stderr(self):
        fake_stdout = MagicMock()
        fake_stderr = MagicMock()
        sys.stdout = fake_stdout
        sys.stderr = fake_stderr

        capture = _CursesOutputCapture(self.ui)
        with capture:
            self.assertIs(sys.stdout, capture)
            self.assertIs(sys.stderr, capture)

        self.assertIs(sys.stdout, fake_stdout)
        self.assertIs(sys.stderr, fake_stderr)

    def test_context_manager_restores_on_exception(self):
        fake_stdout = MagicMock()
        fake_stderr = MagicMock()
        sys.stdout = fake_stdout
        sys.stderr = fake_stderr

        capture = _CursesOutputCapture(self.ui)
        with self.assertRaises(RuntimeError):
            with capture:
                raise RuntimeError("boom")

        self.assertIs(sys.stdout, fake_stdout)
        self.assertIs(sys.stderr, fake_stderr)

    def test_flush_on_exit(self):
        capture = _CursesOutputCapture(self.ui)
        with capture:
            print("printed line")

        self.assertTrue(
            any("printed line" in str(call) for call in self.ui.append_status.call_args_list)
        )


class TestBuildStreamCommandHandler(unittest.TestCase):
    """Tests for _build_stream_command_handler behavior."""

    def setUp(self):
        self.ui = MagicMock()
        self.ui.read_multi_line_blocking.return_value = "multi-line message"
        self.handler = _build_stream_command_handler(
            self.ui,
            "/tmp/tasks",
            [{"filename": "s1.stdout"}],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
        )

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_quit_returns_false(self, mock_handle):
        self.assertFalse(self.handler("q"))
        self.assertFalse(self.handler("quit"))
        self.assertFalse(self.handler("QUIT"))
        mock_handle.assert_not_called()

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_send_command_delegates(self, mock_handle):
        result = self.handler("/send hello")
        self.assertTrue(result)
        mock_handle.assert_called_once()
        args = mock_handle.call_args
        self.assertEqual(args[0][0], "/send hello")
        self.assertEqual(args[0][1], "/tmp/tasks")
        self.assertEqual(args[0][3], "s1")
        self.assertEqual(args[0][4], "/tmp/tasks/s1.123.session.stdout")
        self.assertIsNotNone(args[1]["input_provider"])

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_ctx_btw_command_delegates(self, mock_handle):
        result = self.handler("/ctx.btw remember this")
        self.assertTrue(result)
        mock_handle.assert_called_once()
        args = mock_handle.call_args
        self.assertEqual(args[0][0], "/ctx.btw remember this")
        self.assertIsNotNone(args[1]["input_provider"])

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_help_command_delegates(self, mock_handle):
        result = self.handler("/help")
        self.assertTrue(result)
        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args[0][0], "/help")

    def test_unknown_command_appends_status(self):
        result = self.handler("not-a-command")
        self.assertTrue(result)
        self.ui.append_status.assert_called_once()
        status = self.ui.append_status.call_args[0][0]
        self.assertIn("Unknown streaming command", status)
        self.assertIn("/send", status)

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_input_provider_uses_ui_multi_line(self, mock_handle):
        result = self.handler("/send")
        self.assertTrue(result)
        provider = mock_handle.call_args[1]["input_provider"]
        message = provider("prompt")
        self.ui.read_multi_line_blocking.assert_called_once_with("prompt")
        self.assertEqual(message, "multi-line message")

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_captures_stdout_during_command(self, mock_handle):
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        try:
            fake_stdout = MagicMock()
            fake_stdout.flush = MagicMock()
            sys.stdout = fake_stdout
            sys.stderr = fake_stdout

            def side_effect(*args, **kwargs):
                print("captured output")

            mock_handle.side_effect = side_effect
            self.handler("/send hello")

            self.assertTrue(
                any(
                    "captured output" in str(call)
                    for call in self.ui.append_status.call_args_list
                )
            )
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


if __name__ == "__main__":
    unittest.main()
