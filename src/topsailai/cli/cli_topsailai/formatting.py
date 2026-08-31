"""Output formatting helpers for the TopsailAI CLI."""

import io
import os
import sys
import unicodedata
from contextlib import redirect_stdout as contextlib_redirect_stdout
from datetime import datetime
from typing import List

from cli_topsailai.colors import Colors
from cli_topsailai.log_files import _display_session_id, is_session_pipe_open


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


def _character_display_width(character: str) -> int:
    """Return the terminal display width of one character."""
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in ("F", "W") else 1


def _fit_table_cell(
    value: object,
    width: int,
    alignment: str = "left",
    truncate_from: str = "tail",
) -> str:
    """Truncate and pad a table cell to an exact terminal display width."""
    text = str(value)
    display_width = sum(_character_display_width(character) for character in text)
    if display_width > width:
        ellipsis = "..." if width >= 3 else "." * width
        available_width = width - len(ellipsis)
        characters = []
        used_width = 0
        source = reversed(text) if truncate_from == "head" else text
        for character in source:
            character_width = _character_display_width(character)
            if used_width + character_width > available_width:
                break
            characters.append(character)
            used_width += character_width
        if truncate_from == "head":
            characters.reverse()
            text = ellipsis + "".join(characters)
        else:
            text = "".join(characters) + ellipsis
        display_width = used_width + len(ellipsis)

    padding = width - display_width
    if alignment == "center":
        left_padding = padding // 2
        return " " * left_padding + text + " " * (padding - left_padding)
    return text + " " * padding


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

    w_session = 18
    w_created = 13
    w_project = 24
    w_name = 23
    rows = []

    for idx, file_info in enumerate(files, start=1):
        pid = file_info.get("pid")
        if pid is not None:
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError, OSError):
                pid = None
        file_info["pid"] = pid

        session = _display_session_id(
            file_info["session_id"], file_info.get("is_task", False)
        )
        pid_str = str(pid) if pid else "-"
        if pid and is_session_pipe_open(file_info):
            status_str = "INPUT"
        elif pid:
            status_str = "RUN"
        else:
            status_str = "-"
        rows.append(
            {
                "no": str(idx),
                "session_name": file_info.get("session_name") or "-",
                "session": session,
                "pid": pid_str,
                "status": status_str,
                "created": format_timestamp(file_info["ctime"]),
                "project_workspace": file_info.get("project_workspace") or "-",
                "color": Colors.YELLOW
                if status_str == "INPUT"
                else (Colors.GREEN if pid else Colors.GRAY),
            }
        )

    def dynamic_width(header: str, key: str) -> int:
        """Return the widest terminal display width for a rendered column."""
        values = [header, *(str(row[key]) for row in rows)]
        return max(
            sum(_character_display_width(character) for character in value)
            for value in values
        )

    w_no = dynamic_width("No", "no")
    w_pid = dynamic_width("PID", "pid")
    w_status = dynamic_width("Status", "status")

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {_fit_table_cell('No', w_no, 'center')} |"
        f" {_fit_table_cell('Session Name', w_name, 'center')} |"
        f" {_fit_table_cell('Session ID', w_session, 'center')} |"
        f" {_fit_table_cell('PID', w_pid, 'center')} |"
        f" {_fit_table_cell('Status', w_status, 'center')} |"
        f" {_fit_table_cell('Created', w_created, 'center')} |"
        f" {_fit_table_cell('Project Workspace', w_project, 'center')} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_session + 2)}+"
        f"{'-' * (w_pid + 2)}+"
        f"{'-' * (w_status + 2)}+"
        f"{'-' * (w_created + 2)}+"
        f"{'-' * (w_project + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)
    for row_info in rows:
        row = (
            f"{row_info['color']}"
            f" {_fit_table_cell(row_info['no'], w_no, 'center')} |"
            f" {_fit_table_cell(row_info['session_name'], w_name)} |"
            f" {_fit_table_cell(row_info['session'], w_session)} |"
            f" {_fit_table_cell(row_info['pid'], w_pid, 'center')} |"
            f" {_fit_table_cell(row_info['status'], w_status, 'center')} |"
            f" {_fit_table_cell(row_info['created'], w_created, 'center')} |"
            f" {_fit_table_cell(row_info['project_workspace'], w_project, truncate_from='head')} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)
    print(
        f"{Colors.GREEN}● Running{Colors.RESET}  "
        f"{Colors.GRAY}○ Idle{Colors.RESET}  "
        f"{Colors.YELLOW}● Inputting{Colors.RESET}  "
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
