"""
Input utilities with timeout support.

This module provides helpers for reading user input in interactive
environments while respecting a timeout and preserving terminal echo.
"""

from __future__ import annotations

import atexit
import contextlib
import errno
import functools
import io
import json
import logging
import os
import readline
import select
import subprocess
import sys
import termios
import textwrap
import time
import typing

logger = logging.getLogger(__name__)


class InputTimeoutError(TimeoutError):
    """Raised when :func:`input_with_timeout` exceeds the requested timeout."""


if typing.TYPE_CHECKING:
    TextIO = typing.TextIO
else:
    TextIO = typing.Any


@contextlib.contextmanager
def _configure_terminal(fd: int):
    """
    Context manager that enables canonical mode and echo on a terminal fd.

    Yields the original terminal settings so callers can compare or restore
    them manually. If the fd is invalid or not a terminal, yields None and
    does not modify the terminal.
    """
    old_settings = None
    try:
        old_settings = termios.tcgetattr(fd)
        new_settings = termios.tcgetattr(fd)
        # Ensure canonical mode and echo are enabled so typed characters are
        # visible without relying on the readline library state.
        new_settings[3] |= termios.ICANON | termios.ECHO
        termios.tcsetattr(fd, termios.TCSADRAIN, new_settings)
    except Exception as exc:  # pragma: no cover - fd may not be a real tty
        logger.debug("Could not configure terminal for input_with_timeout: %s", exc)

    try:
        yield old_settings
    finally:
        if old_settings is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception as exc:  # pragma: no cover
                logger.debug(
                    "Could not restore terminal for input_with_timeout: %s", exc
                )


def input_with_timeout(
    prompt: str = "",
    timeout: float | None = None,
    default: str | None = None,
    stream: TextIO | None = None,
    output: TextIO | None = None,
    raise_on_timeout: bool = False,
) -> str | None:
    """
    Read a single line from *stream* with an optional timeout.

    On POSIX systems where *stream* is backed by a real terminal, this
    function explicitly enables canonical mode and echo so that the prompt
    and typed characters are visible, then waits up to *timeout* seconds for
    the user to press Enter.

    On non-POSIX systems, on streams without a file descriptor, or on
    non-interactive streams, the function returns *default* immediately so
    that callers do not block indefinitely.

    Parameters
    ----------
    prompt:
        Text to display before reading input.
    timeout:
        Maximum time to wait in seconds. ``None`` means wait indefinitely.
    default:
        Value returned when the timeout expires or when input is unavailable.
    stream:
        Input stream to read from. Defaults to ``sys.stdin``.
    output:
        Output stream to print the prompt to. Defaults to ``sys.stdout``.
    raise_on_timeout:
        If ``True``, raise :class:`InputTimeoutError` instead of returning
        *default* when the timeout expires.

    Returns
    -------
    The input line without the trailing newline, or *default* if the timeout
    expired or the stream cannot be used for interactive input.

    Raises
    ------
    InputTimeoutError:
        If *raise_on_timeout* is ``True`` and no input was received in time.
    """
    if stream is None:
        stream = sys.stdin
    if output is None:
        output = sys.stdout

    if prompt:
        output.write(prompt)
        output.flush()

    # No timeout requested: use a simple blocking readline.
    if timeout is None:
        try:
            line = stream.readline()
        except EOFError:
            return default
        if not line:
            return default
        return line.rstrip("\n")

    # Determine whether we can use POSIX terminal/select machinery.
    fd: int | None = None
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        fd = None

    is_tty = False
    if fd is not None:
        try:
            is_tty = stream.isatty()
        except Exception:
            is_tty = False

    if fd is None or not is_tty:
        # We cannot enforce a timeout safely on this stream without blocking
        # the caller. Return the default immediately.
        logger.debug(
            "input_with_timeout: stream is not a POSIX tty (fd=%s, isatty=%s); "
            "returning default",
            fd,
            is_tty,
        )
        return default

    # POSIX tty path: configure terminal for visible echo and canonical mode.
    line = ""
    deadline = time.monotonic() + float(timeout)
    with _configure_terminal(fd):
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                # In canonical mode select returns readable only after the user
                # presses Enter, so readline() will return immediately.
                readable, _, _ = select.select(
                    [stream], [], [], min(remaining, 0.1)
                )
                if readable:
                    try:
                        line = stream.readline()
                    except EOFError:
                        break
                    if line:
                        break
        except Exception as exc:  # pragma: no cover - stdin may be unavailable
            logger.debug("input_with_timeout read failed: %s", exc)

    if not line:
        if raise_on_timeout:
            raise InputTimeoutError(
                f"No input received within {timeout} seconds"
            )
        return default

    return line.rstrip("\n")


def _safe_unlink(path: str) -> None:
    """Remove *path* if it exists, ignoring errors."""
    abs_path = os.path.abspath(path)
    try:
        os.unlink(path)
        logger.info("Removed pipe file: %s", abs_path)
    except FileNotFoundError:
        logger.info("Pipe file already removed: %s", abs_path)
    except OSError as exc:  # pragma: no cover - defensive cleanup
        logger.error("Failed to remove pipe file %s: %s", abs_path, exc)


def load_input_history_jsonl(history_file: str) -> list[dict]:
    """Load JSONL input history from *history_file*.

    Each line must be a JSON object. Lines that cannot be parsed are skipped.
    Returns a list of history entries ordered from oldest to newest.
    """
    entries: list[dict] = []
    if not history_file or not os.path.exists(history_file):
        return entries
    try:
        with open(history_file, "r", encoding="utf-8") as fd:
            for line in fd:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if isinstance(entry, dict) and "text" in entry:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.debug("Could not load JSONL history %s: %s", history_file, exc)
    return entries


def append_input_history_jsonl(
    history_file: str, session_id: str, text: str
) -> None:
    """Append a single message to the JSONL history file.

    The entry is written as ``{"ts": <ISO8601>, "session_id": ..., "text": ...}``.
    The parent directory is created if it does not exist.
    """
    if not history_file or not text:
        return
    try:
        parent = os.path.dirname(history_file)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            "session_id": session_id or "",
            "text": text,
        }
        with open(history_file, "a", encoding="utf-8") as fd:
            fd.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("Could not append JSONL history %s: %s", history_file, exc)



def _flatten_completion_data(data: typing.Any) -> list[str]:
    """Flatten completion definitions into a sorted string list.

    Supports:
    - A flat list of strings
    - A dict with a ``completions`` key containing a list of completion
      entries.  Each entry may be a plain string or a dict with at least a
      ``text`` key.  Dict entries may also provide ``aliases`` (a list of
      alternative strings that expand to ``text``).
    - A flat dict whose values are completion entry dicts.
    """
    items: set[str] = set()

    def _collect_entry(entry: typing.Any) -> None:
        if isinstance(entry, str):
            items.add(entry)
        elif isinstance(entry, dict):
            text = entry.get("text")
            if isinstance(text, str):
                items.add(text)
            for alias in entry.get("aliases", []):
                if isinstance(alias, str):
                    items.add(alias)

    def _collect(value: typing.Any) -> None:
        if isinstance(value, list):
            for item in value:
                _collect_entry(item)
        elif isinstance(value, dict):
            if "completions" in value:
                _collect(value["completions"])
            else:
                for item in value.values():
                    _collect_entry(item)

    if isinstance(data, dict) and "completions" in data:
        _collect(data["completions"])
    elif isinstance(data, dict):
        _collect(data)
    elif isinstance(data, list):
        _collect(data)
    return sorted(items)


def load_input_completions(completion_file: str | None) -> list[str]:
    """Load TAB completion items from a JSON file.

    The JSON file may define completions as either a flat list of strings or
    an object with a ``completions`` key containing entry dicts.  Each entry
    dict has a ``text`` field and optionally ``aliases``.  Missing or
    malformed files are ignored.
    """
    completions: list[str] = []
    if not completion_file or not os.path.exists(completion_file):
        return completions
    try:
        with open(completion_file, "r", encoding="utf-8") as fd:
            data = json.load(fd)
        completions = _flatten_completion_data(data)
    except Exception as exc:
        logger.debug("Could not load input completions %s: %s", completion_file, exc)
    return completions


def _ensure_fifo(pipe_path: str) -> None:
    """Create a FIFO at *pipe_path*, ensuring the parent directory exists."""
    parent = os.path.dirname(pipe_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        os.mkfifo(pipe_path)
    except FileExistsError:
        # A leftover pipe from a crashed process; replace it.
        _safe_unlink(pipe_path)
        os.mkfifo(pipe_path)


def _strip_eof_marker(text: str, eof_marker: str) -> str:
    """Return *text* with the first standalone *eof_marker* line removed."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line == eof_marker:
            lines = lines[:i]
            break
    return "\n".join(lines)


def _has_eof_marker(decoded: str, eof_marker: str) -> bool:
    """Check whether *decoded* ends with a standalone EOF marker line."""
    return decoded.endswith(f"\n{eof_marker}")


# Buffer for leftover content read from a pipe when single_line=True.
# Keyed by pipe path so that multiple _input() calls in Strategy A can
# return one line at a time from a multi-line pipe message.
_pipe_leftover_buffer: dict[str, list[str]] = {}


def _get_buffered_line(pipe_path: str, eof_marker: str = "EOF") -> str | None:
    """Return and consume the next buffered line for *pipe_path*.

    The EOF marker line is consumed and returned as an empty string so that
    callers can detect end-of-input while still receiving genuine empty lines
    as content when *raise_eof_error* is not enabled.

    Returns ``None`` when no buffered lines remain.
    """
    lines = _pipe_leftover_buffer.get(pipe_path)
    if not lines:
        return None
    line = lines.pop(0)
    if not lines:
        del _pipe_leftover_buffer[pipe_path]
    if line == eof_marker:
        return ""
    return line


def _strip_eof_suffix(text: str, eof_marker: str) -> tuple[str, bool]:
    """Strip the first standalone EOF marker and everything after it.

    The marker is recognized when:
    - the text contains ``\\n{eof_marker}\\n`` (marker on its own line
      followed by more content), or
    - the text ends with ``\\n{eof_marker}`` (marker as the final line).

    After stripping, the result is ``str.strip()``-ed so callers receive
    clean input.
    """
    marker_prefix = "\n" + eof_marker
    embedded = marker_prefix + "\n"
    idx = text.find(embedded)
    if idx != -1:
        return text[:idx].strip(), True
    eof_seen = text.endswith(marker_prefix)
    if eof_seen:
        text = text[: -len(marker_prefix)]
    return text.strip(), eof_seen


def _buffer_leftover(pipe_path: str, text: str) -> None:
    """Store leftover lines from *text* for later single-line reads."""
    if not text:
        return
    lines = text.splitlines()
    if not lines:
        return
    _pipe_leftover_buffer[pipe_path] = lines


def _clear_leftover_buffer(pipe_path: str) -> None:
    """Discard any buffered lines for *pipe_path*."""
    _pipe_leftover_buffer.pop(pipe_path, None)


def _set_nonblocking(fd: int) -> int:
    """Set *fd* to non-blocking mode and return the original flags.

    Returns -1 if the fd cannot be configured (e.g. on platforms without
    ``fcntl`` or when the fd is invalid).
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows fallback
        return -1
    try:
        original = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, original | os.O_NONBLOCK)
        return original
    except OSError:
        return -1


def _restore_fd_flags(fd: int, original: int) -> None:
    """Restore *fd* flags to *original* if possible."""
    if original < 0:
        return
    try:
        import fcntl
        fcntl.fcntl(fd, fcntl.F_SETFL, original)
    except OSError:  # pragma: no cover - fd may have been closed
        pass


def _read_available(fd: int) -> bytes:
    """Read available data from a non-blocking file descriptor."""
    try:
        return os.read(fd, 4096)
    except BlockingIOError:
        return b""
    except OSError as exc:
        if exc.errno == errno.EAGAIN:
            return b""
        raise


def _spawn_terminal_input_subprocess(
    prompt: str = "",
    timeout: float | None = None,
    stdin_fd: int | None = None,
    history_file: str | None = None,
    completion_file: str | None = None,
) -> tuple[subprocess.Popen | None, int | None]:
    """Spawn a helper process that reads a terminal line and forwards it.

    The helper reads from the caller's terminal *stdin_fd* (which must be a
    terminal), calls ``input(prompt)`` (enabling GNU readline / arrow keys),
    and writes the collected line to an anonymous pipe.  The parent monitors
    the read end of that pipe, so terminal input never blocks pipe input and
    vice versa.

    If *history_file* is provided, it is treated as a JSONL file where each
    line is ``{"ts": ..., "session_id": ..., "text": ...}``.  The ``text``
    values are loaded into readline history so the user can navigate previous
    messages with the UP/DOWN arrow keys.

    If *completion_file* is provided, it is treated as a JSON file containing
    completion entries.  Each entry may be a plain string or an object with
    ``text`` and optional ``aliases``.  Aliases expand to ``text`` when
    completed.

    Parameters
    ----------
    prompt:
        Prompt string displayed by the helper's ``input()`` call.
    timeout:
        Maximum time in seconds to wait for terminal input. ``None`` waits
        indefinitely.
    stdin_fd:
        File descriptor of the terminal to read from.  When ``None``, the
        helper inherits the parent's fd 0.
    history_file:
        Optional path to a JSONL history file to preload into readline.
    completion_file:
        Optional path to a JSON file containing TAB completion candidates.

    Returns
    -------
    A ``(Popen, read_fd)`` tuple, or ``(None, None)`` if the platform is not
    POSIX or the helper cannot be spawned.
    """
    if sys.platform == "win32" or not hasattr(os, "mkfifo"):
        return None, None

    read_fd, write_fd = os.pipe()

    helper = textwrap.dedent(
        f'''import json
import os
import readline
import signal
import sys
import termios

write_fd = {write_fd}
prompt = {prompt!r}
timeout = {timeout!r}
history_file = {history_file!r}
completion_file = {completion_file!r}

def _restore_termios():
    try:
        termios.tcsetattr(0, termios.TCSADRAIN, old_termios)
    except Exception:
        pass

def _alarm_handler(signum, frame):
    _restore_termios()
    sys.exit(0)

def _term_handler(signum, frame):
    _restore_termios()
    sys.exit(0)

old_termios = None
try:
    old_termios = termios.tcgetattr(0)
except Exception:
    pass

signal.signal(signal.SIGALRM, _alarm_handler)
signal.signal(signal.SIGTERM, _term_handler)

# Preload JSONL history so UP/DOWN arrow keys recall previous messages.
if history_file:
    try:
        with open(history_file, "r", encoding="utf-8") as fd:
            for line in fd:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    text = entry.get("text", "")
                    if text:
                        readline.add_history(text)
                except Exception:
                    continue
    except Exception:
        pass

# Load TAB completion candidates from JSON.  Aliases expand to text.
_completion_map = {{}}

def _register(entry):
    if isinstance(entry, str):
        _completion_map[entry] = entry
    elif isinstance(entry, dict):
        text = entry.get("text")
        if isinstance(text, str):
            _completion_map[text] = text
            for alias in entry.get("aliases", []):
                if isinstance(alias, str):
                    _completion_map[alias] = text

def _load_completions(value):
    if isinstance(value, list):
        for item in value:
            _register(item)
    elif isinstance(value, dict):
        if "completions" in value:
            _load_completions(value["completions"])
        else:
            for item in value.values():
                _register(item)

if completion_file:
    try:
        with open(completion_file, "r", encoding="utf-8") as fd:
            data = json.load(fd)
        if data is not None:
            _load_completions(data)
    except Exception:
        pass

_candidates = sorted(set(_completion_map.keys()))

def _completer(text, state):
    matches = [_completion_map[c] for c in _candidates if c.startswith(text)]
    matches = sorted(set(matches))
    if state < len(matches):
        return matches[state]
    return None

if _candidates:
    readline.set_completer(_completer)
    readline.parse_and_bind("tab: complete")
    # Keep leading '/' as part of the completion word so slash
    # commands like /help can be completed from "/h".
    readline.set_completer_delims(
        readline.get_completer_delims().replace("/", "")
    )

eof_or_interrupt = False
try:
    if timeout is not None:
        signal.setitimer(
            signal.ITIMER_REAL, max(float(timeout), 0.001)
        )
    try:
        line = input(prompt)
    except (TimeoutError, EOFError, KeyboardInterrupt, OSError):
        eof_or_interrupt = True
finally:
    signal.alarm(0)
    _restore_termios()

if eof_or_interrupt:
    # Signal EOF/interrupt by closing the write end without writing.
    try:
        os.close(write_fd)
    except Exception:
        pass
else:
    try:
        with os.fdopen(write_fd, "w", closefd=True) as fifo:
            fifo.write(line + chr(10))
    except Exception:
        pass
'''
    )
    try:
        popen_kwargs: dict[str, typing.Any] = {
            "stdout": None,
            "stderr": None,
            "pass_fds": [write_fd],
        }
        if stdin_fd is not None:
            popen_kwargs["stdin"] = stdin_fd
        proc = subprocess.Popen(
            [sys.executable, "-c", helper],
            **popen_kwargs,
        )
        os.close(write_fd)
        return proc, read_fd
    except OSError:  # pragma: no cover - process spawn may fail in restricted envs
        os.close(read_fd)
        os.close(write_fd)
        return None, None

def input_from_pipe(
    pipe_path: str,
    *,
    timeout: float | None = None,
    encoding: str = "utf-8",
    eof_marker: str = "EOF",
    raise_eof_error: bool = False,
    single_line: bool = False,
    prompt: str = "",
    cleanup_pipe: bool = True,
    history_file: str | None = None,
    completion_file: str | None = None,
) -> str:
    """Read a message from a named pipe (FIFO).

    Creates the FIFO at *pipe_path* and waits for input.  When the caller's
    ``sys.stdin`` is a real terminal, a small helper process is spawned that
    calls ``input()`` on the terminal (enabling GNU readline / arrow keys) and
    forwards the collected line through a separate anonymous pipe.  The main
    loop monitors both the FIFO and the helper pipe, so pipe input remains
    non-blocking and takes priority over terminal input.

    By default the FIFO is removed before returning.  Pass
    *cleanup_pipe=False* when the caller wants to keep the FIFO alive for
    subsequent reads (for example, session-scoped pipes that receive multiple
    messages during the process lifetime).

    When *single_line* is ``True`` and the pipe delivers more than one line,
    the first line is returned and the remaining lines are buffered under
    *pipe_path* for subsequent calls. This makes multi-line pipe input work
    when a sender writes several lines at once.

    If *history_file* is provided, it is treated as a JSONL file where each
    line is ``{"ts": ..., "session_id": ..., "text": ...}``.  The ``text``
    values are loaded into the helper's readline history so the user can
    navigate previous messages with the UP/DOWN arrow keys.

    If *completion_file* is provided, it is treated as a JSON file containing
    completion entries.  Each entry may be a plain string or an object with
    ``text`` and optional ``aliases``.  These strings are registered as TAB
    completion candidates in the helper's readline completer.

    Parameters
    ----------
    pipe_path:
        Absolute path to the FIFO to create and read from.
    timeout:
        Maximum time in seconds to wait for input. ``None`` waits
        indefinitely.
    encoding:
        Encoding used to decode bytes read from the pipe.
    eof_marker:
        Optional marker that terminates input when seen on its own line.
        The marker line and anything after it is stripped from the result.
        The marker is recognized when it appears as a standalone line
        preceded by a newline (``\\n{eof_marker}``), either at the end of
        the input or followed by another newline (``\\n{eof_marker}\\n``).
    raise_eof_error:
        When ``True`` and the EOF marker is detected, raise :class:`EOFError`
        instead of returning the stripped content. Defaults to ``False`` for
        backward compatibility.
        When ``True``, return the first line of input (everything before
        the first ``\\n``). Any remaining content is buffered for the next
        call with the same *pipe_path*.
    prompt:
        Prompt displayed to the user when terminal input is used.
    cleanup_pipe:
        When ``True`` (the default), the FIFO is removed before returning.
        When ``False``, the caller is responsible for cleanup.
    history_file:
        Optional path to a JSONL history file to preload into the terminal
        helper's readline history.
    completion_file:
        Optional path to a JSON file containing TAB completion candidates.

    Returns
    -------
    The decoded message read from the pipe or from the terminal helper.

    Raises
    ------
    NotImplementedError:
        If the platform does not support named pipes.
    TimeoutError:
        If *timeout* seconds pass without receiving any data.
    EOFError:
        If *raise_eof_error* is ``True`` and the EOF marker is detected.
    """
    if getattr(os, "mkfifo", None) is None:
        raise NotImplementedError("Named pipes are not supported on this platform")

    buffered = _get_buffered_line(pipe_path, eof_marker)
    if buffered is not None:
        if raise_eof_error and buffered == "":
            raise EOFError(f"EOF marker '{eof_marker}' reached")
        return buffered

    _ensure_fifo(pipe_path)

    cleanup = functools.partial(_safe_unlink, pipe_path)
    if cleanup_pipe:
        atexit.register(cleanup)

    pipe_fd: int | None = None
    terminal_helper: subprocess.Popen | None = None
    helper_read_fd: int | None = None

    def _maybe_return_single_line(
        decoded: str, eof_seen: bool = False
    ) -> str | None:
        """Return the first line and buffer the rest when applicable.

        When *eof_seen* is True and *decoded* contains no newline, the entire
        decoded content is treated as a single line terminated by the EOF
        marker and is returned as-is.
        """
        newline_pos = decoded.find("\n")
        if newline_pos != -1:
            first_line = decoded[:newline_pos]
            leftover = decoded[newline_pos + 1 :]
            if eof_seen:
                # Preserve the EOF marker as a terminator for subsequent
                # single-line reads.
                leftover = leftover + "\n" + eof_marker
            _buffer_leftover(pipe_path, leftover)
            return first_line
        # No newline in the payload.
        if eof_seen:
            # The whole decoded content is the only line; return it.
            return decoded
        return None

    def _process_chunks(chunks: list[bytes]) -> str | None:
        """Decode accumulated chunks and return if a complete result is ready."""
        try:
            decoded = b"".join(chunks).decode(encoding)
        except UnicodeDecodeError:
            return None

        cleaned, eof_seen = _strip_eof_suffix(decoded, eof_marker)
        if eof_seen:
            if single_line:
                result = _maybe_return_single_line(cleaned, eof_seen=True)
                if result is not None:
                    return result
                if raise_eof_error:
                    raise EOFError(f"EOF marker '{eof_marker}' reached")
                return cleaned
            if raise_eof_error:
                raise EOFError(f"EOF marker '{eof_marker}' reached")
            return cleaned

        if single_line:
            result = _maybe_return_single_line(decoded)
            if result is not None:
                return result

        return None

    try:
        # Open the FIFO non-blocking so select can poll it.
        pipe_fd = os.open(pipe_path, os.O_RDONLY | os.O_NONBLOCK)

        # If stdin is a real terminal, spawn a helper that owns terminal input.
        # The helper writes to a separate pipe, so the main loop can monitor
        # both the FIFO and the terminal without blocking on either.
        try:
            stdin_fd = sys.stdin.fileno()
            if os.isatty(stdin_fd):
                terminal_helper, helper_read_fd = _spawn_terminal_input_subprocess(
                    prompt=prompt,
                    timeout=timeout,
                    stdin_fd=stdin_fd,
                    history_file=history_file,
                    completion_file=completion_file,
                )
        except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
            pass

        if helper_read_fd is not None:
            _set_nonblocking(helper_read_fd)

        chunks: list[bytes] = []
        deadline = None if timeout is None else time.monotonic() + float(timeout)

        while True:
            remaining = None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _clear_leftover_buffer(pipe_path)
                    raise TimeoutError(
                        f"No data received from pipe within {timeout} seconds"
                    )
                remaining = max(remaining, 0.0)

            fds = [pipe_fd]
            if helper_read_fd is not None:
                fds.append(helper_read_fd)

            try:
                ready, _, _ = select.select(fds, [], [], remaining)
            except OSError as exc:  # pragma: no cover - fd closed unexpectedly
                _clear_leftover_buffer(pipe_path)
                raise TimeoutError(
                    f"No data received from pipe within {timeout} seconds"
                ) from exc

            # Pipe input has priority.  If data arrived, accumulate it and
            # return immediately when a complete result is ready.
            if pipe_fd in ready:
                data = _read_available(pipe_fd)
                if data:
                    chunks.append(data)
                    result = _process_chunks(chunks)
                    if result is not None:
                        print(result)
                        return result
                elif chunks:
                    # Writer closed after sending data; return what we have.
                    break
                else:
                    # No writer connected yet.  Avoid a tight busy-loop while
                    # waiting for either a writer or terminal input.
                    time.sleep(0.05)

            # Terminal input: the helper wrote a completed line.
            if helper_read_fd in ready:
                line_bytes = _read_available(helper_read_fd)
                if line_bytes:
                    line = line_bytes.decode(encoding).rstrip("\n")
                    return line
                # Helper closed its write end without producing a line.
                # This means the user pressed Ctrl+D / EOF on the terminal.
                try:
                    os.close(helper_read_fd)
                except OSError:
                    pass
                helper_read_fd = None
                if raise_eof_error:
                    raise EOFError("Terminal input closed (EOF or interrupt)")
                # Return empty string for normal EOF.
                return ""

        # Pipe EOF: return whatever we have.
        result = _process_chunks(chunks)
        if result is not None:
            print(result)
            return result
        decoded = b"".join(chunks).decode(encoding)
        cleaned, eof_seen = _strip_eof_suffix(decoded, eof_marker)
        if eof_seen and raise_eof_error:
            raise EOFError(f"EOF marker '{eof_marker}' reached")
        if single_line:
            result = _maybe_return_single_line(cleaned)
            if result is not None:
                print(result)
                return result
        if cleaned:
            print(cleaned)
        return cleaned
    finally:
        if terminal_helper is not None:
            try:
                terminal_helper.terminate()
                terminal_helper.wait(timeout=1)
            except Exception:  # pragma: no cover - cleanup best-effort
                pass
        if helper_read_fd is not None:
            try:
                os.close(helper_read_fd)
            except OSError:  # pragma: no cover - fd may already be closed
                pass
        if pipe_fd is not None:
            try:
                os.close(pipe_fd)
            except OSError:  # pragma: no cover - fd may already be closed
                pass
        if cleanup_pipe:
            atexit.unregister(cleanup)
            cleanup()
