"""Shared session-detail renderers and parsers.

``topsailai_session_info`` and ``topsailai_sessions_info`` render the same card
and the same JSON record, and ``topsailai runtime info`` prints the same failure
object.  The build compiles a top-level script into a standalone executable, so
one script can never import another script; the shared code therefore lives in
this package module, which is compiled to an importable extension.

Author: DawsonLin
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import textwrap
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from cli_topsailai.colors import Colors, colored
from cli_topsailai.process_liveness import session_liveness
from cli_topsailai.session_metrics import METRIC_FIELDS, session_metrics

if TYPE_CHECKING:
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


def _is_session_running(home: str, session_id: str) -> bool:
    """Return True if *session_id* has a live session process.

    Every stdout candidate is inspected, because a newer dead file must not
    hide an older live process for the same session. An unverifiable answer is
    reported as not running, which is the display policy for this command.
    """
    return session_liveness(session_id, home=home) == "live"


def _session_to_dict(
    session: SessionData,
    home: str,
    running: Optional[bool] = None,
    runtime: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Convert a SessionData object into a JSON-serializable dictionary.

    The returned dictionary contains every field stored on *session* plus
    computed metadata such as running status and human-readable timestamps.

    *running* lets a batch caller inject a status it already resolved with one
    directory scan; when it is ``None`` the status is resolved here, which is
    the single-session behaviour.

    *runtime* is the collected runtime record, or ``None`` when runtime data was
    not requested or the session is not running. The key is always present so
    the record shape never changes between invocations, which lets a consumer
    tell "not requested" from "requested but unavailable".
    """
    session_id = str(session.session_id) if session.session_id else ""
    if running is None:
        running = _is_session_running(home, session_id)
    create_time_str = ""
    if session.create_time:
        create_time_str = session.create_time.strftime("%Y-%m-%d %H:%M:%S")
    total_prompt_tokens = int(
        getattr(session, "total_prompt_tokens", getattr(session, "total_tokens", 0)) or 0
    )
    total_completion_tokens = int(getattr(session, "total_completion_tokens", 0) or 0)
    total_usage_tokens = total_prompt_tokens + total_completion_tokens
    total_cached_tokens = int(getattr(session, "total_cached_tokens", 0) or 0)

    return {
        # Original SessionData fields
        "session_id": session_id,
        "session_name": str(session.session_name) if session.session_name else "",
        "category": str(getattr(session, "category", "") or ""),
        "task": str(session.task) if session.task else "",
        "project_workspace": str(session.project_workspace) if session.project_workspace else "",
        "pwd": str(session.pwd) if session.pwd else "",
        "topsailai_home": str(session.topsailai_home) if session.topsailai_home else "",
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_usage_tokens": total_usage_tokens,
        "total_cached_tokens": total_cached_tokens,
        # Every execution metric, emitted without suppression.
        **session_metrics(session),
        "create_time": create_time_str,
        # Computed metadata
        "status": "Running" if running else "Idle",
        "is_running": running,
        "create_time_relative": _relative_time(session.create_time),
        # Optional enrichment, always present so the record shape is stable.
        "runtime": runtime,
    }


def _format_session_json(
    session: SessionData,
    home: str,
    runtime: Optional[dict[str, Any]] = None,
) -> str:
    """Format a single session as a JSON string."""
    data = _session_to_dict(session, home, runtime=runtime)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _collect_runtime(
    session: SessionData, home: str, running: bool
) -> Optional[dict[str, Any]]:
    """Collect runtime data for a running session, or return ``None``.

    Runtime data is fetched only when the session is running, because an idle
    session has no process to answer and probing one would report a failure for
    a state that is not a failure. Collection is best effort: any failure here
    leaves ``runtime`` null instead of breaking the record the caller asked for,
    matching the workspace list contract.
    """
    if not running:
        return None
    session_id = str(session.session_id) if session.session_id else ""
    try:
        from cli_topsailai.process_liveness import live_session_pid
        from cli_topsailai.workspace_runtime import collect_session_runtime

        pid = live_session_pid(session_id, home=home)
        if pid is None:
            return None
        task_dir = os.path.join(home, TASK_SUBDIR)
        return collect_session_runtime(session_id, pid, task_dir)
    except Exception:
        return None


def _format_failure_json(session_id: str, error_code: str, message: str) -> str:
    """Format a failed lookup as one JSON object.

    Only identity and failure facts are reported, because a session that was
    never found has no name, task, or token totals to report. Inventing empty
    session fields would make a failure indistinguishable from a real session
    whose fields happen to be empty, so a consumer decides on ``error_code``.
    """
    payload = {
        "session_id": session_id,
        "error_code": error_code,
        "message": message,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _format_session(
    session: SessionData,
    home: str,
    color_enabled: bool,
    running: Optional[bool] = None,
) -> str:
    """Format a single session as a detailed card.

    *running* lets a batch caller inject a status it already resolved with one
    directory scan; when it is ``None`` the status is resolved here, which is
    the single-session behaviour.
    """
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
    if running is None:
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
    add_row("Category", str(getattr(session, "category", "") or "") or "(none)")

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
    total_prompt_tokens = int(
        getattr(session, "total_prompt_tokens", getattr(session, "total_tokens", 0)) or 0
    )
    total_completion_tokens = int(getattr(session, "total_completion_tokens", 0) or 0)
    add_row("Prompt Tokens", str(total_prompt_tokens))
    add_row("Completion Tokens", str(total_completion_tokens))
    add_row("Total Usage Tokens", str(total_prompt_tokens + total_completion_tokens))
    add_row("Cached Prompt Tokens", str(getattr(session, "total_cached_tokens", 0) or 0))

    # Every execution metric, rendered from the shared field list so this card
    # and the JSON payload can never disagree about which metrics exist.
    metrics = session_metrics(session)
    lines.append("")
    for name, _attribute, _default in METRIC_FIELDS:
        add_row(name, str(metrics[name]))
    add_row("first_byte_avg_ms", str(metrics["first_byte_avg_ms"]))
    add_row("model_name", metrics["model_name"] or "(none)")

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
