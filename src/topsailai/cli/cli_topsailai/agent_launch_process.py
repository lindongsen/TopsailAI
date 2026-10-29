"""Process-table identity, absence and exit proofs for background launches.

These helpers derive every ownership decision from the operating system process
table instead of from a connection state, so a closed socket is never mistaken
for an exited process. Identity is the immutable ``(pid, start token)`` pair read
from ``/proc/<pid>/stat``; signalling binds that identity through a pidfd where
the platform provides one.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

_POLL_INTERVAL = 0.05


def _proc_available() -> bool:
    """Return whether this host exposes the Linux ``/proc`` process table.

    Process identity and absence proofs are derived from ``/proc``. On a POSIX
    host without it (for example macOS or a hardened container) those proofs are
    unavailable, so callers must fail closed instead of treating a missing
    ``/proc/<pid>`` entry as authoritative absence.
    """
    if os.name != "posix":
        return False
    try:
        os.stat("/proc/self/stat")
    except OSError:
        return False
    return True


def _process_start_token(pid: int) -> Optional[int]:
    """Read the OS-owned start token for one process, or None when unreadable.

    The token is the process start time from ``/proc/<pid>/stat``. It is
    immutable for the lifetime of a process, so a recorded identity can be
    compared against a live process to detect PID reuse. The comparison is not
    by itself an atomic binding; signalling uses a pidfd where available.
    """
    if not _proc_available():
        return None
    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
        # The parenthesised comm field may contain spaces, so index after the
        # last ')' instead of splitting the whole line.
        rest = raw[raw.rindex(")") + 2:].split()
        return int(rest[19])
    except (OSError, IndexError, ValueError):
        return None


def _process_identity(pid: int) -> Optional[tuple[int, int]]:
    """Return the immutable (pid, start token) identity of one live process."""
    token = _process_start_token(pid)
    if token is None:
        return None
    return (int(pid), token)


def _identity_matches(pid: int, identity: Optional[tuple[int, int]]) -> bool:
    """Return whether a live process still has the recorded immutable identity."""
    if identity is None:
        return False
    current = _process_identity(pid)
    return current is not None and current == identity


def _process_absent(pid: int) -> bool:
    """Return whether the OS authoritatively proves the process no longer exists.

    Absence is only proven when the ``/proc`` process table is available and the
    entry is missing. Without ``/proc`` the answer is unknown, which is reported
    as "not proven absent" so callers fail closed.
    """
    if not _proc_available():
        return False
    try:
        os.stat(f"/proc/{int(pid)}")
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _process_state(pid: int) -> Optional[str]:
    """Return the OS-reported process state letter, or None when unreadable."""
    if not _proc_available():
        return None
    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
        rest = raw[raw.rindex(")") + 2:].split()
        return rest[0]
    except (OSError, IndexError):
        return None


def _process_dead(pid: int) -> bool:
    """Return whether the process has exited, including an unreaped zombie.

    A zombie has already terminated; only its exit status is still pending. It
    therefore proves exit even though ``/proc/<pid>`` still exists. Without a
    readable process table exit cannot be proven, so the answer is False.
    """
    if _process_absent(pid):
        return True
    return _process_state(pid) == "Z"


def _await_process_absent(pid: int, *, clock: Callable[[], float],
                          sleeper: Callable[[float], None],
                          timeout: float) -> bool:
    """Wait a bounded time for the OS to prove one process is gone."""
    deadline = clock() + timeout
    while clock() < deadline:
        if _process_absent(pid):
            return True
        sleeper(_POLL_INTERVAL)
    return _process_absent(pid)


def _await_process_dead(pid: int, *, clock: Callable[[], float],
                        sleeper: Callable[[float], None],
                        timeout: float) -> bool:
    """Wait a bounded time for the OS to prove one process has exited."""
    deadline = clock() + timeout
    while clock() < deadline:
        if _process_dead(pid):
            return True
        sleeper(_POLL_INTERVAL)
    return _process_dead(pid)


def _reap_client(client: Any, *, wait_timeout: float = 5.0) -> bool:
    """Reap the short-lived terminal client and report whether it exited.

    The client is the ``tmux``/``dtach`` command process, not the supervisor.
    It normally exits immediately after detaching; a bounded wait keeps the
    parent from leaking an unreaped child without ever blocking indefinitely.
    The return value is an explicit result so recovery custody can consume it
    instead of treating a timeout warning as success.
    """
    if client is None:
        return True
    try:
        client.wait(timeout=wait_timeout)
        print(f"[INFO] Reaped terminal client: pid={getattr(client, 'pid', None)}")
        return True
    except subprocess.TimeoutExpired:
        print(f"[WARN] Terminal client did not exit within {wait_timeout}s: "
              f"pid={getattr(client, 'pid', None)}")
        return False
    except (OSError, subprocess.SubprocessError) as error:
        print(f"[WARN] Failed to reap terminal client "
              f"{getattr(client, 'pid', None)}: {error}")
        return False
