"""Disk cleanup helpers for session-related files.

A session produces several files in the task directory:

- ``{session_id}.{pid}.session.stdout``
- ``{session_id}.{pid}.session.stderr``
- ``{session_id}.{pid}.session.pipe``
- ``{session_id}.{pid}.session.agent2llm_inject_messages.jsonl``
- ``{session_id}.{pid}.{extra}.task.stdout``
- ``{session_id}.{pid}.{extra}.task.stderr``

This module provides helpers to discover and delete those files by session
ID or by the ``{session_id}.{pid}`` prefix they share.
"""

import os
from typing import List, Optional, Tuple

from cli_topsailai.log_files import _parse_stdout_filename, is_file_in_use
from cli_topsailai.paths import get_topsailai_home


# File extensions/patterns that belong to a session lifecycle.
_SESSION_RELATED_SUFFIXES = (
    ".session.stdout",
    ".session.stderr",
    ".task.stdout",
    ".task.stderr",
    ".session.pipe",
    ".session.agent2llm_inject_messages.jsonl",
)


def get_task_dir() -> str:
    """Return the task directory used for session output files."""
    return os.path.join(get_topsailai_home(), "workspace", "task")


def _is_session_related_file(filename: str) -> bool:
    """Return True if *filename* is a session output/pipe/inject file."""
    return filename.endswith(_SESSION_RELATED_SUFFIXES)


def _extract_session_prefix(filename: str) -> Optional[str]:
    """Extract the ``{session_id}.{pid}`` prefix from a filename.

    Returns:
        The ``{session_id}.{pid}`` prefix, or ``None`` if the filename does
        not match a known session/task pattern.
    """
    session_id, pid = _parse_stdout_filename(filename)
    if pid is None:
        return None
    # Temporary sessions use "topsailai" as the internal session ID.
    if session_id is None:
        session_id = "topsailai"
    return f"{session_id}.{pid}"


def find_related_files(task_dir: str, prefix: str) -> List[str]:
    """Find all session-related files sharing the same ``{session_id}.{pid}`` prefix.

    Args:
        task_dir: Directory containing session files.
        prefix: The ``{session_id}.{pid}`` prefix to match.

    Returns:
        List of absolute paths to matching files.
    """
    if not os.path.isdir(task_dir):
        return []

    related: List[str] = []
    prefix_with_dot = f"{prefix}."
    for entry in os.listdir(task_dir):
        if not entry.startswith(prefix_with_dot):
            continue
        if not _is_session_related_file(entry):
            continue
        full_path = os.path.join(task_dir, entry)
        if not os.path.exists(full_path):
            continue
        related.append(full_path)

    return related


def find_related_files_for_path(task_dir: str, path: str) -> List[str]:
    """Find all files related to *path* by shared ``{session_id}.{pid}`` prefix.

    Args:
        task_dir: Directory containing session files.
        path: Absolute path to a session-related file.

    Returns:
        List of absolute paths to related files, including *path* itself if
        it still exists.
    """
    filename = os.path.basename(path)
    prefix = _extract_session_prefix(filename)
    if prefix is None:
        return [path] if os.path.exists(path) else []
    return find_related_files(task_dir, prefix)


def find_session_disk_files(task_dir: str, session_id: str) -> List[str]:
    """Find all disk files associated with a session ID.

    Args:
        task_dir: Directory containing session files.
        session_id: Session ID. Use ``"topsailai"`` for temporary sessions.

    Returns:
        List of absolute paths to files whose names start with
        ``{session_id}.`` followed by a PID and are session-related.
    """
    if not os.path.isdir(task_dir):
        return []

    prefix = f"{session_id}."
    related: List[str] = []
    for entry in os.listdir(task_dir):
        if not entry.startswith(prefix):
            continue
        # Require the character after the prefix to be a digit (start of PID)
        # so that "my-session" does not match "my-session-extra".
        if len(entry) <= len(prefix) or not entry[len(prefix)].isdigit():
            continue
        if not _is_session_related_file(entry):
            continue
        full_path = os.path.join(task_dir, entry)
        if not os.path.exists(full_path):
            continue
        related.append(full_path)

    return related


def delete_session_disk_files(
    task_dir: str,
    session_id: str,
    dry_run: bool = False,
) -> Tuple[List[str], List[str]]:
    """Delete all disk files associated with a session.

    Files that are still held open by a process are skipped.

    Args:
        task_dir: Directory containing session files.
        session_id: Session ID. Use ``"topsailai"`` for temporary sessions.
        dry_run: If True, report files without deleting them.

    Returns:
        Tuple of (deleted_paths, failed_paths).
    """
    paths = find_session_disk_files(task_dir, session_id)
    deleted: List[str] = []
    failed: List[str] = []

    for path in paths:
        if dry_run:
            deleted.append(path)
            continue
        if is_file_in_use(path):
            print(f"[WARN] Skipping in-use session file: {path}")
            continue
        try:
            os.remove(path)
            print(f"[INFO] Deleted session file: {path}")
            deleted.append(path)
        except OSError as exc:
            print(f"[ERROR] Failed to delete session file {path}: {exc}")
            failed.append(path)

    return deleted, failed


def _corresponding_stdout_path(task_dir: str, filename: str) -> Optional[str]:
    """Return the `.session.stdout` path a session-related file belongs to.

    The filename must start with ``{session_id}.{pid}.``; the anchor is built
    by replacing the trailing stream suffix with ``.session.stdout``.
    Returns ``None`` when the filename does not look like a session-related
    stream file.
    """
    if not _is_session_related_file(filename):
        return None
    # `.session.stdout` is its own anchor.
    if filename.endswith(".session.stdout"):
        return os.path.join(task_dir, filename)

    # Strip the known stream suffixes to recover the ``{session_id}.{pid}``
    # prefix.  Order matters: longer, more specific suffixes first.
    suffixes = (
        ".session.agent2llm_inject_messages.jsonl",
        ".session.pipe",
        ".session.stderr",
        ".task.stdout",
        ".task.stderr",
    )
    for suffix in suffixes:
        if filename.endswith(suffix):
            base = filename[: -len(suffix)]
            return os.path.join(task_dir, f"{base}.session.stdout")
    return None

def clean_orphaned_session_files(
    task_dir: str,
    dry_run: bool = False,
) -> Tuple[List[str], List[str]]:
    """Delete session-related files whose `.session.stdout` counterpart is gone.

    Any file belonging to a session lifecycle (stderr, pipe, inject JSONL,
    and task outputs) is considered orphaned when its corresponding
    ``{session_id}.{pid}.session.stdout`` no longer exists.  Files still held
    open by a process are skipped.

    Args:
        task_dir: Directory containing session files.
        dry_run: If True, report files without deleting them.

    Returns:
        Tuple of (deleted_paths, failed_paths).
    """
    if not os.path.isdir(task_dir):
        return [], []

    deleted: List[str] = []
    failed: List[str] = []

    for entry in os.listdir(task_dir):
        if not _is_session_related_file(entry):
            continue
        # `.session.stdout` is the anchor; never treat it as orphan.
        if entry.endswith(".session.stdout"):
            continue

        stdout_path = _corresponding_stdout_path(task_dir, entry)
        if stdout_path is None:
            continue
        if os.path.exists(stdout_path):
            continue

        full_path = os.path.join(task_dir, entry)
        if not os.path.exists(full_path):
            continue

        if dry_run:
            deleted.append(full_path)
            continue
        if is_file_in_use(full_path):
            print(f"[WARN] Skipping in-use orphaned session file: {full_path}")
            continue
        try:
            os.remove(full_path)
            print(f"[INFO] Deleted orphaned session file: {full_path}")
            deleted.append(full_path)
        except OSError as exc:
            print(f"[ERROR] Failed to delete orphaned session file {full_path}: {exc}")
            failed.append(full_path)

    return deleted, failed
