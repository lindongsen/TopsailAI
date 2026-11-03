"""Terminal-container control transport and submission lifecycle.

The detached supervisor always runs inside the selected execution container
(independent process, tmux session, or dtach socket) and always spawns the
launcher itself, so the reported ``launcher_pid`` is the real launcher process
rather than a short-lived terminal client. Terminal containers cannot inherit the
parent's acknowledgement pipes, so the supervisor authenticates over the private
AF_UNIX control socket owned by the attempt and then exchanges the same bounded
JSON frames used by the raw pipe transport.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import shutil

from cli_topsailai import agent_launch_process as _process
from cli_topsailai.agent_launch_attempt import (
    MECHANISMS,
    TerminalAttempt,
    TerminalUnavailable,
    TerminalUnconfirmed,
    _authenticate,
    _attempt_root,
    _remove_tree,
    accept_control,
    build_command,
    connect_control,
    open_listener,
    prepare_attempt,
    read_recovery_record,
    resolve_mechanism,
    write_recovery_record,
    write_request,
)
from cli_topsailai.agent_launch_process import (
    _await_process_dead,
    _identity_matches,
    _proc_available,
    _process_absent,
    _process_dead,
    _process_identity,
    _process_state,
    _reap_client,
)
from cli_topsailai.paths import get_topsailai_home

_POLL_INTERVAL = 0.05


def _proc_available() -> bool:
    """Expose process-table capability through this module's compatibility seam."""
    return _process._proc_available()


def _process_identity(pid: int) -> Optional[tuple[int, int]]:
    """Read a process identity through this module's compatibility seam."""
    return _process._process_identity(pid) if _proc_available() else None


def _identity_matches(pid: int, identity: Optional[tuple[int, int]]) -> bool:
    """Compare process identity through this module's compatibility seam."""
    return _process._identity_matches(pid, identity) if _proc_available() else False


def _process_absent(pid: int) -> bool:
    """Prove process absence through this module's compatibility seam."""
    return _process._process_absent(pid) if _proc_available() else False


def _process_state(pid: int) -> Optional[str]:
    """Read process state through this module's compatibility seam."""
    return _process._process_state(pid) if _proc_available() else None


def _process_dead(pid: int) -> bool:
    """Prove process exit through this module's compatibility seam."""
    return _process._process_dead(pid) if _proc_available() else False


def _signal_owned(pid: int, identity: Optional[tuple[int, int]],
                  sig: int = signal.SIGTERM) -> bool:
    """Signal one process only while its immutable identity is still bound.

    A pidfd provides an atomic process reference where supported. Otherwise the
    identity is checked immediately before signalling, with a residual race.
    """
    """Signal one process only while its immutable identity is still bound.

    A plain identity check followed by ``os.kill`` is not atomic: the PID can be
    reused between the check and the signal. Where the platform supports it, a
    pidfd is opened first and the signal is delivered through that descriptor,
    while non-pidfd platforms retain an explicitly documented residual race.

    Returns True when the process was signalled or was already gone, and False
    when the identity could not be verified.
    """
    if identity is None:
        return False
    pidfd_open = getattr(os, "pidfd_open", None)
    pidfd_send = getattr(signal, "pidfd_send_signal", None)
    if pidfd_open is not None and pidfd_send is not None:
        try:
            descriptor = pidfd_open(pid)
        except ProcessLookupError:
            print(f"[INFO] Owned process already absent: pid={pid}")
            return True
        except OSError as error:
            print(f"[WARN] Cannot bind owned process {pid} through a pidfd: {error}")
            return False
        try:
            if not _identity_matches(pid, identity):
                print(f"[WARN] Refusing to signal {pid}: "
                      f"process identity could not be re-verified")
                return False
            try:
                pidfd_send(descriptor, sig)
                print(f"[INFO] Signalled owned process through pidfd: pid={pid}")
                return True
            except ProcessLookupError:
                print(f"[INFO] Owned process already absent: pid={pid}")
                return True
            except OSError as error:
                print(f"[WARN] Failed to signal owned process {pid}: {error}")
                return False
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
    if not _identity_matches(pid, identity):
        print(f"[WARN] Refusing to signal {pid}: "
              f"process identity could not be re-verified")
        return False
    try:
        os.kill(pid, sig)
        print(f"[INFO] Signalled owned process: pid={pid}")
        return True
    except ProcessLookupError:
        print(f"[INFO] Owned process already absent: pid={pid}")
        return True
    except OSError as error:
        print(f"[WARN] Failed to signal owned process {pid}: {error}")
        return False

def _stop_container(attempt: TerminalAttempt, supervisor_pid: Optional[int],
                    supervisor_identity: Optional[tuple[int, int]] = None) -> bool:
    """Stop exactly the terminal container created for this attempt.

    The return value reports whether the container was stopped or was already
    gone. A dtach supervisor is signalled only through a verified identity, and
    an attempt without a verifiable supervisor identity is reported as unproven
    instead of being assumed clean.
    """
    stopped = True
    if attempt.mechanism == "tmux" and attempt.session_name:
        try:
            subprocess.run(
                ["tmux", "-L", str(attempt.tmux_socket), "kill-session",
                 "-t", str(attempt.session_name)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False, timeout=5,
            )
            print(f"[INFO] Stopped owned tmux session: {attempt.session_name}")
        except (OSError, subprocess.SubprocessError) as error:
            print(f"[WARN] Failed to stop owned tmux session "
                  f"{attempt.session_name}: {error}")
            stopped = False
    elif attempt.mechanism == "dtach":
        if not isinstance(supervisor_pid, int) or supervisor_pid <= 0:
            # No supervisor identity was ever published, so nothing proves the
            # container is gone. Fail closed instead of assuming success.
            print("[WARN] No dtach supervisor identity is available; "
                  "container state is unproven")
            stopped = False
        elif _process_absent(supervisor_pid):
            print(f"[INFO] Owned dtach supervisor already absent: "
                  f"pid={supervisor_pid}")
        elif not _signal_owned(supervisor_pid, supervisor_identity):
            stopped = False
    if attempt.dtach_path is not None:
        try:
            attempt.dtach_path.unlink()
            print(f"[INFO] Removed terminal attempt file: {attempt.dtach_path}")
        except FileNotFoundError:
            pass
        except OSError as error:
            print(f"[WARN] Failed to remove dtach socket "
                  f"{attempt.dtach_path}: {error}")
    return stopped

def cleanup_attempt(attempt: TerminalAttempt, supervisor_pid: Optional[int] = None,
                    supervisor_identity: Optional[tuple[int, int]] = None) -> bool:
    """Remove only the terminal resources owned by this attempt."""
    stopped = _stop_container(attempt, supervisor_pid, supervisor_identity)
    _remove_tree(attempt.directory)
    return stopped

class TerminalTransport:
    """Expose one terminal-container supervisor through the control interface."""

    def __init__(self, attempt: TerminalAttempt, conn: socket.socket,
                 hello: Mapping[str, Any], *, clock: Callable[[], float],
                 sleeper: Callable[[float], None], initial: bytes = b"",
                 client: Any = None,
                 supervisor_identity: Optional[tuple[int, int]] = None):
        self.attempt = attempt
        self.conn = conn
        self.hello = hello
        self.supervisor_pid = hello.get("pid")
        self.supervisor_identity = supervisor_identity
        self.client = client
        self.clock = clock
        self.sleeper = sleeper
        # Bytes that arrived together with the hello frame are already
        # authenticated, so they seed the frame buffer instead of being lost.
        self.buffer = bytearray(initial)
        self.pending: deque[dict[str, Any]] = deque()
        self.eof = False
        self.ownership: Any = None
        self.cleanup_ack: Optional[Mapping[str, Any]] = None
        self.submitted = False

    def frames(self) -> list[dict[str, Any]]:
        """Return retained frames plus every frame from one transport read."""
        frames = list(self.pending)
        self.pending.clear()
        frames.extend(self._read())
        return frames

    def _read(self) -> list[dict[str, Any]]:
        """Read available frames; a clean EOF marks the supervisor gone.

        Complete frames are parsed before EOF is classified, so frames that
        arrived together with the peer's close are delivered instead of being
        discarded as a truncated frame. Buffered bytes are parsed even when the
        socket has nothing new, so a frame that arrived together with the hello
        is never stranded.
        """
        from cli_topsailai import agent_launch_background as bg

        try:
            data = self.conn.recv(bg._MAX_FRAME_BYTES + 1)
        except BlockingIOError:
            data = b""
            blocked = True
        except OSError as error:
            raise TerminalUnconfirmed(f"control transport failed: {error}") from error
        else:
            blocked = False
        if data:
            self.buffer.extend(data)
            if len(self.buffer) > bg._MAX_FRAME_BYTES:
                raise TerminalUnconfirmed("acknowledgement frame is too large")
        frames = self._parse()
        if not data and not blocked:
            if self.buffer:
                raise TerminalUnconfirmed("truncated acknowledgement frame")
            self.eof = True
        return frames

    def _parse(self) -> list[dict[str, Any]]:
        """Parse every complete newline-terminated frame from the buffer."""
        frames: list[dict[str, Any]] = []
        while b"\n" in self.buffer:
            raw, _, remaining = self.buffer.partition(b"\n")
            del self.buffer[: len(raw) + 1]
            if not raw:
                raise TerminalUnconfirmed("empty acknowledgement frame")
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as error:
                raise TerminalUnconfirmed("invalid acknowledgement frame") from error
            if not isinstance(value, dict):
                raise TerminalUnconfirmed("acknowledgement must be an object")
            frames.append(value)
        return frames

    def retain(self, frame: dict[str, Any]) -> None:
        """Keep one frame for the next read without starving the transport."""
        self.pending.append(frame)

    def exited(self) -> bool:
        """Return whether the supervisor closed its control connection."""
        return self.eof

    def request_cancel(self) -> None:
        """Send one cancellation byte over the full-duplex control socket."""
        try:
            written = os.write(self.conn.fileno(), b"1")
        except OSError as error:
            raise TerminalUnconfirmed(
                "supervisor cancellation transport failed") from error
        if written != 1:
            raise TerminalUnconfirmed("supervisor cancellation transport failed")

    def supervisor_exited(self, *, wait_timeout: float = 0.25) -> bool:
        """Prove the supervisor process exited, not merely that the socket closed.

        A closed control connection can also mean a crashed or half-closed peer,
        so exit is proven from the process itself: the recorded supervisor PID
        must be absent (or a reaped zombie) in the OS process table.
        """
        pid = self.supervisor_pid
        if not isinstance(pid, int) or pid <= 0:
            return False
        return _await_process_dead(pid, clock=self.clock, sleeper=self.sleeper,
                                   timeout=wait_timeout)

    def reap(self, *, wait_timeout: float = 0.25) -> bool:
        """Wait for the supervisor to exit, stopping the container if it does not."""
        deadline = self.clock() + wait_timeout
        while self.clock() < deadline and not self.eof:
            self.frames()
            if not self.eof:
                self.sleeper(_POLL_INTERVAL)
        if self.supervisor_exited(wait_timeout=wait_timeout):
            return True
        _stop_container(self.attempt, self.supervisor_pid, self.supervisor_identity)
        return self.supervisor_exited(wait_timeout=wait_timeout)

    def close(self) -> None:
        """Close the control socket and reap the short-lived terminal client."""
        try:
            self.conn.close()
        except OSError:
            pass
        _reap_client(self.client)

def _record(transport: TerminalTransport, frame: Mapping[str, Any],
            session_id: str) -> None:
    """Record ownership and cleanup proof from one acknowledgement frame."""
    from cli_topsailai import agent_launch_background as bg

    kind = frame.get("kind")
    if kind == "started":
        candidate = bg._ownership_from_started(frame, session_id)
        if transport.ownership is not None and candidate != transport.ownership:
            raise TerminalUnconfirmed("conflicting started acknowledgement")
        if transport.ownership is None:
            transport.ownership = candidate
    elif kind == "cleanup":
        transport.cleanup_ack = frame

def _protocol(transport: TerminalTransport, session_id: str, log_path: Path, *,
              clock: Callable[[], float], sleeper: Callable[[float], None],
              cancel_requested: Optional[Callable[[], bool]]) -> dict[str, Any]:
    """Run the bounded started/submitted protocol over the control socket."""
    from cli_topsailai import agent_launch_background as bg

    init_deadline = clock() + bg._INIT_TIMEOUT
    while clock() < init_deadline:
        if cancel_requested is not None and cancel_requested():
            return _cancel(transport, session_id, clock=clock, sleeper=sleeper)
        batch = transport.frames()
        for frame in batch:
            _record(transport, frame, session_id)
        for frame in batch:
            kind = frame.get("kind")
            if kind in ("started", "cleanup"):
                continue
            if kind == "failure":
                if not frame.get("cleanup_confirmed", False):
                    raise TerminalUnconfirmed(
                        frame.get("class", "supervisor cleanup unresolved"))
                raise RuntimeError(frame.get("error", "supervisor failed"))
            transport.retain(frame)
        if transport.ownership is not None:
            break
        if transport.exited():
            raise TerminalUnconfirmed("supervisor exited during initialization")
        sleeper(bg._POLL_INTERVAL)
    if transport.ownership is None:
        raise TerminalUnconfirmed("supervisor initialization acknowledgement timed out")

    observe_deadline = clock() + bg._SUBMISSION_TIMEOUT
    while clock() < observe_deadline:
        if cancel_requested is not None and cancel_requested():
            return _cancel(transport, session_id, clock=clock, sleeper=sleeper)
        batch = transport.frames()
        for frame in batch:
            _record(transport, frame, session_id)
        for frame in batch:
            kind = frame.get("kind")
            if kind in ("started", "cleanup"):
                continue
            if (kind == "submitted"
                    and frame.get("session") == session_id
                    and frame.get("launcher_pid") == transport.ownership.launcher_pid
                    and frame.get("log_path") == str(log_path)):
                transport.submitted = True
                return {
                    "session_id": session_id,
                    "launcher_pid": transport.ownership.launcher_pid,
                    "log_path": str(log_path),
                    "outcome": "submitted",
                }
            if kind == "early_exit":
                raise RuntimeError(
                    f"background launcher exited before submission: {frame.get('code')}")
            if kind == "failure":
                if not frame.get("cleanup_confirmed", False):
                    raise TerminalUnconfirmed(
                        frame.get("class", "supervisor cleanup unresolved"))
                raise RuntimeError(frame.get("error", "supervisor failed"))
        if transport.exited():
            raise TerminalUnconfirmed("launcher custody unresolved before submission")
        sleeper(bg._POLL_INTERVAL)
    raise TerminalUnconfirmed("background submission acknowledgement timed out")

def _cancel(transport: TerminalTransport, session_id: str, *,
            clock: Callable[[], float], sleeper: Callable[[float], None]) -> dict[str, Any]:
    """Request cancellation, consume launcher cleanup proof and reap the container."""
    from cli_topsailai import agent_launch_background as bg

    transport.request_cancel()
    deadline = clock() + bg._INIT_TIMEOUT
    while clock() < deadline:
        for frame in transport.frames():
            _record(transport, frame, session_id)
            if frame.get("kind") != "cleanup":
                if frame.get("kind") != "started":
                    transport.retain(frame)
                continue
            if (transport.ownership is None
                    or not bg._validate_launcher_cleanup_ack(frame, transport.ownership)):
                raise TerminalUnconfirmed(
                    "unrelated or incomplete launcher cleanup acknowledgement")
            if not transport.reap():
                raise TerminalUnconfirmed("supervisor reap failed after cancellation")
            return {"outcome": "cancelled", "exit_code": 130,
                    "cleanup_confirmed": True, "launcher_cleanup_confirmed": True,
                    "cleanup": frame}
        if transport.exited():
            raise TerminalUnconfirmed(
                "supervisor exited before cancellation cleanup acknowledgement")
        sleeper(bg._POLL_INTERVAL)
    raise TerminalUnconfirmed("cancellation cleanup acknowledgement timed out")

def _reconcile(transport: TerminalTransport, *,
               clock: Callable[[], float],
               sleeper: Callable[[float], None]) -> Optional[Mapping[str, Any]]:
    """Read correlated launcher cleanup proof before closing the transport.

    Frames other than the cleanup acknowledgement are still recorded, so an
    ownership frame that arrives after an interruption can establish the exact
    launcher owner. Without that, cleanup proof could never be correlated and
    launcher death could not be proven from the launcher PID.
    """
    from cli_topsailai import agent_launch_background as bg

    if transport.cleanup_ack is not None:
        return (transport.cleanup_ack
                if bg._validate_launcher_cleanup_ack(transport.cleanup_ack,
                                                     transport.ownership)
                else None)
    deadline = clock() + bg._INIT_TIMEOUT
    while clock() < deadline:
        for frame in transport.frames():
            if frame.get("kind") == "cleanup":
                if bg._validate_launcher_cleanup_ack(frame, transport.ownership):
                    return frame
                if transport.ownership is not None:
                    return None
                continue
            _record(transport, frame, transport.attempt.session_id)
        if transport.exited():
            return None
        sleeper(bg._POLL_INTERVAL)
    return None

def _launcher_gone(transport: TerminalTransport, *,
                   clock: Callable[[], float],
                   sleeper: Callable[[float], None],
                   timeout: float = 5.0) -> bool:
    """Prove the launcher process itself exited, not merely that it was asked to.

    The launcher runs in its own process session, so supervisor death does not
    imply launcher death. Exit is therefore proven from the launcher PID.
    """
    ownership = transport.ownership
    pid = getattr(ownership, "launcher_pid", None)
    if not isinstance(pid, int) or pid <= 0:
        return False
    return _await_process_dead(pid, clock=clock, sleeper=sleeper, timeout=timeout)

def _recover_pre_handshake(attempt: TerminalAttempt, client: Any, *,
                           clock: Callable[[], float],
                           sleeper: Callable[[float], None]) -> bool:
    """Establish and discharge recovery custody when the handshake never completed.

    The supervisor publishes its immutable identity record before it connects, so
    a failure before the handshake still leaves verifiable custody instead of an
    untracked container process. The record is only trusted after its identity is
    re-verified against the live process table.

    Absence of a record is NOT proof of custody: nothing then identifies the
    supervisor, so the result is unproven and the caller must preserve the
    attempt material instead of deleting it.
    """
    record = read_recovery_record(attempt.record_path)
    if record is None:
        print("[WARN] No pre-handshake supervisor record was published; "
              "supervisor custody is unproven")
        _reap_client(client)
        return False
    supervisor_pid = record["pid"]
    identity = (record["pid"], record["start"])
    print(f"[INFO] Recovered pre-handshake supervisor custody: pid={supervisor_pid}")
    stopped = _stop_container(attempt, supervisor_pid, identity)
    proven = _await_process_dead(supervisor_pid, clock=clock, sleeper=sleeper,
                                 timeout=5.0)
    if not proven:
        print(f"[WARN] Pre-handshake supervisor still alive: pid={supervisor_pid}")
    reaped = _reap_client(client)
    if not reaped:
        print("[WARN] Terminal client could not be reaped; custody is unproven")
    return stopped and proven and reaped

def submit_terminal(folder: str, session_id: str, *, mechanism: str,
                    environment: Optional[Mapping[str, str]] = None,
                    spawn: Optional[Callable[..., Any]] = None,
                    entrypoint_base: Optional[str] = None,
                    clock: Callable[[], float] = time.monotonic,
                    sleeper: Callable[[float], None] = time.sleep,
                    cancel_requested: Optional[Callable[[], bool]] = None,
                    log_identity: Optional[str] = None,
                    driver: Optional[str] = None,
                    non_interactive: bool = False) -> dict[str, Any]:
    """Submit one detached terminal-container supervisor and await its record."""
    from cli_topsailai import agent_launch_background as bg

    bg._validate_resume_driver(driver)
    task_dir = Path(get_topsailai_home()) / "workspace" / "task"
    task_dir.mkdir(parents=True, exist_ok=True)
    log_path = task_dir / f"{log_identity or session_id}.agent-launch.log"
    attempt = prepare_attempt(mechanism, session_id)
    listener: Optional[socket.socket] = None
    transport: Optional[TerminalTransport] = None
    client: Any = None
    try:
        request: dict[str, Any] = {
            "kind": "workspace-agent-supervisor",
            "folder": folder,
            "session_id": session_id,
            "log_path": str(log_path),
            "control_path": str(attempt.control_path),
            "record_path": str(attempt.record_path),
            "token": attempt.token,
            "attempt": attempt.directory.name,
        }
        if driver:
            request["driver"] = driver
        if non_interactive:
            request["non_interactive"] = True
        if environment is not None:
            request["environment"] = dict(environment)
        write_request(attempt.request_path, request)
        listener = open_listener(attempt)
        command = build_command(attempt, bg._entrypoint_command(entrypoint_base),
                                folder, environment)
        kwargs: dict[str, Any] = {
            "stdin": bg._subprocess.DEVNULL,
            "stdout": bg._subprocess.DEVNULL,
            "stderr": bg._subprocess.DEVNULL,
            "close_fds": True,
        }
        if bg._os.name != "nt":
            kwargs["start_new_session"] = True
        factory = spawn or bg._default_popen
        client = factory(command, **kwargs)
        conn, hello, initial = accept_control(listener, attempt, clock=clock,
                                              sleeper=sleeper)
        listener.close()
        listener = None
        supervisor_pid = hello.get("pid")
        identity = (_process_identity(supervisor_pid)
                    if isinstance(supervisor_pid, int) else None)
        transport = TerminalTransport(attempt, conn, hello, clock=clock,
                                      sleeper=sleeper, initial=initial,
                                      client=client,
                                      supervisor_identity=identity)
        return _protocol(transport, session_id, log_path, clock=clock,
                         sleeper=sleeper, cancel_requested=cancel_requested)
    finally:
        in_flight = sys.exc_info()[1]
        custody_proven = False
        try:
            custody_proven, failures = _release_after_failure(
                attempt, transport, client, listener, clock=clock,
                sleeper=sleeper, preserve_primary=in_flight is not None)
        except Exception as error:  # noqa: BLE001 - never mask the primary error
            failures = [f"terminal cleanup aborted: {error}"]
        for failure in failures:
            print(f"[WARN] Terminal cleanup: {failure}")
        if not custody_proven:
            custody_error = TerminalUnconfirmed(
                "terminal custody unproven; timed out or prior failure remains unresolved")
            if in_flight is not None:
                # Never mask an in-flight interruption or error with a custody
                # diagnostic; the original exception keeps its semantics.
                print(f"[WARN] {custody_error}")
            else:
                raise custody_error

def _release_after_failure(attempt: TerminalAttempt, transport: Any, client: Any,
                           listener: Any, *, clock: Callable[[], float],
                           sleeper: Callable[[float], None],
                           preserve_primary: bool = False) -> tuple[bool, list[str]]:
    """Release all owned resources while preserving interruption semantics."""
    failures: list[str] = []
    host_interrupts: list[BaseException] = []

    def capture(label: str, action: Callable[[], Any]) -> Any:
        """Run one cleanup action and defer every host-level interruption."""
        try:
            return action()
        except BaseException as error:  # noqa: BLE001 - cleanup must continue
            failures.append(f"{label}: {error}")
            if not isinstance(error, Exception):
                host_interrupts.append(error)
            return None

    custody_proven = False
    if transport is not None and transport.submitted:
        custody_proven = True
    elif transport is not None:
        capture("launcher cancellation request failed", transport.request_cancel)
        launcher_ack = capture(
            "launcher cleanup reconciliation failed",
            lambda: _reconcile(transport, clock=clock, sleeper=sleeper))
        container_cleaned = bool(capture("supervisor reap failed", transport.reap))
        if transport.ownership is None:
            # A supervisor's disappearance cannot prove the separately spawned
            # launcher is gone when its ownership identity was never established.
            custody_proven = False
        else:
            launcher_gone = bool(capture(
                "launcher exit proof failed",
                lambda: _launcher_gone(transport, clock=clock, sleeper=sleeper)))
            custody_proven = (launcher_ack is not None and container_cleaned
                              and launcher_gone)
    elif client is not None:
        custody_proven = bool(capture(
            "pre-handshake recovery failed",
            lambda: _recover_pre_handshake(attempt, client, clock=clock,
                                           sleeper=sleeper)))

    if listener is not None:
        capture("control listener close failed", listener.close)
    if transport is not None:
        capture("control transport close failed", transport.close)
    if transport is not None and transport.submitted:
        capture("attempt cleanup failed", lambda: _remove_tree(attempt.directory))
    elif custody_proven:
        capture("attempt cleanup failed", lambda: cleanup_attempt(
            attempt, transport.supervisor_pid if transport else None,
            transport.supervisor_identity if transport else None))
    else:
        print(f"[WARN] Preserving terminal attempt material because custody is "
              f"unproven: {attempt.directory}")

    if host_interrupts and not preserve_primary:
        raise host_interrupts[0]
    return custody_proven, failures
