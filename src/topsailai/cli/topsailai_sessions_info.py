#!/usr/bin/env python3
"""Display detailed information about multiple sessions in one invocation.

Each requested session is rendered with exactly the same card and JSON record
as ``topsailai_session_info``, because this command reuses that module's
formatters instead of reimplementing them.

Two costs are bounded independently of the number of requested sessions: all
identifiers are resolved with a single storage query, and the running status of
every session is derived from a single scan of the session stdout directory.
The reference command scans that directory once per session, so calling it in a
loop would cost O(sessions x directory entries); this command pays one scan for
the whole batch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

import _import_topsailai  # noqa: F401

import topsailai_session_info as session_info

from cli_topsailai.colors import Colors, colored
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.process_liveness import ProcessState, pid_state
from topsailai.context.ctx_manager import get_session_manager
from topsailai.context.session_manager import SessionData


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the batch session detail command."""
    parser = argparse.ArgumentParser(
        description="Display detailed information about multiple sessions."
    )
    parser.add_argument(
        "session_ids",
        nargs="+",
        help="The session identifiers to look up; pass one or more.",
    )
    parser.add_argument(
        "--db-conn",
        dest="db_conn",
        default=None,
        help="Optional database connection string (default: use session manager default).",
    )
    parser.add_argument(
        "--home",
        dest="home",
        default=None,
        help="Override TOPSAILAI_HOME directory.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the session information as a JSON array.",
    )
    return parser.parse_args(argv)


def _unique_session_ids(session_ids: list[str]) -> list[str]:
    """Return non-empty identifiers in first-occurrence order without duplicates.

    Duplicates are collapsed so each session is queried and rendered once, and
    the caller's order is preserved because the caller asked for these exact
    sessions rather than for a storage-defined ordering.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in session_ids:
        session_id = raw.strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        ordered.append(session_id)
    return ordered


def _order_found_sessions(
    requested: list[str], sessions: list[SessionData]
) -> tuple[list[SessionData], list[str]]:
    """Return found sessions in requested order plus the missing identifiers."""
    by_id = {str(session.session_id): session for session in sessions}
    found = [by_id[session_id] for session_id in requested if session_id in by_id]
    missing = [session_id for session_id in requested if session_id not in by_id]
    return found, missing


def _session_id_of(session: SessionData) -> str:
    """Return the identifier spelling used by the reference formatters."""
    return str(session.session_id) if session.session_id else ""


def _running_status_map(home: str) -> dict[str, bool]:
    """Return ``session_id -> is_running`` from one scan of the stdout directory.

    The reference command resolves running status per session, and each
    resolution lists the whole task directory.  A batch must not pay that cost
    once per session, so the directory is listed once here.

    Every stdout file of a session is collected, not only the newest one,
    because a newer dead file must not hide an older live process. This is the
    same rule ``topsailai_session_info._is_session_running`` applies, so both
    commands answer identically for the same session and the same on-disk
    state. A zombie or a non-positive PID is never reported as running.

    A session with no stdout file is absent from the returned mapping, which
    callers must read as "not running" rather than "unknown".
    """
    task_dir = os.path.join(home, session_info.TASK_SUBDIR)
    if not os.path.isdir(task_dir):
        return {}

    try:
        entries = os.listdir(task_dir)
    except OSError:
        return {}

    pids_by_session: dict[str, list[int]] = {}
    for entry in entries:
        if not entry.endswith(".session.stdout"):
            continue
        session_id, pid = session_info._parse_session_stdout_filename(entry)
        if session_id is None or pid is None:
            continue
        full_path = os.path.join(task_dir, entry)
        if not os.path.isfile(full_path):
            continue
        pids_by_session.setdefault(session_id, []).append(pid)

    return {
        session_id: any(pid_state(pid) is ProcessState.ALIVE for pid in pids)
        for session_id, pids in pids_by_session.items()
    }


def _format_sessions_json(
    sessions: list[SessionData], home: str, running_by_id: dict[str, bool]
) -> str:
    """Format sessions as a JSON array of the single-session JSON records."""
    return json.dumps(
        [
            session_info._session_to_dict(
                session, home, running_by_id.get(_session_id_of(session), False)
            )
            for session in sessions
        ],
        ensure_ascii=False,
        indent=2,
    )


def _format_sessions(
    sessions: list[SessionData],
    home: str,
    color_enabled: bool,
    running_by_id: dict[str, bool],
) -> str:
    """Format sessions as the single-session cards separated by a blank line."""
    cards = [
        session_info._format_session(
            session, home, color_enabled, running_by_id.get(_session_id_of(session), False)
        )
        for session in sessions
    ]
    return "\n\n".join(cards)


def _stderr_color_enabled() -> bool:
    """Return True if stderr messages may carry ANSI color codes.

    Diagnostics are written to stderr so stdout stays machine-parseable, which
    means their color decision must follow stderr rather than stdout.  Honouring
    ``NO_COLOR`` here keeps ``--no-color`` effective on the diagnostic channel
    too, instead of leaving escape sequences in a stream meant for parsing.
    """
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    return sys.stderr.isatty()


def _diagnostic(text: str, color: str) -> str:
    """Return *text* colored only when the stderr channel supports color."""
    if _stderr_color_enabled():
        return colored(text, color)
    return text


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for ``topsailai_sessions_info``."""
    args = _parse_args(argv)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    requested = _unique_session_ids(args.session_ids)
    if not requested:
        print(
            _diagnostic("[ERROR] No session identifier provided", Colors.RED),
            file=sys.stderr,
        )
        return 2

    home = args.home
    if home is None:
        home = get_topsailai_home()

    try:
        manager = get_session_manager(args.db_conn)
        sessions = manager.list_sessions(sessions=requested)
    except Exception as e:
        print(_diagnostic(f"[ERROR] {e}", Colors.RED), file=sys.stderr)
        return 1

    found, missing = _order_found_sessions(requested, sessions)

    for session_id in missing:
        print(
            _diagnostic(f"[INFO] Session not found: {session_id}", Colors.YELLOW),
            file=sys.stderr,
        )

    if found:
        running_by_id = _running_status_map(home)
        if args.json:
            print(_format_sessions_json(found, home, running_by_id))
        else:
            print(
                _format_sessions(
                    found, home, session_info._supports_color(), running_by_id
                )
            )
    elif args.json:
        print(_format_sessions_json(found, home, {}))

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
