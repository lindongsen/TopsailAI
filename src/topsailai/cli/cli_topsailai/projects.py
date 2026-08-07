"""Managed project list persistence and display for the TopsailAI CLI.

Projects are stored as JSONL lines in ``{TOPSAILAI_HOME}/.projects.jsonl``.
Each line is a JSON object with the following schema:

    {
        "name": "display name",
        "path": "/absolute/path/to/project",
        "created_at": "2026-07-25T08:15:05",
        "updated_at": "2026-07-25T08:15:05"
    }

The list is kept sorted by ``created_at`` (oldest first) so that row numbers
remain stable across sessions and match the README list-sorting convention.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from typing import Any, Dict, Optional

from cli_topsailai.colors import Colors
from cli_topsailai.paths import get_topsailai_home


def _get_projects_path() -> str:
    """Return the absolute path to ``.projects.jsonl`` under TOPSAILAI_HOME."""
    return os.path.join(get_topsailai_home(), ".projects.jsonl")

def _now_iso() -> str:
    """Return the current local time as an ISO-8601 string."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _resolve_project_path(raw_path: str) -> Optional[str]:
    """Expand and normalize a user-provided project path.

    Supports ``~`` and environment variables. Relative paths are resolved
    against ``$PWD`` when it is set so that shell working-directory context
    is honored. Returns an absolute path string or ``None`` if the path
    cannot be resolved.
    """
    if not raw_path:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw_path.strip()))
    if not os.path.isabs(expanded):
        cwd = os.environ.get("PWD", os.getcwd())
        expanded = os.path.join(cwd, expanded)
    try:
        return os.path.abspath(expanded)
    except OSError:
        return None


def load_projects() -> List[Dict[str, Any]]:
    """Load all managed projects from ``.projects.jsonl``.

    Returns:
        List of project dictionaries sorted by ``created_at`` (oldest first).
        Invalid lines are skipped silently.
    """
    path = _get_projects_path()
    if not os.path.exists(path):
        return []

    projects: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    project = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(project, dict) and project.get("path"):
                    projects.append(project)
    except OSError:
        return []
    projects.sort(key=lambda p: p.get("created_at", ""))
    return projects


def save_projects(projects: List[Dict[str, Any]]) -> bool:
    """Persist the managed project list atomically.

    Writes to a temporary file in the same directory and then renames it into
    place so concurrent readers never see a partially-written file.

    Args:
        projects: List of project dictionaries to persist.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    path = _get_projects_path()
    directory = os.path.dirname(path)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        return False

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=".projects.jsonl.tmp", suffix=".jsonl"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for project in projects:
                    fh.write(json.dumps(project, ensure_ascii=False) + "\n")
            os.replace(tmp_path, path)
            return True
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False
    except OSError:
        return False


def has_project_path(raw_path: str) -> bool:
    """Check whether a project with the given path already exists.

    The path is expanded and normalized before comparison so that relative
    paths, ``~`` references, and environment variables resolve consistently.

    Args:
        raw_path: User-provided project folder path.

    Returns:
        ``True`` if a project with the resolved path exists, ``False``
        otherwise (including when the path cannot be resolved).
    """
    path = _resolve_project_path(raw_path)
    if path is None:
        return False
    return any(p.get("path") == path for p in load_projects())


def add_project(raw_path: str, name: Optional[str] = None) -> bool:
    """Add a project to the managed list.

    The path is expanded, normalized to an absolute path, and validated to
    exist and be a directory. Duplicate paths are rejected.

    Args:
        raw_path: User-provided project folder path.
        name: Optional display name; falls back to the folder basename.

    Returns:
        ``True`` if the project was added, ``False`` otherwise.
    """
    path = _resolve_project_path(raw_path)
    if path is None:
        print(
            f"{Colors.RED}[ERROR] Invalid project path: {raw_path!r}.{Colors.RESET}"
        )
        return False

    if not os.path.exists(path):
        print(
            f"{Colors.RED}[ERROR] Path does not exist: {path}{Colors.RESET}"
        )
        return False
    if not os.path.isdir(path):
        print(
            f"{Colors.RED}[ERROR] Path is not a directory: {path}{Colors.RESET}"
        )
        return False

    projects = load_projects()
    for project in projects:
        if project.get("path") == path:
            print(
                f"{Colors.YELLOW}[WARN] Project already exists: {path}{Colors.RESET}"
            )
            return False

    now = _now_iso()
    project = {
        "name": name.strip() if name else os.path.basename(path),
        "path": path,
        "created_at": now,
        "updated_at": now,
    }
    projects.append(project)
    projects.sort(key=lambda p: p.get("created_at", ""))
    return save_projects(projects)


def delete_project_by_index(index: int) -> bool:
    """Delete a managed project by its 1-based displayed row number.

    Prompts the user for ``y/N`` confirmation before removing the entry.
    Only the registry entry is deleted; the project folder on disk is left
    untouched.

    Args:
        index: 1-based row number as shown by ``print_project_table``.

    Returns:
        ``True`` if the project was deleted, ``False`` otherwise.
    """
    projects = load_projects()
    if not 1 <= index <= len(projects):
        print(
            f"{Colors.RED}[ERROR] Invalid project number. "
            f"Please enter 1-{len(projects)}.{Colors.RESET}"
        )
        return False

    project = projects[index - 1]
    name = project.get("name", "")
    path = project.get("path", "")
    print(
        f"{Colors.YELLOW}[WARN] Delete project '{name}' ({path})? [y/N]{Colors.RESET}"
    )
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = "n"
    if answer not in ("y", "yes"):
        print(f"{Colors.DIM}[INFO] Deletion cancelled.{Colors.RESET}")
        return False

    del projects[index - 1]
    if not save_projects(projects):
        print(
            f"{Colors.RED}[ERROR] Failed to save project list.{Colors.RESET}"
        )
        return False
    return True


def delete_project_by_path(raw_path: str) -> bool:
    """Delete a managed project by its path.

    The path is expanded and normalized before comparison. Only the registry
    entry is deleted; the project folder on disk is left untouched.

    Args:
        raw_path: User-provided project folder path.

    Returns:
        ``True`` if the project was deleted, ``False`` otherwise.
    """
    path = _resolve_project_path(raw_path)
    if path is None:
        print(
            f"{Colors.RED}[ERROR] Invalid project path: {raw_path!r}.{Colors.RESET}"
        )
        return False

    projects = load_projects()
    for idx, project in enumerate(projects):
        if project.get("path") == path:
            del projects[idx]
            if not save_projects(projects):
                print(
                    f"{Colors.RED}[ERROR] Failed to save project list.{Colors.RESET}"
                )
                return False
            print(
                f"{Colors.GREEN}[INFO] Deleted project: {path}{Colors.RESET}"
            )
            return True

    print(
        f"{Colors.YELLOW}[WARN] Project not found: {path}{Colors.RESET}"
    )
    return False


def build_managed_project_list() -> List[Dict[str, Any]]:
    """Build a numbered list of managed projects for display.

    Returns:
        List of project dictionaries with an added ``no`` key (1-based row
        number). The list is sorted oldest-first by ``created_at``.
    """
    projects = load_projects()
    for idx, project in enumerate(projects, start=1):
        project["no"] = idx
    return projects


def print_project_table(projects: List[Dict[str, Any]]) -> None:
    """Print a numbered table of managed projects.

    Args:
        projects: Numbered project list as returned by
            :func:`build_managed_project_list`.
    """
    if not projects:
        print(
            f"\n{Colors.YELLOW}[WARN] No managed projects. "
            f"Use 'p add <path> [name]' to add one.{Colors.RESET}"
        )
        return

    w_no = 4
    w_name = 20
    w_path = 44
    w_created = 14

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {'No':^{w_no}} |"
        f" {'Name':^{w_name}} |"
        f" {'Path':^{w_path}} |"
        f" {'Created':^{w_created}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_path + 2)}+"
        f"{'-' * (w_created + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for project in projects:
        name = project.get("name") or "-"
        if len(name) > w_name:
            name = name[: w_name - 3] + "..."

        path = project.get("path") or "-"
        if len(path) > w_path:
            path = path[: w_path - 3] + "..."

        created = "-"
        create_time_raw = project.get("created_at", "")
        if create_time_raw:
            try:
                dt = datetime.fromisoformat(create_time_raw)
                created = dt.strftime("%m-%d %H:%M")
            except ValueError:
                created = create_time_raw

        row = (
            f" {project.get('no', 0):^{w_no}} |"
            f" {name:<{w_name}} |"
            f" {path:<{w_path}} |"
            f" {created:^{w_created}} "
        )
        print(row)

    print(sep)
    print(
        f"{Colors.DIM}(Total: {len(projects)} project"
        f"{'s' if len(projects) != 1 else ''}){Colors.RESET}"
    )
