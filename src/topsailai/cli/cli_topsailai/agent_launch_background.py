"""Detached supervisor and bounded logging for background agent launches."""

from __future__ import annotations
import multiprocessing
import json
import os
import selectors
import signal
import stat as stat_module
import subprocess
import sys
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from dataclasses import dataclass

from cli_topsailai.paths import get_topsailai_home

_MAX_LOG_BYTES = 10 * 1024 * 1024
_MAX_BACKUPS = 2
_INIT_TIMEOUT = 5.0
_OBSERVATION_TIMEOUT = 1.0
# The supervisor observes the launcher for _OBSERVATION_TIMEOUT before it can
# publish a submission, so the parent must wait strictly longer than that window.
_SUBMISSION_TIMEOUT = _OBSERVATION_TIMEOUT + _INIT_TIMEOUT
_POLL_INTERVAL = 0.05

class _OsFacade:
    """Hold OS primitives as attributes so tests patch only this facade."""

    write = staticmethod(os.write)
    read = staticmethod(os.read)
    close = staticmethod(os.close)
    open = staticmethod(os.open)
    pipe = staticmethod(os.pipe)
    set_blocking = staticmethod(os.set_blocking)
    getpid = staticmethod(os.getpid)
    fchmod = staticmethod(os.fchmod)
    fdopen = staticmethod(os.fdopen)
    killpg = staticmethod(getattr(os, "killpg", None))
    isabs = staticmethod(os.path.isabs)
    join = staticmethod(os.path.join)
    getcwd = staticmethod(os.getcwd)
    name = os.name
    environ = os.environ
    O_WRONLY = os.O_WRONLY
    O_CREAT = os.O_CREAT
    O_EXCL = os.O_EXCL
    O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
    fstat = staticmethod(os.fstat)
    stat = staticmethod(os.stat)
    lstat = staticmethod(os.lstat)
    unlink = staticmethod(os.unlink)
    replace = staticmethod(os.replace)
    S_ISREG = staticmethod(stat_module.S_ISREG)


class _SelectorsFacade:
    """Hold selector primitives as attributes so tests patch only this facade."""

    DefaultSelector = selectors.DefaultSelector
    EVENT_READ = selectors.EVENT_READ

class _SubprocessFacade:
    """Hold subprocess primitives as attributes so tests patch only this facade."""

    Popen = staticmethod(subprocess.Popen)
    DEVNULL = subprocess.DEVNULL
    PIPE = subprocess.PIPE
    TimeoutExpired = subprocess.TimeoutExpired
    SubprocessError = subprocess.SubprocessError
    CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)


class _SysFacade:
    """Hold interpreter primitives as attributes so tests patch only this facade."""

    argv = sys.argv
    exc_info = staticmethod(sys.exc_info)


class _JsonFacade:
    """Hold JSON primitives as attributes so tests patch only this facade."""

    dumps = staticmethod(json.dumps)
    loads = staticmethod(json.loads)
    load = staticmethod(json.load)
    dump = staticmethod(json.dump)


# Consumer-local dependency facades keep test seams isolated from shared modules.
_os = _OsFacade()
_selectors = _SelectorsFacade()
_subprocess = _SubprocessFacade()
_sys = _SysFacade()
_json = _JsonFacade()
_MAX_FRAME_BYTES = 16 * 1024
_CHUNK_BYTES = 64 * 1024


def _send_frame(fd: int, payload: Mapping[str, Any]) -> None:
    """Write one bounded JSON frame to the private acknowledgement channel.

    The channel is either a raw descriptor (independent-process supervisor) or
    a connected control socket (terminal-container supervisor).
    """
    frame = _json.dumps(dict(payload), separators=(",", ":")).encode("utf-8") + b"\n"
    if len(frame) > _MAX_FRAME_BYTES:
        raise ValueError("acknowledgement frame is too large")
    sendall = getattr(fd, "sendall", None)
    if sendall is not None:
        sendall(frame)
        return
    view = memoryview(frame)
    while view:
        written = _os.write(fd, view)
        if written <= 0:
            raise OSError("acknowledgement pipe closed")
        view = view[written:]


def _close_channel(fd: Any) -> None:
    """Close one acknowledgement channel whether it is a socket or a descriptor."""
    close = getattr(fd, "close", None)
    if close is not None:
        try:
            close()
        except OSError:
            pass
        return
    try:
        _os.close(fd)
    except OSError:
        pass


def _read_frames(fd: Any, buffer: bytearray) -> list[dict[str, Any]]:
    """Read available acknowledgement frames without blocking.

    EOF with a non-empty buffer is a truncated frame and is never success.
    The channel is either a raw descriptor or a connected control socket.
    """
    frames: list[dict[str, Any]] = []
    try:
        recv = getattr(fd, "recv", None)
        if recv is not None:
            data = recv(_MAX_FRAME_BYTES + 1)
        else:
            data = _os.read(fd, _MAX_FRAME_BYTES + 1)
    except BlockingIOError:
        return frames
    if not data:
        if buffer:
            raise EOFError("truncated acknowledgement frame")
        return frames
    buffer.extend(data)
    if len(buffer) > _MAX_FRAME_BYTES:
        raise ValueError("acknowledgement frame is too large")
    while b"\n" in buffer:
        raw, _, remaining = buffer.partition(b"\n")
        del buffer[: len(raw) + 1]
        if not raw:
            raise ValueError("empty acknowledgement frame")
        value = _json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("acknowledgement must be an object")
        frames.append(value)
    return frames


class BackgroundUnconfirmed(RuntimeError):
    """Raised when supervisor custody or acknowledgement cannot be proven."""


@dataclass(frozen=True)
class LauncherOwnership:
    """Immutable parent-owned identity for the validated launcher."""

    launcher_pid: int
    identity: str
    session: str


class _RotatingLog:
    """Own a private active log and rotate only after closing its descriptor."""

    def __init__(self, path: Path, *, max_bytes: int = _MAX_LOG_BYTES, backups: int = _MAX_BACKUPS):
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups
        self._fd: Optional[int] = None
        self._size = 0

    def open(self) -> None:
        """Exclusively create the active log with private permissions.

        ``O_EXCL`` refuses an existing path and ``O_NOFOLLOW`` refuses a
        symlink, so a pre-existing file or link can never be truncated or
        followed. The opened descriptor is then verified to be a regular file
        so a substituted special file cannot receive log bytes.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = _os.O_WRONLY | _os.O_CREAT | _os.O_EXCL | _os.O_NOFOLLOW
        fd = _os.open(str(self.path), flags, 0o600)
        try:
            if not _os.S_ISREG(_os.fstat(fd).st_mode):
                raise OSError("launch log is not a regular file")
        except OSError:
            _os.close(fd)
            raise
        self._fd = fd
        self._size = 0

    def _close(self) -> None:
        """Close the active descriptor before any rename or stat operation."""
        if self._fd is not None:
            _os.close(self._fd)
            self._fd = None

    def _rotate(self) -> None:
        """Rotate closed files while retaining exactly the configured backups."""
        self._close()
        for index in range(self.backups, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index - 1}") if index > 1 else self.path
            target = self.path.with_name(f"{self.path.name}.{index}")
            if target.exists():
                target.unlink()
            if source.exists():
                source.replace(target)
        self.open()

    def write(self, data: bytes) -> None:
        """Write bounded chunks, rotating before crossing the active limit."""
        if self._fd is None:
            raise OSError("log is not open")
        offset = 0
        while offset < len(data):
            if self._size >= self.max_bytes:
                self._rotate()
            available = self.max_bytes - self._size
            chunk = data[offset: offset + max(1, available)]
            view = memoryview(chunk)
            while view:
                written = _os.write(self._fd, view)
                if written <= 0:
                    raise OSError("log write made no progress")
                self._size += written
                view = view[written:]
            offset += len(chunk)

    def close(self) -> None:
        """Close the active log descriptor."""
        self._close()


def _drain(selector, streams: dict[int, Any], log: _RotatingLog) -> bool:
    """Drain only selector-ready bytes and distinguish EOF from would-block."""
    progressed = False
    for key, _ in selector.select(timeout=0):
        stream = key.fileobj
        try:
            chunk = _os.read(key.fd, _CHUNK_BYTES)
        except BlockingIOError:
            continue
        if not chunk:
            selector.unregister(stream)
            streams.pop(key.fd, None)
            try:
                stream.close()
            except OSError:
                # A failing close must not abort supervision of a live launcher.
                pass
            continue
        log.write(chunk)
        progressed = True
    return progressed


def _close_streams(selector, streams: dict[int, Any]) -> None:
    """Close every owned output stream and selector."""
    for stream in list(streams.values()):
        try:
            stream.close()
        except OSError:
            pass
    selector.close()


def _cleanup_owned(child: Any, *, wait_timeout: float = 0.25, identity: Optional[tuple[int, Any, str]] = None, identity_probe: Optional[Callable[[int], Any]] = None) -> bool:
    """Terminate, escalate and reap exactly one owned child with bounded waits.

    An already-exited child needs no identity proof: absence is the cleanup
    outcome. Identity matching only authorizes signalling a live child.
    """
    if child is None:
        return True
    identity = identity or _child_identity(child, identity_probe)
    try:
        if child.poll() is not None:
            # A child that already reports a terminal status is cleaned: absence
            # is the cleanup outcome and no identity evidence remains to read.
            child.wait(timeout=wait_timeout)
            return True
        if not _identity_matches(child, identity, identity_probe):
            return False
        _signal_owned(child, identity, identity_probe)
        try:
            child.wait(timeout=wait_timeout)
            return _child_absent(child, identity, identity_probe)
        except _subprocess.TimeoutExpired:
            if not _identity_matches(child, identity, identity_probe):
                return False
            child.kill()
            try:
                child.wait(timeout=wait_timeout)
                return _child_absent(child, identity, identity_probe)
            except _subprocess.TimeoutExpired:
                return False
    except (OSError, _subprocess.SubprocessError):
        return False




def _authoritative_child_identity(pid: int) -> Optional[tuple[int, int]]:
    """Read an OS-owned process start token, or return None when unverifiable."""
    if _os.name != "posix":
        return None
    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
        # The parenthesised comm field may contain spaces, so index after the
        # last ')' instead of splitting the whole line.
        rest = raw[raw.rindex(")") + 2:].split()
        return (int(pid), int(rest[19]))
    except (OSError, IndexError, ValueError):
        return None


def _require_injected_spawn(spawn: Optional[Callable[..., Any]]) -> Callable[..., Any]:
    """Reject test calls that omit the required process seam."""
    if spawn is None:
        raise AssertionError("background process creation requires an injected spawn seam")
    return spawn


def _cancel_supervisor_transport(supervisor: Any, cancel_fd: int, *,
                                  write: Optional[Callable[[int, bytes], int]] = None,
                                  cleanup: Optional[Callable[[Any], dict[str, Any]]] = None) -> dict[str, Any]:
    """Request cancellation through an owned control descriptor and reap the supervisor."""
    write = write or _os.write
    cleanup = cleanup or cancel_background
    try:
        written = write(cancel_fd, b"1")
        if written != 1:
            raise OSError("cancellation transport made no progress")
    except OSError as error:
        raise BackgroundUnconfirmed("supervisor cancellation transport failed") from error
    return cleanup(supervisor)


def _resolve_identity_probe(identity_probe: Optional[Callable[[int], Any]]) -> Callable[[int], Any]:
    """Resolve the identity probe at call time so tests can inject a local probe."""
    return identity_probe if identity_probe is not None else _authoritative_child_identity


def _child_identity(child: Any, identity_probe: Optional[Callable[[int], Any]] = None) -> tuple[int, Any, str]:
    """Return process identity evidence and its verification source."""
    pid = int(child.pid)
    token = _resolve_identity_probe(identity_probe)(pid)
    if token is None:
        return (pid, None, "unverifiable")
    if isinstance(token, tuple) and len(token) == 2:
        token = token[1]
    return (pid, token, "authoritative")


def _identity_matches(child: Any, identity: tuple[int, Any, str], identity_probe: Optional[Callable[[int], Any]] = None) -> bool:
    """Check that a child still has the verified identity recorded at ownership time."""
    if len(identity) == 2:
        expected_pid, expected_token = identity
        expected_source = "authoritative"
    else:
        expected_pid, expected_token, expected_source = identity
    if expected_source != "authoritative" or expected_token is None:
        return False
    current = _child_identity(child, identity_probe)
    return current[0] == expected_pid and current[1] == expected_token and current[2] == "authoritative"


def _child_absent(child: Any, identity: tuple[int, Any, str], identity_probe: Optional[Callable[[int], Any]] = None) -> bool:
    """Prove absence without treating a reused PID as the owned child.

    A child that already reports a terminal status is absent regardless of
    identity evidence, because a reaped process has no identity left to read.
    Identity matching guards only the decision to signal a live child.
    """
    try:
        if child.poll() is not None:
            return True
    except (OSError, AttributeError):
        return False
    return False


def _signal_owned(child: Any, identity: Optional[tuple[int, Any, str]] = None,
                  identity_probe: Optional[Callable[[int], Any]] = None) -> None:
    """Terminate exactly the launcher whose verified identity was captured."""
    identity = identity or _child_identity(child, identity_probe)
    if not _identity_matches(child, identity, identity_probe) or child.poll() is not None:
        return
    if _os.name == "nt":
        child.terminate()
    else:
        _os.killpg(child.pid, signal.SIGTERM)


def _validate_launcher_cleanup_ack(
    frame: Mapping[str, Any], ownership: Optional[LauncherOwnership]
) -> bool:
    """Accept cleanup proof only for the exact immutable launcher owner.

    An unestablished owner cannot validate anything, so a missing ownership
    record is a rejection rather than an attribute error: cleanup proof must
    never be inferred from a frame whose owner was never observed.
    """
    if ownership is None:
        return False
    required = ("kind", "session", "launcher_pid", "launcher_identity", "cleanup_confirmed")
    if any(key not in frame for key in required):
        return False
    return (
        frame.get("kind") == "cleanup"
        and frame.get("cleanup_confirmed") is True
        and frame.get("session") == ownership.session
        and frame.get("launcher_pid") == ownership.launcher_pid
        and frame.get("launcher_identity") == ownership.identity
    )


def _ownership_from_started(frame: Mapping[str, Any], session_id: str) -> LauncherOwnership:
    """Materialize one immutable ownership record from a validated started frame."""
    pid = frame.get("launcher_pid")
    identity = frame.get("launcher_identity")
    session = frame.get("session", session_id)
    if not isinstance(pid, int) or pid <= 0 or not isinstance(identity, str) or not identity:
        raise BackgroundUnconfirmed("invalid launcher identity")
    if session != session_id:
        raise BackgroundUnconfirmed("started acknowledgement session mismatch")
    return LauncherOwnership(pid, identity, session)


def _reconcile_launcher(
    read_fd: int, buffer: bytearray, pending_frames: deque[dict[str, Any]],
    ownership: LauncherOwnership, supervisor: Any,
    *, clock: Callable[[], float], sleeper: Callable[[float], None],
    existing_ack: Optional[Mapping[str, Any]] = None,
) -> Optional[Mapping[str, Any]]:
    """Read correlated launcher cleanup proof before closing the control channel."""
    if existing_ack is not None:
        return existing_ack if _validate_launcher_cleanup_ack(existing_ack, ownership) else None
    deadline = clock() + _INIT_TIMEOUT
    while clock() < deadline:
        frames = list(pending_frames)
        pending_frames.clear()
        frames.extend(_read_frames(read_fd, buffer))
        for frame in frames:
            if frame.get("kind") == "cleanup":
                if _validate_launcher_cleanup_ack(frame, ownership):
                    return frame
                return None
        if supervisor.poll() is not None:
            return None
        sleeper(_POLL_INTERVAL)
    return None


def _failure_class(error: BaseException, child: Any, cleanup_confirmed: bool) -> str:
    """Classify a supervisor failure without hiding custody uncertainty."""
    if not cleanup_confirmed:
        return "unresolved_custody"
    if isinstance(error, KeyboardInterrupt):
        return "cancellation"
    if isinstance(error, (TimeoutError, _subprocess.TimeoutExpired)):
        return "cleanup_timeout"
    if child is not None:
        return "relay_failure"
    return "startup_failure"


def _default_popen(*args: Any, **kwargs: Any) -> Any:
    """Resolve process creation through this module's injectable boundary."""
    return _subprocess.Popen(*args, **kwargs)


def _acknowledge_early_exit(ack_fd: int, child: Any, child_identity: Any,
                            session_id: Any, status: int) -> None:
    """Reap the launcher and publish correlated cleanup proof before early exit.

    The parent reconciles launcher custody from a cleanup frame that matches the
    immutable ownership record, so an early exit must never be reported without
    that proof. An unreapable launcher is reported as unconfirmed custody.
    """
    reaped = False
    try:
        child.wait(timeout=_OBSERVATION_TIMEOUT)
        reaped = True
    except (OSError, _subprocess.TimeoutExpired):
        reaped = False
    _send_frame(ack_fd, {
        "kind": "cleanup",
        "class": "early_exit",
        "session": session_id,
        "launcher_pid": getattr(child, "pid", None),
        "launcher_identity": repr(child_identity),
        "cleanup_confirmed": reaped,
    })
    _send_frame(ack_fd, {"kind": "early_exit", "code": status, "launcher_pid": getattr(child, "pid", None)})


def _supervise(request: Mapping[str, Any], ack_fd: int, *, popen: Optional[Callable[..., Any]] = None,
               clock: Callable[[], float] = time.monotonic,
               sleeper: Callable[[float], None] = time.sleep,
               cancel_requested: Optional[Callable[[], bool]] = None,
               cancel_fd: Optional[int] = None,
               identity_probe: Optional[Callable[[int], Any]] = None) -> None:
    """Spawn, observe, relay, acknowledge and reap one launcher."""
    child = None
    if popen is None:
        popen = _default_popen
    selector = _selectors.DefaultSelector()
    streams: dict[int, Any] = {}
    log_path = Path(str(request["log_path"]))
    log = _RotatingLog(log_path)
    lease = active_launch_lease(log_path)
    try:
        # A cancellation or a lost parent control channel that arrives before
        # the launcher exists must abort the launch instead of creating a
        # process nobody owns.
        if _cancel_requested(cancel_fd, cancel_requested) or _control_lost(cancel_fd):
            raise KeyboardInterrupt()
        _write_lease(lease, pid=_os.getpid(), identity=_authoritative_child_identity(_os.getpid()))
        log.open()
        command = ([str(request["driver"])] if request.get("driver") else
                   ["topsailai_launch_agent", "--subprocess", "--session-id", str(request["session_id"])])
        child_environment = dict(request.get("environment") or _os.environ)
        child = popen(command, cwd=str(request["folder"]), env=child_environment,
                       stdin=_subprocess.DEVNULL, stdout=_subprocess.PIPE, stderr=_subprocess.PIPE,
                       close_fds=True, start_new_session=(_os.name != "nt"))
        if child.stdout is None or child.stderr is None:
            raise OSError("launcher output pipes were not created")
        for stream in (child.stdout, child.stderr):
            _os.set_blocking(stream.fileno(), False)
            selector.register(stream, _selectors.EVENT_READ)
            streams[stream.fileno()] = stream
        child_identity = _child_identity(child, identity_probe)
        _send_frame(ack_fd, {"kind": "started", "state": "initialized", "session": request["session_id"],
                             "launcher_pid": child.pid, "launcher_identity": repr(child_identity),
                             "log_path": request["log_path"]})
        deadline = clock() + _OBSERVATION_TIMEOUT
        while clock() < deadline:
            if _cancel_requested(cancel_fd, cancel_requested):
                raise KeyboardInterrupt()
            _drain(selector, streams, log)
            status = child.poll()
            if status is not None:
                drain_deadline = clock() + _OBSERVATION_TIMEOUT
                while streams and clock() < drain_deadline:
                    _drain(selector, streams, log)
                    if streams:
                        sleeper(_POLL_INTERVAL)
                if streams:
                    for stream in list(streams.values()):
                        stream.close()
                    streams.clear()
                log.write(f"launcher exit status={status}\n".encode())
                _acknowledge_early_exit(ack_fd, child, child_identity, request["session_id"], status)
                return
            sleeper(_POLL_INTERVAL)
        _drain(selector, streams, log)
        status = child.poll()
        if status is not None:
            _acknowledge_early_exit(ack_fd, child, child_identity, request["session_id"], status)
            return
        _send_frame(ack_fd, {"kind": "submitted", "state": "observed", "session": request["session_id"],
                             "launcher_pid": child.pid, "log_path": request["log_path"]})
        drain_deadline = None
        while child.poll() is None or streams:
            # After submission the parent closes its control channel while the
            # launcher must keep running, so end-of-stream is not a cancellation.
            if _cancel_requested(cancel_fd, cancel_requested, submitted=True):
                raise KeyboardInterrupt()
            _drain(selector, streams, log)
            if child.poll() is not None:
                if drain_deadline is None:
                    drain_deadline = clock() + _OBSERVATION_TIMEOUT
                if not streams or clock() >= drain_deadline:
                    break
            else:
                sleeper(_POLL_INTERVAL)
        for stream in list(streams.values()):
            try:
                stream.close()
            except OSError:
                pass
        streams.clear()
        status = child.wait(timeout=_OBSERVATION_TIMEOUT)
        log.write(f"launcher exit status={status}\n".encode())
    except BaseException as error:
        cleanup_confirmed = _cleanup_owned(child, identity=locals().get("child_identity"), identity_probe=identity_probe)
        failure_class = _failure_class(error, child, cleanup_confirmed)
        cleanup_payload = {
            "kind": "cleanup",
            "class": failure_class,
            "session": request.get("session_id"),
            "launcher_pid": getattr(child, "pid", None),
            "cleanup_confirmed": cleanup_confirmed,
            "launcher_identity": repr(locals().get("child_identity")),
        }
        try:
            _send_frame(ack_fd, cleanup_payload)
        except (OSError, ValueError):
            pass
        payload = {"kind": "failure", "class": failure_class,
                   "error": str(error)[:512],
                   "launcher_pid": getattr(child, "pid", None),
                   "cleanup_confirmed": cleanup_confirmed,
                   "launcher_identity": repr(locals().get("child_identity"))}
        try:
            _send_frame(ack_fd, payload)
        except (OSError, ValueError):
            pass
    finally:
        _close_streams(selector, streams)
        log.close()
        _remove_lease(log_path)
        _close_channel(ack_fd)


def _cancel_requested(cancel_fd: Any, callback: Optional[Callable[[], bool]],
                      *, submitted: bool = False) -> bool:
    """Consume a parent cancellation signal without blocking the supervisor.

    The cancellation channel is either a raw descriptor or a connected control
    socket. A closed channel means cancellation only *before* submission: after
    a successful submission the parent closes its side of the control channel
    while the launcher must keep running, so EOF there is not a cancellation.
    """
    if callback is not None and callback():
        return True
    if cancel_fd is None:
        return False
    try:
        recv = getattr(cancel_fd, "recv", None)
        if recv is not None:
            data = recv(1)
        else:
            data = _os.read(cancel_fd, 1)
    except BlockingIOError:
        return False
    except OSError:
        return True
    if not data:
        return not submitted
    return True


def _control_lost(cancel_fd: Any) -> bool:
    """Return whether the parent control channel is gone before submission.

    Only an authoritative end-of-stream (or a hard channel error) counts, so a
    parent that is merely idle is never mistaken for a cancelled launch.
    """
    if cancel_fd is None:
        return False
    try:
        recv = getattr(cancel_fd, "recv", None)
        if recv is not None:
            data = recv(1)
        else:
            data = _os.read(cancel_fd, 1)
    except BlockingIOError:
        return False
    except OSError:
        return True
    return data == b""


def _remove_lease(path: Path) -> None:
    """Release the active-launch lease after supervisor cleanup is complete."""
    try:
        active_launch_lease(path).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _supervisor_entry(request_path: str, ack_target: Any) -> None:
    """Load, consume and execute one private supervisor request.

    *ack_target* is either an inherited acknowledgement descriptor (raw
    independent-process supervisor) or the parent's private control socket path
    (terminal-container supervisor). A terminal supervisor must authenticate
    itself before any acknowledgement is trusted.
    """
    request_file = Path(request_path)
    cancel_fd = None
    channel = ack_target
    if isinstance(ack_target, str) and ack_target.isdigit():
        channel = int(ack_target)
    try:
        with request_file.open(encoding="utf-8") as handle:
            request = _json.load(handle)
    finally:
        try:
            request_file.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    if not isinstance(request, dict) or request.get("kind") != "workspace-agent-supervisor":
        raise ValueError("invalid supervisor request")
    _validate_resume_driver(request.get("driver"))
    if isinstance(channel, str):
        from cli_topsailai.agent_launch_terminal import (
            connect_control, write_recovery_record)

        record_path = request.get("record_path")
        if isinstance(record_path, str) and record_path:
            # Publish identity BEFORE connecting so a handshake failure still
            # leaves verifiable recovery custody for the parent.
            write_recovery_record(Path(record_path))
        channel = connect_control(channel, request)
        cancel_fd = channel
    else:
        cancel_fd = request.get("cancel_fd")
        if cancel_fd is not None:
            _os.set_blocking(cancel_fd, False)
    try:
        _supervise(request, channel, cancel_fd=cancel_fd)
    finally:
        if cancel_fd is not None:
            _close_channel(cancel_fd)


def _entrypoint_command(base_dir: Optional[str] = None) -> list[str]:
    """Return the deployed CLI entry point used for the detached supervisor.

    The supervisor is spawned after the launcher changes into the project
    folder, so a relative entry point must be anchored to the invocation
    directory or the detached process cannot resolve it.
    """
    configured = _os.environ.get("TOPSAILAI_CLI_ENTRY")
    if configured:
        return [configured]
    entry = _sys.argv[0] or "topsailai"
    if not _os.isabs(entry):
        entry = _os.join(base_dir or _os.getcwd(), entry)
    return [entry]


def _request_file(folder: Path, request: Mapping[str, Any]) -> tuple[Path, int]:
    """Create a private request file without serializing credentials."""
    temporary = folder / ".tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="workspace-agent-", suffix=".json", dir=temporary)
    _os.fchmod(fd, 0o600)
    with _os.fdopen(fd, "w", encoding="utf-8") as handle:
        _json.dump(dict(request), handle, separators=(",", ":"))
    return Path(name), 0


def _cleanup_request(path: Optional[Path]) -> None:
    """Remove a private request after the supervisor has loaded it."""
    if path is not None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _validate_resume_driver(driver: Any) -> None:
    """Allow only bounded built-in resume executable names, never shell input."""
    if driver is not None and driver not in (
        "topsailai_agent_chats", "topsailai_agent_plan_tasks", "ai-team-flow-dev",
    ):
        raise ValueError("invalid background resume driver")


def launch_log_identity(session_id: str, attempt: Optional[str] = None) -> str:
    """Return the log identity for one launch attempt.

    A fresh launch uses the session identity directly. A resume keeps the
    persisted session in arguments and output but writes to a distinct
    per-attempt log so an earlier attempt's diagnostics are never truncated.
    """
    if not attempt:
        return session_id
    return f"{session_id}.{attempt}"


def launch_background(folder: str, session_id: str, *, environment: Optional[Mapping[str, str]] = None,
                      spawn: Optional[Callable[..., Any]] = None,
                      entrypoint_base: Optional[str] = None,
                      clock: Callable[[], float] = time.monotonic,
                      sleeper: Callable[[float], None] = time.sleep,
                      identity_probe: Optional[Callable[[int], Any]] = None,
                      cancel_requested: Optional[Callable[[], bool]] = None,
                      cancel_write: Optional[Callable[[int, bytes], int]] = None,
                      log_identity: Optional[str] = None,
                      driver: Optional[str] = None) -> dict[str, Any]:
    """Submit a detached supervisor and return its acknowledged launch record.

    *log_identity* selects the per-attempt log name while *session_id* remains
    the persisted identity reported to the caller. *driver* selects the resume
    driver argv executed by the supervisor.
    """
    _validate_resume_driver(driver)
    task_dir = Path(get_topsailai_home()) / "workspace" / "task"
    task_dir.mkdir(parents=True, exist_ok=True)
    log_path = task_dir / f"{log_identity or session_id}.agent-launch.log"
    request_path: Optional[Path] = None
    read_fd = write_fd = cancel_read_fd = cancel_write_fd = None
    supervisor = None
    submitted = False
    custody_proven = False
    cleanup_ack: Optional[Mapping[str, Any]] = None
    started: Optional[Mapping[str, Any]] = None
    ownership: Optional[LauncherOwnership] = None
    buffer = bytearray()
    pending_frames: deque[dict[str, Any]] = deque()
    factory = spawn or _default_popen
    try:
        request = {"kind": "workspace-agent-supervisor", "folder": folder,
                   "session_id": session_id, "log_path": str(log_path)}
        if driver:
            request["driver"] = driver
        request_path, _ = _request_file(Path(folder), request)
        read_fd, write_fd = _os.pipe()
        cancel_read_fd, cancel_write_fd = _os.pipe()
        request["cancel_fd"] = cancel_read_fd
        _cleanup_request(request_path)
        request_path, _ = _request_file(Path(folder), request)
        command = _entrypoint_command(entrypoint_base) + ["--internal-workspace-agent-supervisor", str(request_path), str(write_fd)]
        kwargs = {"stdin": _subprocess.DEVNULL, "stdout": _subprocess.DEVNULL,
                  "stderr": _subprocess.DEVNULL, "close_fds": True,
                  "start_new_session": (_os.name != "nt"), "pass_fds": (write_fd, cancel_read_fd)}
        if _os.name == "nt":
            kwargs.pop("start_new_session", None)
            kwargs.pop("pass_fds", None)
            kwargs["creationflags"] = (
                _subprocess.CREATE_NEW_PROCESS_GROUP
                | _subprocess.DETACHED_PROCESS
            )
        if environment is not None:
            kwargs["env"] = dict(environment)
        supervisor = factory(command, **kwargs)
        # The supervisor now owns these descriptors; a failing close must not
        # discard custody of a process that was already created.
        try:
            _os.close(write_fd)
        except OSError:
            pass
        write_fd = None
        try:
            _os.close(cancel_read_fd)
        except OSError:
            pass
        cancel_read_fd = None
        _os.set_blocking(read_fd, False)
        init_deadline = clock() + _INIT_TIMEOUT

        def frames_available() -> list[dict[str, Any]]:
            """Return retained frames plus every frame from one transport read.

            A retained frame must never starve the pipe: cancellation proof can
            arrive while a coalesced submission is still pending.
            """
            frames = list(pending_frames)
            pending_frames.clear()
            frames.extend(_read_frames(read_fd, buffer))
            return frames

        def consume_cancellation() -> dict[str, Any]:
            """Consume and validate the supervisor cleanup acknowledgement."""
            nonlocal ownership, started
            deadline = clock() + _INIT_TIMEOUT
            while clock() < deadline:
                for frame in frames_available():
                    kind = frame.get("kind")
                    if kind == "started":
                        # Cancellation may arrive before the initialization loop
                        # consumed the started frame, so record ownership here.
                        candidate = _ownership_from_started(frame, session_id)
                        if ownership is not None and candidate != ownership:
                            raise BackgroundUnconfirmed("conflicting started acknowledgement")
                        if ownership is None:
                            ownership = candidate
                            started = frame
                        continue
                    if kind != "cleanup":
                        pending_frames.append(frame)
                        continue
                    if ownership is None or not _validate_launcher_cleanup_ack(frame, ownership):
                        raise BackgroundUnconfirmed("unrelated or incomplete launcher cleanup acknowledgement")
                    return {"outcome": "cancelled", "exit_code": 130,
                            "cleanup_confirmed": True, "launcher_cleanup_confirmed": True,
                            "cleanup": frame}
                if supervisor.poll() is not None:
                    raise BackgroundUnconfirmed("supervisor exited before cancellation cleanup acknowledgement")
                sleeper(_POLL_INTERVAL)
            raise BackgroundUnconfirmed("cancellation cleanup acknowledgement timed out")

        def request_cancellation() -> dict[str, Any]:
            """Send cancellation once, consume cleanup proof and reap the supervisor."""
            if cancel_write_fd is None:
                raise BackgroundUnconfirmed("cancellation transport unavailable")
            result = _cancel_supervisor_transport(
                supervisor, cancel_write_fd,
                write=cancel_write,
                cleanup=lambda _supervisor: consume_cancellation(),
            )
            # Exit 130 requires both launcher cleanup proof and a reaped supervisor.
            if not _cleanup_owned(supervisor, wait_timeout=0.25, identity_probe=identity_probe):
                raise BackgroundUnconfirmed("supervisor reap failed after cancellation")
            nonlocal submitted
            submitted = True
            return result

        try:
            while clock() < init_deadline:
                if cancel_requested is not None and cancel_requested():
                    return request_cancellation()
                batch = frames_available()
                # Record ownership and cleanup proof from the whole batch before
                # classifying terminal frames, so a coalesced acknowledgement is
                # never hidden behind a terminal frame from the same read.
                for frame in batch:
                    if frame.get("kind") == "started":
                        candidate = _ownership_from_started(frame, session_id)
                        if ownership is not None and candidate != ownership:
                            raise BackgroundUnconfirmed("conflicting started acknowledgement")
                        if ownership is None:
                            ownership = candidate
                            started = frame
                    elif frame.get("kind") == "cleanup":
                        cleanup_ack = frame
                for frame in batch:
                    kind = frame.get("kind")
                    if kind in ("started", "cleanup"):
                        continue
                    if kind == "failure":
                        if not frame.get("cleanup_confirmed", False):
                            raise BackgroundUnconfirmed(frame.get("class", "supervisor cleanup unresolved"))
                        raise RuntimeError(frame.get("error", "supervisor failed"))
                    # Preserve every other frame from this batch so a coalesced
                    # submission or early exit is never silently discarded.
                    pending_frames.append(frame)
                if started is not None:
                    break
                if supervisor.poll() is not None:
                    raise BackgroundUnconfirmed("supervisor exited during initialization")
                sleeper(_POLL_INTERVAL)
            if started is None:
                raise BackgroundUnconfirmed("supervisor initialization acknowledgement timed out")
            observe_deadline = clock() + _SUBMISSION_TIMEOUT
            while clock() < observe_deadline:
                if cancel_requested is not None and cancel_requested():
                    return request_cancellation()
                batch = frames_available()
                # Apply the same two-pass rule during observation so a coalesced
                # cleanup acknowledgement survives a terminal frame.
                for frame in batch:
                    if frame.get("kind") == "started":
                        candidate = _ownership_from_started(frame, session_id)
                        if candidate != ownership:
                            raise BackgroundUnconfirmed("conflicting started acknowledgement")
                    elif frame.get("kind") == "cleanup":
                        cleanup_ack = frame
                for frame in batch:
                    kind = frame.get("kind")
                    if kind in ("started", "cleanup"):
                        continue
                    if (kind == "submitted"
                            and frame.get("session") == session_id
                            and frame.get("launcher_pid") == started.get("launcher_pid")
                            and frame.get("log_path") == str(log_path)):
                        submitted = True
                        return {
                            "session_id": session_id,
                            "launcher_pid": started["launcher_pid"],
                            "log_path": str(log_path),
                            "outcome": "submitted",
                        }
                    if kind == "early_exit":
                        raise RuntimeError(
                            f"background launcher exited before submission: {frame.get('code')}"
                        )
                    if kind == "failure":
                        if not frame.get("cleanup_confirmed", False):
                            raise BackgroundUnconfirmed(frame.get("class", "supervisor cleanup unresolved"))
                        raise RuntimeError(frame.get("error", "supervisor failed"))
                if supervisor.poll() is not None:
                    raise BackgroundUnconfirmed("launcher custody unresolved before submission")
                sleeper(_POLL_INTERVAL)
            raise BackgroundUnconfirmed("background submission acknowledgement timed out")
        except KeyboardInterrupt:
            return request_cancellation()
    finally:
        # Custody reconciliation must finish before any control descriptor is closed,
        # but every descriptor must still be released before a custody failure is raised.
        custody_error: Optional[BackgroundUnconfirmed] = None
        if supervisor is not None and not submitted:
            if started is None:
                custody_proven = _cleanup_owned(
                    supervisor, wait_timeout=0.25, identity_probe=identity_probe)
            else:
                launcher_ack = _reconcile_launcher(
                    read_fd, buffer, pending_frames, ownership, supervisor,
                    clock=clock, sleeper=sleeper, existing_ack=cleanup_ack,
                )
                supervisor_cleaned = _cleanup_owned(
                    supervisor, wait_timeout=0.25, identity_probe=identity_probe)
                custody_proven = launcher_ack is not None and supervisor_cleaned
            if not custody_proven and _sys.exc_info()[0] is not BackgroundUnconfirmed:
                custody_error = BackgroundUnconfirmed(
                    "launcher custody unproven; timed out or prior failure remains unresolved")
        _cleanup_request(request_path)
        if read_fd is not None:
            try:
                _os.close(read_fd)
            except OSError:
                pass
        if write_fd is not None:
            try:
                _os.close(write_fd)
            except OSError:
                pass
        for descriptor_name in ("cancel_read_fd", "cancel_write_fd"):
            descriptor = locals().get(descriptor_name)
            if descriptor is not None:
                try:
                    _os.close(descriptor)
                except OSError:
                    pass
        if custody_error is not None:
            raise custody_error


def cancel_background(
    supervisor: Any, *, wait_timeout: float = 0.25,
    started: Optional[Mapping[str, Any]] = None,
    cleanup_ack: Optional[Mapping[str, Any]] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Cancel a supervisor only after launcher custody has been proven separately."""
    supervisor_confirmed = _cleanup_owned(supervisor, wait_timeout=wait_timeout)
    ownership = None
    if started is not None and session_id is not None:
        try:
            ownership = _ownership_from_started(started, session_id)
        except BackgroundUnconfirmed:
            ownership = None
    launcher_confirmed = (
        ownership is not None
        and cleanup_ack is not None
        and _validate_launcher_cleanup_ack(cleanup_ack, ownership)
    )
    confirmed = supervisor_confirmed and launcher_confirmed
    result = {
        "outcome": "cancelled" if confirmed else "unresolved_custody",
        "cleanup_confirmed": confirmed,
        "launcher_cleanup_confirmed": launcher_confirmed,
        "exit_code": 130 if confirmed else 6,
    }
    if not confirmed:
        raise BackgroundUnconfirmed("launcher custody unresolved")
    return result


def active_launch_lease(path: Path) -> Path:
    """Return the sidecar lease path used to protect an active launch log."""
    return path.with_name(path.name + ".lease")


def _write_lease(lease: Path, *, pid: int, identity: Optional[tuple[int, int]]) -> None:
    """Create the lease exclusively and record the owning supervisor identity.

    The recorded owner makes the lease verifiable: a leftover file whose owner
    is gone is stale, while a file with no readable owner is not proof of an
    active launch.
    """
    payload = _json.dumps({
        "pid": int(pid),
        "start": None if identity is None else int(identity[1]),
    }, separators=(",", ":"))
    fd = _os.open(str(lease), _os.O_WRONLY | _os.O_CREAT | _os.O_EXCL, 0o600)
    try:
        view = memoryview(payload.encode("utf-8"))
        while view:
            written = _os.write(fd, view)
            if written <= 0:
                raise OSError("lease write made no progress")
            view = view[written:]
    finally:
        _os.close(fd)


def _read_lease(lease: Path) -> Optional[dict[str, Any]]:
    """Read a lease owner record, or return None when it is unreadable."""
    try:
        raw = lease.read_text(encoding="utf-8")
        record = _json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    pid = record.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    return record


def _process_absent(pid: int) -> bool:
    """Return whether the OS authoritatively proves the process no longer exists.

    Only a missing ``/proc`` entry counts as proof of absence. Off-POSIX hosts
    and unreadable entries are unverifiable, so they must not be treated as
    absence.
    """
    if _os.name != "posix":
        return False
    try:
        _os.stat(f"/proc/{int(pid)}")
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _lease_owner_alive(lease: Path, *, identity_probe: Optional[Callable[[int], Any]] = None) -> bool:
    """Return whether the recorded lease owner is still the same live process.

    An unreadable lease or an unverifiable owner fails closed: the caller must
    treat the log as active rather than delete a possibly live launch log. A
    recorded owner that the OS proves absent is a stale lease, so the log is no
    longer protected.
    """
    record = _read_lease(lease)
    if record is None:
        return True
    pid = int(record["pid"])
    expected_start = record.get("start")
    if expected_start is None:
        return True
    current = _resolve_identity_probe(identity_probe)(pid)
    if current is None:
        # No identity token: the owner is either gone or unverifiable.
        return not _process_absent(pid)
    if isinstance(current, tuple) and len(current) == 2:
        current = current[1]
    return current == expected_start


def _is_active_launch_log(path: Path, *, identity_probe: Optional[Callable[[int], Any]] = None) -> bool:
    """Return whether a launch log is protected by a live supervisor lease."""
    lease = active_launch_lease(path)
    if not lease.exists():
        return False
    return _lease_owner_alive(lease, identity_probe=identity_probe)
