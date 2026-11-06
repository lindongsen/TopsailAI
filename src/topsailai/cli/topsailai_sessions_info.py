#!/usr/bin/env python3
"""Display detailed information about multiple sessions in one invocation.

Each requested session is rendered with exactly the same card and JSON record
as ``topsailai_session_info``, because this command reuses that module's
formatters instead of reimplementing them.  All requested identifiers are
resolved with a single storage query, so the cost does not grow with the
number of sessions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

import _import_topsailai  # noqa: F401

import topsailai_session_info as session_info

from cli_topsailai.colors import Colors
from cli_topsailai.paths import get_topsailai_home
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


def _format_sessions_json(sessions: list[SessionData], home: str) -> str:
    """Format sessions as a JSON array of the single-session JSON records."""
    return json.dumps(
        [session_info._session_to_dict(session, home) for session in sessions],
        ensure_ascii=False,
        indent=2,
    )


def _format_sessions(sessions: list[SessionData], home: str, color_enabled: bool) -> str:
    """Format sessions as the single-session cards separated by a blank line."""
    cards = [session_info._format_session(session, home, color_enabled) for session in sessions]
    return "\n\n".join(cards)


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for ``topsailai_sessions_info``."""
    args = _parse_args(argv)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    requested = _unique_session_ids(args.session_ids)
    if not requested:
        print(
            f"{Colors.RED}[ERROR] No session identifier provided{Colors.RESET}",
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
        print(f"{Colors.RED}[ERROR] {e}{Colors.RESET}")
        return 1

    found, missing = _order_found_sessions(requested, sessions)

    for session_id in missing:
        print(
            f"{Colors.YELLOW}[INFO] Session not found: {session_id}{Colors.RESET}",
            file=sys.stderr,
        )

    if args.json:
        print(_format_sessions_json(found, home))
    elif found:
        print(_format_sessions(found, home, session_info._supports_color()))

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
