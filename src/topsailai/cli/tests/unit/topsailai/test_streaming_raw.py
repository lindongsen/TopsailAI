#!/usr/bin/env python3
"""
Unit tests for the raw runtime streaming mode in cli_topsailai.streaming.
"""

import io
import json
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
    _build_runtime_prompt,
    _dispatch_input,
    _extract_session_id_from_path,
    _handle_stream_command,
    _handle_stream_ctx_btw,
    _handle_stream_meta,
    _handle_stream_send,
    _prompt_send_as_message,
    _read_input_line,
    _read_input_line_tty,
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


class TestBuildRuntimePrompt(unittest.TestCase):
    """Tests for _build_runtime_prompt."""

    def test_named_session_is_cyan(self):
        prompt = _build_runtime_prompt("my-session")
        self.assertIn("[runtime:my-session]>", prompt)
        self.assertIn("\033[36m", prompt)
        self.assertIn("\033[0m", prompt)

    def test_temp_session_uses_temp_label(self):
        prompt = _build_runtime_prompt(None)
        self.assertIn("[runtime:(temp)]>", prompt)
        self.assertIn("\033[36m", prompt)
        self.assertIn("\033[0m", prompt)

    def test_prompt_content_unchanged(self):
        prompt = _build_runtime_prompt("abc-123")
        plain = prompt.replace("\033[36m", "").replace("\033[0m", "")
        self.assertEqual(plain, "[runtime:abc-123]> ")

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

    def test_quit_exits(self):
        for cmd in ("q", "quit", "exit", "QUIT"):
            with self.subTest(cmd=cmd):
                result = _dispatch_input(
                    cmd, "/task", [], "s1", "/task/s.log", default_pid=None
                )
                self.assertFalse(result)

    def test_cd_exits(self):
        for cmd in ("cd", "/cd", "CD"):
            with self.subTest(cmd=cmd):
                result = _dispatch_input(
                    cmd, "/task", [], "s1", "/task/s.log", default_pid=None
                )
                self.assertFalse(result)

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_slash_command_delegates(self, mock_handle):
        result = _dispatch_input(
            "/send hello", "/task", [], "s1", "/task/s.log", default_pid=None
        )
        self.assertTrue(result)
        mock_handle.assert_called_once_with(
            "/send hello",
            "/task",
            [],
            "s1",
            "/task/s.log",
            None,
            default_session_pid=None,
        )

    @patch("cli_topsailai.streaming._prompt_send_as_message")
    def test_unknown_command_prompts_send_as_message(self, mock_prompt):
        mock_prompt.return_value = True
        result = _dispatch_input(
            "what", "/task", [], "s1", "/task/s.log", default_pid=None
        )
        self.assertTrue(result)
        mock_prompt.assert_called_once_with(
            "what",
            "/task",
            [],
            "s1",
            "/task/s.log",
            None,
            input_provider=None,
            output_callback=None,
            input_callback=None,
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

            _stream_file_raw(path, tmpdir, [], "s1", path, default_pid=1234, tail_lines=1)

            mock_run.assert_called_once_with(
                ["tail", "-n", "1", path], check=False
            )
            prompt = mock_read.call_args[0][0]
            self.assertIn("[runtime:s1]>", prompt)
            self.assertIn("\033[36m", prompt)
            self.assertIn("\033[0m", prompt)

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

            _stream_file_raw(path, tmpdir, [], "s1", path, default_pid=1234, tail_lines=1)

            mock_handle.assert_called_once_with(
                "/send hello",
                tmpdir,
                [],
                "s1",
                path,
                1234,
                default_session_pid=None,
            )
            prompt = mock_read.call_args[0][0]
            self.assertIn("[runtime:s1]>", prompt)
            self.assertIn("\033[36m", prompt)
            self.assertIn("\033[0m", prompt)

    @patch("cli_topsailai.streaming.subprocess.run")
    @patch("cli_topsailai.streaming.sys.stdin.isatty", return_value=True)
    @patch("cli_topsailai.streaming.select.select")
    @patch("cli_topsailai.streaming._read_input_line")
    @patch("cli_topsailai.streaming._prompt_send_as_message")
    def test_unknown_command_prompts_in_raw_mode(
        self,
        mock_prompt,
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
            mock_read.side_effect = ["hello", "q"]
            mock_prompt.return_value = True

            _stream_file_raw(path, tmpdir, [], "s1", path, default_pid=1234, tail_lines=1)

            mock_prompt.assert_called_once_with(
                "hello",
                tmpdir,
                [],
                "s1",
                path,
                1234,
                input_provider=None,
                output_callback=None,
                input_callback=None,
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
                _stream_file_raw(path, tmpdir, [], "s1", path, default_pid=1234, tail_lines=1)

            self.assertFalse(cli_state.running)

    def test_file_not_found_prints_error(self):
        with patch("builtins.print") as mock_print:
            _stream_file_raw(
                "/nonexistent/path.log", "/task", [], "s1", "/task/s.log", default_pid=None
            )
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(
            any("File not found" in str(p) for p in printed)
        )


class TestHandleStreamMeta(unittest.TestCase):
    """Tests for runtime session metadata display."""

    def test_prints_parent_session_meta_for_task_log(self):
        with tempfile.TemporaryDirectory() as task_dir:
            meta_path = os.path.join(task_dir, "s1.4321.session.meta")
            with open(meta_path, "w", encoding="utf-8") as meta_file:
                meta_file.write("{\"project_workspace\": \"/work/demo\"}\n")

            with patch("builtins.print") as mock_print:
                _handle_stream_command(
                    "/meta",
                    task_dir,
                    [],
                    "s1",
                    os.path.join(task_dir, "s1.9876.step.task.stdout"),
                    default_pid=9876,
                    default_session_pid=4321,
                )

        mock_print.assert_called_once_with(
            '{"project_workspace": "/work/demo"}\n', end=""
        )

    def test_missing_meta_file_prints_error(self):
        with tempfile.TemporaryDirectory() as task_dir:
            with patch("builtins.print") as mock_print:
                _handle_stream_meta(task_dir, "s1", 4321)

        printed = " ".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("Could not read session metadata", printed)
        self.assertIn("s1.4321.session.meta", printed)

    def test_missing_parent_session_pid_prints_error(self):
        with patch("builtins.print") as mock_print:
            _handle_stream_meta("/task", "s1", None)

        printed = " ".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("Session metadata is unavailable", printed)


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
            default_pid=1234,
        )
        mock_send.assert_called_once_with(
            "s1", "hello world", "/task",
            stdout_path="/task/s1.1234.session.stdout", pid=1234
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
            default_pid=1234,
        )
        mock_read.assert_called_once()
        mock_send.assert_called_once_with(
            "s1", "line1\nline2", "/task",
            stdout_path="/task/s1.1234.session.stdout", pid=1234
        )

    def test_missing_session_prints_error(self):
        with patch("builtins.print") as mock_print:
            _handle_stream_send(
                "/send hello",
                "/task",
                [],
                None,
                "/task/s1.1234.session.stdout",
                default_pid=1234,
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


class TestPromptSendAsMessageRaw(unittest.TestCase):
    """Tests for the yes/no prompt in raw/legacy mode."""

    @patch("cli_topsailai.streaming._handle_stream_command")
    @patch("builtins.input")
    def test_yes_sends_input(self, mock_input, mock_handle):
        mock_input.return_value = "y"
        result = _prompt_send_as_message(
            "hello",
            "/tmp/tasks",
            [],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
            default_pid=123,
        )
        self.assertTrue(result)
        mock_input.assert_called_once_with("Send as message? [y/N]: ")
        mock_handle.assert_called_once_with(
            "/send hello",
            "/tmp/tasks",
            [],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
            123,
            input_provider=None,
        )

    @patch("cli_topsailai.streaming._handle_stream_command")
    @patch("builtins.input")
    def test_no_preserves_unknown_command(self, mock_input, mock_handle):
        mock_input.return_value = "n"
        with patch("builtins.print") as mock_print:
            result = _prompt_send_as_message(
                "hello",
                "/tmp/tasks",
                [],
                "s1",
                "/tmp/tasks/s1.123.session.stdout",
            )
        self.assertTrue(result)
        mock_handle.assert_not_called()
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(
            any("Unknown streaming command" in str(p) for p in printed)
        )

    @patch("cli_topsailai.streaming._handle_stream_command")
    @patch("builtins.input")
    def test_eof_returns_false(self, mock_input, mock_handle):
        mock_input.side_effect = EOFError
        result = _prompt_send_as_message(
            "hello",
            "/tmp/tasks",
            [],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
            default_pid=123,
        )
        self.assertFalse(result)
        mock_handle.assert_not_called()


class TestReadInputLineTty(unittest.TestCase):
    """Tests for the raw TTY line editor used in runtime scope."""

    def _run_tty_input(self, input_bytes, prompt="", already_raw=True):
        stdout = io.StringIO()
        stdin_buffer = io.BytesIO(input_bytes)
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        mock_stdin.fileno.return_value = 0
        mock_stdin.buffer = stdin_buffer

        with patch("cli_topsailai.streaming.sys.stdin", mock_stdin), \
             patch("cli_topsailai.streaming.sys.stdout", stdout), \
             patch("cli_topsailai.streaming.termios") as mock_termios, \
             patch("cli_topsailai.streaming.tty") as mock_tty:
            mock_termios.tcgetattr.return_value = []
            return _read_input_line_tty(prompt, already_raw=already_raw), stdout.getvalue()

    def test_csi_left_arrow_inserts_at_correct_position(self):
        # Type "ab", move cursor left, type "c", press enter.
        result, _ = self._run_tty_input(b"ab\x1b[Dc\r")
        self.assertEqual(result, "acb")

    def test_csi_right_arrow_moves_cursor(self):
        # Type "a", left twice, right once, type "b", press enter.
        result, _ = self._run_tty_input(b"a\x1b[D\x1b[D\x1b[Cb\r")
        self.assertEqual(result, "ab")

    def test_ss3_left_arrow_inserts_at_correct_position(self):
        # Type "ab", move cursor left via SS3 sequence, type "c", press enter.
        result, _ = self._run_tty_input(b"ab\x1bODc\r")
        self.assertEqual(result, "acb")

    def test_ss3_right_arrow_moves_cursor(self):
        # Type "a", left, right, type "b", press enter.
        result, _ = self._run_tty_input(b"a\x1bOD\x1bOCb\r")
        self.assertEqual(result, "ab")

    def test_home_and_end_keys(self):
        # Type "ab", home, type "x", end, type "y", press enter.
        result, _ = self._run_tty_input(b"ab\x1b[Hx\x1b[Fy\r")
        self.assertEqual(result, "xaby")

    def test_wide_character_cursor_positioning(self):
        # Type a CJK character (3 bytes UTF-8), left, type "a", enter.
        result, _ = self._run_tty_input("中\x1b[Da\r".encode("utf-8"))
        self.assertEqual(result, "a中")




class TestRuntimeHistory(unittest.TestCase):
    """Tests for runtime-scope history persistence and recall."""

    def setUp(self):
        self._orig_history_manager = getattr(cli_state, "history_manager", None)
        cli_state.history_manager = MagicMock()
        cli_state.history_manager.filter_entries.return_value = []

    def tearDown(self):
        cli_state.history_manager = self._orig_history_manager

    def test_append_runtime_history_delegates_to_manager(self):
        from cli_topsailai.streaming import _append_runtime_history

        _append_runtime_history("/send hello", "s1")
        cli_state.history_manager.append.assert_called_once_with(
            "runtime", "s1", "/send hello"
        )

    def test_append_runtime_history_ignores_empty_text(self):
        from cli_topsailai.streaming import _append_runtime_history

        _append_runtime_history("", "s1")
        cli_state.history_manager.append.assert_not_called()

    def test_load_runtime_history_returns_newest_first(self):
        from cli_topsailai.streaming import _load_runtime_history

        cli_state.history_manager.filter_entries.return_value = [
            "/send first",
            "/send second",
        ]
        result = _load_runtime_history("s1")
        self.assertEqual(result, ["/send second", "/send first"])
        cli_state.history_manager.filter_entries.assert_called_once_with(
            "runtime", "s1"
        )

    def test_persist_runtime_command_inserts_at_front(self):
        from cli_topsailai.streaming import _persist_runtime_command

        history: List[str] = []
        _persist_runtime_command("/send hello", "s1", history)
        self.assertEqual(history, ["/send hello"])
        cli_state.history_manager.append.assert_called_once_with(
            "runtime", "s1", "/send hello"
        )

    def test_persist_runtime_command_skips_consecutive_duplicate(self):
        from cli_topsailai.streaming import _persist_runtime_command

        history: List[str] = ["/send hello"]
        cli_state.history_manager.append.reset_mock()
        _persist_runtime_command("/send hello", "s1", history)
        self.assertEqual(history, ["/send hello"])
        cli_state.history_manager.append.assert_not_called()

    def test_persist_runtime_command_allows_non_consecutive_duplicate(self):
        from cli_topsailai.streaming import _persist_runtime_command

        history: List[str] = ["/send hello"]
        _persist_runtime_command("/send world", "s1", history)
        _persist_runtime_command("/send hello", "s1", history)
        self.assertEqual(history, ["/send hello", "/send world", "/send hello"])


class TestReadInputLineTtyHistory(unittest.TestCase):
    """Tests for Up/Down arrow history recall in the raw TTY editor."""

    def _run_tty_input(self, input_bytes, prompt="", history=None):
        stdout = io.StringIO()
        stdin_buffer = io.BytesIO(input_bytes)
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        mock_stdin.fileno.return_value = 0
        mock_stdin.buffer = stdin_buffer

        with patch("cli_topsailai.streaming.sys.stdin", mock_stdin), \
             patch("cli_topsailai.streaming.sys.stdout", stdout), \
             patch("cli_topsailai.streaming.termios") as mock_termios, \
             patch("cli_topsailai.streaming.tty") as mock_tty:
            mock_termios.tcgetattr.return_value = []
            return _read_input_line_tty(
                prompt, already_raw=True, session_id="s1", history=history
            )

    def test_up_arrow_recalls_previous_message(self):
        result = self._run_tty_input(
            b"\x1b[A\r", history=["/send hello", "/send world"]
        )
        self.assertEqual(result, "/send hello")

    def test_up_then_down_arrow_returns_to_empty_prompt(self):
        result = self._run_tty_input(
            b"\x1b[A\x1b[B\r", history=["/send hello"]
        )
        self.assertEqual(result, "")

    def test_down_arrow_at_newest_stays_empty(self):
        result = self._run_tty_input(
            b"\x1b[B\r", history=["/send hello"]
        )
        self.assertEqual(result, "")

    def test_up_arrow_beyond_oldest_clamps(self):
        result = self._run_tty_input(
            b"\x1b[A\x1b[A\x1b[A\r", history=["/send hello", "/send world"]
        )
        self.assertEqual(result, "/send world")

    def test_typing_after_recall_appends_to_recalled_text(self):
        result = self._run_tty_input(
            b"\x1b[Ax\r", history=["/send hello"]
        )
        self.assertEqual(result, "/send hellox")

if __name__ == "__main__":
    unittest.main()


class TestReadInputLineTtyCompletion(unittest.TestCase):
    """Tests for TAB completion in the raw TTY editor."""

    def setUp(self):
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = []

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    def _run_tty_input(self, input_bytes, prompt=""):
        stdout = io.StringIO()
        stdin_buffer = io.BytesIO(input_bytes)
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        mock_stdin.fileno.return_value = 0
        mock_stdin.buffer = stdin_buffer

        with patch("cli_topsailai.streaming.sys.stdin", mock_stdin), \
             patch("cli_topsailai.streaming.sys.stdout", stdout), \
             patch("cli_topsailai.streaming.termios") as mock_termios, \
             patch("cli_topsailai.streaming.tty") as mock_tty:
            mock_termios.tcgetattr.return_value = []
            return _read_input_line_tty(
                prompt, already_raw=True, session_id="s1"
            )

    def test_tab_completes_send_command(self):
        # Type "/se" then TAB, then Enter.
        result = self._run_tty_input(b"/se\t\r")
        self.assertEqual(result, "/send")

    def test_tab_cycles_through_candidates(self):
        # Type "/s" then TAB twice, then Enter.
        result = self._run_tty_input(b"/s\t\t\r")
        self.assertIn(result, ["/send", "/session"])

    def test_tab_with_no_match_keeps_buffer(self):
        # Type "/zzz" then TAB, then Enter.
        result = self._run_tty_input(b"/zzz\t\r")
        self.assertEqual(result, "/zzz")

    def test_tab_completes_quit(self):
        # Type "q" then TAB twice (first TAB stays on "q", second goes to "quit"), then Enter.
        result = self._run_tty_input(b"q\t\t\r")
        self.assertEqual(result, "quit")

    def test_typing_after_tab_resets_completion(self):
        # Type "/se", TAB (completes to /send), then type "x", then Enter.
        result = self._run_tty_input(b"/se\tx\r")
        self.assertEqual(result, "/sendx")


class TestHandleStreamCommandYamlDispatch(unittest.TestCase):
    """Tests that runtime-scope slash commands are delegated to the YAML engine."""

    def setUp(self):
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = []

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    @patch("cli_topsailai.streaming.help_text.print_help")
    def test_help_command_prints_help_for_current_scope(self, mock_print_help):
        """/help in runtime scope must list YAML commands available in runtime."""
        _handle_stream_command("/help", "/task", [], "s1", "/tmp/s1.stdout")
        mock_print_help.assert_called_once_with(
            cli_state.yaml_commands, "runtime", keyword=None
        )

    @patch("cli_topsailai.streaming.help_text.print_help")
    def test_help_with_keyword_prints_filtered_help(self, mock_print_help):
        """/help git in runtime scope must filter help by keyword."""
        _handle_stream_command("/help git", "/task", [], "s1", "/tmp/s1.stdout")
        mock_print_help.assert_called_once_with(
            cli_state.yaml_commands, "runtime", keyword="git"
        )

    @patch("cli_topsailai.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.yaml_commands.match_yaml_command")
    def test_git_status_delegates_to_yaml_engine(
        self, mock_match, mock_handle
    ):
        """/git.status in runtime scope must match and execute the YAML instruction."""
        instruction = {
            "cmd": "/git.status",
            "scopes": ["session", "runtime"],
            "shell": "git -C '{project_workspace}' status",
            "use_os_system": 1,
        }
        variables = {"session_id": "s1", "task_dir": "/task"}
        mock_match.return_value = (instruction, variables)
        mock_handle.return_value = "yaml_handled"

        _handle_stream_command("/git.status", "/task", [], "s1", "/tmp/s1.stdout")

        mock_match.assert_called_once_with("/git.status", "/task")
        mock_handle.assert_called_once_with(instruction, variables)

    @patch("cli_topsailai.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.yaml_commands.match_yaml_command")
    def test_git_diff_delegates_to_yaml_engine(
        self, mock_match, mock_handle
    ):
        """/git.diff in runtime scope must match and execute the YAML instruction."""
        instruction = {
            "cmd": "/git.diff",
            "scopes": ["session", "runtime"],
            "shell": "git -C '{project_workspace}' diff",
            "use_os_system": 1,
        }
        variables = {"session_id": "s1", "task_dir": "/task"}
        mock_match.return_value = (instruction, variables)
        mock_handle.return_value = "yaml_handled"

        _handle_stream_command("/git.diff", "/task", [], "s1", "/tmp/s1.stdout")

        mock_match.assert_called_once_with("/git.diff", "/task")
        mock_handle.assert_called_once_with(instruction, variables)

    @patch("cli_topsailai.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.yaml_commands.match_yaml_command")
    def test_git_with_args_delegates_to_yaml_engine(
        self, mock_match, mock_handle
    ):
        """/git log --oneline in runtime scope must match and execute the YAML instruction."""
        instruction = {
            "cmd": "/git {args}",
            "scopes": ["session", "runtime"],
            "shell": "git -C '{project_workspace}' {args}",
            "use_os_system": 1,
        }
        variables = {"session_id": "s1", "task_dir": "/task", "args": "log --oneline"}
        mock_match.return_value = (instruction, variables)
        mock_handle.return_value = "yaml_handled"

        _handle_stream_command(
            "/git log --oneline", "/task", [], "s1", "/tmp/s1.stdout"
        )

        mock_match.assert_called_once_with("/git log --oneline", "/task")
        mock_handle.assert_called_once_with(instruction, variables)

    @patch("cli_topsailai.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.yaml_commands.match_yaml_command")
    @patch("builtins.print")
    def test_unknown_slash_command_prints_error(
        self, mock_print, mock_match, mock_handle
    ):
        """An unmatched slash command in runtime scope must still print an error."""
        mock_match.return_value = None

        _handle_stream_command("/unknown", "/task", [], "s1", "/tmp/s1.stdout")

        mock_match.assert_called_once_with("/unknown", "/task")
        mock_handle.assert_not_called()
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("Unknown streaming command", printed)

    @patch("cli_topsailai.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.yaml_commands.match_yaml_command")
    def test_send_command_takes_precedence_over_yaml_matching(
        self, mock_match, mock_handle
    ):
        """/send must be handled by the dedicated send path, not the YAML engine."""
        with patch(
            "cli_topsailai.streaming._handle_stream_send"
        ) as mock_send:
            _handle_stream_command(
                "/send hello", "/task", [], "s1", "/tmp/s1.stdout"
            )
            mock_send.assert_called_once()
            mock_match.assert_not_called()
            mock_handle.assert_not_called()

    @patch("cli_topsailai.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.yaml_commands.match_yaml_command")
    def test_ctx_btw_command_takes_precedence_over_yaml_matching(
        self, mock_match, mock_handle
    ):
        """/ctx.btw must be handled by the dedicated context path, not the YAML engine."""
        with patch(
            "cli_topsailai.streaming._handle_stream_ctx_btw"
        ) as mock_ctx:
            _handle_stream_command(
                "/ctx.btw note", "/task", [], "s1", "/tmp/s1.stdout"
            )
            mock_ctx.assert_called_once()
            mock_match.assert_not_called()
            mock_handle.assert_not_called()
