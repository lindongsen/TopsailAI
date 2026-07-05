"""Unit tests for cli_topsailai.tui."""

import sys
import unittest
from unittest.mock import MagicMock, patch

from cli_topsailai.tui import (
    CursesStreamUI,
    _MAX_BUFFERED_LINES,
    _split_lines,
    _strip_ansi,
    is_curses_available,
)


class FakeCurses:
    """Minimal mock of the curses module for unit tests."""

    KEY_ENTER = 10
    KEY_BACKSPACE = 127
    KEY_RESIZE = 410
    KEY_PPAGE = 339
    KEY_NPAGE = 338
    COLOR_GREEN = 1
    COLOR_YELLOW = 2
    COLOR_RED = 3
    COLOR_CYAN = 4
    A_NORMAL = 0
    A_BOLD = 2097152
    error = Exception

    def __init__(self):
        self._pairs = {}
        self._ch_queue = []
        self._has_colors = True
        self._use_default_colors_error = False
        self._curs_set_error = False
        self._resize_term_error = False

    def wrapper(self, func):
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        return func(stdscr)

    def start_color(self):
        pass

    def use_default_colors(self):
        if self._use_default_colors_error:
            raise self.error("boom")

    def has_colors(self):
        return self._has_colors

    def init_pair(self, pair_id, fg, bg):
        self._pairs[pair_id] = (fg, bg)

    def color_pair(self, pair_id):
        return pair_id

    def curs_set(self, visibility):
        if self._curs_set_error:
            raise self.error("boom")

    def newpad(self, height, width):
        pad = MagicMock()
        pad.resize = MagicMock()
        return pad

    def napms(self, ms):
        pass

    def doupdate(self):
        pass

    def resize_term(self, height, width):
        if self._resize_term_error:
            raise self.error("boom")


class TestHelpers(unittest.TestCase):
    """Tests for module-level helper functions."""

    def test_strip_ansi_removes_escape_sequences(self):
        colored = "\x1b[32mhello\x1b[0m"
        self.assertEqual(_strip_ansi(colored), "hello")

    def test_strip_ansi_empty_string(self):
        self.assertEqual(_strip_ansi(""), "")

    def test_split_lines_preserves_newlines(self):
        self.assertEqual(_split_lines("a\nb\n"), ["a\n", "b\n"])

    def test_split_lines_no_trailing_newline(self):
        self.assertEqual(_split_lines("a\nb"), ["a\n", "b"])

    def test_split_lines_empty_string(self):
        self.assertEqual(_split_lines(""), [])


class TestIsCursesAvailable(unittest.TestCase):
    """Tests for the is_curses_available helper."""

    @patch.object(sys.stdout, "isatty", return_value=False)
    @patch.object(sys.stdin, "isatty", return_value=True)
    def test_returns_false_when_stdout_not_tty(self, _stdin, _stdout):
        self.assertFalse(is_curses_available())

    @patch.object(sys.stdout, "isatty", return_value=True)
    @patch.object(sys.stdin, "isatty", return_value=False)
    def test_returns_false_when_stdin_not_tty(self, _stdin, _stdout):
        self.assertFalse(is_curses_available())

    @patch.dict("os.environ", {"TERM": ""}, clear=True)
    @patch.object(sys.stdout, "isatty", return_value=True)
    @patch.object(sys.stdin, "isatty", return_value=True)
    def test_returns_false_when_term_missing(self, _stdin, _stdout):
        self.assertFalse(is_curses_available())

    @patch.dict("os.environ", {"TERM": "dumb"}, clear=True)
    @patch.object(sys.stdout, "isatty", return_value=True)
    @patch.object(sys.stdin, "isatty", return_value=True)
    def test_returns_false_when_term_dumb(self, _stdin, _stdout):
        self.assertFalse(is_curses_available())

    @patch.dict("os.environ", {"TERM": "xterm-256color"}, clear=True)
    @patch.object(sys.stdout, "isatty", return_value=True)
    @patch.object(sys.stdin, "isatty", return_value=True)
    def test_returns_true_when_curses_usable(self, _stdin, _stdout):
        fake_curses = MagicMock()
        fake_curses.error = Exception
        with patch.dict("sys.modules", {"curses": fake_curses}):
            self.assertTrue(is_curses_available())

    @patch.dict("os.environ", {"TERM": "xterm-256color"}, clear=True)
    @patch.object(sys.stdout, "isatty", return_value=True)
    @patch.object(sys.stdin, "isatty", return_value=True)
    def test_returns_false_when_setupterm_fails(self, _stdin, _stdout):
        fake_curses = MagicMock()
        fake_curses.error = Exception
        fake_curses.setupterm.side_effect = Exception("boom")
        with patch.dict("sys.modules", {"curses": fake_curses}):
            self.assertFalse(is_curses_available())


class TestCursesStreamUI(unittest.TestCase):
    """Tests for CursesStreamUI using a fake curses module."""

    def _make_ui(self, fake_curses, command_handler=None):
        return CursesStreamUI(
            filepath="/tmp/test.log",
            task_dir="/tmp/tasks",
            log_files=[],
            default_session_id="s1",
            default_stdout_path="/tmp/tasks/s1.123.session.stdout",
            command_handler=command_handler or (lambda _: True),
        )

    def _poll_input_with_key(self, ui, key):
        """Simulate a single key press by wiring get_wch and invoking _poll_input."""
        ui.stdscr.get_wch.return_value = key
        ui._poll_input()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_initial_tail_loads_file_lines(self):
        fake_curses = sys.modules["curses"]
        content = "line1\nline2\nline3\n"
        with patch(
            "builtins.open", unittest.mock.mock_open(read_data=content)
        ) as mock_open:
            ui = self._make_ui(fake_curses)
            ui._tail_initial_lines()
        mock_open.assert_called_once_with(
            "/tmp/test.log", "r", encoding="utf-8", errors="replace"
        )
        self.assertEqual(len(ui._lines), 3)
        self.assertEqual(ui._lines[-1], "line3\n")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_initial_tail_handles_read_error(self):
        fake_curses = sys.modules["curses"]
        with patch("builtins.open", side_effect=OSError("boom")) as mock_open:
            ui = self._make_ui(fake_curses)
            ui._tail_initial_lines()
        self.assertEqual(ui._lines, [])
        self.assertEqual(ui._file_offset, 0)

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_appends_regular_characters(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.side_effect = ["h", "i", "\n"]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._setup_colors = MagicMock()
        ui._build_windows = MagicMock()
        ui._tail_initial_lines = MagicMock()
        ui._draw = MagicMock()

        calls = []

        def handler(line):
            calls.append(line)
            return True

        ui.command_handler = handler

        ui._poll_input()
        ui._poll_input()
        self.assertEqual(ui._input_buffer, "hi")
        ui._poll_input()
        self.assertEqual(ui._input_buffer, "")
        self.assertEqual(calls, ["hi"])

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_submits_on_enter(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        # get_wch() returns Enter as a newline string.
        stdscr.get_wch.side_effect = ["h", "i", "\n"]
        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._setup_colors = MagicMock()
        ui._build_windows = MagicMock()
        ui._tail_initial_lines = MagicMock()
        ui._draw = MagicMock()

        calls = []
        ui.command_handler = lambda line: calls.append(line) or True

        ui._poll_input()
        ui._poll_input()
        ui._poll_input()
        self.assertEqual(calls, ["hi"])
        self.assertEqual(ui._input_buffer, "")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_carriage_return_submits(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.side_effect = ["h", "i", "\r"]
        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._setup_colors = MagicMock()
        ui._build_windows = MagicMock()
        ui._tail_initial_lines = MagicMock()
        ui._draw = MagicMock()

        calls = []
        ui.command_handler = lambda line: calls.append(line) or True

        ui._poll_input()
        ui._poll_input()
        ui._poll_input()
        self.assertEqual(calls, ["hi"])
        self.assertEqual(ui._input_buffer, "")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_backspace_removes_last_character(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.side_effect = ["a", "b", 127]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr

        ui._poll_input()
        ui._poll_input()
        ui._poll_input()
        self.assertEqual(ui._input_buffer, "a")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_quit_stops_running(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.side_effect = ["q", "u", "i", "t", "\n"]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses, command_handler=lambda _: False)
        ui.stdscr = stdscr
        ui._running = True

        for _ in range(5):
            ui._poll_input()
        self.assertFalse(ui._running)

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_accepts_chinese_characters(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        # Chinese characters are returned as strings by get_wch().
        stdscr.get_wch.side_effect = ["中", "文", "\n"]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr

        ui._poll_input()
        ui._poll_input()
        self.assertEqual(ui._input_buffer, "中文")
        ui._poll_input()
        self.assertEqual(ui._input_buffer, "")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_curses_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.get_wch.side_effect = fake_curses.error("boom")

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        # Should not raise.
        ui._poll_input()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_resize_rebuilds_windows(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (40, 120)
        stdscr.get_wch.side_effect = [fake_curses.KEY_RESIZE]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._build_windows = MagicMock()
        ui._handle_resize = MagicMock()

        ui._poll_input()
        ui._handle_resize.assert_called_once()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_log_appends_new_content(self):
        fake_curses = sys.modules["curses"]
        content = b"new log line\nanother line\n"
        with patch(
            "builtins.open", unittest.mock.mock_open(read_data=content)
        ) as mock_open:
            ui = self._make_ui(fake_curses)
            ui._file_offset = 0
            ui._poll_log()
        mock_open.assert_called_once_with("/tmp/test.log", "rb")
        self.assertEqual(len(ui._lines), 2)
        self.assertEqual(ui._lines[0], "new log line\n")
        self.assertEqual(ui._lines[1], "another line\n")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_log_empty_chunk_does_nothing(self):
        fake_curses = sys.modules["curses"]
        with patch("builtins.open", unittest.mock.mock_open(read_data=b"")) as mock_open:
            ui = self._make_ui(fake_curses)
            ui._file_offset = 0
            ui._lines = ["existing\n"]
            ui._poll_log()
        self.assertEqual(ui._lines, ["existing\n"])

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_log_handles_read_error(self):
        fake_curses = sys.modules["curses"]
        with patch("builtins.open", side_effect=OSError("boom")):
            ui = self._make_ui(fake_curses)
            ui._lines = ["existing\n"]
            ui._poll_log()
        self.assertEqual(ui._lines, ["existing\n"])

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_renders_separator_and_input(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        input_win = MagicMock()
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._lines = ["log1\n", "log2\n"]
        ui._input_buffer = "hello"

        ui._draw()

        stdscr.erase.assert_called_once()
        stdscr.addstr.assert_called_once()
        input_win.addstr.assert_any_call(1, 0, "[runtime:s1]> ", 4)
        input_win.addstr.assert_any_call(1, 14, "hello")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_with_too_small_terminal(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (3, 80)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._draw()

        stdscr.noutrefresh.assert_called()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_with_none_stdscr(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui.stdscr = None
        # Should return early without raising.
        ui._draw()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_handle_resize_rebuilds_windows(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (40, 120)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._handle_resize()

        stdscr.subwin.assert_called_once_with(3, 120, 37, 0)
        stdscr.clear.assert_called_once()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_handle_resize_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        fake_curses._resize_term_error = True
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (40, 120)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._build_windows = MagicMock()
        # Should not raise.
        ui._handle_resize()
        ui._build_windows.assert_called_once()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_build_windows_skips_when_terminal_too_small(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (3, 80)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._build_windows()

        self.assertIsNone(ui.log_win)
        self.assertIsNone(ui.input_win)

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_setup_colors_without_color_support(self):
        fake_curses = sys.modules["curses"]
        fake_curses._has_colors = False
        stdscr = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        # Should not raise even though start_color is not called.
        ui._setup_colors()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_setup_colors_use_default_colors_error(self):
        fake_curses = sys.modules["curses"]
        fake_curses._use_default_colors_error = True
        stdscr = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        # Should not raise.
        ui._setup_colors()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_main_loop_runs_and_exits(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        # First iteration reads 'q' + Enter, then loop exits.
        stdscr.get_wch.side_effect = ["q", "\n"]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses, command_handler=lambda _: False)
        ui._main(stdscr)
        self.assertFalse(ui._running)

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_main_loop_curs_set_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        fake_curses._curs_set_error = True
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.side_effect = ["q", "\n"]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses, command_handler=lambda _: False)
        # Should not raise.
        ui._main(stdscr)

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_execute_input_empty_buffer_is_ignored(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui._input_buffer = "   "
        handler_called = []

        def handler(line):
            handler_called.append(line)
            return True

        ui.command_handler = handler
        ui._execute_input()
        self.assertEqual(handler_called, [])
        self.assertEqual(ui._input_buffer, "")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_execute_input_command_exception_is_logged(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui._input_buffer = "boom"

        def handler(line):
            raise RuntimeError("command failed")

        ui.command_handler = handler
        ui._execute_input()
        self.assertTrue(ui._running)
        self.assertTrue(
            any("Command failed" in line for line in ui._lines)
        )

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_append_status_adds_newline(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui.append_status("status message")
        self.assertEqual(ui._lines[-1], "status message\n")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_append_log_line_without_newline(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui._append_log_line("no newline")
        self.assertEqual(ui._lines[-1], "no newline\n")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_handle_multi_line_input_regular_characters(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._multi_line_mode = True
        ui._handle_multi_line_input("h")
        ui._handle_multi_line_input("i")
        self.assertEqual(ui._input_buffer, "hi")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_handle_multi_line_input_enter_appends_line(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui._multi_line_mode = True
        ui._input_buffer = "hi"
        ui._handle_multi_line_input(10)
        self.assertEqual(ui._multi_line_buffer, ["hi"])
        self.assertEqual(ui._input_buffer, "")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_handle_multi_line_input_ctrl_d_finishes(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui._multi_line_mode = True
        ui._input_buffer = "hi"
        ui._handle_multi_line_input(4)
        self.assertTrue(ui._multi_line_finished)
        self.assertEqual(ui._multi_line_buffer, ["hi"])

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_handle_multi_line_input_escape_cancels(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui._multi_line_mode = True
        ui._handle_multi_line_input(27)
        self.assertTrue(ui._multi_line_cancelled)

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_read_multi_line_blocking_collects_lines(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        # Simulate typing two lines followed by Ctrl+D (4).
        stdscr.get_wch.side_effect = [
            "h",
            "i",
            "\n",
            "b",
            "y",
            "e",
            "\n",
            4,
        ]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._setup_colors = MagicMock()
        ui._build_windows = MagicMock()
        ui._tail_initial_lines = MagicMock()
        ui._draw = MagicMock()

        result = ui.read_multi_line_blocking("msg")
        self.assertEqual(result, "hi\nbye")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_read_multi_line_blocking_cancels_on_escape(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.side_effect = ["h", 27]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._setup_colors = MagicMock()
        ui._build_windows = MagicMock()
        ui._tail_initial_lines = MagicMock()
        ui._draw = MagicMock()

        result = ui.read_multi_line_blocking("msg")
        self.assertIsNone(result)

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_read_multi_line_blocking_restores_layout(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.side_effect = [4]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._setup_colors = MagicMock()
        ui._build_windows = MagicMock()
        ui._tail_initial_lines = MagicMock()
        ui._draw = MagicMock()

        ui.read_multi_line_blocking("msg")
        ui._build_windows.assert_called()
        stdscr.clear.assert_called()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_renders_input(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.log_win = log_win
        ui._multi_line_mode = True
        ui._multi_line_prompt = "enter msg:"
        ui._multi_line_buffer = ["line1"]
        ui._input_buffer = "line2"

        ui._draw_multi_line()

        stdscr.erase.assert_called_once()
        stdscr.addstr.assert_called_once()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_with_small_terminal(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (3, 80)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._multi_line_mode = True
        ui._draw_multi_line()

        stdscr.noutrefresh.assert_called()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_curses_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.addstr.side_effect = fake_curses.error("boom")
        log_win = MagicMock()
        log_win.erase.side_effect = fake_curses.error("boom")

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.log_win = log_win
        ui._multi_line_mode = True
        ui._multi_line_prompt = "enter msg:"
        # Should not raise.
        ui._draw_multi_line()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_subwin_error_falls_back(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.subwin.side_effect = fake_curses.error("boom")
        input_win = MagicMock()
        input_win.erase.side_effect = fake_curses.error("boom")
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._multi_line_mode = True
        ui._multi_line_prompt = "enter msg:"
        # Should fall back to existing input_win and not raise.
        ui._draw_multi_line()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_curses_errors_are_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.addstr.side_effect = fake_curses.error("boom")
        input_win = MagicMock()
        input_win.erase.side_effect = fake_curses.error("boom")
        log_win = MagicMock()
        log_win.erase.side_effect = fake_curses.error("boom")

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._lines = ["log1\n"]
        # Should not raise.
        ui._draw()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_escape_stops_running(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.side_effect = [27]

        stdscr.get_wch.return_value = 27

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._running = True
        ui._poll_input()
        self.assertFalse(ui._running)

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_log_appends_chunk_to_buffer(self):
        fake_curses = sys.modules["curses"]
        content = "line1\nline2\nline3\n"
        with patch("builtins.open", unittest.mock.mock_open(read_data=content.encode("utf-8"))):
            ui = self._make_ui(fake_curses)
            ui._file_offset = 0
            ui._poll_log()
        self.assertEqual(len(ui._lines), 3)
        self.assertEqual(ui._file_offset, len(content.encode("utf-8")))

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_append_log_line_truncates_buffer(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        for i in range(6000):
            ui._append_log_line(f"line {i}")
        self.assertEqual(len(ui._lines), 5000)
        self.assertEqual(ui._lines[-1], "line 5999\n")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_input_noutrefresh_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        input_win = MagicMock()
        input_win.noutrefresh.side_effect = fake_curses.error("boom")
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        # Should not raise.
        ui._draw()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_log_addstr_error_stops_rendering(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        input_win = MagicMock()
        log_win = MagicMock()
        log_win.addstr.side_effect = fake_curses.error("boom")

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._lines = ["log1\n"]
        # Should not raise.
        ui._draw()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_log_noutrefresh_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        input_win = MagicMock()
        log_win = MagicMock()
        log_win.noutrefresh.side_effect = fake_curses.error("boom")

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._lines = ["log1\n"]
        # Should not raise.
        ui._draw()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_stdscr_noutrefresh_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.noutrefresh.side_effect = fake_curses.error("boom")
        input_win = MagicMock()
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        # Should not raise.
        ui._draw()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_doupdate_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        input_win = MagicMock()
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        # Replace doupdate on the fake module instance.
        original_doupdate = fake_curses.doupdate
        fake_curses.doupdate = MagicMock(side_effect=fake_curses.error("boom"))
        try:
            ui._draw()
        finally:
            fake_curses.doupdate = original_doupdate

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_input_noutrefresh_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        input_win = MagicMock()
        input_win.noutrefresh.side_effect = fake_curses.error("boom")
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._multi_line_mode = True
        ui._multi_line_prompt = "enter msg:"
        # Should not raise.
        ui._draw_multi_line()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_log_noutrefresh_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        input_win = MagicMock()
        log_win = MagicMock()
        log_win.noutrefresh.side_effect = fake_curses.error("boom")

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._multi_line_mode = True
        ui._multi_line_prompt = "enter msg:"
        # Should not raise.
        ui._draw_multi_line()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_stdscr_noutrefresh_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.noutrefresh.side_effect = fake_curses.error("boom")
        input_win = MagicMock()
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._multi_line_mode = True
        ui._multi_line_prompt = "enter msg:"
        # Should not raise.
        ui._draw_multi_line()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_log_line_truncated_to_width(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 10)
        input_win = MagicMock()
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._multi_line_mode = True
        ui._multi_line_prompt = ">"
        ui._lines = ["a" * 50]
        ui._draw_multi_line()

        # width - 1 == 9, so the line should be truncated.
        log_win.addstr.assert_called_once_with(0, 0, "a" * 9)


    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_run_uses_curses_wrapper(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.side_effect = ["q", "\n"]

        stdscr.get_wch.return_value = 27
        fake_curses.wrapper = MagicMock(side_effect=lambda func: func(stdscr))

        ui = self._make_ui(fake_curses, command_handler=lambda _: False)
        ui.run()
        fake_curses.wrapper.assert_called_once()
        self.assertFalse(ui._running)
    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_input_no_key_returns_early(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.get_wch.return_value = -1

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        # Should return early without modifying input buffer.
        ui._poll_input()
        self.assertEqual(ui._input_buffer, "")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_poll_log_truncates_buffer(self):
        fake_curses = sys.modules["curses"]
        # Pre-populate the buffer near the limit so a small read pushes it over.
        ui = self._make_ui(fake_curses)
        ui._lines = [f"pre {i}\n" for i in range(_MAX_BUFFERED_LINES - 10)]
        ui._file_offset = 0
        content = "\n".join(f"line {i}" for i in range(20)) + "\n"
        with patch("builtins.open", unittest.mock.mock_open(read_data=content.encode("utf-8"))):
            ui._poll_log()
        self.assertEqual(len(ui._lines), _MAX_BUFFERED_LINES)
        self.assertEqual(ui._lines[-1], "line 19\n")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_handle_multi_line_input_backspace(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui._multi_line_mode = True
        ui._input_buffer = "hi"
        ui._handle_multi_line_input(127)
        self.assertEqual(ui._input_buffer, "h")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_with_none_stdscr(self):
        fake_curses = sys.modules["curses"]
        ui = self._make_ui(fake_curses)
        ui.stdscr = None
        ui._multi_line_mode = True
        # Should return early without raising.
        ui._draw_multi_line()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_log_addstr_error_stops_rendering(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        log_win = MagicMock()
        log_win.addstr.side_effect = fake_curses.error("boom")

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.log_win = log_win
        ui._multi_line_mode = True
        ui._multi_line_prompt = "enter msg:"
        ui._lines = ["log1\n"]
        # Should not raise.
        ui._draw_multi_line()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_input_addstr_error_is_ignored(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        input_win = MagicMock()
        input_win.addstr.side_effect = fake_curses.error("boom")
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        # Should not raise.
        ui._draw()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_input_truncation(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 20)
        input_win = MagicMock()
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._input_buffer = "a" * 100
        ui._draw()

        # remaining = width - len(prompt) - 1 = 20 - 14 - 1 = 5
        input_win.addstr.assert_any_call(1, 14, "a" * 5)

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_log_truncation(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 10)
        input_win = MagicMock()
        log_win = MagicMock()

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._lines = ["very long log line that exceeds width\n"]
        ui._draw()

        log_win.addstr.assert_called_once_with(0, 0, "very long")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_draw_multi_line_input_noutrefresh_error_is_ignored_subwin(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        input_win = MagicMock()
        input_win.noutrefresh.side_effect = fake_curses.error("boom")
        log_win = MagicMock()
        # _draw_multi_line creates a fresh subwin; make it return our failing mock.
        stdscr.subwin.return_value = input_win

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui.input_win = input_win
        ui.log_win = log_win
        ui._multi_line_mode = True
        ui._multi_line_prompt = "enter msg:"
        # Should not raise.
        ui._draw_multi_line()

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_page_up_scrolls_up_one_page(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._lines = [f"line {i:03d}\n" for i in range(100)]
        ui._build_windows()
        log_win = ui.log_win

        # log_height = 21, page_scroll_lines = 20
        self.assertEqual(ui._visible_count, 21)
        self.assertEqual(ui._page_scroll_lines, 20)

        self._poll_input_with_key(ui, fake_curses.KEY_PPAGE)
        self.assertEqual(ui._scroll_offset, 20)
        ui._render_log_pane(21, 80)
        # Viewport should start at line 100 - 21 - 20 = 59
        log_win.addstr.assert_any_call(0, 0, "line 059")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_page_down_scrolls_down_one_page(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._lines = [f"line {i:03d}\n" for i in range(100)]
        ui._build_windows()
        log_win = ui.log_win
        ui._scroll_offset = 40

        self._poll_input_with_key(ui, fake_curses.KEY_NPAGE)
        self.assertEqual(ui._scroll_offset, 20)
        ui._render_log_pane(21, 80)
        # Viewport should start at line 100 - 21 - 20 = 59
        log_win.addstr.assert_any_call(0, 0, "line 059")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_page_up_does_not_overscroll(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._lines = [f"line {i:03d}\n" for i in range(30)]
        ui._build_windows()
        log_win = ui.log_win

        # visible_count = 21, max_offset = 30 - 21 = 9
        for _ in range(10):
            self._poll_input_with_key(ui, fake_curses.KEY_PPAGE)
        self.assertEqual(ui._scroll_offset, 9)
        ui._render_log_pane(21, 80)
        # Viewport should start at line 0
        log_win.addstr.assert_any_call(0, 0, "line 000")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_page_down_at_bottom_stays_at_bottom(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._lines = [f"line {i:03d}\n" for i in range(100)]
        ui._build_windows()
        log_win = ui.log_win

        self._poll_input_with_key(ui, fake_curses.KEY_NPAGE)
        self.assertEqual(ui._scroll_offset, 0)
        ui._render_log_pane(21, 80)
        # Viewport should start at line 100 - 21 = 79
        log_win.addstr.assert_any_call(0, 0, "line 079")

    @patch.dict("sys.modules", {"curses": FakeCurses()})
    def test_page_up_then_page_down_roundtrip(self):
        fake_curses = sys.modules["curses"]
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)

        ui = self._make_ui(fake_curses)
        ui.stdscr = stdscr
        ui._lines = [f"line {i:03d}\n" for i in range(100)]
        ui._build_windows()
        log_win = ui.log_win

        self._poll_input_with_key(ui, fake_curses.KEY_PPAGE)
        self._poll_input_with_key(ui, fake_curses.KEY_NPAGE)
        self.assertEqual(ui._scroll_offset, 0)
        ui._render_log_pane(21, 80)
        # Back to tail-following view
        log_win.addstr.assert_any_call(0, 0, "line 079")

if __name__ == "__main__":
    unittest.main()
