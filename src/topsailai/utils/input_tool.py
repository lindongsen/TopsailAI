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
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - defensive cleanup
        logger.debug("Failed to unlink pipe %s: %s", path, exc)


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


def input_from_pipe(
    pipe_path: str,
    *,
    timeout: float | None = None,
    encoding: str = "utf-8",
    eof_marker: str = "EOF",
) -> str:
    """Read a multi-line message from a named pipe (FIFO).

    Creates the FIFO at *pipe_path*, waits for a writer, reads until the
    writer closes the pipe, and always removes the FIFO before returning.

    Parameters
    ----------
    pipe_path:
        Absolute path to the FIFO to create and read from.
    timeout:
        Maximum time in seconds to wait for a writer. ``None`` waits
        indefinitely.
    encoding:
        Encoding used to decode bytes read from the pipe.
    eof_marker:
        Optional marker that terminates input when seen on its own line.
        The marker line and anything after it is stripped from the result.

    Returns
    -------
    The decoded message read from the pipe, with trailing whitespace stripped.

    Raises
    ------
    NotImplementedError:
        If the platform does not support named pipes.
    TimeoutError:
        If *timeout* seconds pass without a writer connecting.
    """
    if getattr(os, "mkfifo", None) is None:
        raise NotImplementedError("Named pipes are not supported on this platform")

    _ensure_fifo(pipe_path)

    cleanup = functools.partial(_safe_unlink, pipe_path)
    atexit.register(cleanup)
    fd = None
    writer_seen = False
    try:
        # Open non-blocking so we can enforce *timeout* ourselves. On Linux
        # this returns immediately even when no writer is connected yet.
        fd = os.open(pipe_path, os.O_RDONLY | os.O_NONBLOCK)
        chunks: list[bytes] = []
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        while True:
            remaining = None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"No data received from pipe within {timeout} seconds"
                    )
                remaining = max(remaining, 0.0)

            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                raise TimeoutError(
                    f"No data received from pipe within {timeout} seconds"
                )

            try:
                data = os.read(fd, 4096)
            except OSError as exc:
                if exc.errno == errno.EAGAIN:
                    continue
                raise

            if data:
                writer_seen = True
                chunks.append(data)
                decoded = b"".join(chunks).decode(encoding)
                if _has_eof_marker(decoded, eof_marker):
                    break
                continue

            # read() returned 0 bytes. Once a writer has sent data this is EOF.
            if writer_seen or chunks:
                break

            # No writer connected yet. Avoid a busy loop by sleeping briefly,
            # but respect the timeout deadline.
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"No data received from pipe within {timeout} seconds"
                )
            time.sleep(0.01)

        return _strip_eof_marker(b"".join(chunks).decode(encoding), eof_marker)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        atexit.unregister(cleanup)
        _safe_unlink(pipe_path)
