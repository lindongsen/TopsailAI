#!/usr/bin/env python3
"""Display detailed information about a single session.

Queries the session storage for the given *session_id* and prints the
session metadata (ID, name, task, creation time, and running status).
The running status is determined by looking for a live
``{session_id}.{pid}.session.stdout`` file under ``workspace/task/`` in
TOPSAILAI_HOME.

The card and JSON renderers live in ``cli_topsailai.session_info_format``
because ``topsailai_sessions_info`` and ``topsailai runtime info`` publish the
same records.  A compiled build turns this script into a standalone executable,
so another script cannot import it; shared code must live in the package.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

import _import_topsailai  # noqa: F401  (adds the core project root to sys.path)

from cli_topsailai.colors import Colors
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.session_info_format import (
    TASK_SUBDIR,  # noqa: F401  (re-exported for callers of this module)
    _collect_runtime,
    _format_failure_json,
    _format_session,
    _format_session_json,
    _is_session_running,
    _parse_session_stdout_filename,  # noqa: F401  (re-exported)
    _relative_time,  # noqa: F401  (re-exported)
    _session_to_dict,  # noqa: F401  (re-exported)
    _supports_color,
)
from topsailai.context.ctx_manager import get_session_manager


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display detailed information about a single session."
    )
    parser.add_argument(
        "session_id",
        help="The session identifier to look up.",
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
        help="Output the session information as JSON.",
    )
    parser.add_argument(
        "--include-runtime",
        dest="include_runtime",
        action="store_true",
        help=(
            "Add a runtime object collected from the running session process. "
            "Selects JSON output by itself, because runtime data has no card "
            "representation."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for ``topsailai_session_info``."""
    args = _parse_args(argv)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    home = args.home
    if home is None:
        home = get_topsailai_home()

    # Runtime data has no card representation, so asking for it selects the
    # JSON document instead of being rejected or silently dropped. The flag is
    # therefore a request for the data, not a modifier of an already-chosen
    # format, which is the same contract ``workspace list`` applies.
    json_output = bool(args.json or args.include_runtime)

    try:
        manager = get_session_manager(args.db_conn)
        session = manager.get_session(args.session_id)
    except Exception as e:
        if json_output:
            print(_format_failure_json(args.session_id, "lookup_failed", str(e)))
        else:
            print(f"{Colors.RED}[ERROR] {e}{Colors.RESET}")
        return 1

    if session is None:
        message = f"Session not found: {args.session_id}"
        if json_output:
            print(_format_failure_json(args.session_id, "session_not_found", message))
        else:
            print(f"{Colors.YELLOW}[INFO] {message}{Colors.RESET}")
        return 1

    if json_output:
        runtime = None
        if args.include_runtime:
            runtime = _collect_runtime(
                session, home, _is_session_running(home, str(session.session_id or ""))
            )
        print(_format_session_json(session, home, runtime))
    else:
        color_enabled = _supports_color()
        print(_format_session(session, home, color_enabled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
