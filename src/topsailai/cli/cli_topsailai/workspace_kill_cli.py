"""Non-interactive termination of one exact workspace session.

Author: DawsonLin
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import sys

from cli_topsailai.log_files import discover_log_files
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


class _UniqueSession(argparse.Action):
    """Reject conflicting repeated session selectors."""

    def __call__(self, parser, namespace, value, option_string=None):
        """Store one literal session ID and reject a conflicting repeat."""
        current = getattr(namespace, self.dest, None)
        if current is not None and current != value:
            raise argparse.ArgumentError(self, "conflicting session values")
        setattr(namespace, self.dest, value)


def build_parser() -> argparse.ArgumentParser:
    """Build the strict non-interactive workspace kill parser."""
    parser = argparse.ArgumentParser(
        prog="topsailai workspace kill",
        description="Send SIGTERM to one exact workspace session process.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "session_id",
        action=_UniqueSession,
        help="exact persisted session ID",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON receipt on stdout, including failures",
    )
    return parser


def _resolve_pid(
    session_id: str, home: Path, rows: list[dict], *, process_probe=os.kill
) -> int:
    """Resolve one exact session stdout row and return its recorded PID."""
    matches = [
        row for row in rows
        if (row.get("session_id") == session_id
            and not row.get("is_task")
            and row.get("filename") == f"{session_id}.{row.get('pid')}.session.stdout")
    ]
    if len(matches) != 1:
        raise WorkspaceKillError("target_not_unique")
    pid = matches[0].get("pid")
    if type(pid) is not int or pid <= 0 or pid > 2147483647:
        raise WorkspaceKillError("invalid_pid")
    if pid == 1 or pid == os.getpid():
        raise WorkspaceKillError("protected_pid")
    try:
        process_probe(pid, 0)
    except ProcessLookupError as error:
        raise WorkspaceKillError("target_not_alive") from error
    except (PermissionError, OSError) as error:
        raise WorkspaceKillError("target_unavailable") from error
    return pid


def run_workspace_kill_cli(
    argv, *, home_resolver=None, discover=discover_log_files,
    signal_sender=os.kill, process_probe=os.kill
) -> int:
    """Resolve one session and send SIGTERM without an interactive prompt."""
    json_mode = json_requested(argv)
    try:
        args = build_parser().parse_args(list(argv))
        json_mode = args.json
    except SystemExit as error:
        code = int(error.code)
        # Help stays ordinary text; only a real usage failure becomes a receipt.
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

    pid = None
    try:
        home = Path((home_resolver or get_topsailai_home)()).resolve()
        rows = discover(str(home / "workspace" / "task"))
        pid = _resolve_pid(
            args.session_id, home, rows, process_probe=process_probe
        )
        signal_sender(pid, signal.SIGTERM)
    except WorkspaceKillError as error:
        if json_mode:
            emit_failure("kill", 3, str(error), "No unique live session target",
                         session_id=args.session_id)
        else:
            print(f"[ERROR] Cannot terminate session {args.session_id}: {error}", file=sys.stderr)
        return 3
    except (OSError, ValueError) as error:
        if json_mode:
            emit_failure("kill", 4, "signal_failed",
                         f"{type(error).__name__}: {error}",
                         session_id=args.session_id, pid=pid)
        else:
            print(
                f"[ERROR] Cannot terminate session {args.session_id}: "
                f"{type(error).__name__}: {error}",
                file=sys.stderr,
            )
        return 4

    if json_mode:
        receipt = new_receipt("kill", session_id=args.session_id, pid=pid)
        receipt.update(
            ok=True, exit_code=0, delivery_state="signal_sent",
            message="SIGTERM submitted; process exit is not confirmed",
            response={
                "signal": "SIGTERM",
                "signal_number": int(signal.SIGTERM),
                "exit_confirmed": False,
            },
        )
        emit_receipt(receipt)
        return 0
    print(
        f"[INFO] SIGTERM sent to session={args.session_id}, PID={pid}; "
        "process exit is not confirmed."
    )
    return 0
