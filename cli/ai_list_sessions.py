#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
List Sessions CLI - List all sessions from the session database

This module provides command-line functionality to list all sessions
stored in the database, displaying session ID, name, creation time,
and task information in a human-readable card format.

Usage:
    ai_list_sessions.py [database_connection_string]

Arguments:
    database_connection_string: Optional database connection string.
                                Defaults to 'sqlite:///sessions.db'

Examples:
    ai_list_sessions.py
    ai_list_sessions.py sqlite:///custom.db

Author: DawsonLin
Email: lin_dongsen@126.com
"""

import argparse
import json
import os
import shutil
import sys
import textwrap
from datetime import datetime

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.context.ctx_manager import get_session_manager


def _supports_color():
    """Return True if the output stream supports ANSI color codes."""
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def _color(text, color_code, enabled):
    """Wrap text with ANSI color codes when enabled."""
    if not enabled:
        return text
    return f"{color_code}{text}\033[0m"


def _relative_time(create_time):
    """Return a human-readable relative time string for *create_time*."""
    if not create_time:
        return ""

    now = datetime.now()
    diff = now - create_time
    seconds = int(diff.total_seconds())

    if seconds < 0:
        return "in the future"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = months // 12
    return f"{years} year{'s' if years != 1 else ''} ago"


def _format_session(session, index, total_width, color_enabled):
    """Format a single session as a card-style block."""
    cyan = "\033[36m"
    yellow = "\033[33m"
    green = "\033[32m"
    gray = "\033[90m"

    session_id = str(session.session_id) if session.session_id else ""
    name = str(session.session_name) if session.session_name else "(unnamed)"
    created = ""
    relative = ""
    if session.create_time:
        created = session.create_time.strftime("%Y-%m-%dT%H:%M:%S")
        relative = _relative_time(session.create_time)

    task = str(session.task) if session.task else ""
    project_workspace = str(session.project_workspace) if session.project_workspace else ""
    pwd = str(session.pwd) if session.pwd else ""
    topsailai_home = str(session.topsailai_home) if session.topsailai_home else ""

    lines = []
    header = f"[{index}] {session_id}"
    if created:
        time_value = created
        if relative:
            time_value = f"{created} ({_color(relative, green, color_enabled)})"
        header = f"{header}  {time_value}"
    lines.append(_color(header, cyan, color_enabled))

    label_width = 16
    indent = "  "
    value_prefix = indent + " " * (label_width + 1)

    name_label = _color("Name:".ljust(label_width), yellow, color_enabled)
    lines.append(f"{indent}{name_label} {name}")

    task_label = _color("Task:".ljust(label_width), yellow, color_enabled)
    wrap_width = max(total_width - len(value_prefix), 20)

    if task:
        wrapped = textwrap.wrap(task, width=wrap_width)
        if wrapped:
            lines.append(f"{indent}{task_label} {wrapped[0]}")
            for continuation in wrapped[1:]:
                lines.append(f"{value_prefix}{continuation}")
    else:
        lines.append(f"{indent}{task_label} {_color('(no task)', gray, color_enabled)}")

    if project_workspace:
        workspace_label = _color("Project:".ljust(label_width), yellow, color_enabled)
        lines.append(f"{indent}{workspace_label} {project_workspace}")

    if pwd:
        pwd_label = _color("PWD:".ljust(label_width), yellow, color_enabled)
        lines.append(f"{indent}{pwd_label} {pwd}")

    if topsailai_home:
        home_label = _color("Home:".ljust(label_width), yellow, color_enabled)
        lines.append(f"{indent}{home_label} {topsailai_home}")

    return "\n".join(lines)


def format_sessions(sessions):
    """
    Format session data for display in a human-readable card format.

    Each session is rendered as a card with clear separators between records.
    Long task descriptions are wrapped to fit the terminal width.

    Args:
        sessions (list): List of session objects with attributes:
                        - session_id: Unique identifier for the session
                        - session_name: Optional name of the session
                        - create_time: datetime object representing creation time
                        - task: Task description string
                        - project_workspace: Project workspace path
                        - pwd: Working directory
                        - topsailai_home: TopsailAI home directory

    Returns:
        str: Formatted string containing all sessions in card format.
             Returns "No sessions found." if sessions list is empty.
    """
    if not sessions:
        return "No sessions found."

    color_enabled = _supports_color()
    total_width = shutil.get_terminal_size().columns
    if total_width < 40:
        total_width = 80

    separator = "=" * total_width
    record_separator = "-" * total_width

    output = []
    output.append(separator)
    title = f" Sessions (Total: {len(sessions)}) "
    output.append(title.center(total_width))
    output.append(separator)
    output.append("")

    for idx, session in enumerate(sessions, start=1):
        output.append(_format_session(session, idx, total_width, color_enabled))
        if idx < len(sessions):
            output.append("")
            output.append(record_separator)
            output.append("")

    output.append("")
    output.append(separator)
    output.append(f"Total: {len(sessions)} session{'s' if len(sessions) != 1 else ''}")

    return "\n".join(output)


def _session_to_dict(session):
    """Convert a session object to a plain dictionary for JSON output."""
    return {
        "session_id": str(session.session_id) if session.session_id else "",
        "session_name": str(session.session_name) if session.session_name else "",
        "create_time": session.create_time.strftime("%Y-%m-%dT%H:%M:%S") if session.create_time else "",
        "task": str(session.task) if session.task else "",
        "project_workspace": str(session.project_workspace) if session.project_workspace else "",
        "pwd": str(session.pwd) if session.pwd else "",
        "topsailai_home": str(session.topsailai_home) if session.topsailai_home else "",
    }


def format_sessions_json(sessions):
    """
    Format session data as a JSON array.

    Args:
        sessions (list): List of session objects.

    Returns:
        str: JSON array string containing session dictionaries.
    """
    return json.dumps([_session_to_dict(session) for session in sessions], indent=2)


def _sort_sessions(sessions, sort_order):
    """Sort sessions by create_time in ascending or descending order."""
    reverse = sort_order == "desc"
    return sorted(sessions, key=lambda session: session.create_time or datetime.min, reverse=reverse)


def _filter_sessions(sessions, has_project):
    """Filter sessions to only those with a non-empty project_workspace when requested."""
    if not has_project:
        return sessions
    return [session for session in sessions if session.project_workspace]


def _limit_sessions(sessions, limit):
    """Limit the number of sessions returned."""
    if limit is None or limit <= 0:
        return sessions
    return sessions[:limit]


def main():
    """
    Main entry point for listing sessions.

    This function:
    1. Parses command-line arguments for database connection
    2. Creates a session manager with the specified database connection
    3. Retrieves all sessions from the database
    4. Displays the sessions in a formatted card layout

    Default Behavior:
        - If no database_connection_string provided, uses 'sqlite:///sessions.db'

    Returns:
        None

    Raises:
        SystemExit: Exits with code 1 if error occurs during retrieval
    """
    parser = argparse.ArgumentParser(
        description="List all sessions from the session database."
    )
    parser.add_argument(
        "db_conn",
        nargs="?",
        default=None,
        help="Optional database connection string (default: sqlite:///sessions.db)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output sessions as JSON instead of human-readable cards",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Return at most N sessions",
    )
    parser.add_argument(
        "--has-project",
        action="store_true",
        help="Only include sessions with a non-empty project_workspace",
    )
    parser.add_argument(
        "--sort",
        choices=["asc", "desc"],
        default="asc",
        help="Sort by create_time (default: asc, oldest first)",
    )
    args = parser.parse_args()

    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    try:
        manager = get_session_manager(args.db_conn)
        sessions = manager.list_sessions()
        sessions = _sort_sessions(sessions, args.sort)
        sessions = _filter_sessions(sessions, args.has_project)
        sessions = _limit_sessions(sessions, args.limit)

        if args.json:
            print(format_sessions_json(sessions))
        else:
            formatted_output = format_sessions(sessions)
            print(formatted_output)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
