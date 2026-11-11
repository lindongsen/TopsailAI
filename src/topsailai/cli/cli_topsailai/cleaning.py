"""Log file cleanup helpers for the TopsailAI CLI."""

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cli_topsailai.colors import Colors, colored, cprint
from cli_topsailai.formatting import format_size, format_timestamp_full, print_header
from cli_topsailai.log_files import is_file_in_use
from cli_topsailai.process_liveness import (
    ProcessState,
    pid_state,
    socket_heartbeat_alive,
)
from cli_topsailai.session_cleanup import (
    _extract_session_prefix,
    find_related_files_for_path,
)
from cli_topsailai.agent_launch_background import _is_active_launch_log


#: On-disk identity of a temporary session. The filename parser reports no
#: session id for ``topsailai.{pid}.session.stdout``, while the control socket is
#: named with the literal ``topsailai`` prefix.
_TEMP_SESSION_ID = "topsailai"

#: Liveness verdicts. ``UNKNOWN`` is deliberately distinct from ``DEAD``: an
#: unanswerable question is not proof of absence, so it must never authorize a
#: deletion.
_LIVE = "live"
_DEAD = "dead"
_UNKNOWN = "unknown"

#: Age after which an idle session file becomes eligible for cleanup. Both the
#: interactive ``/clean`` command and the non-interactive ``workspace clean``
#: command read this one value, so the two paths cannot drift.
EXPIRED_AGE_SECONDS = 3 * 24 * 60 * 60  # 72 hours


def _home_for_task_dir(task_dir: str) -> Optional[str]:
    """Return the ``TOPSAILAI_HOME`` that owns *task_dir*, or ``None``.

    The control socket lives at ``{home}/workspace/task``, so the home is
    recovered from the directory layout instead of reading the environment.
    A directory that does not follow the layout returns ``None`` and the
    heartbeat probe then falls back to the configured home.
    """
    normalized = os.path.normpath(os.path.abspath(task_dir))
    workspace_dir = os.path.dirname(normalized)
    if os.path.basename(normalized) != "task":
        return None
    if os.path.basename(workspace_dir) != "workspace":
        return None
    return os.path.dirname(workspace_dir)


def _owner_identity(path: str) -> Optional[Tuple[str, int]]:
    """Return the ``(session_id, pid)`` that owns *path*, or ``None``.

    ``None`` means the filename carries no session owner at all, which is the
    case for diagnostic launch logs and for generic ``*.stdout`` files. Such a
    file has no session lifecycle to protect, so only the open-descriptor check
    applies to it.

    Every session-related suffix is normalized through the existing
    ``_extract_session_prefix`` helper, so ``.session.pipe`` and
    ``.session.agent2llm_inject_messages.jsonl`` resolve to the same owner as
    ``.session.stdout``. Parsing only ``.session.stdout`` would leave the pipe
    and the inject file without an owner, and their liveness would then never
    be checked.
    """
    prefix = _extract_session_prefix(os.path.basename(path))
    if prefix is None:
        return None
    session_id, _, pid_text = prefix.rpartition(".")
    try:
        pid = int(pid_text)
    except ValueError:
        return None
    return (session_id or _TEMP_SESSION_ID, pid)


def _owner_liveness(
    path: str,
    *,
    home: Optional[str] = None,
    cache: Optional[Dict[Tuple[str, int], str]] = None,
) -> str:
    """Classify the session that owns *path* as live, dead or unknown.

    The control channel is consulted first because a session may run in a
    sibling container that shares this filesystem: the local process table
    cannot see that owner and would report a live session as dead, while the
    channel answers for its own process. The process table is the fallback, and
    it is three-state so an unverifiable owner stays ``UNKNOWN``.

    Args:
        path: Absolute path to a session-related file.
        home: ``TOPSAILAI_HOME`` used to locate the control socket.
        cache: Optional per-operation memo keyed by owner identity, so a
            session with several related files is probed only once.

    Returns:
        ``live``, ``dead`` or ``unknown``.
    """
    identity = _owner_identity(path)
    if identity is None:
        # No session owner is encoded in the filename, so there is no session
        # liveness to prove. The caller still applies the open-descriptor check.
        return _DEAD
    if cache is not None and identity in cache:
        return cache[identity]

    session_id, pid = identity
    verdict = _UNKNOWN
    if socket_heartbeat_alive(session_id, pid, home=home) is True:
        verdict = _LIVE
    else:
        state = pid_state(pid)
        if state is ProcessState.ALIVE:
            verdict = _LIVE
        elif state is ProcessState.DEAD:
            verdict = _DEAD
        else:
            verdict = _UNKNOWN

    if cache is not None:
        cache[identity] = verdict
    return verdict


def _deletion_block_reason(
    path: str,
    *,
    home: Optional[str] = None,
    cache: Optional[Dict[Tuple[str, int], str]] = None,
) -> Optional[str]:
    """Return why *path* must not be deleted, or ``None`` when it may be.

    A file is deletable only when its owning session is provably gone and no
    process holds it open. Both conditions fail closed: an unverifiable owner
    and an unreadable descriptor table both block the deletion.
    """
    liveness = _owner_liveness(path, home=home, cache=cache)
    if liveness == _LIVE:
        return "owning session is still alive"
    if liveness == _UNKNOWN:
        return "owning session liveness cannot be verified"
    if is_file_in_use(path):
        return "file is still held open by a process"
    return None


def _launch_log_records(task_dir: str) -> List[dict]:
    """Discover expired diagnostic launch logs without adding watcher rows."""
    records: List[dict] = []
    try:
        entries = os.listdir(task_dir)
    except OSError:
        return records
    for filename in entries:
        if not filename.endswith(".agent-launch.log") and ".agent-launch.log." not in filename:
            continue
        # A lease sidecar is ownership evidence, never a deletable log record:
        # removing it would make a live launch log look inactive.
        if filename.endswith(".lease"):
            continue
        path = os.path.join(task_dir, filename)
        if not os.path.isfile(path):
            continue
        try:
            stat_info = os.stat(path)
        except OSError:
            continue
        records.append({"filename": filename, "path": path, "size": stat_info.st_size,
                        "mtime": stat_info.st_mtime})
    return records

def _expand_to_related_files(task_dir: str, selected: List[dict]) -> List[dict]:
    """Expand a list of selected files to include all related session files.

    Files sharing the same ``{session_id}.{pid}`` prefix (stdout, stderr,
    pipe, inject JSONL, and task outputs) are grouped and returned as a
    single deduplicated list. A file is skipped when its owning session is
    still alive, when that liveness cannot be verified, or when a process
    still holds it open.

    Args:
        task_dir: Directory containing the log files.
        selected: List of file metadata dictionaries chosen for deletion.

    Returns:
        Deduplicated list of file metadata dictionaries to delete.
    """
    seen: set = set()
    expanded: List[dict] = []
    # Keep the inventory snapshot for files that were already selected, so the
    # mutation-time revalidation can still detect a change made after inventory.
    snapshot = {f["path"]: f["mtime"] for f in selected}
    home = _home_for_task_dir(task_dir)
    # One probe per owning session: a session with several related files must
    # not pay a heartbeat per file.
    liveness_cache: Dict[Tuple[str, int], str] = {}

    for f in selected:
        related_paths = find_related_files_for_path(task_dir, f["path"])
        for path in related_paths:
            if path in seen:
                continue
            seen.add(path)
            reason = _deletion_block_reason(path, home=home, cache=liveness_cache)
            if reason is not None:
                print(f"[WARN] Skipping related file ({reason}): {path}")
                continue
            try:
                stat_info = os.stat(path)
            except OSError:
                continue
            expanded.append({
                "filename": os.path.basename(path),
                "path": path,
                "size": stat_info.st_size,
                "mtime": snapshot.get(path, stat_info.st_mtime),
            })

    return expanded


def _owner_pid(record: dict) -> Optional[int]:
    """Return the session-instance PID that owns *record*.

    ``discover_log_files`` reports a task file's own child PID in ``pid`` and
    the owning session's PID in ``session_pid``. Deletion groups files by the
    ``{session_id}.{pid}`` prefix, so the owner PID is the identity a PID
    selector must match; matching the child PID would select a file whose
    deletion unit belongs to a different PID.
    """
    owner = record.get("session_pid")
    if owner is None:
        owner = record.get("pid")
    return owner


def collect_expired_files(
    task_dir: str,
    files: List[dict],
    *,
    session_ids: Optional[List[str]] = None,
    pids: Optional[List[int]] = None,
    now: Optional[float] = None,
) -> List[dict]:
    """Build the exact inventory of expired, provably idle files.

    This is the single inventory rule shared by the interactive ``/clean``
    command and the non-interactive ``workspace clean`` command, so the two
    paths cannot drift on expiry age, session liveness, launch leases, or
    related-file expansion.

    Args:
        task_dir: Directory containing the log files.
        files: Discovered log file records.
        session_ids: Exact session IDs to restrict the inventory to, or
            ``None`` for every session. Launch logs carry no session owner, so
            they are excluded whenever a restriction is active.
        pids: Exact session-instance PIDs to restrict the inventory to, or
            ``None`` for every PID. A session ID alone selects every instance
            of that session, so a PID narrows the inventory to one instance.
            Launch logs carry no owner PID, so they are excluded whenever a
            restriction is active.
        now: Reference timestamp, defaulting to the current time.

    Returns:
        Deduplicated file records that may be deleted, each carrying
        ``filename``, ``path``, ``size`` and ``mtime``.
    """
    reference = time.time() if now is None else now
    home = _home_for_task_dir(task_dir)
    # One probe per owning session across the whole inventory pass.
    liveness_cache: Dict[Tuple[str, int], str] = {}

    candidates = files
    if session_ids is not None:
        selected = set(session_ids)
        candidates = [f for f in candidates if f.get("session_id") in selected]
    if pids is not None:
        selected_pids = set(pids)
        candidates = [f for f in candidates if _owner_pid(f) in selected_pids]

    expired_files: List[dict] = []
    for f in candidates:
        if not os.path.isfile(f["path"]):
            continue

        try:
            mtime = os.path.getmtime(f["path"])
        except OSError:
            continue

        age = reference - mtime
        if age <= EXPIRED_AGE_SECONDS:
            continue

        reason = _deletion_block_reason(f["path"], home=home, cache=liveness_cache)
        if reason is not None:
            print(f"[WARN] Skipping expired file ({reason}): {f['path']}")
            continue

        expired_files.append({
            "filename": f["filename"],
            "path": f["path"],
            "size": os.path.getsize(f["path"]),
            "mtime": mtime,
            "age_hours": age / 3600,
        })

    if session_ids is None and pids is None:
        expired_files.extend(
            record for record in _launch_log_records(task_dir)
            if reference - record["mtime"] > EXPIRED_AGE_SECONDS
            and not _is_active_launch_log(Path(record["path"]))
            and _deletion_block_reason(
                record["path"], home=home, cache=liveness_cache
            ) is None
        )

    return _expand_to_related_files(task_dir, expired_files)


def delete_collected_files(
    task_dir: str,
    entries: List[dict],
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Delete an already-confirmed inventory with mutation-time revalidation.

    Every entry is revalidated immediately before removal, because a session may
    have started using the file while the operator was reading the confirmation
    prompt or while a non-interactive caller was preparing the deletion.

    Args:
        task_dir: Directory containing the log files.
        entries: Inventory produced by ``collect_expired_files``.

    Returns:
        Tuple of (deleted paths, list of ``(filename, error)`` failures). The
        deleted paths are reported from the removal itself, so a caller never
        has to infer what happened from a count or from a later existence check.
    """
    home = _home_for_task_dir(task_dir)
    # Deletion-time probes must be fresh: a session may have started using the
    # file while the operator was reading the confirmation prompt.
    revalidation_cache: Dict[Tuple[str, int], str] = {}
    deleted_paths: List[str] = []
    failed_files: List[Tuple[str, str]] = []

    for entry in entries:
        # Revalidate immediately before deletion: the file may have become an
        # active launch log, or been replaced, since the inventory was built.
        if _is_active_launch_log(Path(entry["path"])):
            cprint(
                f"[WARN] Skipping active launch log: {entry['filename']}",
                color=Colors.YELLOW,
            )
            continue
        # Liveness is re-probed here, not reused from the inventory pass, so a
        # session that became live after the prompt cannot lose its files.
        reason = _deletion_block_reason(
            entry["path"], home=home, cache=revalidation_cache
        )
        if reason is not None:
            cprint(
                f"[WARN] Skipping {entry['filename']} ({reason})",
                color=Colors.YELLOW,
            )
            continue
        try:
            current = os.stat(entry["path"])
        except OSError as e:
            failed_files.append((entry["filename"], str(e)))
            cprint(
                f"[ERROR] Failed to delete {entry['filename']}: {e}",
                color=Colors.RED,
            )
            continue
        if current.st_mtime != entry["mtime"]:
            cprint(
                f"[WARN] Skipping changed file: {entry['filename']}",
                color=Colors.YELLOW,
            )
            continue
        try:
            os.remove(entry["path"])
            deleted_paths.append(entry["path"])
            cprint(
                f"[OK] Deleted: {entry['filename']}",
                color=Colors.GREEN,
            )
        except OSError as e:
            failed_files.append((entry["filename"], str(e)))
            cprint(
                f"[ERROR] Failed to delete {entry['filename']}: {e}",
                color=Colors.RED,
            )

    return deleted_paths, failed_files


def clean_expired_files(task_dir: str, files: List[dict]) -> int:
    """Clean up session log files that are idle and older than 3 days.

    Shows a confirmation prompt before deletion. When a file is deleted,
    all related session files sharing the same ``{session_id}.{pid}`` prefix
    are also removed, provided the owning session is provably gone and none of
    them are currently in use.

    Args:
        task_dir: Directory containing the log files.
        files: List of file metadata dictionaries.

    Returns:
        Number of files deleted.
    """
    expired_files = collect_expired_files(task_dir, files)

    if not expired_files:
        cprint(
            "\n[INFO] No expired session files found. "
            "(Files must be idle and older than 3 days)",
            color=Colors.GREEN,
        )
        return 0

    now = time.time()
    print_header("Clean Expired Log Files")
    cprint(
        f"[WARN] The following {len(expired_files)} file(s) are idle "
        "and older than 3 days:\n",
        color=Colors.YELLOW,
    )

    w_no = 4
    w_name = 32
    w_size = 10
    w_time = 20
    w_age = 12

    header = (
        f"{colored('', Colors.WHITE, bold=True, bg=Colors.BG_BLUE)}"
        f" {'No':^{w_no}} |"
        f" {'Filename':^{w_name}} |"
        f" {'Size':^{w_size}} |"
        f" {'Modified':^{w_time}} |"
        f" {'Age':^{w_age}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_size + 2)}+"
        f"{'-' * (w_time + 2)}+"
        f"{'-' * (w_age + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for idx, ef in enumerate(expired_files, start=1):
        name = ef["filename"]
        if len(name) > w_name:
            name = name[:w_name - 3] + "..."

        age_hours = (now - ef["mtime"]) / 3600
        size_str = format_size(ef["size"])
        time_str = format_timestamp_full(ef["mtime"])
        age_str = f"{age_hours:.1f}h"

        row = (
            f"{Colors.GRAY}"
            f" {idx:^{w_no}} |"
            f" {name:<{w_name}} |"
            f" {size_str:>{w_size}} |"
            f" {time_str:^{w_time}} |"
            f" {age_str:>{w_age}} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)

    confirm_prompt = (
        f"\n{colored('', Colors.YELLOW, bold=True)}"
        f"Are you sure you want to delete these {len(expired_files)} file(s)? [y/N]: "
        f"{Colors.RESET}"
    )
    sys.stdout.write(confirm_prompt)
    sys.stdout.flush()
    try:
        confirm = input("").strip().lower()
    except (EOFError, KeyboardInterrupt):
        cprint("\n[INFO] Clean cancelled.", color=Colors.YELLOW)
        return 0

    if confirm not in ("y", "yes"):
        cprint("[INFO] Clean cancelled.", color=Colors.YELLOW)
        return 0

    deleted_paths, failed_files = delete_collected_files(task_dir, expired_files)
    deleted_count = len(deleted_paths)

    cprint(
        f"\n[INFO] Clean complete: {deleted_count} deleted, {len(failed_files)} failed.",
        color=Colors.GREEN,
    )
    return deleted_count


def clean_by_numbers(task_dir: str, files: List[dict], indices: List[int]) -> int:
    """Clean up specific session log files by their list numbers.

    Validates each index, shows a confirmation prompt, then deletes the
    selected files along with all related session files sharing the same
    ``{session_id}.{pid}`` prefix. A file is skipped when its owning session is
    still alive, when that liveness cannot be verified, or when a process still
    holds it open.

    Args:
        task_dir: Directory containing the log files.
        files: List of file metadata dictionaries.
        indices: 0-based indices of files to delete.

    Returns:
        Number of files deleted.
    """
    valid_files = []
    invalid_indices = []

    for idx in indices:
        if 0 <= idx < len(files):
            f = files[idx]
            if os.path.isfile(f["path"]):
                valid_files.append(f)
            else:
                invalid_indices.append(idx + 1)
        else:
            invalid_indices.append(idx + 1)

    if invalid_indices:
        cprint(
            f"[WARN] Invalid or out-of-range number(s): {', '.join(str(i) for i in invalid_indices)}",
            color=Colors.YELLOW,
        )

    if not valid_files:
        cprint("[INFO] No valid files to delete.", color=Colors.YELLOW)
        return 0

    valid_files = _expand_to_related_files(task_dir, valid_files)

    print_header("Clean Selected Log Files")
    cprint(
        f"[WARN] The following {len(valid_files)} file(s) will be deleted:\n",
        color=Colors.YELLOW,
    )

    w_no = 4
    w_name = 32
    w_size = 10
    w_time = 20

    header = (
        f"{colored('', Colors.WHITE, bold=True, bg=Colors.BG_BLUE)}"
        f" {'No':^{w_no}} |"
        f" {'Filename':^{w_name}} |"
        f" {'Size':^{w_size}} |"
        f" {'Modified':^{w_time}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_size + 2)}+"
        f"{'-' * (w_time + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for idx, f in enumerate(valid_files, start=1):
        name = f["filename"]
        if len(name) > w_name:
            name = name[:w_name - 3] + "..."

        size_str = format_size(f["size"])
        time_str = format_timestamp_full(f["mtime"])

        row = (
            f"{Colors.GRAY}"
            f" {idx:^{w_no}} |"
            f" {name:<{w_name}} |"
            f" {size_str:>{w_size}} |"
            f" {time_str:^{w_time}} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)

    confirm_prompt = (
        f"\n{colored('', Colors.YELLOW, bold=True)}"
        f"Are you sure you want to delete these {len(valid_files)} file(s)? [y/N]: "
        f"{Colors.RESET}"
    )
    sys.stdout.write(confirm_prompt)
    sys.stdout.flush()
    try:
        confirm = input("").strip().lower()
    except (EOFError, KeyboardInterrupt):
        cprint("\n[INFO] Clean cancelled.", color=Colors.YELLOW)
        return 0

    if confirm not in ("y", "yes"):
        cprint("[INFO] Clean cancelled.", color=Colors.YELLOW)
        return 0

    deleted_count = 0
    failed_files = []
    home = _home_for_task_dir(task_dir)
    # Deletion-time probes must be fresh: a session may have started using the
    # file while the operator was reading the confirmation prompt.
    revalidation_cache: Dict[Tuple[str, int], str] = {}

    for f in valid_files:
        # Revalidate immediately before deletion. The inventory check ran before
        # the confirmation prompt, so a session that became live in between must
        # still keep its files.
        reason = _deletion_block_reason(
            f["path"], home=home, cache=revalidation_cache
        )
        if reason is not None:
            cprint(
                f"[WARN] Skipping {f['filename']} ({reason})",
                color=Colors.YELLOW,
            )
            continue
        try:
            os.remove(f["path"])
            deleted_count += 1
            cprint(f"[OK] Deleted: {f['filename']}", color=Colors.GREEN)
        except OSError as e:
            failed_files.append((f["filename"], str(e)))
            cprint(f"[ERROR] Failed to delete {f['filename']}: {e}", color=Colors.RED)

    cprint(
        f"\n[INFO] Clean complete: {deleted_count} deleted, {len(failed_files)} failed.",
        color=Colors.GREEN,
    )
    return deleted_count
