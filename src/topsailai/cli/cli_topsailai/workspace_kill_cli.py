"""Non-interactive termination of one exact workspace session.

Author: DawsonLin
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import sys
from typing import Callable, Optional

from cli_topsailai.agent_launch_process import _process_identity
from cli_topsailai.log_files import discover_log_files, is_process_holding_file
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.runtime_target import _valid_session
from cli_topsailai.workspace_receipt import (
    emit_failure,
    emit_receipt,
    json_requested,
    new_receipt,
)


class WorkspaceKillError(ValueError):
    """Classify an exact workspace kill target failure."""


@dataclass(frozen=True)
class KillTarget:
    """Bind one session row to an immutable operating-system process identity."""

    pid: int
    generation: int
    identity: tuple[int, int]


class _UniqueSession(argparse.Action):
    """Reject conflicting repeated session selectors."""

    def __call__(self, parser, namespace, value, option_string=None):
        """Store one literal session ID and reject a conflicting repeat."""
        current = getattr(namespace, self.dest, None)
        if current is not None and current != value:
            raise argparse.ArgumentError(self, "conflicting session values")
        setattr(namespace, self.dest, value)


class _UniqueGeneration(argparse.Action):
    """Accept one strict positive process-generation selector."""

    def __call__(self, parser, namespace, value, option_string=None):
        """Parse one generation and reject conflicts or nonpositive values."""
        try:
            generation = int(value)
        except (TypeError, ValueError) as error:
            raise argparse.ArgumentError(self, "generation must be a positive integer") from error
        if str(generation) != str(value) or generation <= 0:
            raise argparse.ArgumentError(self, "generation must be a positive integer")
        current = getattr(namespace, self.dest, None)
        if current is not None and current != generation:
            raise argparse.ArgumentError(self, "conflicting generation values")
        setattr(namespace, self.dest, generation)


def build_parser() -> argparse.ArgumentParser:
    """Build the strict non-interactive workspace kill parser."""
    parser = argparse.ArgumentParser(
        prog="topsailai workspace kill",
        description="Send SIGTERM to one exact verified workspace process instance.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "session_id",
        action=_UniqueSession,
        help="exact persisted session ID",
    )
    parser.add_argument(
        "-g", "--generation", required=True, action=_UniqueGeneration,
        help="exact process generation reported by workspace JSON",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON receipt on stdout, including failures",
    )
    return parser


def _valid_pid(pid) -> bool:
    """Return whether a discovered PID is a signal-eligible integer value."""
    return type(pid) is int and 1 < pid <= 2147483647 and pid != os.getpid()


def _resolve_target(
    session_id: str,
    expected_generation: int,
    rows: list[dict],
    *,
    identity_probe: Callable[[int], Optional[tuple[int, int]]] = _process_identity,
    absence_probe: Callable[[int], bool],
    relation_probe: Callable[[int, str], bool] = is_process_holding_file,
) -> KillTarget:
    """Select one live original instance and require its expected generation."""
    candidates: list[KillTarget] = []
    uncertain = False
    for row in rows:
        pid = row.get("pid")
        if (row.get("session_id") != session_id or row.get("is_task")
                or row.get("filename") != f"{session_id}.{pid}.session.stdout"):
            continue
        if not _valid_pid(pid):
            uncertain = True
            continue
        identity = identity_probe(pid)
        path = row.get("path")
        if identity is None:
            if not absence_probe(pid):
                uncertain = True
            continue
        if not isinstance(path, str):
            uncertain = True
            continue
        if not relation_probe(pid, path):
            uncertain = True
            continue
        candidates.append(KillTarget(pid, identity[1], identity))
    if len(candidates) > 1:
        raise WorkspaceKillError("multiple_live_instances")
    if not candidates:
        category = "target_identity_unavailable" if uncertain else "target_not_alive"
        raise WorkspaceKillError(category)
    target = candidates[0]
    if target.generation != expected_generation:
        raise WorkspaceKillError("generation_mismatch")
    return target


def _signal_bound(target: KillTarget, sig: int) -> str:
    """Deliver one signal to the verified instance and report the binding used.

    A pidfd binds the exact process instance atomically, so it is always
    preferred. When the running interpreter does not expose the pidfd bindings,
    the identity is re-verified immediately before ``os.kill``, which keeps a
    documented residual race but is still stronger than the interactive ``/kill``
    path that ships today. The returned binding name lets the receipt state which
    guarantee was actually obtained instead of implying the stronger one.
    """
    pidfd_open = getattr(os, "pidfd_open", None)
    pidfd_send = getattr(signal, "pidfd_send_signal", None)
    if pidfd_open is not None and pidfd_send is not None:
        try:
            descriptor = pidfd_open(target.pid)
        except ProcessLookupError as error:
            raise WorkspaceKillError("target_changed") from error
        except OSError as error:
            raise WorkspaceKillError("target_identity_unavailable") from error
        try:
            if _process_identity(target.pid) != target.identity:
                raise WorkspaceKillError("target_changed")
            try:
                pidfd_send(descriptor, sig)
            except ProcessLookupError as error:
                raise WorkspaceKillError("target_changed") from error
        finally:
            os.close(descriptor)
        return "pidfd"
    kill = getattr(os, "kill", None)
    if kill is None:
        raise WorkspaceKillError("safe_signal_unsupported")
    if _process_identity(target.pid) != target.identity:
        raise WorkspaceKillError("target_changed")
    try:
        kill(target.pid, sig)
    except ProcessLookupError as error:
        raise WorkspaceKillError("target_changed") from error
    return "identity_recheck"


# One human-readable message per classified failure. The message must state what
# actually failed, because a fixed message sends the investigation to the wrong
# layer: a capability gap is not a target-selection failure.
_KILL_ERROR_MESSAGES = {
    "multiple_live_instances":
        "Multiple live process instances match this session; none is selected",
    "target_identity_unavailable":
        "The process identity of the session target could not be verified",
    "target_not_alive":
        "No live process instance holds this session's stdout file",
    "generation_mismatch":
        "The live process generation differs from the requested generation",
    "target_changed":
        "The process instance changed before the signal was delivered",
    "safe_signal_unsupported":
        "This platform cannot deliver a signal to a verified process instance",
}


def _kill_error_message(error_code: str) -> str:
    """Derive the failure message from the classified error code."""
    return _KILL_ERROR_MESSAGES.get(
        error_code, f"Termination failed: {error_code}"
    )


def _kill_failure_exit_code(error_code: str) -> int:
    """Separate an environment capability gap from a target rejection.

    Exit ``3`` means the target was rejected, so a caller may retry with a fresh
    generation. Exit ``5`` means the environment cannot signal safely at all, so
    retrying the same command can never succeed.
    """
    return 5 if error_code == "safe_signal_unsupported" else 3


def run_workspace_kill_cli(
    argv, *, home_resolver=None, discover=discover_log_files,
    identity_probe=_process_identity, absence_probe=None,
    relation_probe=is_process_holding_file, bound_signal_sender=_signal_bound,
) -> int:
    """Resolve one exact process generation and submit SIGTERM through a pidfd."""
    json_mode = json_requested(argv)
    try:
        args = build_parser().parse_args(list(argv))
        json_mode = args.json
    except SystemExit as error:
        code = int(error.code)
        if json_mode and code != 0:
            emit_failure("kill", code, "usage_error", "Invalid kill arguments")
        return code
    if not _valid_session(args.session_id):
        if json_mode:
            emit_failure("kill", 2, "usage_error", "Invalid session identifier",
                         session_id=args.session_id)
        else:
            print("[ERROR] Invalid session identifier", file=sys.stderr)
        return 2

    target = None
    binding = None
    try:
        home = Path((home_resolver or get_topsailai_home)()).resolve()
        rows = discover(str(home / "workspace" / "task"))
        if absence_probe is None:
            from cli_topsailai.agent_launch_process import _process_absent
            absence_probe = _process_absent
        target = _resolve_target(
            args.session_id, args.generation, rows,
            identity_probe=identity_probe, absence_probe=absence_probe,
            relation_probe=relation_probe,
        )
        binding = bound_signal_sender(target, signal.SIGTERM)
    except WorkspaceKillError as error:
        error_code = str(error)
        exit_code = _kill_failure_exit_code(error_code)
        message = _kill_error_message(error_code)
        if json_mode:
            emit_failure("kill", exit_code, error_code, message,
                         session_id=args.session_id,
                         pid=target.pid if target is not None else None)
        else:
            print(f"[ERROR] Cannot terminate session {args.session_id}: {message}",
                  file=sys.stderr)
        return exit_code
    except OSError as error:
        if json_mode:
            emit_failure("kill", 4, "signal_failed",
                         f"{type(error).__name__}: {error}",
                         session_id=args.session_id,
                         pid=target.pid if target is not None else None)
        else:
            print(
                f"[ERROR] Cannot terminate session {args.session_id}: "
                f"{type(error).__name__}: {error}", file=sys.stderr,
            )
        return 4

    # A sender seam may return a non-string value; only a real binding name is
    # reported, so the receipt never claims a guarantee it did not obtain.
    binding_name = binding if isinstance(binding, str) else "unknown"
    if binding_name == "pidfd":
        message = ("SIGTERM submitted through a pidfd bound to the verified "
                   "process instance; exit is not confirmed")
    else:
        message = ("SIGTERM submitted after re-verifying the process identity; "
                   "a residual PID-reuse race remains and exit is not confirmed")
    if json_mode:
        receipt = new_receipt("kill", session_id=args.session_id, pid=target.pid)
        receipt.update(
            ok=True, exit_code=0, delivery_state="signal_sent",
            message=message,
            response={
                "signal": "SIGTERM", "signal_number": int(signal.SIGTERM),
                "generation": target.generation, "exit_confirmed": False,
                "binding": binding_name,
            },
        )
        emit_receipt(receipt)
        return 0
    print(
        f"[INFO] SIGTERM sent to session={args.session_id}, PID={target.pid}, "
        f"generation={target.generation}, binding={binding_name}; "
        f"process exit is not confirmed."
    )
    return 0
