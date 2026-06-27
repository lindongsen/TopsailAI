"""
Input utilities with timeout support.

This module provides helpers for reading user input in interactive
environments while respecting a timeout and preserving terminal echo.
"""

from __future__ import annotations

import contextlib
import io
import logging
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
