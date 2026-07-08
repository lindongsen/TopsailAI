#!/usr/bin/env python3
"""Display detailed information about a single session.

Queries the session storage for the given *session_id* and prints the
session metadata (ID, name, task, creation time, and running status).
The running status is determined by looking for a live
``{session_id}.{pid}.session.stdout`` file under ``workspace/task/`` in
TOPSAILAI_HOME.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import textwrap
from datetime import datetime
from typing import Any, Optional

from cli_topsailai.colors import Colors, colored
from cli_topsailai.paths import get_topsailai_home

# Add project root to path so that ``src/topsailai`` modules are importable.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root + "/src")

from topsailai.context.ctx_manager import get_session_manager
from topsailai.context.session_manager import SessionData

TASK_SUBDIR = "workspace/task"


def _supports_color() -> bool:
    """Return True if the output stream supports ANSI color codes."""
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def _relative_time(create_time: Optional[datetime]) -> str:
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


def _is_pid_alive(pid: int) -> bool:
    """Return True if *pid* is currently running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _parse_session_stdout_filename(filename: str) -> tuple[Optional[str], Optional[int]]:
    """Parse a ``*.session.stdout`` filename into (session_id, pid)."""
    if not filename.endswith(".session.stdout"):
        return None, None
    base = filename[: -len(".session.stdout")]
    if not base:
        return None, None

    parts = base.split(".")
    if len(parts) == 2 and parts[0] == "topsailai":
        try:
            return "topsailai", int(parts[1])
        except ValueError:
            return None, None

    try:
        pid = int(parts[-1])
    except ValueError:
        return None, None
    session_id = ".".join(parts[:-1])
    return session_id, pid


def _find_session_pid(home: str, session_id: str) -> Optional[int]:
    """Return the PID from the most recent stdout file for *session_id*."""
    task_dir = os.path.join(home, TASK_SUBDIR)
    if not os.path.isdir(task_dir):
        return None

    candidates = []
    for entry in os.listdir(task_dir):
        if not entry.endswith(".session.stdout"):
            continue
        full_path = os.path.join(task_dir, entry)
        if not os.path.isfile(full_path):
            continue
        sid, pid = _parse_session_stdout_filename(entry)
        if sid != session_id or pid is None:
            continue
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            continue
        candidates.append((mtime, pid))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _is_session_running(home: str, session_id: str) -> bool:
    """Return True if *session_id* has a live session process."""
    pid = _find_session_pid(home, session_id)
    if pid is None:
        return False
    return _is_pid_alive(pid)


def _session_to_dict(session: SessionData, home: str) -> dict[str, Any]:
    """Convert a SessionData object into a JSON-serializable dictionary.

    The returned dictionary contains every field stored on *session* plus
    computed metadata such as running status and human-readable timestamps.
    """
    session_id = str(session.session_id) if session.session_id else ""
    running = _is_session_running(home, session_id)
    create_time_str = ""
    if session.create_time:
        create_time_str = session.create_time.strftime("%Y-%m-%d %H:%M:%S")

    return {
        # Original SessionData fields
        "session_id": session_id,
        "session_name": str(session.session_name) if session.session_name else "",
        "task": str(session.task) if session.task else "",
        "project_workspace": str(session.project_workspace) if session.project_workspace else "",
        "pwd": str(session.pwd) if session.pwd else "",
        "topsailai_home": str(session.topsailai_home) if session.topsailai_home else "",
        "create_time": create_time_str,
        # Computed metadata
        "status": "Running" if running else "Idle",
        "is_running": running,
        "create_time_relative": _relative_time(session.create_time),
    }


def _format_session_json(session: SessionData, home: str) -> str:
    """Format a single session as a JSON string."""
    data = _session_to_dict(session, home)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _format_session(session: SessionData, home: str, color_enabled: bool) -> str:
    """Format a single session as a detailed card."""
    total_width = shutil.get_terminal_size().columns
    if total_width < 40:
        total_width = 80

    separator = "=" * total_width

    session_id = str(session.session_id) if session.session_id else ""
    name = str(session.session_name) if session.session_name else "(unnamed)"
    created = ""
    relative = ""
    if session.create_time:
        created = session.create_time.strftime("%Y-%m-%d %H:%M:%S")
        relative = _relative_time(session.create_time)

    task = str(session.task) if session.task else ""
    running = _is_session_running(home, session_id)
    status = "Running" if running else "Idle"
    status_color = Colors.GREEN if running else Colors.GRAY

    lines = []
    lines.append(separator)
    title = " Session Information "
    lines.append(title.center(total_width))
    lines.append(separator)
    lines.append("")

    label_width = 18
    indent = "  "
    value_prefix = indent + " " * (label_width + 1)

    def add_row(label: str, value: str, value_color: str = "") -> None:
        label_text = f"{label}:".ljust(label_width)
        if color_enabled:
            label_text = colored(label_text, Colors.YELLOW)
        if value_color and color_enabled:
            value = colored(value, value_color)
        lines.append(f"{indent}{label_text} {value}")

    add_row("Session ID", session_id)
    add_row("Name", name)

    time_value = created
    if relative:
        relative_text = relative
        if color_enabled:
            relative_text = colored(relative, Colors.GREEN)
        time_value = f"{created} ({relative_text})"
    add_row("Created", time_value)

    add_row("Status", status, status_color)
    add_row("Project Workspace", str(session.project_workspace) if session.project_workspace else "(none)")
    add_row("PWD", str(session.pwd) if session.pwd else "(none)")
    add_row("TOPSAILAI_HOME", str(session.topsailai_home) if session.topsailai_home else "(none)")

    task_label = "Task"
    task_label_text = f"{task_label}:".ljust(label_width)
    if color_enabled:
        task_label_text = colored(task_label_text, Colors.YELLOW)

    wrap_width = max(total_width - len(value_prefix), 20)
    if task:
        wrapped = textwrap.wrap(task, width=wrap_width)
        if wrapped:
            lines.append(f"{indent}{task_label_text} {wrapped[0]}")
            for continuation in wrapped[1:]:
                lines.append(f"{value_prefix}{continuation}")
    else:
        no_task = "(no task)"
        if color_enabled:
            no_task = colored(no_task, Colors.GRAY)
        lines.append(f"{indent}{task_label_text} {no_task}")

    lines.append("")
    lines.append(separator)

    return "\n".join(lines)


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
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for ``topsailai_session_info``."""
    args = _parse_args(argv)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    home = args.home
    if home is None:
        home = get_topsailai_home()

    try:
        manager = get_session_manager(args.db_conn)
        session = manager.get_session(args.session_id)
    except Exception as e:
        print(f"{Colors.RED}[ERROR] {e}{Colors.RESET}")
        return 1

    if session is None:
        print(
            f"{Colors.YELLOW}[INFO] Session not found: {args.session_id}{Colors.RESET}"
        )
        return 1

    if args.json:
        print(_format_session_json(session, home))
    else:
        color_enabled = _supports_color()
        print(_format_session(session, home, color_enabled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
