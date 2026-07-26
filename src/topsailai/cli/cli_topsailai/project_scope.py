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
from cli_topsailai.projects import (
    build_managed_project_list as _build_managed_project_list,
    print_project_table as _print_managed_project_table,
)


# Maximum number of concurrent running-status checks per refresh.
_MAX_RUNNING_STATUS_WORKERS = 8

# Built-in agent drivers offered when resuming a session.
_RESUME_DRIVER_OPTIONS = [
    "topsailai_agent_chats",
    "topsailai_agent_plan_tasks",
    "ai-team-flow-dev",
]


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


def build_project_list(
    limit: Optional[int] = 10, session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Build the list of recent sessions with a project workspace.

    Runs ``ai_list_sessions.py --json --has-project --sort desc`` with an
    optional session ID and limit, then parses the JSON output.  The database
    returns entries newest-first, so the list is reversed before rendering so
    the oldest entry appears at the top of the project scope table and the
    newest entry appears at the bottom.

    Each entry is enriched with a ``status`` field (``Running`` or ``Idle``)
    by scanning ``{TOPSAILAI_HOME}/workspace/task/`` for the most recent
    ``*.session.stdout`` file and checking whether its embedded PID is alive.
    Status checks run concurrently in a thread pool.

    Args:
        limit: Maximum number of sessions to return, or ``None`` for no limit.
        session_id: Optional exact session ID to retrieve.

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
    ]
    if session_id:
        cmd.append(session_id)
    if limit is not None:
        cmd.extend(["--limit", str(limit)])

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


def build_managed_project_list() -> List[Dict[str, Any]]:
    """Build the user-managed project list.

    This is a thin wrapper around :func:`cli_topsailai.projects.build_managed_project_list`
    so callers only need to import from ``project_scope``.

    Returns:
        Numbered list of managed project dictionaries.
    """
    return _build_managed_project_list()


def print_managed_project_table(entries: List[Dict[str, Any]]) -> None:
    """Print the user-managed project list.

    This is a thin wrapper around :func:`cli_topsailai.projects.print_project_table`.

    Args:
        entries: Numbered managed project list.
    """
    _print_managed_project_table(entries)


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

    If *arg* is a number, it is mapped to the project workspace of the
    corresponding entry in *entries* (1-based index).  Project scope entries
    provide ``project_workspace`` directly; managed project entries provide
    ``path`` directly; workspace log file entries provide ``session_id`` and
    the project workspace is resolved from ``.project_history.jsonl``.
    Otherwise *arg* is returned as-is so it can be used as a direct folder path.

    Args:
        arg: User-provided argument, either a list number or a folder path.
        entries: Current project scope entries or workspace log file entries.

    Returns:
        Resolved folder path, or ``None`` when the number is out of range or
        no project workspace can be determined.
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
            entry = entries[idx]
            folder = entry.get("project_workspace", "")
            if folder:
                return folder
            folder = entry.get("path", "")
            if folder:
                return folder
            session_id = entry.get("session_id", "")
            if session_id and session_id != "(temp)":
                lookup = load_project_workspace_lookup()
                folder = lookup.get(session_id, "")
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


def _generate_agent_session_name() -> str:
    """Return a unique session name for tmux-based agent launches."""
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S.%f")
    return f"topsailai-{timestamp}"


def _wrap_command_for_agent_mode(command: str, mode: str) -> str:
    """Wrap *command* according to the requested agent launch mode.

    Supported modes:

    - ``raw``: return *command* unchanged.
    - ``dtach``: wrap with ``dtach -A {socket} {command}`` when ``dtach`` is
      available in ``PATH``; otherwise fall back to *command* unchanged.
    - ``tmux``: wrap with ``tmux new-session -e KEY=VALUE ... -s {name}
      {command}``.  Requires ``tmux`` to be available in ``PATH``; raises
      ``RuntimeError`` if it is not.  Environment variables set by the
      caller (``TOPSAILAI_SESSION_ID``, ``TOPSAILAI_PWD`` and ``PWD``) are
      forwarded explicitly so the tmux session sees the same environment as
      raw and dtach modes.

    Args:
        command: The command to wrap.
        mode: Launch mode, one of ``"raw"``, ``"dtach"`` or ``"tmux"``.

    Returns:
        The wrapped command string.

    Raises:
        RuntimeError: If *mode* is ``"tmux"`` and ``tmux`` is not installed.
        ValueError: If *mode* is not one of the supported values.
    """
    if mode == "raw":
        return command

    if mode == "dtach":
        if shutil.which("dtach") is None:
            return command
        socket_path = _build_dtach_socket_path()
        return f"dtach -A {shlex.quote(socket_path)} {command}"

    if mode == "tmux":
        if shutil.which("tmux") is None:
            raise RuntimeError(
                "tmux is not installed or not found in PATH. "
                "Install tmux to use --agent-mode tmux, or choose raw/dtach."
            )
        session_name = _generate_agent_session_name()
        env_vars = {
            key: os.environ.get(key)
            for key in ("TOPSAILAI_SESSION_ID", "TOPSAILAI_PWD", "PWD")
            if os.environ.get(key) is not None
        }
        env_args = " ".join(
            f"-e {shlex.quote(f'{key}={value}')}" for key, value in env_vars.items()
        )
        env_part = f" {env_args}" if env_args else ""
        return (
            f"tmux new-session{env_part} -s {shlex.quote(session_name)} {command}"
        )

    raise ValueError(f"Unsupported agent launch mode: {mode!r}")


def launch_agent_in_folder(folder: str, agent_mode: str = "dtach") -> None:
    """Change to *folder* and launch ``topsailai_launch_agent`` via os.system.

    The launch mode is controlled by *agent_mode*:

    - ``raw``: invoke ``topsailai_launch_agent`` directly.
    - ``dtach`` (default): wrap with ``dtach -A {socket}`` when ``dtach`` is
      available; fall back to raw otherwise.
    - ``tmux``: wrap with ``tmux new-session -s {name}``; requires ``tmux``.

    The launcher reads ``TOPSAILAI_PWD`` at import time and uses it to decide
    its working directory, so both the process working directory and the
    ``TOPSAILAI_PWD``/``PWD`` environment variables are set to the target
    folder before invoking the launcher.  The original working directory and
    environment values are restored after the launcher returns.

    Args:
        folder: Target project workspace folder.
        agent_mode: How to launch the agent: ``"raw"``, ``"dtach"`` or
            ``"tmux"``.  Defaults to ``"dtach"``.
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
            f"{Colors.GREEN}[INFO] Launching agent in {target_folder} "
            f"(mode: {agent_mode}) ...{Colors.RESET}"
        )
        command = _wrap_command_for_agent_mode("topsailai_launch_agent", agent_mode)
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

def launch_agent_driver(
    folder: str, driver: str, session_id: str, agent_mode: str = "dtach"
) -> None:
    """Change to *folder* and launch *driver* directly with *session_id* set.

    The launch mode is controlled by *agent_mode*:

    - ``raw``: invoke *driver* directly.
    - ``dtach`` (default): wrap with ``dtach -A {socket}`` when ``dtach`` is
      available; fall back to raw otherwise.
    - ``tmux``: wrap with ``tmux new-session -s {name}``; requires ``tmux``.

    The process working directory and the ``TOPSAILAI_PWD``/``PWD``
    environment variables are set to the target folder so the driver reads
    ``.topsailai/settings.yaml`` from the correct project workspace.
    ``TOPSAILAI_SESSION_ID`` is set to *session_id* so the resumed agent
    continues the existing session instead of generating a new one.

    The original working directory and environment values are restored
    after the driver returns.

    Args:
        folder: Target project workspace folder.
        driver: Agent driver command to execute.
        session_id: Session ID to resume.
        agent_mode: How to launch the driver: ``"raw"``, ``"dtach"`` or
            ``"tmux"``.  Defaults to ``"dtach"``.
    """
    original_cwd = os.getcwd()
    target_folder = os.path.abspath(folder)

    env_keys = ("TOPSAILAI_PWD", "PWD", "TOPSAILAI_SESSION_ID")
    original_env: Dict[str, Optional[str]] = {
        key: os.environ.get(key) for key in env_keys
    }

    try:
        os.chdir(target_folder)
        os.environ["TOPSAILAI_PWD"] = target_folder
        os.environ["PWD"] = target_folder
        os.environ["TOPSAILAI_SESSION_ID"] = session_id
        print(
            f"{Colors.GREEN}[INFO] Launching driver '{driver}' in {target_folder} "
            f"for session '{session_id}' (mode: {agent_mode}) ...{Colors.RESET}"
        )
        command = _wrap_command_for_agent_mode(driver, agent_mode)
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

def _prompt_for_driver() -> str:
    """Prompt the user to select an agent driver for resuming a session.

    Presents a numbered list of built-in drivers plus a custom-input option.
    The default selection is ``topsailai_agent_plan_tasks`` (option 2).

    Returns:
        The selected driver command string.
    """
    print("\nSelect an agent driver to resume the session:")
    for idx, driver in enumerate(_RESUME_DRIVER_OPTIONS, start=1):
        print(f"  {idx}. {driver}")
    print(f"  {len(_RESUME_DRIVER_OPTIONS) + 1}. (custom input)")

    default_option = 2
    total_options = len(_RESUME_DRIVER_OPTIONS) + 1
    prompt_text = f"Select driver (1-{total_options}, default: {default_option}): "

    while True:
        try:
            answer = input(prompt_text).strip()
        except EOFError:
            answer = ""
        if not answer:
            return _RESUME_DRIVER_OPTIONS[default_option - 1]
        if answer.isdigit():
            option = int(answer)
            if 1 <= option <= len(_RESUME_DRIVER_OPTIONS):
                return _RESUME_DRIVER_OPTIONS[option - 1]
            if option == total_options:
                custom = input("Enter custom driver name: ").strip()
                if custom:
                    return custom
                print(
                    f"{Colors.YELLOW}[WARN] Custom driver name cannot be empty.{Colors.RESET}"
                )
                continue
        print(
            f"{Colors.RED}[ERROR] Invalid selection. Please enter 1-{total_options}.{Colors.RESET}"
        )


def _resolve_session_entry(
    arg: str, entries: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Resolve a numeric argument to a project-scope session entry.

    Args:
        arg: User-provided argument, expected to be a 1-based number.
        entries: Current project scope entries.

    Returns:
        The matching entry dictionary, or ``None`` if the argument is invalid.
    """
    if not arg.isdigit():
        print(
            f"{Colors.RED}[ERROR] Usage: /resume <number>{Colors.RESET}"
        )
        return None
    idx = int(arg) - 1
    if not (0 <= idx < len(entries)):
        print(
            f"{Colors.RED}[ERROR] Invalid number. Please enter 1-{len(entries)}.{Colors.RESET}"
        )
        return None
    return entries[idx]


def resume_session(
    arg: str, entries: List[Dict[str, Any]], agent_mode: str = "dtach"
) -> bool:
    """Resume an idle session by launching an agent driver in its workspace.

    The selected session must not be running.  If it is, a message is printed
    and no action is taken.  Otherwise the user is prompted to choose an agent
    driver (default ``topsailai_agent_plan_tasks``) and the selected driver is
    launched directly in the session's project workspace with
    ``TOPSAILAI_SESSION_ID`` set to the session ID.

    The launch mode is controlled by *agent_mode* (``raw``, ``dtach`` or
    ``tmux``).  See ``launch_agent_driver`` for details.

    Args:
        arg: User-provided argument, expected to be a 1-based entry number.
        entries: Current project scope entries.
        agent_mode: How to launch the driver: ``"raw"``, ``"dtach"`` or
            ``"tmux"``.  Defaults to ``"dtach"``.

    Returns:
        ``True`` when the resume is launched, otherwise ``False``.
    """
    entry = _resolve_session_entry(arg, entries)
    if entry is None:
        return False

    session_id = entry.get("session_id", "")
    if not session_id:
        print(
            f"{Colors.RED}[ERROR] Selected entry has no session ID.{Colors.RESET}"
        )
        return False

    status = entry.get("status") or "Idle"
    if status == "Running":
        print(
            f"{Colors.RED}[ERROR] Session '{session_id}' is already running and "
            f"cannot be resumed.{Colors.RESET}"
        )
        return False

    project_workspace = entry.get("project_workspace", "")
    if not project_workspace:
        lookup = load_project_workspace_lookup()
        project_workspace = lookup.get(session_id, "")
    if not project_workspace:
        print(
            f"{Colors.RED}[ERROR] Selected session has no project workspace.{Colors.RESET}"
        )
        return False

    driver = _prompt_for_driver()
    print(
        f"{Colors.GREEN}[INFO] Resuming session '{session_id}' with driver '{driver}' "
        f"in {project_workspace} (mode: {agent_mode}) ...{Colors.RESET}"
    )
    launch_agent_driver(project_workspace, driver, session_id, agent_mode=agent_mode)
    return True
