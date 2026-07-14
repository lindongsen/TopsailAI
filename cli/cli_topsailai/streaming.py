"""Streaming session helpers for the TopsailAI CLI."""

import errno
import os
import re
import select
import stat
import subprocess
import sys
import time
import unicodedata
from typing import Any, Callable, Dict, List, Optional

try:
    import termios
    import tty
except ImportError:
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

_DEBUG_INPUT = os.environ.get("TOPSAILAI_DEBUG_INPUT")

from cli_topsailai.colors import (
    Colors,
    print_error,
    print_info,
    print_success,
    print_warning,
)
from cli_topsailai.constants import DEFAULT_TIMEOUT_SECONDS
from cli_topsailai.formatting import print_header
from cli_topsailai.log_files import (
    _build_pipe_path,
    _find_session_stdout_file,
    _get_pid_from_stdout_path,
    _parse_stdout_filename,
    _resolve_send_target_from_arg,
    get_file_pid,
)
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.process import register_process, unregister_process
from cli_topsailai import yaml_commands
import cli_topsailai.state as state


def _debug_input(msg: str) -> None:
    if _DEBUG_INPUT:
        with open("/TopsailAI/cli/.tmp/read_input_debug.log", "a", encoding="utf-8") as f:
            f.write(f"{time.time():.6f} {msg}\n")


def _extract_session_id_from_path(path: str) -> Optional[str]:
    """Extract the session_id from a stdout file path, if possible."""
    session_id, _ = _parse_stdout_filename(os.path.basename(path))
    return session_id


def stream_sessions(
    command: List[str],
    env: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    poll_interval: float = 1.0,
) -> int:
    """
    Run a command and stream its stdout/stderr line by line.

    Args:
        command: Command and arguments to execute.
        env: Environment variables for the subprocess.
        timeout: Maximum runtime in seconds.
        poll_interval: Interval between output polls.

    Returns:
        Subprocess return code.
    """
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    start = time.time()
    try:
        while proc.poll() is None:
            if time.time() - start > timeout:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                print_error("Streaming timed out")
                return 1
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                print(line, end="")
            else:
                time.sleep(poll_interval)
        # Drain remaining output
        if proc.stdout:
            for line in proc.stdout:
                print(line, end="")
        return proc.returncode or 0
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise


def tail_session_log(
    session_id: str,
    lines: int = 20,
    follow: bool = False,
    log_dir: Optional[str] = None,
) -> int:
    """
    Tail the log file for a session.

    Args:
        session_id: Session identifier.
        lines: Number of trailing lines to display.
        follow: Whether to keep following new output.
        log_dir: Directory containing session logs.

    Returns:
        Exit code.
    """
    if log_dir is None:
        log_dir = os.path.join(get_topsailai_home(), "logs")
    log_path = os.path.join(log_dir, f"{session_id}.log")
    if not os.path.isfile(log_path):
        print_error(f"Log not found: {log_path}")
        return 1

    cmd = ["tail"]
    if follow:
        cmd.append("-f")
    cmd.extend(["-n", str(lines), log_path])
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        # Fallback pure-Python tail when `tail` is unavailable.
        with open(log_path, "r", encoding="utf-8") as fh:
            all_lines = fh.readlines()
        for line in all_lines[-lines:]:
            print(line, end="")
        if follow:
            print_warning("'tail' not available; follow mode is not supported")
        return 0


def _can_use_curses() -> bool:
    """Return True if the two-pane curses UI can be used."""
    from cli_topsailai.tui import is_curses_available

    return is_curses_available()


def stream_file(
    filepath: str,
    task_dir: str = "",
    log_files: Optional[List[dict]] = None,
    default_session_id: Optional[str] = None,
    default_stdout_path: Optional[str] = None,
    runtime_raw: bool = False,
    tail_lines: int = 100,
) -> None:
    """
    Stream a log file in real-time, similar to ``tail -f``.

    Shows the last 100 lines, then follows new writes.  Supports ``q`` to
    quit, ``/send [message]`` to send a message to the watched session,
    ``/ctx.btw [message]`` to inject an agent2llm message, or Ctrl+C for
    graceful exit.

    When ``runtime_raw`` is True, a simple curses-free raw streaming mode is
    used instead of the two-pane curses UI or legacy single-pane fallback.
    The last ``tail_lines`` lines are echoed on startup.

    When the terminal supports it and ``runtime_raw`` is False, a two-pane
    curses UI is used so that the log scrolls in the top pane while a fixed
    input bar stays at the bottom.  In non-TTY environments or when curses is
    unavailable, the legacy single-pane mode is used instead.

    While streaming, the interactive scope is temporarily set to
    ``"runtime"`` so that scope-aware YAML commands target the watched
    session automatically.

    Args:
        filepath: Path to the log file to stream.
        task_dir: Task directory for resolving session targets.
        log_files: Current list of discovered log files.
        default_session_id: Session ID associated with the watched file.
        default_stdout_path: Exact stdout path for the watched session.
        runtime_raw: Use the simple curses-free raw streaming mode.
        tail_lines: Number of recent log lines to echo on startup.
    """
    previous_scope = state.current_scope
    previous_session_id = state.current_session_id
    if default_session_id is not None:
        state.current_scope = "runtime"
        state.current_session_id = default_session_id

    try:
        if runtime_raw:
            _stream_file_raw(
                filepath,
                task_dir,
                log_files or [],
                default_session_id,
                default_stdout_path,
                tail_lines=tail_lines,
            )
        elif _can_use_curses():
            _run_curses_ui(
                filepath,
                task_dir,
                log_files or [],
                default_session_id,
                default_stdout_path,
            )
        else:
            _stream_file_legacy(
                filepath,
                task_dir,
                log_files or [],
                default_session_id,
                default_stdout_path,
            )
    finally:
        state.current_scope = previous_scope
        state.current_session_id = previous_session_id


def _run_curses_ui(
    filepath: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> None:
    """Run the two-pane curses UI for streaming."""
    from cli_topsailai.tui import CursesStreamUI

    ui: Any = None  # type: ignore[assignment]
    real_handler: Callable[[str], bool] = lambda _: True

    def command_handler(cmd_line: str) -> bool:
        return real_handler(cmd_line)

    ui = CursesStreamUI(
        filepath=filepath,
        task_dir=task_dir,
        log_files=log_files,
        default_session_id=default_session_id,
        default_stdout_path=default_stdout_path,
        command_handler=command_handler,
    )
    real_handler = _build_stream_command_handler(
        ui,
        task_dir,
        log_files,
        default_session_id,
        default_stdout_path,
    )
    ui.run()


class _CursesOutputCapture:
    """Capture stdout/stderr writes and forward them to a curses UI."""

    def __init__(self, ui: Any) -> None:
        self.ui = ui
        self._buffer: List[str] = []
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

    def write(self, text: str) -> None:
        self._buffer.append(text)
        if "\n" in text:
            self._flush()

    def flush(self) -> None:
        self._flush()
        if hasattr(self._original_stdout, "flush"):
            self._original_stdout.flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        data = "".join(self._buffer)
        self._buffer = []
        for line in data.splitlines():
            if line:
                self.ui.append_status(line)

    def __enter__(self) -> "_CursesOutputCapture":
        sys.stdout = self  # type: ignore[assignment]
        sys.stderr = self  # type: ignore[assignment]
        return self

    def __exit__(self, *args: Any) -> None:
        self._flush()
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr


def _build_stream_command_handler(
    ui: Any,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> Any:
    """Build the command callback used by the curses UI."""

    def _multi_line_input_provider(prompt: str) -> Optional[str]:
        return ui.read_multi_line_blocking(prompt)

    def handler(cmd_line: str) -> bool:
        lower = cmd_line.lower()
        if lower in ("q", "quit", "cd", "/cd"):
            return False
        with _CursesOutputCapture(ui):
            if lower.startswith("/"):
                _handle_stream_command(
                    cmd_line,
                    task_dir,
                    log_files,
                    default_session_id,
                    default_stdout_path,
                    input_provider=_multi_line_input_provider,
                )
            else:
                _prompt_send_as_message(
                    cmd_line,
                    task_dir,
                    log_files,
                    default_session_id,
                    default_stdout_path,
                    input_provider=_multi_line_input_provider,
                    output_callback=ui.append_status,
                    input_callback=ui.read_multi_line_blocking,
                )
        return True

    return handler


def _prompt_send_as_message(
    raw_input: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
    input_provider: Optional[Callable[[str], Optional[str]]] = None,
    output_callback: Optional[Callable[[str], None]] = None,
    input_callback: Optional[Callable[[str], Optional[str]]] = None,
) -> bool:
    """
    Ask the user whether to send unrecognized runtime input as a message.

    If the user confirms, the raw input is forwarded to the existing ``/send``
    mechanism.  If the user declines, the original "Unknown command" behavior
    is preserved.

    Returns ``True`` if the input was handled (sent or declined), ``False``
    when the user cancels the prompt.
    """
    prompt = "Send as message? [y/N]: "
    if input_callback is not None:
        answer = input_callback(prompt)
    else:
        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return False

    if answer is None:
        return False

    answer_lower = answer.strip().lower()
    if answer_lower in ("y", "yes"):
        _handle_stream_command(
            f"/send {raw_input}",
            task_dir,
            log_files,
            default_session_id,
            default_stdout_path,
            input_provider=input_provider,
        )
        return True

    if output_callback is not None:
        output_callback(
            f"[ERROR] Unknown streaming command: {raw_input}. "
            f"Use '/send [message]', '/ctx.btw [message]', '/help', 'q', 'quit', 'exit', or 'cd'."
        )
    else:
        print(
            f"{Colors.RED}[ERROR] Unknown streaming command: {raw_input}. "
            f"Use '/send [message]', '/ctx.btw [message]', '/help', 'q', 'quit', 'exit', or 'cd'.{Colors.RESET}"
        )
    return True


def _tail_file(path: str, tail_lines: int, raw_mode: bool = False) -> None:
    """Print the most recent ``tail_lines`` lines of ``path`` to stdout.

    When ``raw_mode`` is True the TTY is in raw mode (``ONLCR`` is disabled),
    so newlines are translated to ``\\r\\n`` to avoid stair-stepped output.
    """
    n = max(0, tail_lines)
    if not raw_mode:
        try:
            subprocess.run(
                ["tail", "-n", str(n), path],
                check=False,
            )
            return
        except FileNotFoundError:
            pass
        except Exception:
            pass

    # Fallback pure-Python tail when the system ``tail`` is unavailable or
    # when the TTY is raw and we must control line endings.
    try:
        with open(path, "rb") as fh:
            all_lines = fh.read().splitlines()
        for line in all_lines[-n:]:
            if raw_mode and hasattr(sys.stdout, "buffer"):
                sys.stdout.buffer.write(line + b"\r\n")
                sys.stdout.buffer.flush()
            else:
                print(line.decode("utf-8", errors="replace") + "\n", end="")
    except Exception:
        pass

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text for display-width calculation."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _display_width_str(text: str) -> int:
    """Return the display width of a string, ignoring ANSI escape sequences."""
    return sum(_char_display_width(ch) for ch in _strip_ansi(text))


def _char_display_width(ch: str) -> int:
    """Return the display width of a single character.

    Uses ``wcwidth`` when available; otherwise falls back to
    ``unicodedata.east_asian_width`` so CJK characters are counted as two
    columns.
    """
    if not ch:
        return 0
    try:
        import wcwidth

        return wcwidth.wcwidth(ch) or 0
    except Exception:
        pass
    ea = unicodedata.east_asian_width(ch)
    if ea in ("F", "W"):
        return 2
    return 1


def _read_input_line(prompt: str = "", already_raw: bool = False) -> Optional[str]:
    """Read a single line from stdin, returning None on EOF/KeyboardInterrupt.

    In an interactive terminal we put the TTY into raw mode and implement a
    tiny ANSI line editor so that arrow keys, backspace, and multi-byte UTF-8
    characters (including CJK) work correctly while the raw stream loop is
    using ``select.select``.  The standard ``input()``/readline path conflicts
    with that loop and leaks escape sequences or miscalculates display widths
    for wide characters.

    The raw editor is only used when the caller has already placed the TTY in
    raw mode (``already_raw=True``).  In all other cases we keep the original
    ``input()`` behaviour so that existing tests and non-raw callers continue
    to work.
    """
    try:
        if not sys.stdin.isatty() or not already_raw:
            print(prompt, end="", flush=True)
            return input().strip()
        return _read_input_line_tty(prompt, already_raw=already_raw)
    except (EOFError, KeyboardInterrupt):
        return None


def _read_input_line_tty(prompt: str, already_raw: bool = False) -> Optional[str]:
    """TTY-aware line editor using raw byte reads.

    Puts the terminal into raw mode so keystrokes are available one byte at a
    time, parses UTF-8 incrementally, handles ANSI escape sequences for arrow
    keys/home/end/delete, and maintains the display using ``\\r`` and
    backspaces.  Returns ``None`` on Ctrl+C, Ctrl+D at empty line, or EOF.

    When ``already_raw`` is True the caller manages the TTY mode and this
    function only reads and interprets keystrokes.
    """
    _debug_input(f"_read_input_line_tty start prompt={prompt!r} already_raw={already_raw}")
    if termios is None or tty is None:
        print(prompt, end="", flush=True)
        return input().strip()

    fd = sys.stdin.fileno()
    old_settings = None
    if not already_raw:
        try:
            old_settings = termios.tcgetattr(fd)
        except termios.error:
            print(prompt, end="", flush=True)
            return input().strip()

    # Read raw bytes from the binary buffer.  Python's TextIOWrapper can
    # buffer and decode multi-byte UTF-8 sequences into a single character,
    # which breaks our incremental parser.  Reading from the binary buffer
    # gives us the true raw bytes.
    stdin_buffer = getattr(sys.stdin, "buffer", None)
    if stdin_buffer is None:
        print(prompt, end="", flush=True)
        return input().strip()

    buffer: List[str] = []
    cursor = 0

    def display_width(chars: List[str]) -> int:
        return sum(_char_display_width(c) for c in chars)

    last_total_rows = 1

    def redraw() -> None:
        # Repaint the prompt and input buffer, wrapping long input across
        # multiple terminal lines manually.  The terminal's auto-wrap is
        # disabled during the repaint so the prompt is not duplicated when
        # the input is wider than the screen; we emit explicit \r\n at the
        # calculated wrap points instead.
        nonlocal last_total_rows
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80

        full_text = prompt + "".join(buffer)

        def _wrap_text(text: str, width: int) -> List[str]:
            lines: List[str] = []
            current_line = ""
            current_width = 0
            pos = 0
            while pos < len(text):
                m = _ANSI_ESCAPE_RE.match(text, pos)
                if m:
                    current_line += m.group(0)
                    pos = m.end()
                    continue
                ch = text[pos]
                w = _char_display_width(ch)
                if current_width + w > width and current_line:
                    lines.append(current_line)
                    current_line = ch
                    current_width = w
                else:
                    current_line += ch
                    current_width += w
                pos += 1
            lines.append(current_line)
            return lines

        lines = _wrap_text(full_text, cols)
        if not lines:
            lines = [""]

        prompt_width = _display_width_str(prompt)
        cursor_offset = prompt_width + display_width(buffer[:cursor])

        cursor_row = 0
        cursor_col = 0
        pos = 0
        found = False
        for i, line in enumerate(lines):
            line_width = _display_width_str(line)
            if pos + line_width >= cursor_offset:
                cursor_row = i
                remaining = cursor_offset - pos
                cursor_col = 0
                for ch in line:
                    w = _char_display_width(ch)
                    if remaining <= 0:
                        break
                    cursor_col += w
                    remaining -= w
                found = True
                break
            pos += line_width
        if not found:
            cursor_row = len(lines) - 1
            cursor_col = _display_width_str(lines[-1])

        sys.stdout.write("\033[?7l")
        try:
            sys.stdout.write("\r")
            if last_total_rows > 1:
                sys.stdout.write(f"\033[{last_total_rows - 1}A")
            for i, line in enumerate(lines):
                if i > 0:
                    sys.stdout.write("\r\n")
                sys.stdout.write(line)
            sys.stdout.write("\033[J")
            rows_up = len(lines) - 1 - cursor_row
            if rows_up > 0:
                sys.stdout.write(f"\033[{rows_up}A")
            sys.stdout.write(f"\033[{cursor_col + 1}G")
            sys.stdout.flush()
        finally:
            sys.stdout.write("\033[?7h")
            sys.stdout.flush()
            last_total_rows = len(lines)

    def read_byte() -> Optional[int]:
        data = stdin_buffer.read(1)
        if not data:
            return None
        return data[0]

    try:
        if not already_raw:
            tty.setraw(fd)
        redraw()
        while True:
            byte = read_byte()
            _debug_input(f"read byte byte={byte}")
            if byte is None:
                _debug_input("EOF on read, returning None")
                return None

            if byte in (0x0A, 0x0D):
                result = "".join(buffer).strip()
                _debug_input(f"Enter pressed, returning result={result!r}")
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return result

            # Ctrl+C
            if byte == 0x03:
                _debug_input("Ctrl+C, returning None")
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return None

            # Ctrl+D
            if byte == 0x04:
                if not buffer:
                    _debug_input("Ctrl+D on empty buffer, returning None")
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    return None
                _debug_input("Ctrl+D ignored (non-empty buffer)")
                continue

            # Backspace / DEL / Ctrl+H
            if byte in (0x08, 0x7F):
                if cursor > 0:
                    cursor -= 1
                    deleted = buffer[cursor]
                    del buffer[cursor]
                    _debug_input(f"Backspace deleted={deleted!r} cursor={cursor} buffer={''.join(buffer)!r}")
                    redraw()
                else:
                    _debug_input("Backspace ignored at cursor=0")
                continue

            # Ctrl+A (home)
            if byte == 0x01:
                cursor = 0
                _debug_input("Ctrl+A home")
                redraw()
                continue

            # Ctrl+E (end)
            if byte == 0x05:
                cursor = len(buffer)
                _debug_input("Ctrl+E end")
                redraw()
                continue

            # Escape sequences
            if byte == 0x1B:
                seq1 = read_byte()
                _debug_input(f"ESC seq1={seq1}")
                if seq1 == 0x5B:  # '['
                    seq2 = read_byte()
                    _debug_input(f"ESC [ seq2={seq2}")
                    if seq2 == 0x44:  # 'D' left
                        if cursor > 0:
                            cursor -= 1
                            _debug_input(f"Left cursor={cursor}")
                            redraw()
                    elif seq2 == 0x43:  # 'C' right
                        if cursor < len(buffer):
                            cursor += 1
                            _debug_input(f"Right cursor={cursor}")
                            redraw()
                    elif seq2 == 0x48:  # 'H' home
                        cursor = 0
                        _debug_input("Home")
                        redraw()
                    elif seq2 == 0x46:  # 'F' end
                        cursor = len(buffer)
                        _debug_input("End")
                        redraw()
                    elif seq2 == 0x33:  # '3' delete
                        seq3 = read_byte()
                        _debug_input(f"Delete seq3={seq3}")
                        if seq3 == 0x7E and cursor < len(buffer):  # '~'
                            del buffer[cursor]
                            _debug_input(f"Delete cursor={cursor} buffer={''.join(buffer)!r}")
                            redraw()
                    # up/down (A/B) ignored
                elif seq1 == 0x4F:  # 'O'
                    seq2 = read_byte()
                    _debug_input(f"ESC O seq2={seq2}")
                    if seq2 == 0x44:  # 'D' left
                        if cursor > 0:
                            cursor -= 1
                            _debug_input(f"SS3 Left cursor={cursor}")
                            redraw()
                    elif seq2 == 0x43:  # 'C' right
                        if cursor < len(buffer):
                            cursor += 1
                            _debug_input(f"SS3 Right cursor={cursor}")
                            redraw()
                    elif seq2 == 0x48:  # home
                        cursor = 0
                        redraw()
                    elif seq2 == 0x46:  # end
                        cursor = len(buffer)
                        redraw()
                continue

            # Ignore other control characters
            if byte < 0x20:
                _debug_input(f"Ignoring control byte {byte:#x}")
                continue

            # Decode UTF-8 character
            if byte < 0x80:
                char = chr(byte)
            else:
                if byte < 0xC0:
                    _debug_input(f"Invalid UTF-8 start byte {byte:#x}")
                    continue
                elif byte < 0xE0:
                    num_bytes = 2
                elif byte < 0xF0:
                    num_bytes = 3
                elif byte < 0xF8:
                    num_bytes = 4
                else:
                    _debug_input(f"Invalid UTF-8 start byte {byte:#x}")
                    continue

                bytes_data = [byte]
                valid = True
                for _ in range(num_bytes - 1):
                    next_byte = read_byte()
                    if next_byte is None:
                        _debug_input("EOF in middle of UTF-8 sequence")
                        return None
                    if next_byte & 0xC0 != 0x80:
                        valid = False
                        _debug_input(f"Invalid UTF-8 continuation {next_byte:#x}")
                        break
                    bytes_data.append(next_byte)
                if not valid:
                    continue
                try:
                    char = bytes(bytes_data).decode("utf-8")
                except UnicodeDecodeError:
                    _debug_input(f"UTF-8 decode error bytes={bytes_data!r}")
                    continue

            buffer.insert(cursor, char)
            cursor += 1
            _debug_input(f"Inserted char={char!r} cursor={cursor} buffer={''.join(buffer)!r}")
            redraw()
    finally:
        _debug_input("_read_input_line_tty finally")
        if old_settings is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except termios.error:
                pass


class _RawStdoutBufferWrapper:
    """Binary buffer companion for ``_RawStdoutWrapper``.

    In raw TTY mode the terminal's ``ONLCR`` output processing is disabled,
    so ``\n`` bytes must be converted to ``\r\n`` to keep output aligned.
    This wrapper performs the same normalization as ``_RawStdoutWrapper``
    but on byte strings.
    """

    def __init__(self, buffer: Any) -> None:
        self._buffer = buffer

    def write(self, data: bytes) -> None:
        self._buffer.write(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    def flush(self) -> None:
        self._buffer.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._buffer, name)


class _RawStdoutWrapper:
    """Wrap a text stream so that lone ``\\n`` characters are emitted as ``\\r\\n``.

    In raw TTY mode the terminal's ``ONLCR`` output processing is disabled,
    so normal ``print()`` calls would produce stair-stepped output.  This
    wrapper normalizes any existing ``\\r\\n`` first and then converts remaining
    ``\\n`` characters to ``\\r\\n``.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        if hasattr(stream, "buffer"):
            self.buffer = _RawStdoutBufferWrapper(stream.buffer)

    def write(self, text: str) -> None:
        self._stream.write(text.replace("\r\n", "\n").replace("\n", "\r\n"))

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return getattr(self._stream, "isatty", lambda: False)()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)

def _restore_tty_for_command(
    fd: Optional[int],
    old_settings: Optional[Any],
    original_stdout: Any,
    raw_mode_active: bool,
) -> None:
    """Restore cooked TTY mode and original stdout while handling a command.

    Raw mode is great for the single-line ANSI editor, but commands such as
    ``/send`` may drop into multi-line ``input()`` loops.  Those need the
    terminal back in cooked mode and stdout unwrapped so ``\n`` is handled
    normally.
    """
    if not raw_mode_active:
        return
    sys.stdout = original_stdout
    if fd is not None and old_settings is not None and termios is not None:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except termios.error:
            pass


def _enter_raw_tty_for_input(
    fd: Optional[int],
    original_stdout: Any,
    raw_mode_active: bool,
) -> None:
    """Re-enable raw TTY mode and wrap stdout after command handling."""
    if not raw_mode_active:
        return
    if fd is not None and tty is not None:
        try:
            tty.setraw(fd)
        except termios.error:
            pass
    sys.stdout = _RawStdoutWrapper(original_stdout)


def _dispatch_input(
    cmd_line: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> bool:
    """Handle a single raw-mode user command.

    Returns ``False`` when the user wants to leave the stream (q/quit/exit/cd).
    """
    lower = cmd_line.lower()
    if lower in ("q", "quit", "exit"):
        print(f"\n{Colors.YELLOW}[INFO] Quit requested.{Colors.RESET}")
        return False
    if lower in ("cd", "/cd"):
        print(
            f"\n{Colors.YELLOW}[INFO] Return to workspace scope requested.{Colors.RESET}"
        )
        return False
    if lower.startswith("/"):
        _handle_stream_command(
            cmd_line,
            task_dir,
            log_files,
            default_session_id,
            default_stdout_path,
        )
        return True
    return _prompt_send_as_message(
        cmd_line,
        task_dir,
        log_files,
        default_session_id,
        default_stdout_path,
        input_provider=None,
        output_callback=None,
        input_callback=None,
    )


def _stream_file_raw(
    filepath: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
    tail_lines: int = 100,
) -> None:
    """Raw curses-free stream implementation used when ``--runtime-raw`` is set."""

    filename = os.path.basename(filepath)
    print_header(f"Streaming: {filename}")
    print(
        f"{Colors.YELLOW}[INFO] Press 'q' then Enter to quit, "
        f"type '/send [message]' to send a message, "
        f"'/ctx.btw [message]' to inject an agent2llm message, or Ctrl+C to exit.{Colors.RESET}\n"
    )
    session_label = default_session_id or "(temp)"
    prompt = f"[runtime:{session_label}]> "

    fd = None
    if sys.stdin.isatty():
        try:
            fd = sys.stdin.fileno()
        except (OSError, ValueError):
            fd = None
    old_settings = None
    raw_mode_active = False
    original_stdout = sys.stdout

    try:
        try:
            if fd is not None and termios is not None and tty is not None:
                try:
                    old_settings = termios.tcgetattr(fd)
                    tty.setraw(fd)
                    raw_mode_active = True
                except Exception:
                    pass

            if raw_mode_active:
                sys.stdout = _RawStdoutWrapper(sys.stdout)

            if raw_mode_active:
                _tail_file(filepath, tail_lines, raw_mode=True)
            else:
                _tail_file(filepath, tail_lines)

            with open(filepath, "rb") as f:
                f.seek(0, 2)
                while state.running:
                    chunk = f.read(4096)
                    if chunk:
                        if raw_mode_active:
                            chunk = chunk.replace(b"\r\n", b"\n").replace(
                                b"\n", b"\r\n"
                            )
                        if hasattr(sys.stdout, "buffer"):
                            sys.stdout.buffer.write(chunk)
                            sys.stdout.buffer.flush()
                        else:
                            print(chunk.decode("utf-8", errors="replace"), end="")
                            sys.stdout.flush()
                    else:
                        if sys.stdin.isatty():
                            readable, _, _ = select.select([sys.stdin], [], [], 0.05)
                            if readable:
                                cmd_line = _read_input_line(
                                    prompt, already_raw=raw_mode_active
                                )
                                if cmd_line is None:
                                    break
                                if not cmd_line:
                                    continue
                                _restore_tty_for_command(
                                    fd,
                                    old_settings,
                                    original_stdout,
                                    raw_mode_active,
                                )
                                keep_running = True
                                try:
                                    keep_running = _dispatch_input(
                                        cmd_line,
                                        task_dir,
                                        log_files,
                                        default_session_id,
                                        default_stdout_path,
                                    )
                                finally:
                                    if keep_running:
                                        _enter_raw_tty_for_input(
                                            fd,
                                            original_stdout,
                                            raw_mode_active,
                                        )
                                if not keep_running:
                                    break
                        else:
                            time.sleep(0.05)
        finally:
            sys.stdout = original_stdout
            if old_settings is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except termios.error:
                    pass
    except FileNotFoundError:
        print(f"{Colors.RED}[ERROR] File not found: {filepath}{Colors.RESET}")
    except PermissionError:
        print(f"{Colors.RED}[ERROR] Permission denied: {filepath}{Colors.RESET}")
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[INFO] Interrupted by user.{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to stream file: {e}{Colors.RESET}")

    print(f"\n{Colors.CYAN}[INFO] Streaming stopped.{Colors.RESET}")


def _stream_file_legacy(
    filepath: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> None:
    """Legacy single-pane stream implementation for non-TTY environments."""

    filename = os.path.basename(filepath)
    print_header(f"Streaming: {filename}")
    print(
        f"{Colors.YELLOW}[INFO] Press 'q' then Enter to quit, "
        f"type '/send [message]' to send a message, "
        f"'/ctx.btw [message]' to inject an agent2llm message, or Ctrl+C to exit.{Colors.RESET}\n"
    )

    session_label = default_session_id or "(temp)"
    prompt = f"[runtime:{session_label}]> "

    try:
        subprocess.run(["tail", "-n", "100", filepath], check=False)
    except Exception:
        pass

    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            while state.running:
                chunk = f.read(4096)
                if chunk:
                    if hasattr(sys.stdout, "buffer"):
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                    else:
                        print(chunk.decode("utf-8", errors="replace"), end="")
                        sys.stdout.flush()
                else:
                    if sys.stdin.isatty():
                        readable, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if readable:
                            cmd_line = _read_input_line(prompt)
                            if cmd_line is None:
                                break
                            if not cmd_line:
                                continue
                            lower = cmd_line.lower()
                            if lower in ("q", "quit", "exit"):
                                print(
                                    f"\n{Colors.YELLOW}[INFO] Quit requested.{Colors.RESET}"
                                )
                                break
                            if lower in ("cd", "/cd"):
                                print(
                                    f"\n{Colors.YELLOW}[INFO] Return to workspace scope requested.{Colors.RESET}"
                                )
                                break
                            if lower.startswith("/"):
                                _handle_stream_command(
                                    cmd_line,
                                    task_dir,
                                    log_files,
                                    default_session_id,
                                    default_stdout_path,
                                )
                                continue
                            _prompt_send_as_message(
                                cmd_line,
                                task_dir,
                                log_files,
                                default_session_id,
                                default_stdout_path,
                                input_provider=None,
                                output_callback=None,
                                input_callback=None,
                            )
                    else:
                        time.sleep(0.05)
    except FileNotFoundError:
        print(f"{Colors.RED}[ERROR] File not found: {filepath}{Colors.RESET}")
    except PermissionError:
        print(f"{Colors.RED}[ERROR] Permission denied: {filepath}{Colors.RESET}")
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[INFO] Interrupted by user.{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to stream file: {e}{Colors.RESET}")

    print(f"\n{Colors.CYAN}[INFO] Streaming stopped.{Colors.RESET}")


def _handle_stream_command(
    cmd_line: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
    input_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """
    Execute a command entered while streaming a log file.

    Supports ``/send`` (defaulting to the watched session), ``/ctx.btw``
    (inject an agent2llm message), and ``/help``.

    Args:
        input_provider: Optional callable used to collect multi-line input
            in environments where ``input()`` is not available (e.g. the
            curses UI).  Receives a prompt string and returns the collected
            text, or ``None`` if the user cancelled.
    """
    if not cmd_line:
        return

    parts = cmd_line.split(None, 1)
    cmd = parts[0].lower()
    if cmd == "/send":
        _handle_stream_send(
            cmd_line,
            task_dir,
            log_files,
            default_session_id,
            default_stdout_path,
            input_provider=input_provider,
        )
        return

    if cmd == "/ctx.btw":
        _handle_stream_ctx_btw(cmd_line, task_dir, input_provider=input_provider)
        return

    if cmd == "/help":
        print(
            "Available commands:\n"
            "  /send [message]      - Send a message to the watched session\n"
            "  /ctx.btw [message]   - Inject an agent2llm message\n"
            "  /help                - Show this help message\n"
            "  q / quit / exit      - Stop streaming\n"
            "  cd or /cd            - Return to workspace scope"
        )
        return

    print(
        f"{Colors.RED}[ERROR] Unknown streaming command: {cmd_line}. "
        f"Use '/send [message]', '/ctx.btw [message]', '/help', 'q', 'quit', 'exit', or 'cd'.{Colors.RESET}"
    )


def _handle_stream_send(
    cmd_line: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
    input_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """
    Handle ``/send`` while streaming, defaulting to the watched session.

    In runtime scope the watched session is already known, so any text after
    ``/send`` is treated as the message body.  When no message is provided,
    multi-line input is collected through the available input provider.
    """
    if default_session_id is None:
        print(
            f"{Colors.RED}[ERROR] No session associated with this log file.{Colors.RESET}"
        )
        return

    message: Optional[str] = cmd_line[len("/send"):].strip() or None

    if message is None:
        if input_provider is not None:
            message = input_provider(
                f"{Colors.CYAN}[INFO] Enter /send message (Ctrl+D to finish):{Colors.RESET}"
            )
        else:
            message = _read_multiline_input_for_send()
        if message is None:
            return

    send_message_to_session(
        default_session_id, message, task_dir, stdout_path=default_stdout_path
    )


def _read_multiline_input_for_send() -> Optional[str]:
    """
    Read multi-line input until a standalone 'EOF' line is entered.

    Returns ``None`` if the user cancels with Ctrl+C.
    """
    print(
        f"{Colors.CYAN}[INFO] Enter message (type EOF on its own line to finish):{Colors.RESET}"
    )
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}[INFO] Cancelled.{Colors.RESET}")
            return None
        if line == "EOF":
            break
        lines.append(line)
    return "\n".join(lines)


def _read_multiline_input_for_ctx_btw() -> Optional[str]:
    """
    Read multi-line input until EOF (Ctrl+D) or a standalone 'EOF' line is received.

    Returns ``None`` if the user cancels with Ctrl+C.
    """
    print(
        f"{Colors.CYAN}[INFO] Enter /ctx.btw message (type EOF on its own line or Ctrl+D to finish):{Colors.RESET}"
    )
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}[INFO] Cancelled.{Colors.RESET}")
            return None
        if line == "EOF":
            break
        lines.append(line)
    return "\n".join(lines)

def _handle_stream_ctx_btw(
    cmd_line: str,
    task_dir: str,
    input_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """
    Handle ``/ctx.btw`` while streaming by delegating to the YAML command.

    The ``runtime`` scope and watched session ID are already set by
    ``stream_file``, so ``match_yaml_command`` can resolve the target
    session automatically.  Supports inline arguments as well as
    interactive multi-line input when no argument is provided.
    """
    matched = yaml_commands.match_yaml_command(cmd_line, task_dir)
    if matched is None:
        print(
            f"{Colors.RED}[ERROR] Could not match /ctx.btw command. "
            f"Is there a session associated with this log file?{Colors.RESET}"
        )
        return
    instruction, variables = matched

    # When no inline message is provided, collect multi-line input.  Use the
    # external provider (e.g. the curses UI) when available; otherwise fall
    # back to standard input so raw/legacy streaming modes also support
    # multi-line messages.
    if not variables.get("message", "").strip() and instruction.get("shell", ""):
        if input_provider is not None:
            message = input_provider(
                f"{Colors.CYAN}[INFO] Enter /ctx.btw message (Ctrl+D to finish):{Colors.RESET}"
            )
        else:
            message = _read_multiline_input_for_ctx_btw()
        if message is None:
            print(f"\n{Colors.YELLOW}[INFO] Cancelled.{Colors.RESET}")
            return
        message = message.strip()
        if not message:
            print(f"{Colors.RED}[ERROR] Message cannot be empty.{Colors.RESET}")
            return
        variables = dict(variables)
        variables["message"] = message

    yaml_commands.handle_yaml_command(instruction, variables)


def _format_pipe_payload(message: str) -> bytes:
    """
    Format a message for the pipe protocol.

    Ensures the message body ends with a newline, then appends the EOF
    marker on its own line.
    """
    if not message.endswith("\n"):
        message += "\n"
    if not message.endswith("EOF\n"):
        message += "EOF\n"
    return message.encode("utf-8")


def send_message_to_session(
    session_id: str,
    message: str,
    task_dir: str,
    timeout: float = 5.0,
    stdout_path: Optional[str] = None,
    pid: Optional[int] = None,
) -> bool:
    """
    Send a message to a running session through its named pipe.

    Session and task stdout files follow the conventions documented in
    README.md:
      - Session stdout: ``{session_id}.{pid}.session.stdout``
      - Task stdout: ``{session_id}.{pid}[.{other}].task.stdout``
      - ``topsailai`` as ``{session_id}`` means the session id is undefined
        and is displayed as ``(temp)``.

    PID resolution priority:
      1. ``pid`` argument when provided (e.g. from the task list entry).
      2. PID parsed from the stdout filename.
      3. PID discovered by scanning processes that currently have the stdout
         file open (``lsof`` / ``fuser``).

    Args:
        session_id: Target session identifier.
        message: Message text to send.
        task_dir: Task directory containing stdout/pipe files.
        timeout: Maximum seconds to wait for the receiver to open the pipe.
        stdout_path: Exact stdout file path when known (e.g. from numeric
            selection), used to target temporary sessions precisely.
        pid: Optional process PID known to own the session. When provided,
            this takes precedence over filename parsing and process scanning.

    Returns:
        ``True`` if the message was sent, ``False`` otherwise.
    """
    if stdout_path is None:
        stdout_path = _find_session_stdout_file(task_dir, session_id)
        if stdout_path is None:
            print(
                f"{Colors.RED}[ERROR] No stdout file found for session '{session_id}'.{Colors.RESET}"
            )
            return False
    elif stdout_path.endswith(".task.stdout"):
        # Task stdout files use the child task PID in the filename
        # ({session_id}.{pid}[.{other}].task.stdout), not the session PID.
        # Resolve the canonical session stdout file for the same session so
        # the named pipe path uses the session process PID.
        task_session_id, _ = _parse_stdout_filename(os.path.basename(stdout_path))
        resolved_session_id = (
            task_session_id if task_session_id is not None else session_id
        )
        resolved_stdout = _find_session_stdout_file(task_dir, resolved_session_id)
        if resolved_stdout is None:
            print(
                f"{Colors.RED}[ERROR] No session stdout file found for session "
                f"'{resolved_session_id}'.{Colors.RESET}"
            )
            return False
        stdout_path = resolved_stdout
    elif not os.path.isfile(stdout_path):
        print(
            f"{Colors.RED}[ERROR] Stdout file not found: {stdout_path}.{Colors.RESET}"
        )
        return False

    # Resolve the session PID using the documented priority:
    #   1. Caller-supplied pid (e.g. from the task list entry).
    #   2. PID embedded in the stdout filename.
    #   3. PID from scanning open files (lsof / fuser).
    pipe_path: Optional[str] = None

    if pid is not None:
        candidate_pipe = _build_pipe_path(task_dir, session_id, pid)
        if os.path.exists(candidate_pipe):
            pipe_path = candidate_pipe

    if pipe_path is None:
        pid = _get_pid_from_stdout_path(stdout_path)
        if pid is not None:
            candidate_pipe = _build_pipe_path(task_dir, session_id, pid)
            if os.path.exists(candidate_pipe):
                pipe_path = candidate_pipe

    if pipe_path is None:
        pid = get_file_pid(stdout_path)
        if pid is not None:
            candidate_pipe = _build_pipe_path(task_dir, session_id, pid)
            if os.path.exists(candidate_pipe):
                pipe_path = candidate_pipe

    if pipe_path is None:
        print(
            f"{Colors.RED}[ERROR] Session '{session_id}' does not appear to be running "
            f"(no process owns its stdout file).{Colors.RESET}"
        )
        return False

    if not stat.S_ISFIFO(os.stat(pipe_path).st_mode):
        print(
            f"{Colors.RED}[ERROR] Path exists but is not a named pipe: {pipe_path}.{Colors.RESET}"
        )
        return False

    payload = _format_pipe_payload(message)
    fd: Optional[int] = None
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
                break
            except OSError as exc:
                if exc.errno == errno.ENXIO:
                    if time.monotonic() >= deadline:
                        print(
                            f"{Colors.RED}[ERROR] Timed out waiting for session to open "
                            f"the pipe for reading.{Colors.RESET}"
                        )
                        return False
                    time.sleep(0.1)
                    continue
                raise
        os.write(fd, payload)
        print(
            f"{Colors.GREEN}[INFO] Message sent to session '{session_id}' via "
            f"{pipe_path} ({len(payload)} bytes).{Colors.RESET}"
        )
        return True
    except OSError as exc:
        print(
            f"{Colors.RED}[ERROR] Failed to write to pipe {pipe_path}: {exc}{Colors.RESET}"
        )
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def handle_send_command(
    user_input: str, task_dir: str, log_files: List[dict]
) -> None:
    """
    Parse and execute the ``/send`` command.

    In session scope, the argument is the message.  In workspace scope, the
    first argument is a session ID or 1-based index, and the remainder is the
    message.  When no message is provided, interactive multi-line input is used.
    """
    stdout_path: Optional[str] = None
    pid: Optional[int] = None
    parts = user_input.split(None, 1)
    if len(parts) < 2:
        if state.current_scope == "session" and state.current_session_id:
            session_id = state.current_session_id
            message: Optional[str] = None
        else:
            print(
                f"{Colors.RED}[ERROR] Usage: /send <session_id_or_index> [message...] "
                f"or enter a session scope first with /cd.{Colors.RESET}"
            )
            return
    else:
        arg = parts[1]
        if state.current_scope == "session" and state.current_session_id:
            session_id = state.current_session_id
            message = arg
        else:
            sub_parts = arg.split(None, 1)
            target = _resolve_send_target_from_arg(sub_parts[0], log_files)
            if target is None:
                print(
                    f"{Colors.RED}[ERROR] Could not resolve session from "
                    f"'{sub_parts[0]}'.{Colors.RESET}"
                )
                return
            session_id, stdout_path, pid = target
            message = sub_parts[1] if len(sub_parts) > 1 else None

    if message is None:
        message = _read_multiline_input_for_send()
        if message is None:
            return

    if stdout_path is not None:
        send_message_to_session(
            session_id, message, task_dir, stdout_path=stdout_path, pid=pid
        )
    else:
        send_message_to_session(session_id, message, task_dir, pid=pid)
