"""Observe and route exact child-task input without changing core CLI targets.

Author: DawsonLin
"""

from pathlib import Path
import re
import stat

from cli_topsailai.log_files import discover_log_files, is_session_pipe_open
from cli_topsailai.runtime_pipe import send_to_pipe
from cli_topsailai.runtime_target import ProcessState, RuntimeTarget, probe_process


def own_pipe_open(record):
    """Ignore inherited parent pipe status when identifying an input owner."""
    return is_session_pipe_open(dict(record, session_pid=record.get("pid")))


def observe_records(records, alive, pipe_open=own_pipe_open):
    """Detach records and compute per-process state with input precedence."""
    rows = []
    for record in records:
        row = dict(record)
        live = alive(row.get("pid"))
        row["status"] = "input" if live and pipe_open(dict(row, session_pid=row.get("pid"))) else "running" if live else "idle"
        rows.append(row)
    status = next((state for state in ("input", "running")
                   if any(row["status"] == state for row in rows)), "idle")
    return rows, status


def task_log_target(task_dir, record):
    """Require exact regular child log evidence inside the configured folder."""
    path = Path(record["path"])
    folder = Path(task_dir)
    if not folder.is_absolute() or path.parent != folder or path.name != record["filename"]:
        raise ValueError("task log outside configured task directory")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("task log is not a regular file")
    return RuntimeTarget(record["session_id"], record["pid"], path, folder)


def send_task_input(task_dir, session_id, pid, content, *, timeout):
    """Send only to a freshly verified child-owned pipe; never use its parent."""
    if (not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}", session_id)
            or type(pid) is not int or pid <= 0):
        raise ValueError("invalid task session/PID selector")
    records = discover_log_files(str(task_dir))
    matches = [row for row in records if row.get("session_id") == session_id
               and row.get("pid") == pid]
    # Session evidence retains the core runtime resolver's semantics.
    if any(not row.get("is_task") for row in matches):
        return False
    tasks = [row for row in matches if row.get("is_task")]
    if not tasks:
        return False
    targets = [task_log_target(task_dir, row) for row in tasks]
    identities = [target.stdout_path.lstat() for target in targets]
    if probe_process(pid) is not ProcessState.ALIVE or not own_pipe_open(tasks[0]):
        raise ValueError("child task is no longer waiting for input")
    for target, before in zip(targets, identities):
        after = target.stdout_path.lstat()
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or not stat.S_ISREG(after.st_mode):
            raise ValueError("child task evidence changed")
    send_to_pipe(Path(task_dir) / f"{session_id}.{pid}.session.pipe", content, timeout=timeout)
    return True
