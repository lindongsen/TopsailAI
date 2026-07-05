"""Output formatting helpers for the TopsailAI CLI."""

import os
import sys
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
    """Format a Unix timestamp to a full date/time string."""
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
    w_session = 22
    w_name = 20
    w_pid = 8
    w_size = 10
    w_modified = 14
    w_created = 14

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {'No':^{w_no}} |"
        f" {'Session ID':^{w_session}} |"
        f" {'Session Name':^{w_name}} |"
        f" {'PID':^{w_pid}} |"
        f" {'Size':^{w_size}} |"
        f" {'Modified':^{w_modified}} |"
        f" {'Created':^{w_created}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_session + 2)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_pid + 2)}+"
        f"{'-' * (w_size + 2)}+"
        f"{'-' * (w_modified + 2)}+"
        f"{'-' * (w_created + 1)}"
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

        session_name = f.get("session_name") or "-"
        if len(session_name) > w_name:
            session_name = session_name[:w_name - 3] + "..."

        pid_str = str(pid) if pid else "-"
        size_str = format_size(f["size"])
        modified_str = format_timestamp(f["mtime"])
        created_str = format_timestamp(f["ctime"])
        color = Colors.GREEN if pid else Colors.GRAY

        row = (
            f"{color}"
            f" {idx:^{w_no}} |"
            f" {session:<{w_session}} |"
            f" {session_name:<{w_name}} |"
            f" {pid_str:^{w_pid}} |"
            f" {size_str:>{w_size}} |"
            f" {modified_str:^{w_modified}} |"
            f" {created_str:^{w_created}} "
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
    import io

    captured = io.StringIO()
    with contextlib_redirect_stdout(captured):
        print_table(files)
    return captured.getvalue()


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
