"""Project scope support for the TopsailAI CLI.

This module builds the list of recent sessions that have a project workspace
by invoking ``ai_list_sessions.py`` with JSON output, and renders the list as
a table compatible with the interactive selection loop.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from typing import Any, Dict, Optional

from cli_topsailai.colors import Colors
from cli_topsailai.log_files import _find_session_stdout_file, _get_pid_from_stdout_path
from cli_topsailai.paths import get_topsailai_home


# Maximum number of concurrent running-status checks per refresh.
_MAX_RUNNING_STATUS_WORKERS = 8


def _script_path() -> str:
    """Return the absolute path to ``ai_list_sessions.py``."""
    module_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(module_dir)
    return os.path.join(project_root, "ai_list_sessions.py")


def _is_pid_alive(pid: int) -> bool:
    """Return True if *pid* is currently running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _check_session_running(home: str, session_id: str) -> bool:
    """Check whether *session_id* has a live session process.

    Scans ``{home}/workspace/task/`` for the most recent
    ``{session_id}.{pid}.session.stdout`` file and checks whether the embedded
    PID is still alive.
    """
    if not session_id:
        return False
    task_dir = os.path.join(home, "workspace", "task")
    stdout_path = _find_session_stdout_file(task_dir, session_id)
    if not stdout_path:
        return False
    pid = _get_pid_from_stdout_path(stdout_path)
    if pid is None:
        return False
    return _is_pid_alive(pid)


def _enrich_running_status(entries: List[Dict[str, Any]]) -> None:
    """Add a ``status`` field to each entry by scanning stdout files.

    Running status is determined by checking the embedded PID of the most
    recent ``*.session.stdout`` file for each session.  Checks run in a
    thread pool so filesystem scans do not block each other.
    """
    if not entries:
        return

    home = get_topsailai_home()
    max_workers = min(_MAX_RUNNING_STATUS_WORKERS, len(entries))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_entry = {
            executor.submit(_check_session_running, home, entry.get("session_id", "")): entry
            for entry in entries
        }
        for future in as_completed(future_to_entry):
            entry = future_to_entry[future]
            try:
                is_running = future.result()
            except Exception:
                is_running = False
            entry["status"] = "Running" if is_running else "Idle"


def _format_create_time(create_time: str) -> str:
    """Format an ISO create_time string for the project table."""
    if not create_time:
        return "-"
    try:
        dt = datetime.fromisoformat(create_time)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return create_time


def _read_project_history_lines(home: str) -> list[str]:
    """Yield non-empty lines from ``.project_history.jsonl`` newest first."""
    history_path = os.path.join(home, ".project_history.jsonl")
    if not os.path.exists(history_path):
        return []
    try:
        with open(history_path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    # Iterate from the end so the most recent entry wins.
    return [line for line in reversed(lines) if line.strip()]


def load_project_workspace_lookup() -> Dict[str, str]:
    """Build a mapping from ``session_id`` to latest ``project_workspace``.

    Reads ``{TOPSAILAI_HOME}/.project_history.jsonl`` and returns the most
    recent ``project_workspace`` value recorded for each ``session_id``.
    Temporary sessions (``topsailai``) are included as-is because callers
    decide how to display them.

    Returns:
        Dictionary mapping ``session_id`` to ``project_workspace``.
    """
    home = get_topsailai_home()
    lookup: Dict[str, str] = {}
    for line in _read_project_history_lines(home):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        session_id = record.get("session_id")
        project_workspace = record.get("project_workspace")
        if not session_id or not isinstance(project_workspace, str) or not project_workspace:
            continue
        # Because we iterate newest-first, the first hit for a session is the
        # most recent workspace.  Skip later (older) entries.
        if session_id not in lookup:
            lookup[session_id] = project_workspace
    return lookup


def build_project_list(limit: int = 10) -> List[Dict[str, Any]]:
    """Build the list of recent sessions with a project workspace.

    Runs ``ai_list_sessions.py --json --has-project --sort desc --limit N`` and
    parses the JSON output.  The database returns entries newest-first, so the
    list is reversed before rendering so the oldest entry appears at the top of
    the project scope table and the newest entry appears at the bottom.

    Each entry is enriched with a ``status`` field (``Running`` or ``Idle``)
    by scanning ``{TOPSAILAI_HOME}/workspace/task/`` for the most recent
    ``*.session.stdout`` file and checking whether its embedded PID is alive.
    Status checks run concurrently in a thread pool.

    Args:
        limit: Maximum number of sessions to return (default 10).

    Returns:
        List of session dictionaries with keys ``no``, ``session_id``,
        ``session_name``, ``project_workspace``, ``create_time``,
        ``create_time_raw``, ``task``, and ``status``.
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

    sessions.reverse()

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

    _enrich_running_status(entries)
    return entries


def print_project_table(entries: List[Dict[str, Any]]) -> None:
    """Print a table of recent project workspaces."""
    if not entries:
        print(
            f"\n{Colors.YELLOW}[WARN] No sessions with project_workspace found.{Colors.RESET}"
        )
        return

    w_no = 4
    w_session = 20
    w_project = 30
    w_created = 14
    w_name = 16

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

        status = entry.get("status") or "Idle"
        row_color = Colors.GREEN if status == "Running" else Colors.RESET

        row = (
            f"{row_color}"
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


def resolve_agent_folder(arg: str, entries: List[Dict[str, Any]]) -> Optional[str]:
    """Resolve a `/agent` argument to a folder path.

    If *arg* is a number, it is mapped to the ``project_workspace`` of the
    corresponding entry in *entries* (1-based index).  Otherwise *arg* is
    returned as-is so it can be used as a direct folder path.

    Args:
        arg: User-provided argument, either a list number or a folder path.
        entries: Current project scope entries.

    Returns:
        Resolved folder path, or ``None`` when the number is out of range.
    """
    arg = arg.strip()
    if not arg:
        print(
            f"{Colors.RED}[ERROR] Usage: /agent <number> or /agent <folder>{Colors.RESET}"
        )
        return None

    if arg.isdigit():
        idx = int(arg) - 1
        if 0 <= idx < len(entries):
            folder = entries[idx].get("project_workspace", "")
            if folder:
                return folder
            print(
                f"{Colors.RED}[ERROR] Selected entry has no project workspace.{Colors.RESET}"
            )
            return None
        print(
            f"{Colors.RED}[ERROR] Invalid number. Please enter 1-{len(entries)}.{Colors.RESET}"
        )
        return None

    return arg


def _build_dtach_socket_path() -> str:
    """Return an absolute dtach socket path under the task directory.

    The socket is placed in ``{TOPSAILAI_HOME}/workspace/task/`` so it lives
    alongside other session/task runtime artifacts.  The directory is created
    on demand.
    """
    home = get_topsailai_home()
    task_dir = os.path.join(home, "workspace", "task")
    os.makedirs(task_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S.%f")
    return os.path.join(task_dir, f"{timestamp}.dtach")


def _wrap_command_with_dtach(command: str) -> str:
    """Wrap *command* with dtach if the dtach binary is available.

    If ``dtach`` is not found in ``PATH``, *command* is returned unchanged.
    The dtach socket is placed under ``{TOPSAILAI_HOME}/workspace/task/``
    with a timestamped filename.
    """
    if shutil.which("dtach") is None:
        return command
    socket_path = _build_dtach_socket_path()
    return f"dtach -A {shlex.quote(socket_path)} {command}"


def launch_agent_in_folder(folder: str) -> None:
    """Change to *folder* and launch ``topsailai_launch_agent`` via os.system.

    When the ``dtach`` tool is available in ``PATH``, the launcher is wrapped
    as ``dtach -A {socket} topsailai_launch_agent`` so the agent runs inside
    a dtach session.  The socket is placed under
    ``{TOPSAILAI_HOME}/workspace/task/`` with a timestamped filename.  If
    ``dtach`` is not available, the launcher is invoked unchanged.

    The launcher reads ``TOPSAILAI_PWD`` at import time and uses it to decide
    its working directory, so both the process working directory and the
    ``TOPSAILAI_PWD``/``PWD`` environment variables are set to the target
    folder before invoking the launcher.  The original working directory and
    environment values are restored after the launcher returns.

    Args:
        folder: Target project workspace folder.
    """
    original_cwd = os.getcwd()
    target_folder = os.path.abspath(folder)

    env_keys = ("TOPSAILAI_PWD", "PWD")
    original_env: Dict[str, Optional[str]] = {
        key: os.environ.get(key) for key in env_keys
    }

    try:
        os.chdir(target_folder)
        for key in env_keys:
            os.environ[key] = target_folder
        print(
            f"{Colors.GREEN}[INFO] Launching agent in {target_folder} ...{Colors.RESET}"
        )
        command = _wrap_command_with_dtach("topsailai_launch_agent")
        os.system(command)
    except OSError as exc:
        print(
            f"{Colors.RED}[ERROR] Failed to change to folder '{target_folder}': {exc}{Colors.RESET}"
        )
    finally:
        for key in env_keys:
            original_value = original_env[key]
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value
        try:
            os.chdir(original_cwd)
        except OSError as exc:
            print(
                f"{Colors.RED}[ERROR] Failed to restore working directory '{original_cwd}': {exc}{Colors.RESET}"
            )
