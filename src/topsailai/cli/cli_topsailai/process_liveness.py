"""One authoritative process-liveness probe for every CLI status path.

The CLI previously carried several independent probes: ``os.kill(pid, 0)``,
``/proc/<pid>`` existence, and a newest-file-only scan. They disagreed on
zombies, on reused PIDs and on non-positive PIDs, so the same session could be
reported as running by one command and idle by another.

This module is the single place that answers "does this process exist". It is
three-state on purpose: an unverifiable process must be reported as ``UNKNOWN``
so each caller can apply its own policy instead of silently treating an
unanswerable question as absence.

The Linux process table is the authority. ``/proc`` parsing is reused from
:mod:`cli_topsailai.agent_launch_process` rather than copied, because that
module already owns the zombie and absence proofs.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import List, Optional

from cli_topsailai.agent_launch_process import (
    _proc_available,
    _process_absent,
    _process_state,
)
from cli_topsailai.log_files import _get_pid_from_stdout_path, _parse_stdout_filename
from cli_topsailai.paths import get_topsailai_home

#: Process state letter reported by the OS for an exited, unreaped process.
_ZOMBIE_STATE = "Z"


class ProcessState(Enum):
    """Outcome of a process-existence probe."""

    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


def _valid_pid(pid: object) -> bool:
    """Return whether *pid* is a usable positive process identifier.

    ``bool`` is rejected explicitly because it is an ``int`` subclass, and
    non-positive values are rejected because ``os.kill(0, sig)`` addresses the
    caller's process group while ``os.kill(-1, sig)`` addresses every process
    the caller may signal. Neither is a probe of one process.
    """
    if isinstance(pid, bool):
        return False
    if not isinstance(pid, int):
        return False
    return pid > 0


def pid_state(pid: object) -> ProcessState:
    """Classify one PID as ``ALIVE``, ``DEAD`` or ``UNKNOWN``.

    A zombie is ``DEAD``: it has already terminated and only its exit status is
    pending, so it must never keep a session looking alive. When the process
    table cannot answer, the result is ``UNKNOWN`` so callers fail closed.
    """
    if not _valid_pid(pid):
        return ProcessState.UNKNOWN
    if not _proc_available():
        return _portable_pid_state(pid)
    if _process_absent(pid):
        return ProcessState.DEAD
    state = _process_state(pid)
    if state is None:
        # The entry existed a moment ago but is now unreadable: the process
        # exited between the two reads, so absence is the honest answer.
        return ProcessState.DEAD if _process_absent(pid) else ProcessState.UNKNOWN
    if state == _ZOMBIE_STATE:
        return ProcessState.DEAD
    return ProcessState.ALIVE


def _portable_pid_state(pid: int) -> ProcessState:
    """Classify a PID on a host without a readable ``/proc`` process table.

    ``kill(pid, 0)`` performs the permission and existence check without
    delivering a signal. A permission refusal proves the process exists, while
    an unexplained failure stays ``UNKNOWN``.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return ProcessState.DEAD
    except PermissionError:
        return ProcessState.ALIVE
    except OSError:
        return ProcessState.UNKNOWN
    return ProcessState.ALIVE


def is_pid_alive(pid: object) -> bool:
    """Return whether *pid* is a live, non-zombie process."""
    return pid_state(pid) is ProcessState.ALIVE


def _session_stdout_candidates(task_dir: str, session_id: str) -> List[str]:
    """Return every session stdout file belonging to *session_id*.

    Every candidate is returned because a newer dead file must not hide an
    older live process for the same session.
    """
    candidates: List[str] = []
    try:
        entries = os.listdir(task_dir)
    except FileNotFoundError:
        return []
    for entry in entries:
        if not entry.endswith(".session.stdout"):
            continue
        parsed_session_id, _pid = _parse_stdout_filename(entry)
        if parsed_session_id == session_id:
            candidates.append(os.path.join(task_dir, entry))
    return candidates


def session_liveness(session_id: str, *, home: Optional[str] = None) -> str:
    """Return ``live``, ``idle`` or ``unknown`` for one session identity.

    A single live candidate proves the session is running. An unverifiable
    candidate makes the answer ``unknown`` so a caller that is about to resume
    or signal the session fails closed instead of assuming it is idle.
    """
    if not session_id:
        return "unknown"
    base = home or get_topsailai_home()
    task_dir = os.path.join(base, "workspace", "task")
    try:
        candidates = _session_stdout_candidates(task_dir, session_id)
    except OSError:
        return "unknown"
    if not candidates:
        return "idle"
    unknown = False
    for path in candidates:
        state = pid_state(_get_pid_from_stdout_path(path))
        if state is ProcessState.ALIVE:
            return "live"
        if state is ProcessState.UNKNOWN:
            unknown = True
    return "unknown" if unknown else "idle"
