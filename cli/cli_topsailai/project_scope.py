"""Project scope support for the TopsailAI CLI.

This module builds the list of recent sessions that have a project workspace
by invoking ``ai_list_sessions.py`` with JSON output, and renders the list as
a table compatible with the interactive selection loop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from typing import Any, Dict, Optional

from cli_topsailai.colors import Colors


def _script_path() -> str:
    """Return the absolute path to ``ai_list_sessions.py``."""
    module_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(module_dir)
    return os.path.join(project_root, "ai_list_sessions.py")


def _format_create_time(create_time: str) -> str:
    """Format an ISO create_time string for the project table."""
    if not create_time:
        return "-"
    try:
        dt = datetime.fromisoformat(create_time)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return create_time


def build_project_list(limit: int = 10) -> List[Dict[str, Any]]:
    """Build the list of recent sessions with a project workspace.

    Runs ``ai_list_sessions.py --json --has-project --sort desc --limit N`` and
    parses the JSON output.  Sessions are returned in descending chronological
    order (newest first) so the most recent entry appears at the top of the
    project scope table.

    Args:
        limit: Maximum number of sessions to return (default 10).

    Returns:
        List of session dictionaries with keys ``no``, ``session_id``,
        ``session_name``, ``project_workspace``, ``create_time``,
        ``create_time_raw``, and ``task``.
    """
    script = _script_path()
    cmd = [
        sys.executable,
        script,
        "--json",
        "--has-project",
        "--sort",
        "desc",
        "--limit",
        str(limit),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        print(
            f"{Colors.RED}[ERROR] Failed to run ai_list_sessions.py: {exc}{Colors.RESET}"
        )
        return []

    if result.returncode != 0:
        stderr = result.stderr.strip()
        print(
            f"{Colors.RED}[ERROR] ai_list_sessions.py failed: {stderr}{Colors.RESET}"
        )
        return []

    stdout = result.stdout.strip()
    if not stdout:
        return []

    try:
        sessions = json.loads(stdout)
    except json.JSONDecodeError as exc:
        print(
            f"{Colors.RED}[ERROR] Failed to parse session JSON: {exc}{Colors.RESET}"
        )
        return []

    if not isinstance(sessions, list):
        print(
            f"{Colors.RED}[ERROR] Unexpected session JSON shape: expected list{Colors.RESET}"
        )
        return []

    entries = []
    for idx, session in enumerate(sessions, start=1):
        create_time_raw = session.get("create_time") or ""
        entries.append(
            {
                "no": idx,
                "session_id": session.get("session_id") or "",
                "session_name": session.get("session_name") or "",
                "project_workspace": session.get("project_workspace") or "",
                "create_time": _format_create_time(create_time_raw),
                "create_time_raw": create_time_raw,
                "task": session.get("task") or "",
            }
        )
    return entries


def print_project_table(entries: List[Dict[str, Any]]) -> None:
    """Print a table of recent project workspaces."""
    if not entries:
        print(
            f"\n{Colors.YELLOW}[WARN] No sessions with project_workspace found.{Colors.RESET}"
        )
        return

    w_no = 4
    w_session = 24
    w_project = 36
    w_created = 14
    w_name = 20

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {'No':^{w_no}} |"
        f" {'Session ID':^{w_session}} |"
        f" {'Project Workspace':^{w_project}} |"
        f" {'Created':^{w_created}} |"
        f" {'Session Name':^{w_name}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_session + 2)}+"
        f"{'-' * (w_project + 2)}+"
        f"{'-' * (w_created + 2)}+"
        f"{'-' * (w_name + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for entry in entries:
        session_id = entry.get("session_id") or "-"
        if len(session_id) > w_session:
            session_id = session_id[: w_session - 3] + "..."

        project = entry.get("project_workspace") or "-"
        if len(project) > w_project:
            project = project[: w_project - 3] + "..."

        created = entry.get("create_time") or "-"
        session_name = entry.get("session_name") or "-"
        if len(session_name) > w_name:
            session_name = session_name[: w_name - 3] + "..."

        row = (
            f"{Colors.GRAY}"
            f" {entry['no']:^{w_no}} |"
            f" {session_id:<{w_session}} |"
            f" {project:<{w_project}} |"
            f" {created:^{w_created}} |"
            f" {session_name:<{w_name}} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)
    print(
        f"{Colors.DIM}(Total: {len(entries)} project session"
        f"{'s' if len(entries) != 1 else ''}){Colors.RESET}"
    )


def refresh_project_list(
    entries: List[Dict[str, Any]], limit: int = 10
) -> List[Dict[str, Any]]:
    """Reload the project session list.

    Args:
        entries: Previous list (unused, kept for API symmetry).
        limit: Maximum number of sessions to return.

    Returns:
        Fresh list from :func:`build_project_list`.
    """
    return build_project_list(limit=limit)
