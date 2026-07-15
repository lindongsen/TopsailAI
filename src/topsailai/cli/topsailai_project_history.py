#!/usr/bin/env python3
"""Display recent project history entries from TOPSAILAI_HOME.

Reads ``.project_history.jsonl`` in the resolved TOPSAILAI_HOME directory
and prints the latest *N* records as a formatted table or as JSON. Sessions
that are still running (their session stdout PID is alive in
``workspace/task/``) are highlighted in the table view.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from cli_topsailai.colors import Colors
from cli_topsailai.paths import get_topsailai_home


DEFAULT_LIMIT = 20
HISTORY_FILENAME = ".project_history.jsonl"
TASK_SUBDIR = "workspace/task"


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show recent project history entries from TOPSAILAI_HOME."
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum number of recent entries to display (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--home",
        type=str,
        default=None,
        help="Override TOPSAILAI_HOME directory.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output entries as JSON instead of a formatted table.",
    )
    return parser.parse_args(argv)


def _normalize_timestamp(ts: Any) -> Optional[str]:
    """Convert legacy timestamp formats to local ISO 8601 string with offset."""
    if ts is None:
        return None
    if isinstance(ts, bool):
        return None
    if isinstance(ts, (int, float)):
        seconds = ts if ts >= 1_000_000_000_000 else ts * 1000
        dt = datetime.fromtimestamp(seconds / 1000.0)
        return dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    if isinstance(ts, str):
        ts = ts.strip()
        if not ts:
            return None
        try:
            numeric = float(ts)
            return _normalize_timestamp(numeric)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            return dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        except (ValueError, TypeError, OverflowError):
            return None
    return None


def _read_last_lines(filepath: str, n: int) -> List[str]:
    """Return up to the last *n* non-empty lines from *filepath*.

    Reads from the end in chunks so large files do not need to be loaded
    entirely into memory.
    """
    if n <= 0:
        return []

    lines: List[str] = []
    try:
        with open(filepath, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()

            if not isinstance(size, int):
                f.seek(0)
                result: List[str] = []
                for line in f.readlines():
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    line = line.strip()
                    if line:
                        result.append(line)
                return result[:n]

            if size == 0:
                return []

            chunk_size = 8192
            buffer = b""
            pos = size

            while pos > 0:
                start = max(0, pos - chunk_size)
                read_size = pos - start
                f.seek(start)
                chunk = f.read(read_size)
                buffer = chunk + buffer
                pos = start

                while True:
                    newline_pos = buffer.rfind(b"\n")
                    if newline_pos == -1:
                        break
                    line = buffer[newline_pos + 1 :]
                    if line:
                        lines.append(line.decode("utf-8", errors="replace"))
                        if len(lines) >= n:
                            return list(reversed(lines))
                    buffer = buffer[:newline_pos]

            if buffer and len(lines) < n:
                lines.append(buffer.decode("utf-8", errors="replace"))

            return list(reversed(lines))
    except OSError:
        return []


def _load_entries(home: str, limit: int) -> List[Dict[str, Any]]:
    """Load the latest *limit* entries from ``.project_history.jsonl``."""
    filepath = os.path.join(home, HISTORY_FILENAME)
    if not os.path.isfile(filepath):
        return []

    lines = _read_last_lines(filepath, limit)
    entries: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        ts = entry.get("ts")
        normalized = _normalize_timestamp(ts)
        if normalized is not None:
            entry["ts"] = normalized
        entries.append(entry)
    return entries


def _ellipsize(text: str, width: int) -> str:
    """Truncate *text* to fit within *width* characters."""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _display_session_id(session_id: Any, fallback: str = "-") -> str:
    """Return a display-friendly session id string."""
    if session_id is None:
        return fallback
    text = str(session_id)
    if text == "topsailai":
        return "(temp)"
    return text if text else fallback


def _parse_session_stdout_filename(filename: str) -> tuple[Optional[str], Optional[int]]:
    """Parse a ``*.session.stdout`` filename into (session_id, pid).

    Supports ``{session_id}.{pid}.session.stdout`` and the temporary session
    form ``topsailai.{pid}.session.stdout``.
    """
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


def _is_pid_alive(pid: int) -> bool:
    """Return True if *pid* is currently running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _find_session_pid(home: str, session_id: str) -> Optional[int]:
    """Return the PID from the most recent stdout file for *session_id*.

    Prefers the PID recorded in the history entry when it matches a live
    process and a corresponding stdout file exists. Otherwise falls back to
    scanning ``workspace/task/`` for the most recent matching
    ``{session_id}.{pid}.session.stdout`` file.
    """
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


def _is_session_running(home: str, session_id: str, recorded_pid: Optional[int] = None) -> bool:
    """Return True if *session_id* has a live session process.

    When *recorded_pid* is provided and the PID is alive and a matching
    stdout file exists, it is used directly. Otherwise the most recent
    ``{session_id}.{pid}.session.stdout`` file in ``workspace/task/`` is
    used.
    """
    if recorded_pid is not None and _is_pid_alive(recorded_pid):
        task_dir = os.path.join(home, TASK_SUBDIR)
        expected = f"{session_id}.{recorded_pid}.session.stdout"
        if os.path.isfile(os.path.join(task_dir, expected)):
            return True

    pid = _find_session_pid(home, session_id)
    if pid is None:
        return False
    return _is_pid_alive(pid)


def _print_table(entries: List[Dict[str, Any]], home: str) -> None:
    """Print project history entries as a formatted table."""
    if not entries:
        print(f"{Colors.YELLOW}[INFO] No project history entries found.{Colors.RESET}")
        return

    w_no = 4
    w_ts = 22
    w_session = 22
    w_pid = 10
    w_project = 28
    w_pwd = 28

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {'No':^{w_no}} |"
        f" {'Timestamp':^{w_ts}} |"
        f" {'Session ID':^{w_session}} |"
        f" {'PID':^{w_pid}} |"
        f" {'Project Workspace':^{w_project}} |"
        f" {'PWD':^{w_pwd}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_ts + 2)}+"
        f"{'-' * (w_session + 2)}+"
        f"{'-' * (w_pid + 2)}+"
        f"{'-' * (w_project + 2)}+"
        f"{'-' * (w_pwd + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for idx, entry in enumerate(entries, start=1):
        ts = str(entry.get("ts") or "-")
        raw_session = entry.get("session_id")
        session = _display_session_id(raw_session)
        recorded_pid = entry.get("pid")
        pid_text = str(recorded_pid) if isinstance(recorded_pid, int) else "-"
        project = str(entry.get("project_workspace") or "-")
        pwd = str(entry.get("pwd") or "-")

        is_running = False
        if raw_session is not None:
            is_running = _is_session_running(home, str(raw_session), recorded_pid)

        session_color = Colors.GREEN if is_running else Colors.RESET

        row = (
            f"{Colors.RESET}"
            f" {idx:^{w_no}} |"
            f" {_ellipsize(ts, w_ts):^{w_ts}} |"
            f" {session_color}{_ellipsize(session, w_session):^{w_session}}{Colors.RESET} |"
            f" {session_color}{_ellipsize(pid_text, w_pid):^{w_pid}}{Colors.RESET} |"
            f" {_ellipsize(project, w_project):^{w_project}} |"
            f" {_ellipsize(pwd, w_pwd):^{w_pwd}} "
        )
        print(row)

    print(sep)
    print(
        f"{Colors.GREEN}● Running{Colors.RESET}  "
        f"{Colors.RESET}○ Idle{Colors.RESET}  "
        f"{Colors.DIM}(Total: {len(entries)} entries){Colors.RESET}"
    )


def _print_json(entries: List[Dict[str, Any]], home: str) -> None:
    """Print project history entries as JSON with running status."""
    output: List[Dict[str, Any]] = []
    for entry in entries:
        record = dict(entry)
        raw_session = record.get("session_id")
        recorded_pid = record.get("pid")
        is_running = False
        if raw_session is not None:
            is_running = _is_session_running(home, str(raw_session), recorded_pid)
        record["is_running"] = is_running
        output.append(record)
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for ``topsailai_project_history``."""
    args = _parse_args(argv)

    if args.limit <= 0:
        print(f"{Colors.RED}[ERROR] --limit must be a positive integer.{Colors.RESET}")
        return 1

    home = args.home
    if home is None:
        home = get_topsailai_home()

    entries = _load_entries(home, args.limit)
    if args.json:
        _print_json(entries, home)
    else:
        _print_table(entries, home)
    return 0


if __name__ == "__main__":
    sys.exit(main())
