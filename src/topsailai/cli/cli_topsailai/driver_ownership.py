"""Ownership of a launched resume driver process tree.

A resume driver is not always the direct child of the CLI process: ``dtach``
daemonizes into its own session and ``tmux`` runs the driver inside a server.
Signalling only the direct child therefore proves nothing about the driver.
This module records how a driver tree is owned and stops the whole owned
process group.

Proof rule: absence of the owned group may come ONLY from the kernel. The
group is gone only when ``killpg(pgid, 0)`` answers ``ESRCH``; a successful
probe means the group still exists, and an unanswerable probe means the state
is unknown. ``/proc`` enumeration is a diagnostic aid only, so a malformed or
incomplete record can never be turned into a false proof of absence.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Grace period granted to a driver before the stop escalates to SIGKILL.
_STOP_GRACE_SECONDS = 2.0

# Poll interval while waiting for a driver to disappear.
_POLL_INTERVAL_SECONDS = 0.05

# Modes whose driver is not the direct child of the CLI process.
_WRAPPED_MODES = ("dtach", "tmux")


@dataclass(frozen=True)
class DriverOwnership:
    """Describe how one launched driver tree is owned and stopped.

    Attributes:
        kind: Launch mode that produced the tree (``raw``, ``dtach``, ``tmux``).
        pidfile: File recording the driver PID, or ``None`` for ``raw``.
        session_name: tmux session name, or ``None`` for other modes.
    """

    kind: str
    pidfile: Optional[str] = None
    session_name: Optional[str] = None


def read_pidfile(path: Optional[str]) -> Optional[int]:
    """Return the driver PID recorded in *path*, or ``None`` when absent."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read().strip()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        return None
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def remove_pidfile(path: Optional[str]) -> None:
    """Delete the driver pidfile and log the deletion event."""
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as error:
        print(f"[WARN] Failed to delete {path}: {error}")
        return
    print(f"[OK] Deleted: {path}")


def _signal_group_pgid(pgid: int, sig: int) -> None:
    """Signal the process group *pgid*, ignoring an absent or invalid group."""
    if not isinstance(pgid, int) or pgid <= 1:
        return
    try:
        os.killpg(pgid, sig)
    except OSError:
        pass


def _signal_group(pid: int, sig: int) -> None:
    """Signal the process group led by *pid*, ignoring an absent group."""
    try:
        os.killpg(os.getpgid(pid), sig)
    except OSError:
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def _signal_child_group(child, sig: int) -> None:
    """Signal the process group of the directly owned child, if it has one."""
    pid = getattr(child, "pid", None)
    if not isinstance(pid, int):
        return
    _signal_group(pid, sig)


def _parse_proc_stat(data: str) -> Optional[Tuple[int, str, int]]:
    """Parse one ``/proc/PID/stat`` record into ``(pid, state, pgid)``.

    This parser feeds diagnostics only. It never decides whether the owned
    group is gone, so a malformed record cannot weaken custody proof; it can
    only make the diagnostic less informative.

    The record is validated structurally before any field is consumed:

    * the leading field must be the numeric PID;
    * the command field must be enclosed in parentheses, and the closing
      parenthesis is located from the right because the command may itself
      contain spaces and parentheses;
    * the state and the process-group fields are read from their fixed
      positions after that closing parenthesis.

    Returns ``None`` when the record does not have that structure.
    """
    open_paren = data.find("(")
    close_paren = data.rfind(")")
    if open_paren <= 0 or close_paren < open_paren:
        return None
    try:
        record_pid = int(data[:open_paren].strip())
    except ValueError:
        return None
    fields = data[close_paren + 1 :].split()
    if len(fields) < 3:
        return None
    state = fields[0]
    if len(state) != 1 or not state.isalpha():
        return None
    try:
        member_pgid = int(fields[2])
    except ValueError:
        return None
    return record_pid, state, member_pgid


def _proc_group_members(pgid: int) -> Optional[List[int]]:
    """Return live (non-zombie) PIDs in *pgid*, or ``None`` when unknown.

    This is a diagnostic helper: it reports which PIDs appear to remain so an
    operator can see what survived. It is deliberately NOT part of the custody
    proof, because any parser or observation defect would otherwise become a
    false proof of absence.

    The return value is tri-state:

    * a list (possibly empty) means the scan completed;
    * ``None`` means the observation is incomplete or unavailable.

    A process that disappears between ``listdir`` and ``open`` is a benign
    race and is skipped. Any other read failure (``PermissionError``, ``EIO``,
    ...) or a structurally invalid ``stat`` record leaves the state unknown.
    """
    proc_root = "/proc"
    if not os.path.isdir(proc_root):
        return None
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return None
    members: List[int] = []
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(
                os.path.join(proc_root, entry, "stat"),
                encoding="utf-8",
                errors="replace",
            ) as handle:
                data = handle.read()
        except (FileNotFoundError, ProcessLookupError):
            # The process vanished while scanning; it cannot be a live member.
            continue
        except OSError:
            # An unreadable record could belong to the owned group, so the
            # scan is incomplete and the group state stays unknown.
            return None
        parsed = _parse_proc_stat(data)
        if parsed is None:
            # A structurally invalid record could belong to the owned group,
            # so the scan is incomplete and the group state stays unknown.
            return None
        record_pid, state, member_pgid = parsed
        if record_pid != int(entry):
            # The record does not describe the process it was read from.
            return None
        if state == "Z":
            continue
        if member_pgid != pgid:
            continue
        members.append(record_pid)
    return members


def describe_owned_group(pgid: int) -> str:
    """Return a diagnostic description of the remaining members of *pgid*.

    The description is informational only. It is used in the custody error
    message so an operator can see which PIDs appear to survive, and it never
    influences whether custody is considered proven.
    """
    members = _proc_group_members(pgid)
    if members is None:
        return f"pgid={pgid} remaining=unknown"
    return f"pgid={pgid} remaining={members}"


def describe_ownership(ownership: DriverOwnership, child) -> str:
    """Return a diagnostic description of one owned driver tree."""
    if ownership.kind in _WRAPPED_MODES:
        driver_pid = read_pidfile(ownership.pidfile)
        if driver_pid is None:
            return f"kind={ownership.kind} driver=unknown"
        return (
            f"kind={ownership.kind} driver={driver_pid} "
            f"{describe_owned_group(driver_pid)}"
        )
    pid = getattr(child, "pid", None)
    if not isinstance(pid, int):
        return f"kind={ownership.kind} driver=unknown"
    return f"kind={ownership.kind} driver={pid} {describe_owned_group(pid)}"


def _group_state(pgid: int) -> Optional[bool]:
    """Return the kernel's answer about the owned group *pgid*.

    Returns:
        ``False`` only when ``killpg(pgid, 0)`` reports ``ESRCH``, which is the
        kernel stating that the group does not exist. ``True`` when the probe
        succeeds, because the group exists whether or not its members can be
        enumerated. ``None`` when the probe cannot answer, so the state is
        unknown and must be treated as not-gone.
    """
    if not isinstance(pgid, int) or pgid <= 1:
        return None
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    except OSError:
        return None
    return True


def _group_alive(pgid: int) -> bool:
    """Return whether the owned group is not proven gone by the kernel."""
    return _group_state(pgid) is not False


def _reap_owned_pid(pid: int) -> None:
    """Reap *pid* when it is a child of this process, ignoring non-children.

    A not-yet-reaped zombie keeps its process group visible to the kernel, so
    the leader must be reaped before ``ESRCH`` can be observed. A PID that is
    not our child raises ``ChildProcessError`` and is left to its own parent.
    """
    if not isinstance(pid, int) or pid <= 1:
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return
    except OSError:
        return


def _wait_group_gone(
    pgid: int, timeout: float, *, reap_pid: Optional[int] = None
) -> bool:
    """Return whether the kernel reports the owned group gone within *timeout*.

    Args:
        pgid: Owned process-group ID.
        timeout: Maximum seconds to wait.
        reap_pid: Optional leader PID to reap while polling, so a zombie leader
            does not keep the group visible.
    """
    deadline = time.monotonic() + timeout
    while True:
        if reap_pid is not None:
            _reap_owned_pid(reap_pid)
        if not _group_alive(pgid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_INTERVAL_SECONDS)


def _stop_owned_group(
    pgid: int, timeout: float, *, reap_pid: Optional[int] = None
) -> bool:
    """Stop an owned group, escalating to SIGKILL, and prove it is gone.

    Proof of absence is the kernel's ``ESRCH`` answer only, so no enumeration
    defect can turn a surviving tree into a proven-empty one.
    """
    _signal_group_pgid(pgid, signal.SIGTERM)
    if _wait_group_gone(pgid, timeout, reap_pid=reap_pid):
        return True
    _signal_group_pgid(pgid, signal.SIGKILL)
    return _wait_group_gone(pgid, timeout, reap_pid=reap_pid)


def _stop_direct_child(child, *, signal_group: bool = True) -> bool:
    """Stop and reap the directly owned child, proving its whole group is gone.

    The leader exiting is not proof of custody: a descendant that ignores
    ``SIGTERM`` stays alive in the same owned group. The group is therefore
    signalled, escalated to ``SIGKILL`` when it survives, and re-checked until
    the kernel reports it gone.

    Args:
        child: The directly owned child returned by the spawn factory.
        signal_group: Whether the child leads its own process group. A tmux
            client does not: it shares the caller's group, so signalling that
            group would terminate the CLI itself.
    """
    pid = getattr(child, "pid", None)
    pgid = pid if (signal_group and isinstance(pid, int)) else None
    try:
        if child.poll() is None:
            if signal_group:
                _signal_child_group(child, signal.SIGTERM)
            child.terminate()
            try:
                child.wait(timeout=_STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                if pgid is not None:
                    _signal_group_pgid(pgid, signal.SIGKILL)
                child.kill()
                child.wait(timeout=1.0)
        elif pgid is not None:
            # The leader already exited, but the owned group may still hold
            # descendants, so the group is signalled before it is proven gone.
            _signal_group_pgid(pgid, signal.SIGTERM)
    except (OSError, AttributeError, subprocess.TimeoutExpired, KeyboardInterrupt):
        return False
    if pgid is None:
        return True
    if _wait_group_gone(pgid, _STOP_GRACE_SECONDS):
        return True
    _signal_group_pgid(pgid, signal.SIGKILL)
    return _wait_group_gone(pgid, _STOP_GRACE_SECONDS)


def _kill_tmux_session(session_name: str) -> bool:
    """Kill exactly one tmux session and report whether it is gone.

    The target is addressed with tmux's exact-match prefix so a session whose
    name is a prefix of another cannot be confused with it.
    """
    target = f"={session_name}"
    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", target],
            capture_output=True,
            timeout=_STOP_GRACE_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    try:
        probe = subprocess.run(
            ["tmux", "has-session", "-t", target],
            capture_output=True,
            timeout=_STOP_GRACE_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode != 0


def stop_owned_driver(ownership: DriverOwnership, child) -> bool:
    """Stop the whole owned driver tree and prove no owned member survives.

    Args:
        ownership: Ownership record produced for this launch.
        child: The directly owned child returned by the spawn factory.

    Returns:
        ``True`` only when the kernel reports the owned process group gone,
        otherwise ``False`` so the caller reports unresolved custody instead of
        claiming a clean cancellation.
    """
    if ownership.kind not in _WRAPPED_MODES:
        return _stop_direct_child(child)

    driver_pid = read_pidfile(ownership.pidfile)
    if ownership.kind == "tmux":
        # The tmux client shares the caller's process group, so only the client
        # PID may be signalled. The session kill is the authoritative stop for
        # the driver running inside the tmux server, and the driver group is
        # still proven gone afterwards.
        session_gone = True
        if ownership.session_name:
            session_gone = _kill_tmux_session(ownership.session_name)
        client_gone = _stop_direct_child(child, signal_group=False)
        if driver_pid is None:
            # Without a recorded driver identity the owned tree cannot be
            # proven gone, so custody stays unproven instead of assumed.
            return False
        tree_gone = _stop_owned_group(
            driver_pid, _STOP_GRACE_SECONDS, reap_pid=driver_pid
        )
        if tree_gone:
            remove_pidfile(ownership.pidfile)
        return session_gone and client_gone and tree_gone

    if driver_pid is None:
        # Without a recorded driver identity the tree cannot be proven stopped.
        _stop_direct_child(child)
        return False
    client_gone = _stop_direct_child(child)
    tree_gone = _stop_owned_group(
        driver_pid, _STOP_GRACE_SECONDS, reap_pid=driver_pid
    )
    if tree_gone:
        remove_pidfile(ownership.pidfile)
    return tree_gone and client_gone
