"""Two-pane terminal UI for streaming session logs.

Provides a curses-based interface with a log pane on top and a fixed
input bar at the bottom.  When curses is unavailable the caller should
fall back to the legacy single-pane stream implementation.
"""

from __future__ import annotations

import os
import re
import sys
from typing import TYPE_CHECKING

import cli_topsailai.state as state

if TYPE_CHECKING:
    from typing import Callable, List, Optional

# Regex to strip ANSI escape sequences from log lines before rendering.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

# Maximum number of lines kept in memory to avoid unbounded growth.
_MAX_BUFFERED_LINES = 5000

# Default number of trailing lines to load when entering the UI.
_INITIAL_TAIL_LINES = 100

# Fixed height of the input pane (separator + prompt row + input row).
_INPUT_PANE_HEIGHT = 3

# Minimum terminal height required to render both panes.
_MIN_TERMINAL_HEIGHT = 5


def _strip_ansi(text: str) -> str:
    """Remove ANSI color escape sequences from *text*."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _split_lines(text: str) -> List[str]:
    """Split *text* into lines, preserving a trailing newline if present."""
    if not text:
        return []
    lines = text.split("\n")
    # split() drops the final empty segment when text ends with "\n".
    # Restore it so that each original line keeps its newline marker.
    if text.endswith("\n"):
        lines = [f"{line}\n" for line in lines[:-1]]
    else:
        lines = [f"{line}\n" for line in lines[:-1]] + [lines[-1]]
    return lines


class CursesStreamUI:
    """Two-pane UI: log pane on top, input pane at the bottom.

    Args:
        filepath: Path to the log file to stream.
        task_dir: Task directory used when resolving session targets.
        log_files: Current list of discovered log files.
        default_session_id: Session ID associated with the watched file.
        default_stdout_path: Exact stdout path for the watched session.
        command_handler: Callback invoked when the user presses Enter.
            Receives the entered command string and should return ``True``
            to keep the UI running or ``False`` to exit.
    """

    def __init__(
        self,
        filepath: str,
        task_dir: str,
        log_files: List[dict],
        default_session_id: Optional[str],
        default_stdout_path: Optional[str],
        command_handler: Callable[[str], bool],
    ) -> None:
        self.filepath = filepath
        self.task_dir = task_dir
        self.log_files = log_files
        self.session_id = default_session_id
        self.stdout_path = default_stdout_path
        self.command_handler = command_handler

        self._lines: List[str] = []
        self._input_buffer = ""
        # Cursor position within _input_buffer (0 = before first character).
        self._cursor_pos = 0
        self._prompt = self._build_prompt()
        self._running = True
        self._multi_line_mode = False
        self._multi_line_buffer: List[str] = []
        self._multi_line_prompt = ""

        # Runtime command history for the single-line input prompt.
        # _history stores commands newest-first; _history_index is the
        # currently recalled position, or -1 when the user is editing a
        # fresh line.
        self._history: List[str] = []
        self._history_index = -1

        self.stdscr = None
        self.log_win = None
        self.input_win = None
        self._file_offset: int = 0
        # Number of lines scrolled up from the bottom. 0 means "follow tail".
        self._scroll_offset: int = 0
        self._page_scroll_lines: int = 0
        self._needs_redraw: bool = True

    def _build_prompt(self) -> str:
        """Build the input prompt from the current session ID."""
        display = self.session_id or "?"
        return f"[runtime:{display}]> "

    def _load_history(self) -> None:
        """Load persisted runtime history for the current session.

        filter_entries returns oldest-first, but the UI navigates history
        newest-first (Up arrow recalls the most recent command).  Reverse the
        loaded list so index 0 is the newest entry.
        """
        manager = getattr(state, "history_manager", None)
        if manager is None:
            return
        try:
            self._history = list(reversed(manager.filter_entries("runtime", self.session_id)))
        except Exception:
            self._history = []
        self._history_index = -1

    def run(self) -> None:
        """Start the curses UI."""
        import curses

        curses.wrapper(self._main)


    def _main(self, stdscr) -> None:
        """Main curses loop."""
        import curses

        self.stdscr = stdscr
        self._load_history()
        self._setup_colors()
        self._build_windows()
        self._tail_initial_lines()
        self._needs_redraw = True
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        try:
            curses.curs_set(1)
        except curses.error:
            pass

        while self._running:
            had_log = self._poll_log()
            had_input = self._poll_input()
            if had_log or had_input or self._needs_redraw:
                self._draw()
                self._needs_redraw = False
            curses.napms(50)

    def _setup_colors(self) -> None:
        """Initialize curses color pairs."""
        import curses

        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                pass
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_RED, -1)
            curses.init_pair(4, curses.COLOR_CYAN, -1)

    def _build_windows(self) -> None:
        """Create or recreate the log pad and input sub-window."""
        import curses

        height, width = self.stdscr.getmaxyx()
        if height < _MIN_TERMINAL_HEIGHT or width < 1:
            self.log_win = None
            self.input_win = None
            self._visible_count = 0
            return

        log_height = height - _INPUT_PANE_HEIGHT
        # Use a pad for the log so it can hold more lines than the screen.
        self.log_win = curses.newpad(max(_MAX_BUFFERED_LINES, log_height * 2), width)
        self.log_win.scrollok(True)
        self.input_win = self.stdscr.subwin(_INPUT_PANE_HEIGHT, width, log_height, 0)
        self._visible_count = max(0, log_height)
        self._page_scroll_lines = max(1, log_height - 1)
        self._needs_redraw = True

    def _tail_initial_lines(self) -> None:
        """Load the trailing lines of the file into the buffer."""
        try:
            with open(self.filepath, "r", encoding="utf-8", errors="replace") as fh:
                all_lines = fh.readlines()
                self._lines = all_lines[-_INITIAL_TAIL_LINES:]
                self._file_offset = sum(len(line) for line in all_lines)
        except OSError:
            self._lines = []
            self._file_offset = 0
        self._scroll_offset = 0
        self._needs_redraw = True

    def _poll_log(self) -> bool:
        """Read new content from the log file and append it to the buffer.

        Returns True if new content was read and the screen should be redrawn.
        """
        changed = False
        try:
            with open(self.filepath, "rb") as fh:
                fh.seek(self._file_offset)
                chunk = fh.read(4096)
                if chunk:
                    self._file_offset += len(chunk)
                    text = chunk.decode("utf-8", errors="replace")
                    self._lines.extend(_split_lines(text))
                    if len(self._lines) > _MAX_BUFFERED_LINES:
                        self._lines = self._lines[-_MAX_BUFFERED_LINES:]
                    changed = True
        except OSError:
            pass

        # When following the tail, keep the scroll offset at zero so new lines
        # push older lines off the top of the screen.
        if changed and self._scroll_offset == 0:
            self._needs_redraw = True
        elif changed:
            # User has scrolled up; do not jump to the bottom.  The new lines
            # are appended in memory and will become visible once they scroll
            # back down.
            self._needs_redraw = True
        return changed

    def _poll_input(self) -> bool:
        """Read a single keystroke and update the input state.

        Returns True if the input state changed and the screen should be redrawn.
        """
        import curses

        try:
            ch = self.stdscr.get_wch()
        except curses.error:
            return False

        if ch == -1:
            return False

        if ch == curses.KEY_RESIZE:
            self._handle_resize()
            return True

        if self._multi_line_mode:
            return self._handle_multi_line_input(ch)

        if ch in (curses.KEY_ENTER, "\n", "\r"):
            self._execute_input()
            return True
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if self._cursor_pos > 0:
                self._input_buffer = (
                    self._input_buffer[: self._cursor_pos - 1]
                    + self._input_buffer[self._cursor_pos :]
                )
                self._cursor_pos -= 1
                self._history_index = -1
                return True
            return False
        if ch in (curses.KEY_DC, 330):
            if self._cursor_pos < len(self._input_buffer):
                self._input_buffer = (
                    self._input_buffer[: self._cursor_pos]
                    + self._input_buffer[self._cursor_pos + 1 :]
                )
                self._history_index = -1
                return True
            return False
        if ch == curses.KEY_LEFT or ch == 260:
            if self._cursor_pos > 0:
                self._cursor_pos -= 1
                return True
            return False
        if ch == curses.KEY_RIGHT or ch == 261:
            if self._cursor_pos < len(self._input_buffer):
                self._cursor_pos += 1
                return True
            return False
        if ch == curses.KEY_HOME or ch == 262:
            if self._cursor_pos != 0:
                self._cursor_pos = 0
                return True
            return False
        if ch == curses.KEY_END or ch == 360:
            if self._cursor_pos != len(self._input_buffer):
                self._cursor_pos = len(self._input_buffer)
                return True
            return False
        if ch == curses.KEY_UP or ch == 259:
            return self._recall_history(1)
        if ch == curses.KEY_DOWN or ch == 258:
            return self._recall_history(-1)
        if ch == curses.KEY_PPAGE or ch == curses.KEY_NPAGE:
            if ch == curses.KEY_PPAGE:
                self._scroll_up(self._page_scroll_lines)
            else:
                self._scroll_down(self._page_scroll_lines)
            return True
        if ch == 27:
            self._running = False
            return True
        if isinstance(ch, str):
            self._input_buffer = (
                self._input_buffer[: self._cursor_pos]
                + ch
                + self._input_buffer[self._cursor_pos :]
            )
            self._cursor_pos += 1
            self._history_index = -1
            return True
        return False

    def _recall_history(self, direction: int) -> bool:
        """Recall a previous or next command into the input buffer.

        direction=1 moves toward newer history (Up arrow), direction=-1
        moves toward older history (Down arrow).  Returns True when the
        input buffer changed.
        """
        if not self._history:
            return False

        new_index = self._history_index + direction
        new_index = max(-1, min(new_index, len(self._history) - 1))
        if new_index == self._history_index:
            return False

        self._history_index = new_index
        if self._history_index == -1:
            self._input_buffer = ""
        else:
            self._input_buffer = self._history[self._history_index]
        self._cursor_pos = len(self._input_buffer)
        return True

    def _scroll_up(self, lines: int) -> None:
        """Scroll the log pane up by *lines* (towards older log lines)."""
        # The viewport shows at most _visible_count lines, so the largest
        # useful offset is the number of lines hidden above the viewport.
        max_offset = max(0, len(self._lines) - self._visible_count)
        self._scroll_offset = min(self._scroll_offset + lines, max_offset)
        self._needs_redraw = True

    def _scroll_down(self, lines: int) -> None:
        """Scroll the log pane down by *lines* (towards newer log lines).

        Scrolling past the bottom resets to follow mode.
        """
        self._scroll_offset = max(self._scroll_offset - lines, 0)
        self._needs_redraw = True

    def _handle_resize(self) -> None:
        """Rebuild windows after a terminal resize."""
        import curses

        try:
            curses.resize_term(*self.stdscr.getmaxyx())
        except (AttributeError, curses.error):
            # Some curses implementations or mocks do not expose resize_term.
            pass
        self._build_windows()
        self.stdscr.clear()
        self.stdscr.noutrefresh()
        self._needs_redraw = True

    def _handle_multi_line_input(self, ch) -> bool:
        """Handle input while collecting a multi-line message.

        Returns True if the screen should be redrawn.
        """
        import curses

        if ch in (curses.KEY_ENTER, "\n", "\r"):
            if self._input_buffer == "EOF":
                self._multi_line_finished = True
                return True
            self._multi_line_buffer.append(self._input_buffer)
            self._input_buffer = ""
            self._cursor_pos = 0
            return True
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if self._input_buffer and self._cursor_pos > 0:
                self._input_buffer = (
                    self._input_buffer[: self._cursor_pos - 1]
                    + self._input_buffer[self._cursor_pos :]
                )
                self._cursor_pos -= 1
                return True
            if self._multi_line_buffer:
                self._input_buffer = self._multi_line_buffer.pop()
                self._cursor_pos = len(self._input_buffer)
                return True
            return False
        if ch in (curses.KEY_DC, 330):
            if self._input_buffer and self._cursor_pos < len(self._input_buffer):
                self._input_buffer = (
                    self._input_buffer[: self._cursor_pos]
                    + self._input_buffer[self._cursor_pos + 1 :]
                )
                return True
            return False
        if ch in (curses.KEY_LEFT, 260):
            if self._cursor_pos > 0:
                self._cursor_pos -= 1
                return True
            return False
        if ch in (curses.KEY_RIGHT, 261):
            if self._cursor_pos < len(self._input_buffer):
                self._cursor_pos += 1
                return True
            return False
        if ch in (curses.KEY_HOME, 262):
            if self._cursor_pos != 0:
                self._cursor_pos = 0
                return True
            return False
        if ch in (curses.KEY_END, 360):
            if self._cursor_pos != len(self._input_buffer):
                self._cursor_pos = len(self._input_buffer)
                return True
            return False
        if ch == 4:  # Ctrl+D finishes multi-line input
            if self._input_buffer:
                self._multi_line_buffer.append(self._input_buffer)
                self._input_buffer = ""
            self._multi_line_finished = True
            return True
        if ch == 27:  # ESC cancels multi-line mode
            self._multi_line_cancelled = True
            return True
        if ch == curses.KEY_PPAGE or ch == curses.KEY_NPAGE:
            # Allow log scrolling even while collecting multi-line input.
            if ch == curses.KEY_PPAGE:
                self._scroll_up(self._page_scroll_lines)
            else:
                self._scroll_down(self._page_scroll_lines)
            return True
        if isinstance(ch, str):
            self._input_buffer = (
                self._input_buffer[: self._cursor_pos]
                + ch
                + self._input_buffer[self._cursor_pos :]
            )
            self._cursor_pos += 1
            return True
        return False

    def _execute_input(self) -> None:
        """Run the command currently in the input buffer."""
        raw = self._input_buffer.strip()
        self._input_buffer = ""
        self._cursor_pos = 0
        self._history_index = -1
        if not raw:
            return
        # Persist the command so future sessions can recall it.
        # _history is newest-first; insert at the front and avoid consecutive
        # duplicates.
        if not self._history or self._history[0] != raw:
            self._history.insert(0, raw)
        manager = getattr(state, "history_manager", None)
        if manager is not None:
            try:
                manager.append("runtime", self.session_id, raw)
            except Exception:
                pass

        self._append_log_line(f"{self._prompt}{raw}")
        try:
            keep_running = self.command_handler(raw)
        except Exception as exc:
            self._append_log_line(f"[ERROR] Command failed: {exc}")
            keep_running = True
        if not keep_running:
            self._running = False

    def _append_log_line(self, text: str) -> None:
        """Append a line to the log buffer, used for command echo/status."""
        if not text.endswith("\n"):
            text += "\n"
        self._lines.append(text)
        if len(self._lines) > _MAX_BUFFERED_LINES:
            self._lines = self._lines[-_MAX_BUFFERED_LINES:]
        # A command/status line is always interesting; jump back to the bottom
        # so the user sees the result.
        self._scroll_offset = 0
        self._needs_redraw = True

    def append_status(self, text: str) -> None:
        """Append a status message to the log pane."""
        self._append_log_line(text)

    def read_multi_line_blocking(self, prompt: str) -> Optional[str]:
        """Collect multi-line input from the user and return it.

        The input pane is expanded temporarily while collecting lines.  The
        user finishes with Ctrl+D, a standalone 'EOF' line, or cancels with ESC.
        """
        import curses

        self._multi_line_mode = True
        self._multi_line_buffer = []
        self._multi_line_prompt = prompt
        self._multi_line_finished = False
        self._multi_line_cancelled = False
        self._input_buffer = ""
        self._cursor_pos = 0
        self._scroll_offset = 0
        self._needs_redraw = True
        # Temporarily expand the input pane to give more room for typing.
        try:
            while (
                self._running
                and self._multi_line_mode
                and not self._multi_line_finished
                and not self._multi_line_cancelled
            ):
                had_log = self._poll_log()
                had_input = self._poll_input()
                if had_log or had_input or self._needs_redraw:
                    self._draw_multi_line()
                    self._needs_redraw = False
                curses.napms(50)
        finally:
            self._multi_line_mode = False
            self._multi_line_prompt = ""
            self._input_buffer = ""
            # Restore normal layout.
            self._build_windows()
            self.stdscr.clear()
            self.stdscr.noutrefresh()
            self._needs_redraw = True

        if self._multi_line_cancelled:
            return None
        return "\n".join(self._multi_line_buffer)

    def _draw_multi_line(self) -> None:
        """Render the UI while collecting multi-line input."""
        import curses

        if self.stdscr is None:
            return

        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()

        if height < _MIN_TERMINAL_HEIGHT or width < 1:
            self.stdscr.noutrefresh()
            curses.doupdate()
            return

        # Use a third of the screen for the input pane during multi-line mode.
        input_height = max(_INPUT_PANE_HEIGHT, height // 3)
        log_height = height - input_height
        separator_y = log_height

        # Draw separator line.
        try:
            self.stdscr.addstr(separator_y, 0, "─" * (width - 1))
        except curses.error:
            pass

        # Refresh the background first so subwindows/pads render on top.
        try:
            self.stdscr.noutrefresh()
        except curses.error:
            pass

        # Recreate input window with expanded height.  Remove the old one so
        # it does not continue to be rendered by stdscr.noutrefresh() and
        # overwrite the log pane.
        try:
            if self.input_win is not None:
                curses.delwin(self.input_win)
        except curses.error:
            pass
        try:
            self.input_win = self.stdscr.subwin(input_height, width, log_height, 0)
        except curses.error:
            self.input_win = None

        if self.input_win is not None:
            try:
                self.input_win.erase()
                # Prompt on the first row.
                self.input_win.addstr(0, 0, self._multi_line_prompt, curses.color_pair(4))
                # Show recently entered lines plus the current line.
                display_lines = self._multi_line_buffer[-(input_height - 2):]
                for row, line in enumerate(display_lines, start=1):
                    if row < input_height - 1:
                        self.input_win.addstr(row, 0, line[: width - 1])
                current_row = 1 + len(display_lines)
                if current_row < input_height:
                    visible_input = self._input_buffer[: width - 1]
                    self.input_win.addstr(
                        current_row, 0, visible_input, curses.A_BOLD
                    )
                    try:
                        self.input_win.move(current_row, len(visible_input))
                    except curses.error:
                        pass
            except curses.error:
                pass
            try:
                self.input_win.noutrefresh()
            except curses.error:
                pass

        if self.log_win is not None:
            self._render_log_pane(log_height, width)

        curses.doupdate()

    def _draw(self) -> None:
        """Render the log pane, separator, and input pane."""
        import curses

        if self.stdscr is None:
            return

        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()

        if height < _MIN_TERMINAL_HEIGHT or width < 1:
            self.stdscr.noutrefresh()
            curses.doupdate()
            return

        log_height = height - _INPUT_PANE_HEIGHT
        separator_y = log_height

        # Draw separator line.
        try:
            self.stdscr.addstr(separator_y, 0, "─" * (width - 1))
        except curses.error:
            pass

        # Refresh the background first so subwindows/pads render on top.
        try:
            self.stdscr.noutrefresh()
        except curses.error:
            pass

        # Draw input pane.
        cursor_y = 0
        cursor_x = 0
        if self.input_win is not None:
            try:
                self.input_win.erase()
            except curses.error:
                pass
            prompt = self._multi_line_prompt if self._multi_line_mode else self._prompt
            try:
                self.input_win.addstr(1, 0, prompt, curses.color_pair(4))
                remaining = width - len(prompt) - 1
                visible_input = ""
                if remaining > 0:
                    # Horizontal scroll so the cursor stays visible.
                    if self._cursor_pos > remaining:
                        start = self._cursor_pos - remaining
                        visible_input = self._input_buffer[start:self._cursor_pos]
                    else:
                        visible_input = self._input_buffer[:remaining]
                    self.input_win.addstr(1, len(prompt), visible_input)
                cursor_y = log_height + 1
                cursor_x = len(prompt) + min(len(visible_input), self._cursor_pos)
                try:
                    self.input_win.move(1, cursor_x)
                except curses.error:
                    pass
            except curses.error:
                pass
            try:
                self.input_win.noutrefresh()
            except curses.error:
                pass

        # Draw log pane.
        if self.log_win is not None:
            self._render_log_pane(log_height, width)

        # The log pane refresh moves the physical cursor to the end of the
        # last log line. Move it back to the input pane so the cursor appears
        # right after the prompt.
        try:
            self.stdscr.move(cursor_y, cursor_x)
            self.stdscr.noutrefresh()
        except curses.error:
            pass

        try:
            curses.doupdate()
        except curses.error:
            pass

    def _render_log_pane(self, log_height: int, width: int) -> None:
        """Render the log pane into *log_win* respecting *_scroll_offset*."""
        try:
            self.log_win.erase()
        except Exception:
            pass

        visible_count = max(0, log_height)
        total = len(self._lines)
        # When scrolled up, show older lines; when at the bottom, follow tail.
        start_idx = max(0, total - visible_count - self._scroll_offset)
        visible = self._lines[start_idx : start_idx + visible_count]
        for row, line in enumerate(visible):
            clean = _strip_ansi(line).rstrip("\r\n")
            if len(clean) > width - 1:
                clean = clean[: width - 1]
            try:
                self.log_win.addstr(row, 0, clean)
            except Exception:
                break
        # The visible slice already accounts for scrolling, so always refresh
        # from the top of the pad.  This avoids showing empty pad rows when
        # _scroll_offset moves the viewport away from the bottom.
        try:
            self.log_win.noutrefresh(0, 0, 0, 0, log_height - 1, width - 1)
        except Exception:
            pass



def is_curses_available() -> bool:
    """Return True if curses can be used for an interactive TUI.

    Requires both stdin and stdout to be TTYs, a usable TERM environment
    variable, and the ability to initialise curses without error.
    """
    if not sys.stdout.isatty():
        return False
    if not sys.stdin.isatty():
        return False
    term = os.environ.get("TERM", "")
    if not term or term.lower() in ("dumb", "unknown"):
        return False
    try:
        import curses

        curses.setupterm()
        return True
    except (ImportError, curses.error):
        return False
