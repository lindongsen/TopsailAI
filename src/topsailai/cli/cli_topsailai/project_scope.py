"""Project scope support for the TopsailAI CLI.

This module builds the list of recent sessions that have a project workspace
by invoking ``topsailai_list_sessions`` with JSON output, and renders the list as
a table compatible with the interactive selection loop.
"""

from __future__ import annotations

import json
import os
import re
import select
import shlex
import shutil
import subprocess
import time
from datetime import datetime
from typing import TYPE_CHECKING, Callable, List

if TYPE_CHECKING:
    from typing import Any, Dict, Optional

from cli_topsailai.colors import Colors
from cli_topsailai.driver_ownership import (
    DriverOwnership,
    describe_ownership,
    remove_pidfile,
    stop_owned_driver,
)
from cli_topsailai.formatting import _fit_table_cell
from cli_topsailai.log_files import (
    _find_session_stdout_file,
    _get_pid_from_stdout_path,
    _parse_stdout_filename,
)
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.process_liveness import (
    ProcessState,
    _TEMP_SESSION_ID,
    pid_state,
    session_liveness as _liveness_session_liveness,
)
from cli_topsailai.projects import (
    build_managed_project_list as _build_managed_project_list,
    print_project_table as _print_managed_project_table,
)


# Built-in agent drivers offered when resuming a session.
_RESUME_DEFAULT_DRIVER = "topsailai_agent_chats"
_RESUME_DRIVER_OPTIONS = [
    "topsailai_agent_chats",
    "topsailai_agent_plan_tasks",
    "ai-team-flow-dev",
]

# Environment aliases that carry the session identity into a launched child.
# Both are set and restored together so a resumed worker observes the persisted
# session through either alias.
_IDENTITY_ENV_KEYS = ("TOPSAILAI_SESSION_ID", "SESSION_ID")

# Environment keys mutated for one launch and restored immediately afterward.
_LAUNCH_ENV_KEYS = ("TOPSAILAI_PWD", "PWD") + _IDENTITY_ENV_KEYS

# Bounds for the single authoritative session lookup: the capture must never
# grow without limit and a hung query must not block the resume forever.
_LOOKUP_TIMEOUT_SECONDS = 30.0
_LOOKUP_MAX_BYTES = 4 * 1024 * 1024

# In-flight capture tuning. The reader consumes the child pipe in chunks of at
# most _LOOKUP_READ_CHUNK bytes and stops at the byte budget, so the retained
# data never exceeds _LOOKUP_MAX_BYTES per channel. Bytes the child already
# wrote into the kernel pipe buffer before consumption stopped are bounded by
# the pipe capacity (measured 65536 bytes on this host via F_GETPIPE_SZ);
# _LOOKUP_CAPTURE_MARGIN is a deliberately generous upper bound for that
# unread remainder and is reported when the budget is exceeded.
_LOOKUP_READ_CHUNK = 64 * 1024
_LOOKUP_CAPTURE_MARGIN = 1024 * 1024
_LOOKUP_POLL_INTERVAL = 0.01
_LOOKUP_DRAIN_SECONDS = 5.0
_LOOKUP_REAP_SECONDS = 5.0


def _build_stdout_index(task_dir: str) -> Dict[str, List[tuple]]:
    """Return ``session_id -> [(path, mtime), ...]`` from one directory listing.

    The refresh needs two facts per session: the newest stdout mtime and whether
    any candidate process is alive. Resolving either fact per session lists the
    whole task directory, so a refresh of N sessions paid 2N listings of M
    entries. This index pays one listing and both consumers read it.

    Entries keep the ``os.listdir`` order because the newest-file rule resolves
    equal mtimes to the first entry in listing order. Non-file entries and
    entries whose mtime cannot be read are skipped, matching
    :func:`cli_topsailai.log_files._find_session_stdout_file`.

    The key is the display identity, so a temporary session
    (``topsailai.{pid}.session.stdout``) is keyed by ``_TEMP_SESSION_ID``. That
    is exactly the equivalence :func:`cli_topsailai.process_liveness._matches_session`
    defines, which keeps lookup a single dictionary access instead of a scan
    over every session in the directory.
    """
    index: Dict[str, List[tuple]] = {}
    try:
        entries = os.listdir(task_dir)
    except OSError:
        return index

    for entry in entries:
        if not entry.endswith(".session.stdout"):
            continue
        full_path = os.path.join(task_dir, entry)
        if not os.path.isfile(full_path):
            continue
        parsed_session_id, _pid = _parse_stdout_filename(entry)
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            continue
        key = parsed_session_id if parsed_session_id is not None else _TEMP_SESSION_ID
        index.setdefault(key, []).append((full_path, mtime))
    return index


def _index_candidates(index: Dict[str, List[tuple]], session_id: str) -> List[tuple]:
    """Return the indexed candidates that belong to *session_id*.

    The index is keyed by display identity, so this is one dictionary lookup.
    """
    return index.get(session_id, [])


def _check_session_running(
    home: str,
    session_id: str,
    index: Optional[Dict[str, List[tuple]]] = None,
) -> bool:
    """Check whether *session_id* has a live session process.

    Every ``{session_id}.{pid}.session.stdout`` candidate is inspected, because
    a newer dead file must not hide an older live process. An unverifiable
    candidate is reported as not running: this is a display path, so it must
    never claim a session is running when the OS refuses to answer.

    When *index* is supplied the directory is not listed again, so a batch
    caller pays one listing instead of one per session.
    """
    if not session_id:
        return False
    if index is None:
        return session_liveness(session_id, home=home) == "live"

    candidates = _index_candidates(index, session_id)
    if not candidates:
        return False
    for path, _mtime in candidates:
        if pid_state(_get_pid_from_stdout_path(path)) is ProcessState.ALIVE:
            return True
    # An unverifiable candidate is not running: this is a display path, so it
    # must never claim a session is running when the OS refuses to answer.
    return False


def _resolve_session_mtime(
    task_dir: str,
    session_id: str,
    index: Optional[Dict[str, List[tuple]]] = None,
) -> Optional[float]:
    """Return the modification time of the most recent session stdout file.

    The newest ``*.session.stdout`` file for *session_id* decides the value. If
    no stdout file exists, returns ``None`` so callers can fall back to another
    timestamp (e.g. ``create_time``).

    When *index* is supplied the directory is not listed again. The newest-file
    rule is reproduced exactly: sort by mtime descending, and because the sort
    is stable, an equal mtime resolves to the first entry in listing order.
    """
    if index is None:
        stdout_path = _find_session_stdout_file(task_dir, session_id)
        if not stdout_path:
            return None
        try:
            return os.path.getmtime(stdout_path)
        except OSError:
            return None

    candidates = _index_candidates(index, session_id)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates[0][1]


def _enrich_running_status(
    entries: List[Dict[str, Any]],
    index: Optional[Dict[str, List[tuple]]] = None,
) -> None:
    """Add a ``status`` field to each entry from one stdout directory listing.

    Running status is determined by probing the embedded PID of every
    ``*.session.stdout`` candidate for the session. The directory is listed once
    for the whole batch, so the cost does not grow with the number of entries.
    """
    if not entries:
        return

    home = get_topsailai_home()
    if index is None:
        task_dir = os.path.join(home, "workspace", "task")
        index = _build_stdout_index(task_dir)

    for entry in entries:
        try:
            is_running = _check_session_running(
                home, entry.get("session_id", ""), index=index
            )
        except Exception:
            is_running = False
        entry["status"] = "Running" if is_running else "Idle"


def _format_time(time_value: str) -> str:
    """Format an ISO timestamp string for the project table."""
    if not time_value:
        return "-"
    try:
        dt = datetime.fromisoformat(time_value)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return time_value


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
    limit: Optional[int] = 10,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build the list of recent sessions with a project workspace.

    Runs ``topsailai_list_sessions --json --has-project --sort desc`` with an
    optional session ID and limit, then parses the JSON output. Sessions are
    then re-sorted by the modification time of their most recent
    ``*.session.stdout`` file (oldest first, newest last). When a session has
    no stdout file, its ``create_time`` is used as a fallback.

    Each entry is enriched with a ``status`` field (``Running`` or ``Idle``)
    by scanning ``{TOPSAILAI_HOME}/workspace/task/`` for the most recent
    ``*.session.stdout`` file and checking whether its embedded PID is alive.
    Status checks run concurrently in a thread pool.

    Args:
        limit: Maximum number of sessions to return, or ``None`` for no limit.
        session_id: Optional exact session ID to retrieve.

    Returns:
        List of session dictionaries with keys ``no``, ``session_id``,
        ``session_name``, ``project_workspace``, ``modified_time``,
        ``modified_time_raw``, ``task``, and ``status``.
    """
    cmd = [
        "topsailai_list_sessions",
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
            f"{Colors.RED}[ERROR] Failed to run topsailai_list_sessions: {exc}{Colors.RESET}"
        )
        return []

    if result.returncode != 0:
        stderr = result.stderr.strip()
        print(
            f"{Colors.RED}[ERROR] topsailai_list_sessions failed: {stderr}{Colors.RESET}"
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

    home = get_topsailai_home()
    task_dir = os.path.join(home, "workspace", "task")
    # One listing serves both the mtime sort and the running-status enrichment.
    stdout_index = _build_stdout_index(task_dir)

    entries = []
    for session in sessions:
        session_id_value = session.get("session_id") or ""
        create_time_raw = session.get("create_time") or ""
        mtime = _resolve_session_mtime(task_dir, session_id_value, index=stdout_index)
        if mtime is not None:
            modified_time_raw = datetime.fromtimestamp(mtime).isoformat()
        else:
            modified_time_raw = create_time_raw
        entries.append(
            {
                "session_id": session_id_value,
                "session_name": session.get("session_name") or "",
                "project_workspace": session.get("project_workspace") or "",
                "modified_time_raw": modified_time_raw,
                "create_time_raw": create_time_raw,
                "task": session.get("task") or "",
                "_mtime": mtime if mtime is not None else 0.0,
                "_fallback_time": create_time_raw,
            }
        )

    # Sort oldest-first by stdout mtime. Entries without a stdout file fall
    # back to their create_time for stable ordering.
    entries.sort(
        key=lambda e: (
            e["_mtime"] if e["_mtime"] else datetime.fromisoformat(
                e["_fallback_time"]
            ).timestamp() if e["_fallback_time"] else 0.0
        )
    )

    # Assign visible row numbers after sorting and drop internal sort keys.
    for idx, entry in enumerate(entries, start=1):
        entry["no"] = idx
        entry["modified_time"] = _format_time(entry["modified_time_raw"])
        entry.pop("_mtime", None)
        entry.pop("_fallback_time", None)

    _enrich_running_status(entries, index=stdout_index)
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
    w_project = 24
    w_modified = 14
    w_name = 23

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {'No':^{w_no}} |"
        f" {_fit_table_cell('Session Name', w_name, 'center')} |"
        f" {'Session ID':^{w_session}} |"
        f" {'Modified':^{w_modified}} |"
        f" {_fit_table_cell('Project Workspace', w_project, 'center')} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_session + 2)}+"
        f"{'-' * (w_modified + 2)}+"
        f"{'-' * (w_project + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for entry in entries:
        session_id = entry.get("session_id") or "-"
        if len(session_id) > w_session:
            session_id = session_id[: w_session - 3] + "..."

        project = entry.get("project_workspace") or "-"
        modified = entry.get("modified_time") or "-"
        session_name = entry.get("session_name") or "-"

        status = entry.get("status") or "Idle"
        row_color = Colors.GREEN if status == "Running" else Colors.RESET

        row = (
            f"{row_color}"
            f" {entry['no']:^{w_no}} |"
            f" {_fit_table_cell(session_name, w_name)} |"
            f" {session_id:<{w_session}} |"
            f" {modified:^{w_modified}} |"
            f" {_fit_table_cell(project, w_project, truncate_from='head')} "
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
    entries: List[Dict[str, Any]],
    limit: int = 10,
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
    """Return a unique tmux session name for agent launches.

    tmux rewrites ``.`` and ``:`` in session names, so a name containing them
    cannot be addressed later with ``has-session``/``kill-session``. The
    generated name therefore uses only characters tmux preserves verbatim,
    which keeps the owned session addressable for an exact stop.
    """
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S_%f")
    return f"topsailai-{timestamp}"


def _apply_selected_model_environment(
    project_workspace: str,
) -> Optional[tuple[Dict[str, Optional[str]], set[str]]]:
    """Apply the selected model and return restore values and forwarded keys."""
    from cli_topsailai.models import (
        ModelConfigurationError,
        build_model_environment,
        load_models,
        resolve_effective_model,
    )

    registry = load_models()
    try:
        effective = resolve_effective_model(
            registry.models,
            project_workspace=project_workspace,
        )
        if effective.model is None:
            return {}, set()
        model = effective.model
        child_environment, warnings = build_model_environment(model, os.environ)
    except ModelConfigurationError as error:
        print(f"{Colors.RED}[ERROR] Cannot apply selected model: {error}{Colors.RESET}")
        return None

    for warning in warnings:
        print(f"{Colors.YELLOW}[WARN] {warning}{Colors.RESET}")

    forwarded_keys = set(model.environment)
    forwarded_keys.add("OPENAI_MODEL")
    if model.base_url:
        forwarded_keys.update(("OPENAI_BASE_URL", "OPENAI_API_BASE"))
    source_targets = (
        (model.api_key_env, "OPENAI_API_KEY"),
        (model.organization_env, "OPENAI_ORG_ID"),
        (model.project_env, "OPENAI_PROJECT_ID"),
    )
    forwarded_keys.update(target for source, target in source_targets if source)
    changed_values = {
        key: child_environment[key]
        for key in forwarded_keys
        if key in child_environment and os.environ.get(key) != child_environment[key]
    }
    original_values = {key: os.environ.get(key) for key in changed_values}
    os.environ.update(changed_values)
    return original_values, forwarded_keys


def _restore_environment(original_values: Dict[str, Optional[str]]) -> None:
    """Restore environment values changed for one child launch."""
    for key, original_value in original_values.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value

def _tmux_supports_environment_option(tmux_path: str) -> bool:
    """Return whether *tmux_path* supports ``new-session -e``."""
    try:
        result = subprocess.run(
            [tmux_path, "-V"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False

    if result.returncode != 0:
        return False
    version_text = result.stdout.strip()
    if not version_text.startswith("tmux "):
        return False
    version = version_text[len("tmux "):].split()[0]
    # Tmux version strings may include suffixes such as "3.5a", "3.1-rc2",
    # or "next-3.4".  Extract the first MAJOR.MINOR pair and ignore the rest.
    version_match = re.search(r"(\d+)\.(\d+)", version)
    if version_match is None:
        return False
    major, minor = (int(part) for part in version_match.groups())
    return (major, minor) >= (3, 2)


def _tmux_safe_env_value(value: str) -> str:
    """Escape ``;`` in a value passed to ``tmux new-session -e KEY=value``.

    Tmux re-parses the environment VALUE as a command list separated by
    semicolons, so an unescaped ``;`` makes tmux treat the following token
    (for example ``-s`` or ``-e``) as a fresh standalone command.  Escape it
    with a backslash so tmux keeps the literal character.
    """
    return value.replace(";", r"\;")


def _wrap_command_for_agent_mode(
    command: str,
    mode: str,
    forwarded_environment: Optional[set[str]] = None,
    session_name: Optional[str] = None,
) -> str:
    """Wrap a command for raw, dtach, or tmux agent launch mode.

    Tmux receives the requested model environment explicitly because an
    existing tmux server may otherwise retain stale environment values.

    Args:
        session_name: Optional tmux session name. When omitted a unique name is
            generated. Callers that must stop the session later pass the name
            they generated so the owned session can be addressed exactly.
    """
    if mode == "raw":
        return command

    if mode == "dtach":
        if shutil.which("dtach") is None:
            return command
        socket_path = _build_dtach_socket_path()
        return f"dtach -A {shlex.quote(socket_path)} {command}"

    if mode == "tmux":
        tmux_path = shutil.which("tmux")
        if tmux_path is None:
            raise RuntimeError(
                "tmux is not installed or not found in PATH. "
                "Install tmux to use --agent-mode tmux, or choose raw/dtach."
            )
        if not _tmux_supports_environment_option(tmux_path):
            print(
                f"{Colors.YELLOW}[WARN] tmux does not support new-session -e; "
                f"falling back to dtach/raw mode.{Colors.RESET}"
            )
            return _wrap_command_for_agent_mode(
                command,
                "dtach",
                forwarded_environment,
            )
        if session_name is None:
            session_name = _generate_agent_session_name()
        forwarded_keys = {
            key for key in os.environ if key.startswith("TOPSAILAI_")
        }
        forwarded_keys.update(("PATH", "HOME", "SHELL", "USER", "PWD"))
        # Both accepted identity aliases must be forwarded explicitly: an
        # existing tmux server keeps its own environment, so an alias that is
        # not passed with ``-e`` can retain a stale or conflicting identity.
        forwarded_keys.update(_IDENTITY_ENV_KEYS)
        forwarded_keys.update(forwarded_environment or set())
        env_vars = {
            key: os.environ[key]
            for key in forwarded_keys
            if os.environ.get(key) is not None
        }
        env_args = " ".join(
            f"-e {shlex.quote(_tmux_safe_env_value(f'{key}={value}'))}"
            for key, value in sorted(env_vars.items())
        )
        env_part = f" {env_args}" if env_args else ""
        return (
            f"tmux new-session{env_part} -s {shlex.quote(session_name)} {command}"
        )

    raise ValueError(f"Unsupported agent launch mode: {mode!r}")

def launch_agent_in_folder(folder: str, agent_mode: str = "dtach", *, spawn=None) -> None:
    """Launch a fresh configured agent through the shared launch boundary."""
    from cli_topsailai.agent_launch import launch_configured_agent

    launch_configured_agent(
        os.path.abspath(folder), mode=agent_mode, background=False, spawn=spawn
    )

def _stop_owned_driver(ownership, child) -> bool:
    """Stop the whole owned driver tree and prove the driver is gone.

    Returns:
        ``True`` when the driver is proven gone, otherwise ``False`` so the
        caller can report unresolved custody instead of claiming success.
    """
    return stop_owned_driver(ownership, child)


def _spawn_owned_child(argv, **kwargs):
    """Create the directly owned production child for one resume launch."""
    return subprocess.Popen(argv, **kwargs)


def _driver_argv(driver: str) -> List[str]:
    """Split a driver command line into an executable and its arguments.

    A driver value is a command line, so a custom driver may carry arguments.
    Splitting here keeps the driver a directly owned child instead of handing
    the whole string to a shell.

    Raises:
        ValueError: The command line is empty or cannot be parsed.
    """
    try:
        argv = shlex.split(driver)
    except ValueError as error:
        raise ValueError(f"invalid driver command line: {error}") from error
    if not argv:
        raise ValueError("driver command line is empty")
    return argv


def _driver_is_resolvable(argv: List[str]) -> bool:
    """Return whether the driver executable in *argv* can be resolved.

    A missing executable must be reported as a launch failure instead of
    leaking the shell's ``127`` status.
    """
    if not argv:
        return False
    executable = argv[0]
    separators = [sep for sep in (os.sep, os.altsep) if sep]
    if any(sep in executable for sep in separators):
        return os.path.isfile(executable) and os.access(executable, os.X_OK)
    return shutil.which(executable) is not None


def _ownership_wrapper(command: str, pidfile: str) -> str:
    """Wrap *command* so the driver records its own PID before it execs.

    ``dtach`` daemonizes and ``tmux`` runs the driver inside a server, so the
    driver is not the direct child in those modes. Recording the driver PID
    inside the wrapper gives the caller an exact identity to stop.
    """
    inner = f"echo $$ > {shlex.quote(pidfile)}; exec {command}"
    return f"sh -c {shlex.quote(inner)}"


def _build_owned_command(
    driver: str,
    mode: str,
    forwarded_environment: Optional[set[str]],
    session_name: Optional[str],
    pidfile: str,
) -> tuple[str, "DriverOwnership"]:
    """Return the command to run and the ownership record for one launch.

    The effective mode is derived from the produced command because the tmux
    wrapper may fall back to dtach or raw when tmux lacks ``new-session -e``.
    """
    if mode == "raw":
        return driver, DriverOwnership(kind="raw")
    wrapped = _ownership_wrapper(driver, pidfile)
    command = _wrap_command_for_agent_mode(
        wrapped, mode, forwarded_environment, session_name,
    )
    if command.startswith("tmux new-session"):
        return command, DriverOwnership(
            kind="tmux", pidfile=pidfile, session_name=session_name,
        )
    if command.startswith("dtach -A"):
        return command, DriverOwnership(kind="dtach", pidfile=pidfile)
    # The wrapper fell back to raw: the recorded PID is still the driver.
    return command, DriverOwnership(kind="raw")


def _build_driver_pidfile() -> str:
    """Return an absolute path where a wrapped driver records its own PID.

    The file lives under the task directory so it sits beside the other
    session runtime artifacts, and the directory is created on demand.
    """
    home = get_topsailai_home()
    task_dir = os.path.join(home, "workspace", "task")
    os.makedirs(task_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S.%f")
    return os.path.join(task_dir, f"{timestamp}.driver.pid")


def launch_agent_driver(
    folder: str, driver: str, session_id: str, agent_mode: str = "dtach",
    *, spawn=None, emit_status: bool = True,
    prelaunch_check: Optional[Callable[[], Optional[int]]] = None,
    receipt: Optional[Dict[str, Any]] = None, child_stdout=None,
) -> int:
    """Launch a resume driver with the selected model environment.

    The target workspace, session ID, and effective model configuration are
    applied only for the child launch and restored immediately afterward.

    The persisted session identity is exported through both accepted aliases so
    the resumed worker observes the same session it was resumed from.

    The driver value is a command line: it is split into an executable and its
    arguments, so a custom driver may carry arguments while the driver itself
    stays a directly owned child. In ``dtach`` and ``tmux`` modes the driver is
    not the direct child, so the wrapper records the driver PID and the whole
    owned tree is stopped on interruption.

    Args:
        prelaunch_check: Optional late revalidation invoked after preparation
            and immediately before the child is spawned. It returns ``None`` to
            proceed or a status code to refuse the launch.

    Returns:
        ``0`` on success, ``4`` when preparation fails, ``5`` when the launch
        cannot be started, ``6`` when custody or restoration cannot be proven,
        ``130`` after an interrupt, or the child exit code.
    """
    original_cwd = os.getcwd()
    original_env: Dict[str, Optional[str]] = {
        key: os.environ.get(key) for key in _LAUNCH_ENV_KEYS
    }
    model_restore: Dict[str, Optional[str]] = {}
    factory = spawn or _spawn_owned_child
    pidfile: Optional[str] = None

    def record(**facts) -> None:
        """Publish only resume facts established by this launch boundary."""
        if receipt is not None:
            receipt.update(facts)

    record(
        session_id=session_id, workspace=os.path.abspath(folder),
        mode=agent_mode, background=False, resumed=True,
    )

    def _run_owned_launch() -> int:
        """Prepare, revalidate and run one owned resume child."""
        nonlocal pidfile
        target_folder = os.path.abspath(folder)
        try:
            os.chdir(target_folder)
            os.environ["TOPSAILAI_PWD"] = target_folder
            os.environ["PWD"] = target_folder
            os.environ["TOPSAILAI_SESSION_ID"] = session_id
            os.environ["SESSION_ID"] = session_id
            model_environment = _apply_selected_model_environment(target_folder)
            if model_environment is None:
                return 4
            model_restore.update(model_environment[0])
            forwarded_keys = model_environment[1]
            if emit_status:
                print(
                    f"{Colors.GREEN}[INFO] Launching driver '{driver}' in "
                    f"{target_folder} for session '{session_id}' "
                    f"(mode: {agent_mode}) ...{Colors.RESET}"
                )
            driver_argv = _driver_argv(driver)
            session_name = (
                _generate_agent_session_name() if agent_mode == "tmux" else None
            )
            if agent_mode == "raw":
                command, ownership = _build_owned_command(
                    driver, agent_mode, forwarded_keys, session_name, "",
                )
            else:
                pidfile = _build_driver_pidfile()
                command, ownership = _build_owned_command(
                    driver, agent_mode, forwarded_keys, session_name, pidfile,
                )
        except (RuntimeError, ValueError, OSError) as exc:
            print(
                f"{Colors.RED}[ERROR] Resume preparation failed: {exc}{Colors.RESET}"
            )
            return 4
        if not _driver_is_resolvable(driver_argv):
            print(
                f"{Colors.RED}[ERROR] Driver executable not found: "
                f"{driver_argv[0]}{Colors.RESET}"
            )
            return 5
        # Late fail-closed revalidation: the caller rechecks liveness and the
        # workspace after preparation and immediately before the launch.
        if prelaunch_check is not None:
            refusal = prelaunch_check()
            if refusal is not None:
                return refusal
        if ownership.kind == "raw":
            argv = driver_argv
            kwargs = {
                "cwd": target_folder,
                "env": os.environ.copy(),
                "start_new_session": True,
            }
        else:
            argv = command
            kwargs = {"cwd": target_folder, "env": os.environ.copy(), "shell": True}
            if ownership.kind != "tmux":
                # dtach daemonizes, so the direct child must lead its own
                # session for the wrapper group to be addressable.
                kwargs["start_new_session"] = True
        if child_stdout is not None:
            kwargs["stdout"] = child_stdout
        try:
            child = factory(argv, **kwargs)
        except (OSError, ValueError) as exc:
            print(
                f"{Colors.RED}[ERROR] Failed to launch driver '{driver}': {exc}{Colors.RESET}"
            )
            return 5
        record(launcher_pid=getattr(child, "pid", None), startup_confirmed=False,
               spawn_confirmed=True)
        try:
            code = child.wait()
        except KeyboardInterrupt:
            if not _stop_owned_driver(ownership, child):
                record(effect_uncertain=True)
                print(
                    f"{Colors.RED}[ERROR] Resume custody unresolved: "
                    f"session={session_id} "
                    f"{describe_ownership(ownership, child)}{Colors.RESET}"
                )
                return 6
            record(cancellation_confirmed=True)
            print(
                f"{Colors.YELLOW}[WARN] Resume interrupted: session={session_id}{Colors.RESET}"
            )
            return 130
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"{Colors.RED}[ERROR] Resume wait failed: {exc}{Colors.RESET}")
            if not _stop_owned_driver(ownership, child):
                record(effect_uncertain=True)
                print(
                    f"{Colors.RED}[ERROR] Resume custody unresolved: "
                    f"session={session_id} "
                    f"{describe_ownership(ownership, child)}{Colors.RESET}"
                )
                return 6
            return 5
        record(child_exit_code=code, launcher_exit_observed=True)
        return code if code >= 0 else 128 + (-code)

    result = 4
    try:
        result = _run_owned_launch()
    except KeyboardInterrupt:
        print(
            f"{Colors.YELLOW}[WARN] Resume interrupted: session={session_id}{Colors.RESET}"
        )
        result = 130
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"{Colors.RED}[ERROR] Resume launch failed: {exc}{Colors.RESET}")
        result = 4
    finally:
        remove_pidfile(pidfile)
        _restore_environment(model_restore)
        for key in _LAUNCH_ENV_KEYS:
            original_value = original_env[key]
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value
        try:
            os.chdir(original_cwd)
        except OSError as exc:
            # A launch that cannot restore the caller's working directory is
            # not a clean success, so the status must reflect the failure.
            print(
                f"{Colors.RED}[ERROR] Failed to restore working directory "
                f"'{original_cwd}': {exc}{Colors.RESET}"
            )
            result = 6
    return result

def _prompt_for_driver() -> str:
    """Prompt the user to select an agent driver for resuming a session.

    Presents a numbered list of built-in drivers plus a custom-input option.
    The default selection is ``_RESUME_DEFAULT_DRIVER``, so pressing Enter
    always agrees with the non-interactive resume default.

    Returns:
        The selected driver command string.
    """
    print("\nSelect an agent driver to resume the session:")
    for idx, driver in enumerate(_RESUME_DRIVER_OPTIONS, start=1):
        print(f"  {idx}. {driver}")
    print(f"  {len(_RESUME_DRIVER_OPTIONS) + 1}. (custom input)")

    default_option = _RESUME_DRIVER_OPTIONS.index(_RESUME_DEFAULT_DRIVER) + 1
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
    arg: str, entries: List[Dict[str, Any]], agent_mode: str = "dtach", *,
    driver: Optional[str] = None,
) -> bool:
    """Resume an idle session with the selected built-in agent driver.

    The explicit driver wins; otherwise the chats driver is selected without
    prompting. Existing row, workspace, refusal and boolean behavior remains.
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

    selected_driver = driver or _RESUME_DEFAULT_DRIVER
    if selected_driver not in _RESUME_DRIVER_OPTIONS:
        print(
            f"{Colors.RED}[ERROR] Unsupported resume driver: {selected_driver}{Colors.RESET}"
        )
        return False
    print(
        f"{Colors.GREEN}[INFO] Resuming session '{session_id}' with driver '{selected_driver}' "
        f"in {project_workspace} (mode: {agent_mode}) ...{Colors.RESET}"
    )
    launch_agent_driver(
        project_workspace, selected_driver, session_id, agent_mode=agent_mode
    )
    return True


class ResumeLookupError(RuntimeError):
    """Raised when the authoritative session lookup cannot be trusted."""


class ResumeNotFoundError(ResumeLookupError):
    """Raised when no unique persisted session matches the requested identity."""


def session_liveness(session_id: str, *, home: Optional[str] = None) -> str:
    """Return ``live``, ``idle`` or ``unknown`` for a persisted session.

    Every native session stdout candidate is inspected. A single live process
    proves the session is running; an unverifiable candidate makes the answer
    ``unknown`` so the caller fails closed rather than resuming a live session.
    """
    return _liveness_session_liveness(session_id, home=home)


def lookup_persisted_session(
    session_id: str, *, query: Optional[Callable[[str], Any]] = None
) -> Dict[str, Any]:
    """Return the single persisted record for an exact session identity.

    Exactly one authoritative query is issued. A failed query, malformed
    payload or ambiguous result is reported as an error instead of being
    reinterpreted as an empty (idle) result.

    Raises:
        ResumeNotFoundError: when no record matches the exact identity.
        ResumeLookupError: when the lookup itself cannot be trusted.
    """
    from cli_topsailai.runtime_target import _valid_session

    if not _valid_session(session_id):
        raise ResumeLookupError("invalid session identifier")
    runner = query or _query_session_records
    try:
        records = runner(session_id)
    except ResumeLookupError:
        raise
    except Exception as error:
        raise ResumeLookupError(f"session lookup failed: {error}") from error
    if not isinstance(records, list):
        raise ResumeLookupError("session lookup returned an unexpected payload")
    # A malformed entry makes the whole payload untrustworthy: silently
    # filtering it could turn a real record into a false "not found".
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ResumeLookupError(
                f"session lookup returned a malformed record at index {index}"
            )
        if not isinstance(record.get("session_id"), str):
            raise ResumeLookupError(
                f"session lookup record at index {index} has no session identity"
            )
    matches = [
        record for record in records
        if record.get("session_id") == session_id
    ]
    if not matches:
        raise ResumeNotFoundError(f"no persisted session matches '{session_id}'")
    if len(matches) > 1:
        raise ResumeLookupError(
            f"session lookup is ambiguous for '{session_id}' ({len(matches)} records)"
        )
    return matches[0]


class _LookupChannel:
    """Capture one child channel under a hard in-flight byte budget.

    The descriptor is read in bounded chunks by the caller's own thread and
    consumption stops the moment the budget is exceeded, so this process never
    holds more than ``limit`` bytes for the channel. Overflow is therefore
    detected while the child is still running, which lets the caller terminate
    it instead of discovering the problem only after the child has written
    everything.

    No reader thread is used: the descriptor is non-blocking and is pumped by
    the caller, so ``close`` only closes a raw descriptor and can never wait
    behind a reader that is blocked on an inherited write end.
    """

    def __init__(self, fd: int, limit: int) -> None:
        self._fd = fd
        self._limit = limit
        self._chunks: List[bytes] = []
        self._size = 0
        self.eof = False
        self.overflow = False
        self.error: Optional[BaseException] = None

    @property
    def fd(self) -> int:
        """Return the open descriptor, or -1 once it has been closed."""
        return self._fd

    def pump(self) -> None:
        """Read bounded chunks without ever blocking.

        The descriptor is non-blocking, so this drains whatever the kernel has
        buffered and returns as soon as the pipe is empty. Consumption stops
        immediately once the byte budget is exceeded.
        """
        while self._fd >= 0 and not self.eof and not self.overflow:
            try:
                chunk = os.read(self._fd, _LOOKUP_READ_CHUNK)
            except BlockingIOError:
                return
            except OSError as error:
                self.error = error
                self.eof = True
                return
            if not chunk:
                self.eof = True
                return
            remaining = self._limit - self._size
            if len(chunk) > remaining:
                # Keep only the budgeted prefix; the excess proves overflow.
                if remaining > 0:
                    self._chunks.append(chunk[:remaining])
                    self._size += remaining
                self.overflow = True
                return
            self._chunks.append(chunk)
            self._size += len(chunk)

    def close(self) -> None:
        """Close the raw descriptor; this never waits for a reader."""
        fd = self._fd
        self._fd = -1
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass

    @property
    def size(self) -> int:
        """Return the number of bytes retained for this channel."""
        return self._size

    def text(self) -> str:
        """Return the retained bytes decoded for diagnostics."""
        return b"".join(self._chunks).decode("utf-8", "replace")


def _lookup_command(session_id: str) -> List[str]:
    """Return the argv of the single authoritative session query."""
    return ["topsailai_list_sessions", "--json", "--", session_id]


def _reap_lookup_child(child, timeout: float) -> bool:
    """Wait for the child within *timeout*, surviving repeated interrupts.

    A second ``KeyboardInterrupt`` while reaping must not abandon the owned
    query, so the bounded wait is retried until it completes or the deadline
    passes.
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return child.poll() is not None
        try:
            child.wait(timeout=remaining)
            return True
        except subprocess.TimeoutExpired:
            return False
        except KeyboardInterrupt:
            continue


def _terminate_lookup_child(child) -> None:
    """Terminate and reap one lookup child by its exact PID.

    The child is signalled directly, never by name or process group, and is
    always reaped, so an overflow, timeout or interruption cannot leave an
    orphan query process behind. Every wait is bounded, so cleanup itself can
    never block indefinitely.
    """
    if child.poll() is None:
        try:
            child.terminate()
        except OSError as error:
            print(f"[WARN] Cannot terminate lookup process {child.pid}: {error}")
    if _reap_lookup_child(child, _LOOKUP_REAP_SECONDS):
        return
    try:
        child.kill()
    except OSError as error:
        print(f"[WARN] Cannot kill lookup process {child.pid}: {error}")
    if not _reap_lookup_child(child, _LOOKUP_REAP_SECONDS):
        print(f"[WARN] Lookup process {child.pid} did not exit after SIGKILL")


def _lookup_diagnostic(stdout: str, stderr: str) -> str:
    """Combine both captured channels into one bounded diagnostic.

    ``topsailai_list_sessions`` reports failures on stdout, so reading only
    stderr would lose the real cause.
    """
    parts = []
    for label, text in (("stdout", stdout), ("stderr", stderr)):
        stripped = text.strip()
        if stripped:
            parts.append(f"{label}: {stripped}")
    return " | ".join(parts) if parts else "no diagnostic output"


def _open_lookup_pipes():
    """Create the two capture pipes, closing any partial result on failure.

    Non-blocking configuration is part of the same protected region as the
    pipe creation: ``os.set_blocking`` runs after the descriptors exist, so a
    failure there (or an interruption during setup) must still close every
    descriptor that was created. Otherwise the descriptors would be lost
    before the caller can take ownership of them.
    """
    out_read = out_write = err_read = err_write = -1
    try:
        out_read, out_write = os.pipe()
        err_read, err_write = os.pipe()
        for fd in (out_read, err_read):
            os.set_blocking(fd, False)
    except BaseException:
        for fd in (out_read, out_write, err_read, err_write):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        raise
    return out_read, out_write, err_read, err_write


def _pump_channels(channels, timeout: float) -> None:
    """Consume whatever is readable on the capture descriptors within *timeout*.

    Only channels that are still open and not yet at EOF are polled, so a
    finished channel cannot make ``select`` return immediately and spin the
    loop. When ``select`` cannot watch these descriptors the wait degrades to a
    bounded sleep followed by non-blocking reads, so the loop stays bounded and
    never busy-spins.
    """
    pending = [
        channel for channel in channels
        if channel.fd >= 0 and not channel.eof and not channel.overflow
    ]
    if not pending:
        time.sleep(timeout)
        return
    readable = None
    try:
        readable, _, _ = select.select(
            [channel.fd for channel in pending], [], [], timeout,
        )
    except (OSError, ValueError):
        readable = None
    if readable is None:
        time.sleep(min(timeout, _LOOKUP_POLL_INTERVAL))
        readable = [channel.fd for channel in pending]
    for channel in pending:
        if channel.fd in readable:
            channel.pump()


def _drain_lookup_channels(out_channel, err_channel) -> bool:
    """Drain both channels to EOF within the bounded drain window.

    Returns False when a channel is still open after the window, which happens
    when a descendant inherited the write end. The caller reports a lookup
    failure instead of blocking, and closing the raw descriptors afterwards
    never waits for a reader.
    """
    deadline = time.monotonic() + _LOOKUP_DRAIN_SECONDS
    while True:
        pending = [
            channel for channel in (out_channel, err_channel)
            if channel.fd >= 0 and not channel.eof and not channel.overflow
        ]
        if not pending:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        _pump_channels(pending, min(remaining, _LOOKUP_POLL_INTERVAL))


def _query_session_records(session_id: str) -> List[Dict[str, Any]]:
    """Run the single authoritative session query for one identity.

    The capture is bounded in both bytes and duration, and it is pumped by this
    thread from raw non-blocking descriptors: there is no reader thread, so no
    close can wait behind a blocked reader. The byte budget is enforced while
    the child is still writing, and the child is terminated and reaped on
    overflow, timeout or interruption, so no query process is left behind.
    Cleanup responsibility starts before the spawn, so an interruption at any
    point after the pipes exist still closes them and reaps the child.
    A failed command, an empty payload, oversized output or a malformed payload
    is reported as a lookup failure so it can never be reinterpreted as an
    empty (idle) result.
    """
    cmd = _lookup_command(session_id)
    try:
        out_read, out_write, err_read, err_write = _open_lookup_pipes()
    except OSError as error:
        raise ResumeLookupError(
            f"failed to run topsailai_list_sessions: {error}"
        ) from error
    try:
        out_channel = _LookupChannel(out_read, _LOOKUP_MAX_BYTES)
        err_channel = _LookupChannel(err_read, _LOOKUP_MAX_BYTES)
    except BaseException:
        # Channel construction is part of the protected region: an interruption
        # or exception here must not lose the descriptors that already exist.
        for fd in (out_read, out_write, err_read, err_write):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        raise
    child = None
    overflow = False
    timed_out = False
    drained = False
    returncode = None
    try:
        try:
            child = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=out_write,
                stderr=err_write,
                close_fds=True,
            )
        except Exception as error:
            raise ResumeLookupError(
                f"failed to run topsailai_list_sessions: {error}"
            ) from error
        finally:
            # The parent must not keep the write ends, otherwise EOF never
            # arrives. This also runs when the spawn itself failed.
            for fd in (out_write, err_write):
                try:
                    os.close(fd)
                except OSError:
                    pass
        deadline = time.monotonic() + _LOOKUP_TIMEOUT_SECONDS
        while True:
            _pump_channels((out_channel, err_channel), _LOOKUP_POLL_INTERVAL)
            if out_channel.overflow or err_channel.overflow:
                overflow = True
                break
            if child.poll() is not None:
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
        if overflow or timed_out:
            _terminate_lookup_child(child)
        drained = _drain_lookup_channels(out_channel, err_channel)
        overflow = overflow or out_channel.overflow or err_channel.overflow
        returncode = child.poll()
    except BaseException:
        # Interruption or any other exceptional exit must not leave the owned
        # query running; termination and reaping stay bounded.
        if child is not None:
            _terminate_lookup_child(child)
        raise
    finally:
        out_channel.close()
        err_channel.close()
    stdout = out_channel.text()
    stderr = err_channel.text()
    if timed_out:
        raise ResumeLookupError(
            f"topsailai_list_sessions timed out after "
            f"{_LOOKUP_TIMEOUT_SECONDS:g}s"
        )
    if overflow:
        raise ResumeLookupError(
            f"topsailai_list_sessions output exceeded {_LOOKUP_MAX_BYTES} bytes "
            f"(captured {out_channel.size} bytes on stdout, "
            f"{err_channel.size} bytes on stderr, "
            f"pipe margin {_LOOKUP_CAPTURE_MARGIN} bytes)"
        )
    # An unreadable channel makes the payload untrustworthy: reporting it as a
    # lookup failure keeps it from becoming a false "empty".
    if out_channel.error is not None or err_channel.error is not None:
        raise ResumeLookupError(
            "failed to read topsailai_list_sessions output: "
            f"{out_channel.error or err_channel.error}"
        )
    if not drained:
        raise ResumeLookupError(
            "topsailai_list_sessions output could not be drained within "
            f"{_LOOKUP_DRAIN_SECONDS:g}s"
        )
    if returncode != 0:
        raise ResumeLookupError(
            f"topsailai_list_sessions failed (status {returncode}): "
            f"{_lookup_diagnostic(stdout, stderr)}"
        )
    if not stdout.strip():
        raise ResumeLookupError(
            "topsailai_list_sessions produced no JSON payload: "
            f"{_lookup_diagnostic(stdout, stderr)}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ResumeLookupError(
            f"failed to parse session JSON: {error}: "
            f"{_lookup_diagnostic(stdout, stderr)}"
        ) from error
    if not isinstance(payload, list):
        raise ResumeLookupError("unexpected session JSON shape: expected list")
    return payload


def _validate_resume_workspace(record: Dict[str, Any]) -> str:
    """Return the persisted workspace after strict validation.

    The persisted value is authoritative: no caller cwd, history or task
    directory fallback is applied, and no directory is created. A workspace
    that exists but cannot be entered is rejected rather than launched into.
    """
    workspace = record.get("project_workspace")
    if not isinstance(workspace, str) or not workspace:
        raise ResumeLookupError("persisted session has no project workspace")
    if not os.path.isabs(workspace):
        raise ResumeLookupError(f"persisted workspace is not absolute: {workspace}")
    if not os.path.isdir(workspace):
        raise ResumeLookupError(f"persisted workspace is not a directory: {workspace}")
    if not os.access(workspace, os.R_OK | os.X_OK):
        raise ResumeLookupError(
            f"persisted workspace is not accessible: {workspace}"
        )
    return workspace


def _session_stdout_snapshot(
    session_id: str, *, home: Optional[str] = None,
) -> List[str]:
    """Return the stdout files that exist for *session_id* before a launch.

    The snapshot is taken before the launch so a file created by the resumed
    run itself can never be mistaken for a leftover. A directory that cannot be
    listed yields an empty snapshot, which disables cleanup for this resume
    instead of guessing.
    """
    from cli_topsailai.process_liveness import _session_stdout_candidates

    base = home or get_topsailai_home()
    task_dir = os.path.join(base, "workspace", "task")
    try:
        return _session_stdout_candidates(task_dir, session_id)
    except OSError as error:
        print(
            f"{Colors.YELLOW}[WARN] Cannot list session stdout files for "
            f"'{session_id}': {error}{Colors.RESET}"
        )
        return []


def _delete_invalid_session_stdout(
    session_id: str, candidates: List[str], *, home: Optional[str] = None,
) -> List[str]:
    """Delete the pre-launch stdout leftovers that are proven invalid.

    Only *candidates* captured before the launch are considered, so the output
    of the resumed run itself is never removed. Each candidate is re-proven
    immediately before removal instead of trusting the earlier observation: the
    control channel is consulted first because a session may run in a sibling
    container that shares this filesystem, then the process table, then the
    open-descriptor check.

    Returns:
        The deleted paths. A candidate that cannot be proven invalid is kept,
        and a failed removal is reported as a warning instead of raising, so a
        cleanup problem never changes the resume result.
    """
    from cli_topsailai.log_files import is_file_in_use
    from cli_topsailai.process_liveness import (
        _get_pid_from_stdout_path,
        pid_state,
        socket_heartbeat_alive,
    )

    base = home or get_topsailai_home()
    deleted: List[str] = []
    for path in candidates:
        pid = _get_pid_from_stdout_path(path)
        # A heartbeat that answers proves the session is in use, so the file is
        # never a leftover even when the recorded PID differs.
        if socket_heartbeat_alive(session_id, pid, home=base) is True:
            continue
        if pid_state(pid) is not ProcessState.DEAD:
            continue
        if is_file_in_use(path):
            continue
        try:
            os.remove(path)
        except OSError as error:
            print(
                f"{Colors.YELLOW}[WARN] Failed to delete invalid session stdout "
                f"{path}: {error}{Colors.RESET}"
            )
            continue
        # A deletion must always be logged, so the removed path stays auditable.
        print(f"[INFO] Deleted invalid session stdout: {path}")
        deleted.append(path)
    return deleted


#: Bounded window for the resumed process to publish its control channel. A
#: healthy agent creates its socket within a few hundred milliseconds, so this
#: only bounds a slow or wedged startup.
RESUME_STARTUP_CONFIRM_SECONDS = 7.0

#: Poll interval while waiting for the resumed control channel to appear.
RESUME_STARTUP_POLL_SECONDS = 0.2


def _session_socket_pids(task_dir: str, session_id: str) -> List[int]:
    """Return the PIDs that published a control socket for *session_id*.

    A socket file outlives its owner, so this only enumerates candidates; the
    heartbeat decides whether one of them is actually reachable.
    """
    from cli_topsailai.process_liveness import _matches_session

    pids: List[int] = []
    try:
        entries = os.listdir(task_dir)
    except OSError:
        return pids
    suffix = ".session.sock"
    for entry in entries:
        if not entry.endswith(suffix):
            continue
        parts = entry[: -len(suffix)].split(".")
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid <= 0 or not _matches_session(".".join(parts[:-1]), session_id):
            continue
        pids.append(pid)
    return pids


def _new_session_pids(
    session_id: str, snapshot: List[str], *, home: Optional[str] = None,
) -> List[int]:
    """Return the PIDs that appeared for *session_id* after the launch.

    The pre-launch snapshot is the baseline, so a leftover PID is never mistaken
    for the process this resume started. Both the stdout file and the control
    socket are inspected because either one may be published first.
    """
    from cli_topsailai.process_liveness import (
        _get_pid_from_stdout_path,
        _session_stdout_candidates,
    )

    base = home or get_topsailai_home()
    task_dir = os.path.join(base, "workspace", "task")
    known = set()
    for path in snapshot:
        pid = _get_pid_from_stdout_path(path)
        if pid is not None:
            known.add(pid)
    found: List[int] = []
    try:
        current = _session_stdout_candidates(task_dir, session_id)
    except OSError:
        current = []
    for path in current:
        pid = _get_pid_from_stdout_path(path)
        if pid is not None and pid not in known and pid not in found:
            found.append(pid)
    for pid in _session_socket_pids(task_dir, session_id):
        if pid not in known and pid not in found:
            found.append(pid)
    return found


def _confirm_resumed_startup(
    session_id: str, snapshot: List[str], *, code: int, mode: str,
    background: bool, home: Optional[str] = None,
    timeout: float = RESUME_STARTUP_CONFIRM_SECONDS,
) -> Dict[str, Any]:
    """Prove the resumed process is reachable on its own control channel.

    A launcher exit code only reports what the wrapper did, so it cannot prove
    the resumed agent is running: ``dtach`` and ``tmux`` exit as soon as they
    have detached, and a background submission only proves delivery. The control
    channel is the authority instead, because the resumed process publishes its
    own socket and answers a heartbeat on it.

    A foreground ``raw`` resume is the one exception: the agent itself is the
    child, so its exit status already reports the completed run and no channel
    survives it.

    Returns:
        The confirmation facts: ``startup_confirmed``, ``startup_pid`` and
        ``startup_reason``.
    """
    from cli_topsailai.process_liveness import (
        HEARTBEAT_TIMEOUT_SECONDS,
        socket_heartbeat_alive,
    )

    if code != 0:
        return {
            "startup_confirmed": False,
            "startup_pid": None,
            "startup_reason": "launch_failed",
        }
    if mode == "raw" and not background:
        return {
            "startup_confirmed": True,
            "startup_pid": None,
            "startup_reason": "foreground_raw_exited",
        }
    base = home or get_topsailai_home()
    deadline = time.monotonic() + max(timeout, 0.0)
    # At least one probe is always attempted, so a zero-length window still
    # performs an immediate check instead of reporting a failure it never tried.
    first_pass = True
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 and not first_pass:
            break
        for pid in _new_session_pids(session_id, snapshot, home=base):
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not first_pass:
                break
            # Each probe is bounded by what is left of the window, so a socket
            # that accepts a connection but never answers cannot stretch the
            # confirmation past the stated deadline.
            budget = min(HEARTBEAT_TIMEOUT_SECONDS, remaining) if remaining > 0 else 0.0
            if socket_heartbeat_alive(
                session_id, pid, home=base, timeout=budget,
            ) is True:
                return {
                    "startup_confirmed": True,
                    "startup_pid": pid,
                    "startup_reason": "heartbeat_answered",
                }
        first_pass = False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(RESUME_STARTUP_POLL_SECONDS, remaining))
    return {
        "startup_confirmed": False,
        "startup_pid": None,
        "startup_reason": "heartbeat_unreachable",
    }


def resume_session_result(
    session_id: str, *, agent_mode: Optional[str] = None, background: bool = False,
    spawn=None, prompt_driver: bool = False, driver: Optional[str] = None,
    emit_status: bool = True, prelaunch: Optional[Callable[[Dict[str, Any]], None]] = None,
    query: Optional[Callable[[str], Any]] = None, home: Optional[str] = None,
    entrypoint_base: Optional[str] = None,
    receipt: Optional[Dict[str, Any]] = None, child_stdout=None,
) -> int:
    """Resume one exact persisted session and return a definite status code.

    The persisted identity is resolved once, validated, revalidated immediately
    before launch, and then handed to the shared launch boundary. The persisted
    session ID is preserved in both identity environment aliases; no fresh
    identity is generated for a resume.

    *agent_mode* selects the launch mechanism. When it is omitted the foreground
    default stays ``dtach`` while a background resume defaults to ``raw``, so a
    background request never depends on an external terminal multiplexer.

    Returns:
        ``0`` on success, ``3`` when the identity is missing or ambiguous,
        ``4`` when the lookup, workspace or liveness cannot be trusted,
        ``5``/``6``/``130`` from the launch boundary, or the child exit code.
    """
    effective_mode = agent_mode or ("raw" if background else "dtach")

    def record_receipt(**facts) -> None:
        """Publish resume facts as soon as they become authoritative."""
        if receipt is not None:
            receipt.update(facts)

    record_receipt(
        session_id=session_id, mode=effective_mode,
        background=background, resumed=True,
    )
    try:
        record = lookup_persisted_session(session_id, query=query)
        workspace = _validate_resume_workspace(record)
    except ResumeNotFoundError as error:
        print(f"{Colors.RED}[ERROR] {error}{Colors.RESET}")
        return 3
    except ResumeLookupError as error:
        print(f"{Colors.RED}[ERROR] {error}{Colors.RESET}")
        return 4
    record_receipt(workspace=workspace)

    liveness = session_liveness(session_id, home=home)
    if liveness == "live":
        print(
            f"{Colors.RED}[ERROR] Session '{session_id}' is already running and "
            f"cannot be resumed.{Colors.RESET}"
        )
        return 4
    if liveness != "idle":
        print(
            f"{Colors.RED}[ERROR] Session '{session_id}' liveness cannot be "
            f"verified; refusing to resume.{Colors.RESET}"
        )
        return 4

    if prelaunch is not None:
        try:
            prelaunch(record)
        except ResumeLookupError as error:
            print(f"{Colors.RED}[ERROR] {error}{Colors.RESET}")
            return 4

    selected_driver = driver
    if selected_driver is None:
        selected_driver = _RESUME_DEFAULT_DRIVER
    if prompt_driver and driver is None:
        selected_driver = _prompt_for_driver()
    record_receipt(driver=selected_driver)

    def late_check() -> Optional[int]:
        """Revalidate workspace and liveness at the launch boundary.

        This runs after model/wrapper preparation and immediately before the
        child is spawned or the supervisor is submitted, so a session that
        became live during preparation is refused instead of resumed.
        """
        try:
            _validate_resume_workspace(record)
        except ResumeLookupError as error:
            print(f"{Colors.RED}[ERROR] {error}{Colors.RESET}")
            return 4
        late_liveness = session_liveness(session_id, home=home)
        if late_liveness == "live":
            print(
                f"{Colors.RED}[ERROR] Session '{session_id}' became live before "
                f"launch; refusing to resume.{Colors.RESET}"
            )
            return 4
        if late_liveness != "idle":
            print(
                f"{Colors.RED}[ERROR] Session '{session_id}' liveness cannot be "
                f"verified at launch; refusing to resume.{Colors.RESET}"
            )
            return 4
        return None

    if emit_status:
        print(
            f"{Colors.GREEN}[INFO] Resuming session '{session_id}' with driver "
            f"'{selected_driver}' in {workspace} (mode: {effective_mode}) ...{Colors.RESET}"
        )
    # Snapshot the leftovers before the launch so the output produced by the
    # resumed run itself can never be mistaken for an invalid leftover.
    stdout_snapshot = _session_stdout_snapshot(session_id, home=home)
    if background:
        from cli_topsailai.agent_launch import launch_configured_agent

        code = launch_configured_agent(
            workspace, mode=effective_mode, background=True, spawn=spawn,
            session_id=session_id, driver=selected_driver,
            entrypoint_base=entrypoint_base, prelaunch_check=late_check,
            receipt=receipt, child_stdout=child_stdout,
        )
    else:
        code = launch_agent_driver(
            workspace, selected_driver, session_id, agent_mode=effective_mode,
            spawn=spawn, emit_status=False, prelaunch_check=late_check,
            receipt=receipt, child_stdout=child_stdout,
        )
    # A launcher exit code only reports what the wrapper did, so the resumed
    # process must prove itself on its own control channel before the resume is
    # reported as successful.
    startup = _confirm_resumed_startup(
        session_id, stdout_snapshot, code=code, mode=effective_mode,
        background=background, home=home,
    )
    record_receipt(**startup)
    if not startup["startup_confirmed"]:
        # A launch that already failed keeps its own status, so the caller can
        # still tell a spawn failure from an unreachable control channel.
        if code != 0:
            return code
        print(
            f"{Colors.RED}[ERROR] Session '{session_id}' did not answer on its "
            f"control channel; the resumed agent is not running.{Colors.RESET}"
        )
        return 4
    # The resume already proved every stdout candidate of this session idle, so
    # the leftovers are removed only after the resumed process answered. A
    # cleanup problem is reported but never changes the resume result.
    record_receipt(
        cleaned_stdout=_delete_invalid_session_stdout(
            session_id, stdout_snapshot, home=home
        )
    )
    return code
