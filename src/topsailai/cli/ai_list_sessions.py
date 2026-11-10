#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
List Sessions CLI - List sessions from the session database

This module provides command-line functionality to list sessions
stored in the database, displaying session ID, name, creation time,
and task information in a human-readable card format.

Usage:
    ai_list_sessions.py [sessions ...] [options]

Arguments:
    sessions: Optional session IDs to include. Multiple IDs can be provided
              as positional arguments.

Options:
    --db-conn: Database connection string. Defaults to 'sqlite:///sessions.db'
    --category: Exact category to include; one value of lowercase letters,
                digits, and underscores, or an empty value for uncategorized.
    --excluded-categories: Comma-separated categories to exclude; repeatable.

Examples:
    ai_list_sessions.py
    ai_list_sessions.py --db-conn sqlite:///custom.db
    ai_list_sessions.py s1 s2 s3 --json
    ai_list_sessions.py --limit 10 --sort desc
    ai_list_sessions.py --since 2026-07-28T00:00:00 --until 2026-07-28T23:59:59
    ai_list_sessions.py --db-conn sqlite:///custom.db s1 s2 --json
    ai_list_sessions.py --excluded-categories agent_driver,agent

Author: DawsonLin
Email: lin_dongsen@126.com
"""

import argparse
import json
import os
import re
import shutil
import sys
import textwrap
from datetime import datetime

import _import_topsailai

os.chdir(_import_topsailai.PROJECT_FOLDER_BASE)

from topsailai.context.ctx_manager import get_session_manager
from topsailai.context.session_category import resolve_session_category


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


def _cache_hit_rate(cached_tokens, total_tokens):
    """Return the cache hit rate as a percentage string.

    The cache hit rate is computed as ``cached_tokens / total_tokens``.
    Returns an empty string when *total_tokens* is zero to avoid a
    division-by-zero error.
    """
    if not total_tokens:
        return ""
    return f"{cached_tokens / total_tokens * 100:.1f}%"

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

    category = str(getattr(session, "category", "") or "")
    task = str(session.task) if session.task else ""
    project_workspace = str(session.project_workspace) if session.project_workspace else ""
    pwd = str(session.pwd) if session.pwd else ""
    topsailai_home = str(session.topsailai_home) if session.topsailai_home else ""
    total_prompt_tokens = int(
        getattr(session, "total_prompt_tokens", getattr(session, "total_tokens", 0)) or 0
    )
    total_completion_tokens = int(getattr(session, "total_completion_tokens", 0) or 0)
    total_usage_tokens = total_prompt_tokens + total_completion_tokens
    total_cached_tokens = int(getattr(session, "total_cached_tokens", 0) or 0)

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

    category_label = _color("Category:".ljust(label_width), yellow, color_enabled)
    lines.append(f"{indent}{category_label} {category or "(none)"}")

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

    prompt_tokens_label = _color("Prompt Tokens:".ljust(label_width), yellow, color_enabled)
    lines.append(f"{indent}{prompt_tokens_label} {total_prompt_tokens}")

    completion_tokens_label = _color("Completion Tokens:".ljust(label_width), yellow, color_enabled)
    lines.append(f"{indent}{completion_tokens_label} {total_completion_tokens}")

    usage_tokens_label = _color("Usage Tokens:".ljust(label_width), yellow, color_enabled)
    lines.append(f"{indent}{usage_tokens_label} {total_usage_tokens}")

    cached_tokens_label = _color("Cached Prompt Tokens:".ljust(label_width), yellow, color_enabled)
    lines.append(f"{indent}{cached_tokens_label} {total_cached_tokens}")

    cache_hit_label = _color("Cache Hit Rate:".ljust(label_width), yellow, color_enabled)
    lines.append(f"{indent}{cache_hit_label} {_cache_hit_rate(total_cached_tokens, total_prompt_tokens)}")

    if topsailai_home:
        home_label = _color("Home:".ljust(label_width), yellow, color_enabled)
        lines.append(f"{indent}{home_label} {topsailai_home}")

    return "\n".join(lines)


def format_sessions(sessions, matched_count=None):
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
        matched_count (int, optional): Number of rows matching every selection
            filter before pagination. When no sessions are displayed, it is still
            shown when supplied for an explicit filter.

    Returns:
        str: Formatted string containing all sessions in card format.
             Returns "No sessions found." for an unfiltered empty result.
    """
    if not sessions:
        if matched_count is None:
            return "No sessions found."
        return f"No sessions found.\nMatched Total: {matched_count}"

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
    if matched_count is not None:
        output.append(f"Matched Total: {matched_count}")

    return "\n".join(output)


def _session_to_dict(session):
    """Convert a session object to a plain dictionary for JSON output."""
    total_prompt_tokens = int(
        getattr(session, "total_prompt_tokens", getattr(session, "total_tokens", 0)) or 0
    )
    total_completion_tokens = int(getattr(session, "total_completion_tokens", 0) or 0)
    total_cached_tokens = int(getattr(session, "total_cached_tokens", 0) or 0)
    return {
        "session_id": str(session.session_id) if session.session_id else "",
        "session_name": str(session.session_name) if session.session_name else "",
        "category": str(getattr(session, "category", "") or ""),
        "create_time": session.create_time.strftime("%Y-%m-%dT%H:%M:%S") if session.create_time else "",
        "task": str(session.task) if session.task else "",
        "project_workspace": str(session.project_workspace) if session.project_workspace else "",
        "pwd": str(session.pwd) if session.pwd else "",
        "topsailai_home": str(session.topsailai_home) if session.topsailai_home else "",
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_usage_tokens": total_prompt_tokens + total_completion_tokens,
        "total_cached_tokens": total_cached_tokens,
        "cache_hit_rate": _cache_hit_rate(total_cached_tokens, total_prompt_tokens),
    }


def format_sessions_json(sessions):
    """
    Format session data as a JSON array.

    Args:
        sessions (list): List of session objects.

    Returns:
        str: JSON array string containing session dictionaries.
    """
    return json.dumps([_session_to_dict(session) for session in sessions], indent=2, ensure_ascii=False)


def _parse_order_by(sort_order):
    """Convert legacy --sort value to backend order_by string."""
    if sort_order == "desc":
        return "-create_time"
    return "create_time"


def _parse_datetime(value):
    """Parse an ISO datetime string into a datetime object."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _parse_sessions(positional_sessions):
    """Parse positional session IDs into a list of strings."""
    if not positional_sessions:
        return None
    return [session_id.strip() for session_id in positional_sessions if session_id.strip()]


def _parse_excluded_categories(raw_values):
    """Parse repeated comma-separated exclusion values into a normalized set.

    An exactly empty value is meaningful: it excludes uncategorized sessions.
    Any other value must pass the same validation as the inclusion filter, and
    an invalid name is rejected instead of being resolved to the empty
    category, because silently excluding uncategorized rows would hide data the
    caller never asked to hide. Returns an empty set when no exclusion was
    requested, which keeps the unfiltered query path unchanged.
    """
    if not raw_values:
        return set()

    excluded = set()
    for raw_value in raw_values:
        for name in raw_value.split(","):
            if name == "":
                excluded.add("")
                continue
            normalized = resolve_session_category(name)
            if normalized != name:
                raise ValueError(f"Invalid excluded category: {name!r}")
            excluded.add(normalized)
    return excluded


def _parse_included_categories(raw_values):
    """Parse repeated comma-separated inclusion values into a normalized set.

    An exactly empty value is meaningful: it includes uncategorized sessions.
    Any other value must pass the same validation as the exclusion filter, and
    an invalid name is rejected instead of being resolved to the empty
    category, because silently including uncategorized rows would expose data
    the caller never asked to see. Returns an empty set when no inclusion was
    requested, which keeps the unfiltered query path unchanged.
    """
    if not raw_values:
        return set()

    included = set()
    for raw_value in raw_values:
        for name in raw_value.split(","):
            if name == "":
                included.add("")
                continue
            normalized = resolve_session_category(name)
            if normalized != name:
                raise ValueError(f"Invalid included category: {name!r}")
            included.add(normalized)
    return included


_CATEGORY_PATTERN = re.compile(r"[a-z0-9_]+")


def _parse_category_value(raw_value):
    """Validate one --category value and return it unchanged.

    The value must be exactly empty, which selects uncategorized sessions, or
    match lowercase letters, digits, and underscores. Anything else is rejected
    instead of being resolved to the empty category, because resolving it would
    silently select uncategorized rows the caller never asked for.
    """
    if raw_value == "":
        return ""
    if _CATEGORY_PATTERN.fullmatch(raw_value):
        return raw_value
    raise argparse.ArgumentTypeError(
        f"invalid category {raw_value!r}: expected lowercase letters, digits, or underscores"
    )


class _SingleCategory(argparse.Action):
    """Reject a repeated --category option instead of silently keeping the last."""

    def __call__(self, parser, namespace, values, option_string=None):
        """Store the first value and fail on any second occurrence."""
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(self, "may only be given once")
        setattr(namespace, self.dest, values)


def main():
    """
    Main entry point for listing sessions.

    This function:
    1. Parses command-line arguments for database connection and query options
    2. Creates a session manager with the specified database connection
    3. Retrieves sessions from the database using backend filtering/sorting/pagination
    4. Displays the sessions in a formatted card layout or JSON

    Default Behavior:
        - If no --db-conn provided, uses 'sqlite:///sessions.db'

    Returns:
        None

    Raises:
        SystemExit: Exits with code 1 if error occurs during retrieval
    """
    parser = argparse.ArgumentParser(
        description="List sessions from the session database."
    )
    parser.add_argument(
        "sessions",
        nargs="*",
        help="Session IDs to include as positional arguments",
    )
    parser.add_argument(
        "--db-conn",
        type=str,
        default=None,
        help="Database connection string (default: sqlite:///sessions.db)",
    )
    parser.add_argument(
        "--category",
        dest="session_category",
        type=_parse_category_value,
        action=_SingleCategory,
        default=None,
        help=(
            "Filter by exact category; omit to include all categories, use an empty "
            "value for uncategorized sessions. Accepts one value made of lowercase "
            "letters, digits, and underscores"
        ),
    )
    parser.add_argument(
        "--included-categories",
        dest="included_categories",
        action="append",
        default=None,
        metavar="NAMES",
        help=(
            "Include only sessions whose category is listed; accepts comma-separated "
            "names and may be repeated. An empty value includes uncategorized "
            "sessions. Applied in the database, so pagination stays correct"
        ),
    )
    parser.add_argument(
        "--excluded-categories",
        dest="excluded_categories",
        action="append",
        default=None,
        metavar="NAMES",
        help=(
            "Exclude sessions whose category is listed; accepts comma-separated "
            "names and may be repeated. An empty value excludes uncategorized "
            "sessions. Applied in the database, so pagination stays correct"
        ),
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
        "--offset",
        type=int,
        default=0,
        help="Skip the first N sessions (default: 0)",
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
    parser.add_argument(
        "--order-by",
        type=str,
        default=None,
        help="Sort by field name; prefix with '-' for descending (e.g., '-create_time')",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Include sessions created at or after this ISO datetime (e.g., 2026-07-28T00:00:00)",
    )
    parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Include sessions created at or before this ISO datetime (e.g., 2026-07-28T23:59:59)",
    )
    args = parser.parse_args()

    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    try:
        manager = get_session_manager(args.db_conn)

        order_by = args.order_by
        if order_by is None:
            order_by = _parse_order_by(args.sort)

        query_sessions = _parse_sessions(args.sessions)
        normalized_category = args.session_category
        included_categories = _parse_included_categories(args.included_categories)
        excluded_categories = _parse_excluded_categories(args.excluded_categories)
        since = _parse_datetime(args.since)
        until = _parse_datetime(args.until)
        # Every selection predicate runs in the database, so the page is chosen
        # after filtering and a limit always returns a full page of surviving rows.
        list_kwargs = {
            "sessions": query_sessions,
            "order_by": order_by,
            "offset": args.offset,
            "limit": args.limit,
        }
        count_kwargs = {"sessions": query_sessions}
        if normalized_category is not None:
            list_kwargs["category"] = normalized_category
            count_kwargs["category"] = normalized_category
        if included_categories:
            list_kwargs["included_categories"] = included_categories
            count_kwargs["included_categories"] = included_categories
        if excluded_categories:
            list_kwargs["excluded_categories"] = excluded_categories
            count_kwargs["excluded_categories"] = excluded_categories
        if args.has_project:
            list_kwargs["has_project"] = True
            count_kwargs["has_project"] = True
        if since is not None:
            list_kwargs["since"] = since
            count_kwargs["since"] = since
        if until is not None:
            list_kwargs["until"] = until
            count_kwargs["until"] = until
        sessions = manager.list_sessions(**list_kwargs)
        matched_count = None
        if len(count_kwargs) > 1:
            matched_count = manager.count_sessions(**count_kwargs)

        if args.json:
            print(format_sessions_json(sessions))
        else:
            formatted_output = format_sessions(sessions, matched_count=matched_count)
            print(formatted_output)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
