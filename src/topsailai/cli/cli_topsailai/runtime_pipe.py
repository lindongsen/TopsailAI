"""Exact FIFO delivery with bounded nonblocking I/O and explicit ownership."""

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import io
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

# Local seams keep tests from mutating shared standard-library modules.
_lstat = os.lstat
_open = os.open
_fstat = os.fstat
_write = os.write
_close = os.close
_unlink = os.unlink
_fdopen = os.fdopen
_clock = time.monotonic
_sleep = time.sleep


@dataclass(frozen=True)
class PipeDeliveryResult:
    """Report bytes written, without claiming receiver consumption."""

    bytes_written: int


class PipeDeliveryError(Exception):
    """Describe an unsuccessful delivery, including possible partial input."""

    def __init__(self, error_code: str, message: str, *, bytes_written: int = 0):
        """Preserve the error category and amount already delivered."""
        super().__init__(message)
        self.error_code = error_code
        self.bytes_written = bytes_written
        self.delivery_unknown = bytes_written > 0

    @property
    def exit_code(self) -> int:
        """Map validation, endpoint and transmission errors to CLI exits."""
        if self.error_code == "usage_error":
            return 2
        if self.error_code in {
            "endpoint_missing", "endpoint_invalid", "permission_denied",
            "unsupported_transport",
        }:
            return 4
        return 5


def format_pipe_payload(message: str) -> bytes:
    """Preserve message text and append the existing newline/EOF framing."""
    if not isinstance(message, str) or not message.strip():
        raise PipeDeliveryError("usage_error", "Message must be nonempty text")
    if "EOF" in message.splitlines():
        raise PipeDeliveryError("usage_error", "Message contains a standalone 'EOF' line")
    try:
        return (message + ("" if message.endswith("\n") else "\n") + "EOF\n").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PipeDeliveryError("usage_error", "Message is not valid UTF-8 text") from exc


def _supported() -> bool:
    """Require POSIX FIFO and safe nonblocking open capabilities."""
    return os.name == "posix" and all(
        hasattr(os, name) for name in ("O_NONBLOCK", "O_NOFOLLOW", "O_CLOEXEC")
    )


def _remaining(deadline: float, written: int) -> float:
    """Reject late completion using the one absolute deadline."""
    remaining = deadline - _clock()
    if remaining <= 0:
        raise PipeDeliveryError("timeout", "Timed out delivering to pipe", bytes_written=written)
    return remaining


def _wait(deadline: float, written: int) -> None:
    """Yield on backpressure without resetting the deadline or busy looping."""
    _sleep(min(0.01, _remaining(deadline, written)))
    _remaining(deadline, written)


def _io_error(exc: OSError, written: int) -> PipeDeliveryError:
    """Keep operating-system failures distinct from usage errors."""
    code = "transport_error"
    if exc.errno in (errno.EACCES, errno.EPERM):
        code = "permission_denied"
    elif exc.errno == errno.ENOENT:
        code = "endpoint_missing"
    elif exc.errno in (errno.ELOOP, errno.ENOTDIR):
        code = "endpoint_invalid"
    return PipeDeliveryError(code, str(exc), bytes_written=written)


def _diagnose(message: str) -> None:
    """Keep ordinary diagnostic failures secondary to delivery evidence."""
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass


@contextmanager
def _payload_stream(payload: bytes, staged: bool):
    """Stage payloads and preserve primary failures through all cleanup."""
    if not staged:
        with io.BytesIO(payload) as stream:
            yield stream
        return
    directory = Path(__file__).absolute().parent.parent / ".tmp"
    directory.mkdir(exist_ok=True)
    fd, name = tempfile.mkstemp(dir=directory, prefix="runtime-send-", suffix=".tmp")
    stream = None
    primary = None
    try:
        try:
            stream = _fdopen(fd, "w+b")
        except BaseException:
            _close_owned(fd)
            raise
        stream.write(payload)
        stream.seek(0)
        yield stream
    except BaseException as exc:
        primary = exc
        raise
    finally:
        cleanup_error = None
        if stream is not None:
            try:
                stream.close()
            except OSError as exc:
                cleanup_error = exc
                _diagnose(f"[WARNING] Failed to close temporary send payload: {exc}")
        try:
            _unlink(name)
            _diagnose(f"[INFO] Removed temporary send payload: {name}")
        except OSError as exc:
            _diagnose(f"[WARNING] Failed to remove temporary send payload: {name}: {exc}")
        if primary is None and cleanup_error is not None:
            raise cleanup_error


def _observe_failure(deadline: float, written: int, exc: Exception) -> None:
    """Observe late failing I/O while retaining its cause and byte evidence."""
    try:
        _remaining(deadline, written)
    except PipeDeliveryError as timeout:
        raise timeout from exc


def _check_fifo(path: Path):
    """Inspect the exact endpoint without following its final symlink."""
    info = _lstat(path)
    if not stat.S_ISFIFO(info.st_mode):
        raise PipeDeliveryError("endpoint_invalid", f"Path is not a named pipe: {path}")
    return info


def _open_fifo(path: Path, deadline: float) -> int:
    """Open only this FIFO and compare pre-open and opened resource identity."""
    while True:
        _remaining(deadline, 0)
        try:
            before = _check_fifo(path)
        except (OSError, PipeDeliveryError) as exc:
            _observe_failure(deadline, 0, exc)
            raise
        _remaining(deadline, 0)
        try:
            fd = _open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as exc:
            _observe_failure(deadline, 0, exc)
            if exc.errno not in (errno.ENXIO, errno.EAGAIN, errno.EINTR):
                raise
            _wait(deadline, 0)
            continue
        # Ownership is protected before the first fallible observation.
        try:
            _remaining(deadline, 0)
            try:
                after = _fstat(fd)
            except OSError as exc:
                _observe_failure(deadline, 0, exc)
                raise
            _remaining(deadline, 0)
            if not stat.S_ISFIFO(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise PipeDeliveryError("endpoint_invalid", "FIFO changed during open")
        except BaseException:
            _close_owned(fd)
            raise
        return fd


def _close_owned(fd: int) -> None:
    """Close once; cleanup failure must not replace delivery/interruption evidence."""
    try:
        _close(fd)
    except OSError as exc:
        _diagnose(f"[WARNING] Failed to close pipe descriptor: {exc}")


def _write_payload(fd: int, stream, deadline: float) -> int:
    """Write chunks exactly once, tracking short writes and uncertain delivery."""
    written = 0
    while True:
        _remaining(deadline, written)
        try:
            chunk = stream.read(64 * 1024)
        except OSError as exc:
            _observe_failure(deadline, written, exc)
            raise _io_error(exc, written) from exc
        _remaining(deadline, written)
        if not chunk:
            return written
        offset = 0
        while offset < len(chunk):
            _remaining(deadline, written)
            try:
                count = _write(fd, chunk[offset:])
            except OSError as exc:
                _observe_failure(deadline, written, exc)
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    _wait(deadline, written)
                    continue
                raise _io_error(exc, written) from exc
            if count <= 0:
                _remaining(deadline, written)
                raise PipeDeliveryError("transport_error", "Pipe write returned zero bytes", bytes_written=written)
            offset += count
            written += count
            _remaining(deadline, written)


def send_to_pipe(pipe_path: Path, message: str, *, timeout: float = 5.0) -> PipeDeliveryResult:
    """Deliver to one exact FIFO under a single open/write deadline."""
    payload = format_pipe_payload(message)
    if not isinstance(pipe_path, Path) or not pipe_path.is_absolute() or "\x00" in str(pipe_path):
        raise PipeDeliveryError("usage_error", "Pipe path must be an absolute Path")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise PipeDeliveryError("usage_error", "Timeout must be positive and finite")
    if not _supported():
        raise PipeDeliveryError("unsupported_transport", "Safe FIFO transport is unavailable")
    deadline = _clock() + timeout
    written = 0
    try:
        with _payload_stream(payload, "\n" in message or len(payload) >= 64 * 1024) as stream:
            fd = _open_fifo(pipe_path, deadline)
            try:
                written = _write_payload(fd, stream, deadline)
            finally:
                _close_owned(fd)
        return PipeDeliveryResult(written)
    except OSError as exc:
        raise _io_error(exc, written) from exc
