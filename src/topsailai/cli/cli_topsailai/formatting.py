"""Output formatting helpers for the TopsailAI CLI."""

import io
import os
import sys
from contextlib import redirect_stdout as contextlib_redirect_stdout
from datetime import datetime
from typing import List

from cli_topsailai.colors import Colors
from cli_topsailai.log_files import _display_session_id


def format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}K"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}M"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f}G"


def format_timestamp(ts: float) -> str:
    """Format a Unix timestamp to a short month-day hour:minute string."""
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%m-%d %H:%M")


def format_timestamp_full(ts: float) -> str:
    """Format a Unix timestamp to a full date-time string."""
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def print_header(title: str) -> None:
    """Print a bold cyan header with the given title."""
    width = 80
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}")


def print_table(files: List[dict]) -> None:
    """Print a table of discovered .stdout log files."""
    if not files:
        print(f"{Colors.YELLOW}[WARN] No log files found.{Colors.RESET}")
        return

    w_no = 4
    w_session = 18
    w_pid = 6
    w_created = 13
    w_project = 24
    w_name = 16

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {'No':^{w_no}} |"
        f" {'Session ID':^{w_session}} |"
        f" {'PID':^{w_pid}} |"
        f" {'Created':^{w_created}} |"
        f" {'Project Workspace':^{w_project}} |"
        f" {'Session Name':^{w_name}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_session + 2)}+"
        f"{'-' * (w_pid + 2)}+"
        f"{'-' * (w_created + 2)}+"
        f"{'-' * (w_project + 2)}+"
        f"{'-' * (w_name + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for idx, f in enumerate(files, start=1):
        pid = f.get("pid")
        if pid is not None:
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError, OSError):
                pid = None
        f["pid"] = pid

        session = _display_session_id(f["session_id"], f.get("is_task", False))
        if len(session) > w_session:
            session = session[:w_session - 3] + "..."

        pid_str = str(pid) if pid else "-"
        created_str = format_timestamp(f["ctime"])

        project_workspace = f.get("project_workspace") or "-"
        if len(project_workspace) > w_project:
            project_workspace = project_workspace[:w_project - 3] + "..."

        session_name = f.get("session_name") or "-"
        if len(session_name) > w_name:
            session_name = session_name[:w_name - 3] + "..."

        color = Colors.GREEN if pid else Colors.GRAY

        row = (
            f"{color}"
            f" {idx:^{w_no}} |"
            f" {session:<{w_session}} |"
            f" {pid_str:^{w_pid}} |"
            f" {created_str:^{w_created}} |"
            f" {project_workspace:<{w_project}} |"
            f" {session_name:<{w_name}} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)
    print(
        f"{Colors.GREEN}● Running{Colors.RESET}  "
        f"{Colors.GRAY}○ Idle{Colors.RESET}  "
        f"{Colors.DIM}(Total: {len(files)} files){Colors.RESET}"
    )


def format_file_table(files: List[dict]) -> str:
    """Return a formatted table of log files as a string.

    This is a string-returning variant of :func:`print_table` for callers
    that need the rendered output rather than direct printing.
    """
    captured = io.StringIO()
    with contextlib_redirect_stdout(captured):
        print_table(files)
    return captured.getvalue()


def print_simple_table(headers: List[str], rows: List[List[str]]) -> None:
    """Print a generic table with the given headers and rows.

    Column widths are calculated from the headers and row data. Each row must
    contain the same number of cells as ``headers``.
    """
    if not rows:
        print(f"{Colors.YELLOW}[WARN] No data to display.{Colors.RESET}")
        return

    widths = [len(str(h)) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            if idx >= len(widths):
                widths.append(0)
            widths[idx] = max(widths[idx], len(str(cell)))

    sep_parts = ["-" * (w + 2) for w in widths]
    sep = f"{Colors.CYAN}+".join(sep_parts) + Colors.RESET

    header_cells = [
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE} {str(headers[i]):^{widths[i]}} "
        for i in range(len(headers))
    ]
    header = f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}|".join(header_cells) + Colors.RESET

    print(f"+{sep}+")
    print(f"|{header}|")
    print(f"+{sep}+")
    for row in rows:
        row_cells = []
        for idx, width in enumerate(widths):
            cell = str(row[idx]) if idx < len(row) else ""
            row_cells.append(f" {cell:<{width}} ")
        print(f"|{'|'.join(row_cells)}|")
    print(f"+{sep}+")


def format_command_table(commands: List[dict]) -> str:
    """Return a formatted table of YAML commands as a string."""
    lines = []
    if not commands:
        lines.append("No commands available.")
        return "\n".join(lines)

    max_cmd = max(len(str(cmd.get("cmd", ""))) for cmd in commands)
    max_desc = max(len(str(cmd.get("desc", ""))) for cmd in commands)
    width = max(max_cmd + max_desc + 4, 40)

    lines.append("-" * width)
    lines.append(f"{'Command':<{max_cmd}}  {'Description':<{max_desc}}")
    lines.append("-" * width)
    for cmd in commands:
        command = str(cmd.get("cmd", ""))
        desc = str(cmd.get("desc", ""))
        lines.append(f"{command:<{max_cmd}}  {desc:<{max_desc}}")
    lines.append("-" * width)
    return "\n".join(lines)


class _RedirectStdout:
    """Minimal context manager to redirect sys.stdout."""

    def __init__(self, new_target):
        self._new_target = new_target
        self._old_target = None

    def __enter__(self):
        self._old_target = sys.stdout
        sys.stdout = self._new_target
        return self._new_target

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._old_target
        return False


def contextlib_redirect_stdout(new_target):
    """Backport of contextlib.redirect_stdout for direct use."""
    return _RedirectStdout(new_target)
