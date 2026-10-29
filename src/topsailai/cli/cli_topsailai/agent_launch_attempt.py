"""Private attempt resources and control-channel handshake for terminal launches.

One attempt owns a mode-0700 directory, a 0600 AF_UNIX control socket, a 0600
exclusive request file and a 0600 recovery record. The supervisor publishes its
immutable identity before it connects, so a failure before the handshake still
leaves verifiable recovery custody.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from cli_topsailai.agent_launch_process import _process_start_token
from cli_topsailai.paths import get_topsailai_home

MECHANISMS = ("raw", "tmux", "dtach")
_ATTEMPT_ROOT = ".agent-launch"
# AF_UNIX paths are limited to roughly 108 bytes on Linux.
_MAX_CONTROL_PATH_BYTES = 100
_MAX_HANDSHAKE_BYTES = 4096
_ACCEPT_TIMEOUT = 5.0
_POLL_INTERVAL = 0.05
# Environment keys forwarded to a tmux server so the supervisor itself is
# runnable; the launcher environment travels through the private request file.
_ENV_KEYS = (
    "PATH", "HOME", "SHELL", "USER", "PWD", "TOPSAILAI_HOME",
    "TOPSAILAI_PWD", "SESSION_ID", "TOPSAILAI_SESSION_ID",
)


class TerminalUnavailable(RuntimeError):
    """Raised when the requested background mechanism cannot be used."""


class TerminalUnconfirmed(RuntimeError):
    """Raised when terminal custody or the control handshake cannot be proven."""


@dataclass(frozen=True)
class TerminalAttempt:
    """Immutable private resources owned by one terminal background attempt."""

    mechanism: str
    session_id: str
    directory: Path
    control_path: Path
    dtach_path: Optional[Path]
    request_path: Path
    record_path: Path
    token: str
    session_name: Optional[str]
    tmux_socket: Optional[str]

def resolve_mechanism(mechanism: str) -> str:
    """Validate one explicit background mechanism, failing closed when absent.

    An explicitly selected mechanism that cannot run is never silently
    replaced by another mechanism; the caller reports a preparation failure.
    """
    if mechanism not in MECHANISMS:
        raise TerminalUnavailable(f"unsupported background mechanism: {mechanism!r}")
    if mechanism == "raw":
        return mechanism
    binary = shutil.which(mechanism)
    if binary is None:
        raise TerminalUnavailable(
            f"{mechanism} is not installed or not found in PATH; "
            f"install {mechanism} or select --agent-mode raw"
        )
    if mechanism == "tmux":
        from cli_topsailai.project_scope import _tmux_supports_environment_option

        if not _tmux_supports_environment_option(binary):
            raise TerminalUnavailable(
                "tmux does not support new-session -e; select --agent-mode raw or dtach"
            )
    return mechanism

def _attempt_root() -> Path:
    """Return the private attempt root under the task directory."""
    return Path(get_topsailai_home()) / "workspace" / "task" / _ATTEMPT_ROOT

def _remove_tree(directory: Path) -> None:
    """Remove one owned attempt directory and log every deletion."""
    try:
        children = sorted(directory.iterdir())
    except FileNotFoundError:
        return
    except OSError as error:
        print(f"[WARN] Failed to list terminal attempt directory {directory}: {error}")
        return
    for child in children:
        try:
            child.unlink()
            print(f"[INFO] Removed terminal attempt file: {child}")
        except FileNotFoundError:
            pass
        except OSError as error:
            print(f"[WARN] Failed to remove terminal attempt file {child}: {error}")
    try:
        directory.rmdir()
        print(f"[INFO] Removed terminal attempt directory: {directory}")
    except FileNotFoundError:
        pass
    except OSError as error:
        print(f"[WARN] Failed to remove terminal attempt directory {directory}: {error}")

def prepare_attempt(mechanism: str, session_id: str) -> TerminalAttempt:
    """Create one private attempt directory and its control socket path."""
    root = _attempt_root()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    directory = root / uuid.uuid4().hex[:12]
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    control_path = directory / "c"
    if len(str(control_path).encode("utf-8")) > _MAX_CONTROL_PATH_BYTES:
        _remove_tree(directory)
        raise TerminalUnavailable(
            "control socket path is too long for AF_UNIX; "
            "set TOPSAILAI_HOME to a shorter path"
        )
    suffix = uuid.uuid4().hex[:12]
    return TerminalAttempt(
        mechanism=mechanism,
        session_id=session_id,
        directory=directory,
        control_path=control_path,
        dtach_path=(directory / "d") if mechanism == "dtach" else None,
        request_path=directory / "r.json",
        record_path=directory / "s.json",
        token=uuid.uuid4().hex,
        session_name=(f"topsailai-{suffix}" if mechanism == "tmux" else None),
        tmux_socket=(f"topsailai-{suffix}" if mechanism == "tmux" else None),
    )

def write_request(path: Path, request: Mapping[str, Any]) -> None:
    """Write one private request file without serializing credentials to argv."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags, 0o600)
    try:
        payload = json.dumps(dict(request), separators=(",", ":")).encode("utf-8")
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("request write made no progress")
            view = view[written:]
    finally:
        os.close(fd)

def read_recovery_record(path: Path) -> Optional[dict[str, Any]]:
    """Read the supervisor's own published identity record, if it exists.

    The supervisor publishes this record before it connects, so a failure that
    happens before the handshake completes still leaves verifiable recovery
    custody instead of an untracked process.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        record = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    pid = record.get("pid")
    start = record.get("start")
    if not isinstance(pid, int) or pid <= 0 or not isinstance(start, int):
        return None
    return record

def write_recovery_record(path: Path) -> None:
    """Publish this supervisor's immutable identity before it connects.

    The record is written first so that a failure during the handshake still
    leaves verifiable recovery custody: the parent can re-verify the identity and
    stop exactly this supervisor instead of leaking an untracked container.
    """
    record = {"pid": os.getpid(), "start": _process_start_token(os.getpid())}
    if record["start"] is None:
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags, 0o600)
    except OSError as error:
        print(f"[WARN] Failed to publish supervisor recovery record: {error}")
        return
    try:
        payload = json.dumps(record, separators=(",", ":")).encode("utf-8")
        os.write(fd, payload)
    finally:
        os.close(fd)

def build_command(attempt: TerminalAttempt, entrypoint: list[str], folder: str,
                  environment: Optional[Mapping[str, str]]) -> list[str]:
    """Build the detached terminal command that runs the internal supervisor."""
    supervisor = list(entrypoint) + [
        "--internal-workspace-agent-supervisor",
        str(attempt.request_path),
        str(attempt.control_path),
    ]
    if attempt.mechanism == "tmux":
        command = ["tmux", "-L", str(attempt.tmux_socket), "new-session", "-d",
                   "-s", str(attempt.session_name), "-c", folder]
        for key in _ENV_KEYS:
            value = (environment or {}).get(key)
            if value is not None:
                command.extend(["-e", f"{key}={value}"])
        command.extend(supervisor)
        return command
    return ["dtach", "-n", str(attempt.dtach_path), *supervisor]

def open_listener(attempt: TerminalAttempt) -> socket.socket:
    """Bind and listen on the private control socket before the container starts."""
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(attempt.control_path))
        os.chmod(attempt.control_path, 0o600)
        listener.listen(1)
        listener.setblocking(False)
    except BaseException:
        listener.close()
        raise
    return listener

def _authenticate(conn: socket.socket, attempt: TerminalAttempt, *,
                  clock: Callable[[], float], sleeper: Callable[[float], None],
                  timeout: float) -> tuple[dict[str, Any], bytes]:
    """Read and validate the supervisor's bounded hello frame.

    The supervisor writes its hello and then its first acknowledgement without
    waiting, so one read can carry both. The bytes after the hello line are
    returned to the caller instead of being discarded, otherwise the first
    acknowledgement frame would be lost and custody could never be proven.
    """
    conn.setblocking(False)
    buffer = bytearray()
    deadline = clock() + timeout
    while clock() < deadline:
        try:
            data = conn.recv(_MAX_HANDSHAKE_BYTES + 1)
        except BlockingIOError:
            sleeper(_POLL_INTERVAL)
            continue
        if not data:
            raise TerminalUnconfirmed("terminal supervisor closed before handshake")
        buffer.extend(data)
        if len(buffer) > _MAX_HANDSHAKE_BYTES:
            raise TerminalUnconfirmed("terminal handshake is too large")
        if b"\n" not in buffer:
            continue
        raw, _, rest = buffer.partition(b"\n")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise TerminalUnconfirmed("invalid terminal handshake") from error
        if not isinstance(value, dict) or value.get("kind") != "hello":
            raise TerminalUnconfirmed("invalid terminal handshake")
        if value.get("token") != attempt.token:
            raise TerminalUnconfirmed("terminal handshake token mismatch")
        if value.get("session") != attempt.session_id:
            raise TerminalUnconfirmed("terminal handshake session mismatch")
        if value.get("attempt") != attempt.directory.name:
            raise TerminalUnconfirmed("terminal handshake attempt mismatch")
        return value, bytes(rest)
    raise TerminalUnconfirmed("terminal handshake timed out")

def accept_control(listener: socket.socket, attempt: TerminalAttempt, *,
                   clock: Callable[[], float], sleeper: Callable[[float], None],
                   timeout: float = _ACCEPT_TIMEOUT
                   ) -> tuple[socket.socket, dict[str, Any], bytes]:
    """Accept and authenticate the supervisor's control connection.

    The trailing bytes read together with the hello frame are returned so the
    caller can seed its frame buffer instead of losing an early acknowledgement.
    """
    deadline = clock() + timeout
    conn = None
    while clock() < deadline:
        try:
            conn, _ = listener.accept()
            break
        except BlockingIOError:
            sleeper(_POLL_INTERVAL)
    if conn is None:
        raise TerminalUnconfirmed("terminal supervisor did not connect")
    try:
        hello, rest = _authenticate(conn, attempt, clock=clock, sleeper=sleeper,
                                    timeout=timeout)
    except BaseException:
        conn.close()
        raise
    conn.setblocking(False)
    return conn, hello, rest

def connect_control(control_path: str, request: Mapping[str, Any], *,
                    timeout: float = _ACCEPT_TIMEOUT) -> socket.socket:
    """Connect to the parent's private control socket and present the token."""
    deadline = time.monotonic() + timeout
    while True:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            conn.connect(control_path)
            break
        except OSError:
            conn.close()
            if time.monotonic() >= deadline:
                raise TerminalUnconfirmed("control socket unavailable")
            time.sleep(_POLL_INTERVAL)
    try:
        payload = json.dumps({
            "kind": "hello",
            "token": request.get("token"),
            "session": request.get("session_id"),
            "attempt": request.get("attempt"),
            "pid": os.getpid(),
        }, separators=(",", ":")).encode("utf-8") + b"\n"
        conn.sendall(payload)
    except BaseException:
        conn.close()
        raise
    conn.setblocking(False)
    return conn
