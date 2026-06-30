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
import logging
import os
import select
import sys
import termios
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
    """Check whether *decoded* contains a standalone EOF marker line."""
    return f"\n{eof_marker}\n" in decoded or decoded.endswith(f"\n{eof_marker}")


# Buffer for leftover content read from a pipe when single_line=True.
# Keyed by pipe path so that multiple _input() calls in Strategy A can
# return one line at a time from a multi-line pipe message.
_pipe_leftover_buffer: dict[str, list[str]] = {}


def _get_buffered_line(pipe_path: str, eof_marker: str = "EOF") -> str | None:
    """Return and consume the next buffered line for *pipe_path*.

    The EOF marker line is consumed and returned as an empty string to
    signal end of input.

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

def input_from_pipe(
    pipe_path: str,
    *,
    timeout: float | None = None,
    encoding: str = "utf-8",
    eof_marker: str = "EOF",
    single_line: bool = False,
) -> str:
    """Read a message from a named pipe (FIFO) and/or standard input.

    Creates the FIFO at *pipe_path* and waits for input on either the FIFO
    or ``sys.stdin`` using ``select.select``. This lets users feed data
    through the pipe or type directly in the terminal. The FIFO is always
    removed before returning.

    Terminal input uses normal blocking line reads (``sys.stdin.readline()``)
    so that the terminal's line editing, readline history and arrow keys keep
    working. Pipe input uses non-blocking reads so that both sources can be
    multiplexed.

    When *single_line* is ``True`` and the pipe delivers more than one line,
    the first line is returned and the remaining lines are buffered under
    *pipe_path* for subsequent calls. This makes Strategy A multi-line input
    work when a sender writes several lines to the pipe at once.

    Parameters
    ----------
    pipe_path:
        Absolute path to the FIFO to create and read from.
    timeout:
        Maximum time in seconds to wait for input. ``None`` waits
        indefinitely.
    encoding:
        Encoding used to decode bytes read from the pipe/stdin.
    eof_marker:
        Optional marker that terminates input when seen on its own line.
        The marker line and anything after it is stripped from the result.
        In *single_line* mode the marker is only stripped when no newline
        is present in the input.
    single_line:
        When ``True``, return the first line of input (everything before
        the first ``\\n``). Any remaining content is buffered for the next
        call with the same *pipe_path*.

    Returns
    -------
    The decoded message read from the pipe or stdin.

    Raises
    ------
    NotImplementedError:
        If the platform does not support named pipes.
    TimeoutError:
        If *timeout* seconds pass without receiving any data.
    EOFError:
        If terminal stdin reaches EOF before any input is received.
    """
    if getattr(os, "mkfifo", None) is None:
        raise NotImplementedError("Named pipes are not supported on this platform")
    # Serve any leftover lines from a previous single-line read first.
    buffered = _get_buffered_line(pipe_path, eof_marker)
    if buffered is not None:
        return buffered

    _ensure_fifo(pipe_path)

    cleanup = functools.partial(_safe_unlink, pipe_path)
    atexit.register(cleanup)

    pipe_fd = None
    stdin_fd: int | None = None
    try:
        # Open the FIFO non-blocking so select can multiplex it with stdin.
        pipe_fd = os.open(pipe_path, os.O_RDONLY | os.O_NONBLOCK)

        # Attempt to use sys.stdin as a secondary input source. If it does not
        # expose a usable file descriptor we simply ignore it.
        try:
            stdin_fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
            stdin_fd = None

        chunks: list[bytes] = []
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        pipe_eof = False
        stdin_eof = False
        writer_seen = False
        def _maybe_return_single_line(decoded: str) -> str | None:
            """Return the first line and buffer the rest when applicable."""
            newline_pos = decoded.find("\n")
            if newline_pos != -1:
                first_line = decoded[:newline_pos]
                leftover = decoded[newline_pos + 1 :]
                _buffer_leftover(pipe_path, leftover)
                return first_line
            # Allow EOF marker to terminate a single line that has no trailing
            # newline.
            stripped = decoded.rstrip("\n")
            if stripped.endswith(eof_marker):
                return _strip_eof_marker(decoded, eof_marker)
            return None

        while True:
            readers: list[int] = []
            if not pipe_eof:
                readers.append(pipe_fd)
            if stdin_fd is not None and not stdin_eof:
                readers.append(stdin_fd)

            if not readers:
                break

            remaining = None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _clear_leftover_buffer(pipe_path)
                    raise TimeoutError(
                        f"No data received from pipe or terminal within {timeout} seconds"
                    )
                remaining = max(remaining, 0.0)

            try:
                ready, _, _ = select.select(readers, [], [], remaining)
            except OSError as exc:  # pragma: no cover - fd closed unexpectedly
                _clear_leftover_buffer(pipe_path)
                raise TimeoutError(
                    f"No data received from pipe or terminal within {timeout} seconds"
                ) from exc

            if not ready:
                _clear_leftover_buffer(pipe_path)
                raise TimeoutError(
                    f"No data received from pipe or terminal within {timeout} seconds"
                )

            for fd in ready:
                if fd == pipe_fd:
                    data = _read_available(pipe_fd)
                    if data:
                        writer_seen = True
                        chunks.append(data)
                        # Echo pipe data to the terminal so the user can see
                        # what was received even when it came from the FIFO.
                        try:
                            sys.stdout.buffer.write(data)
                            sys.stdout.buffer.flush()
                        except (AttributeError, OSError, ValueError):
                            # stdout may not expose a binary buffer or may be
                            # closed; visibility is best-effort here.
                            pass
                    else:
                        pipe_eof = True
                else:
                    # Terminal input: use readline() so that canonical mode,
                    # readline history and arrow keys remain functional.
                    try:
                        line = sys.stdin.readline()
                    except EOFError:
                        line = ""
                    if line:
                        writer_seen = True
                        chunks.append(line.encode(encoding))
                    else:
                        stdin_eof = True
                        # EOF on an idle terminal should raise EOFError
                        # so upper layers can detect Ctrl+D gracefully.
                        if not writer_seen:
                            raise EOFError("EOF on terminal stdin")

            try:
                decoded = b"".join(chunks).decode(encoding)
            except UnicodeDecodeError:
                # Partial multi-byte character; keep reading.
                continue

            if single_line:
                result = _maybe_return_single_line(decoded)
                if result is not None:
                    return result
            else:
                if _has_eof_marker(decoded, eof_marker):
                    return _strip_eof_marker(decoded, eof_marker)

            # Once we have seen at least one writer and both sources are EOF,
            # we are done.
            if writer_seen and pipe_eof and stdin_eof:
                break

            # If neither source has produced data yet and the pipe returned
            # EOF without a writer, avoid a tight busy-loop by sleeping briefly
            # while still respecting the overall timeout.
            if not writer_seen and pipe_eof:
                if deadline is not None and time.monotonic() >= deadline:
                    _clear_leftover_buffer(pipe_path)
                    raise TimeoutError(
                        f"No data received from pipe or terminal within {timeout} seconds"
                    )
                time.sleep(0.01)

        decoded = b"".join(chunks).decode(encoding)
        if single_line:
            result = _maybe_return_single_line(decoded)
            if result is not None:
                return result
            return _strip_eof_marker(decoded, eof_marker)
        return _strip_eof_marker(decoded, eof_marker)
    finally:
        if pipe_fd is not None:
            try:
                os.close(pipe_fd)
            except OSError:  # pragma: no cover - fd may already be closed
                pass
        atexit.unregister(cleanup)
        cleanup()
