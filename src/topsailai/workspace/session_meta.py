'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-07-30
  Purpose: Persist per-session metadata as a single JSON file under FOLDER_WORKSPACE_TASK.
'''

import atexit
import functools
import glob
import json
import logging
import os
from os import lstat as _lstat
import socket
import stat
import threading
import time
from datetime import datetime

from topsailai.utils import env_tool
from topsailai.utils.qos_tool import log_if_slow_decorator
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK
from topsailai.workspace.project_workspace import resolve_project_workspace
from topsailai.context.session_activity import (
    ActivityState,
    SessionActivityProbe,
    _OWNER_PATTERN,
)
from topsailai.context.session_category import resolve_session_category

logger = logging.getLogger(__name__)

META_VERSION = 1
META_EXTENSION = "meta"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_INTERRUPTED = "interrupted"
SESSION_META_CLEANUP_SLOW_SECONDS = 5

# Artifacts that share a session metadata basename. They are retained on every
# exit path, so they are reclaimed only together with the metadata that
# authorizes their removal. `stats.jsonl` belongs here because it is an owner
# record: leaving it behind creates a PID with no metadata, which makes the
# whole session unauthorized forever.
ARTIFACT_SUFFIXES = ("stdout", "events", "stats.jsonl")

_META_LOCK = threading.RLock()


def safe_session_meta(func):
    """Decorator that makes session metadata operations safe.

    Any exception raised by the wrapped function is logged and suppressed so
    that metadata failures never propagate to the main agent flow.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception("Failed to execute %s: %s", func.__qualname__, e)
            return None
    return wrapper


def _serialized_session_meta(func):
    """Serialize complete metadata transactions, including nested writes."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        """Hold the shared reentrant lock for the entire operation."""
        with _META_LOCK:
            return func(*args, **kwargs)
    return wrapper


def _now_iso8601() -> str:
    """Return the current local timestamp in ISO 8601 format."""
    return datetime.now().isoformat()


def _get_hostname() -> str:
    """Return the process hostname, or an empty value when unavailable."""
    try:
        hostname = socket.gethostname()
    except Exception as error:
        logger.warning(
            "Failed to resolve hostname for session metadata: %s",
            error,
            exc_info=True,
        )
        return ""
    if not hostname or not hostname.strip():
        logger.warning("Hostname resolution returned an empty value")
        return ""
    return hostname


def get_session_meta_path(session_id: str | None = None) -> str:
    """Return the path for the session metadata file.

    Naming convention:
      {session_id}.{pid}.session.meta
    Fallback when session_id is empty:
      topsailai.{pid}.session.meta

    Args:
        session_id: Optional session identifier. If not provided, read from env.

    Returns:
        Absolute path to the session metadata file.
    """
    if not session_id:
        session_id = env_tool.get_session_id() or "topsailai"
    return os.path.join(
        FOLDER_WORKSPACE_TASK,
        f"{session_id}.{os.getpid()}.session.{META_EXTENSION}",
    )


@_serialized_session_meta
def _atomic_write(path: str, data: dict) -> None:
    """Write JSON data atomically using a temporary file and os.replace.

    Failures are logged but never raised. On failure, any partial temporary
    file is removed so no stale ``.tmp`` residue remains on disk.

    Args:
        path: Destination file path.
        data: Data to serialize as JSON.
    """
    tmp_path = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as fd:
            json.dump(data, fd, ensure_ascii=False, indent=2)
            fd.flush()
            os.fsync(fd.fileno())
        os.replace(tmp_path, path)
    except Exception as e:
        logger.exception("Failed to write session meta to %s: %s", path, e)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                logger.debug("Removed partial session meta temp file: %s", tmp_path)
        except Exception:
            pass


def _read_meta(path: str) -> dict | None:
    """Read and parse a session metadata file.

    Args:
        path: Path to the metadata file.

    Returns:
        Parsed metadata dict, or None if reading/parsing fails.
    """
    try:
        with open(path, "r", encoding="utf-8") as fd:
            return json.load(fd)
    except Exception:
        return None


def _get_related_files(meta_basename: str) -> dict:
    """Build relative paths to related session files.

    Args:
        meta_basename: Basename of the metadata file, e.g. "abc.123.session.meta".

    Returns:
        Dict mapping file type to relative path. Missing/irrelevant files are omitted.
    """
    base = meta_basename[: -len(f".{META_EXTENSION}")]
    files = {
        "events": f"{base}.events",
        "stdout": f"{base}.stdout",
    }

    if env_tool.EnvReaderInstance.check_bool("TOPSAILAI_INPUT_PIPE_ENABLED", False):
        files["pipe"] = f"{base}.pipe"

    if env_tool.EnvReaderInstance.check_bool("TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED", True):
        files["agent2llm_inject_messages"] = f"{base}.agent2llm_inject_messages.jsonl"

    return files


def _get_feature_flags() -> dict:
    """Capture a snapshot of relevant feature flags."""
    return {
        "TOPSAILAI_ENABLE_SESSION_TEE_OUT": env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_ENABLE_SESSION_TEE_OUT", True
        ),
        "TOPSAILAI_INPUT_PIPE_ENABLED": env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_INPUT_PIPE_ENABLED", False
        ),
        "TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS": env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS", False
        ),
        "TOPSAILAI_ENABLE_SESSION_LOCK": env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_ENABLE_SESSION_LOCK", False
        ),
    }


@safe_session_meta
@_serialized_session_meta
def create_session_meta(
    session_id: str | None = None, ai_agent=None, session_name: str = "", category: str = ""
) -> str | None:
    """Create the initial session metadata file.

    This function is best-effort: failures are logged and None is returned.

    Args:
        session_id: Optional session identifier.
        ai_agent: Optional AI agent instance to extract agent metadata.
        session_name: Current session name, or empty when unavailable.
        category: Session category, or empty when unavailable.

    Returns:
        Path to the created metadata file, or None on failure.
    """
    path = get_session_meta_path(session_id)
    meta_basename = os.path.basename(path)

    resolved_session_id = session_id or env_tool.get_session_id() or ""
    project_workspace = resolve_project_workspace(session_id=resolved_session_id) or ""
    pwd = os.getenv("TOPSAILAI_PWD") or ""
    task_id = os.getenv("TOPSAILAI_TASK_ID") or ""

    agent_name = ""
    agent_type = ""
    agent_role = ""
    model_name = ""
    if ai_agent is not None:
        agent_name = getattr(ai_agent, "agent_name", "") or ""
        agent_type = getattr(ai_agent, "agent_type", "") or ""
        agent_role = getattr(ai_agent, "agent_role", "") or ""
        llm_model = getattr(ai_agent, "llm_model", None)
        if llm_model is not None:
            model_name = getattr(llm_model, "model_name", "") or ""

    meta = {
        "version": META_VERSION,
        "session_id": resolved_session_id,
        "session_name": session_name,
        "category": resolve_session_category(category),
        "pid": os.getpid(),
        "hostname": _get_hostname(),
        "start_ts": _now_iso8601(),
        "end_ts": None,
        "status": STATUS_RUNNING,
        "project_workspace": project_workspace,
        "pwd": pwd,
        "agent_name": agent_name,
        "agent_type": agent_type,
        "agent_role": agent_role,
        "model_name": model_name,
        "task_id": task_id,
        "files": _get_related_files(meta_basename),
        "feature_flags": _get_feature_flags(),
    }

    _atomic_write(path, meta)

    # Register an atexit handler to mark the session as interrupted if the
    # process exits without normal finalization. This is best-effort and
    # intentionally does not delete the file.
    atexit.register(_finalize_on_exit, path)

    return path


@_serialized_session_meta
def _finalize_on_exit(path: str) -> None:
    """Mark the session metadata as interrupted if it is still running.

    This is registered as an atexit handler. It is safe to call even if the
    metadata file has already been finalized.

    Args:
        path: Path to the metadata file.
    """
    meta = _read_meta(path)
    if meta is None:
        return
    if meta.get("status") == STATUS_RUNNING:
        meta["status"] = STATUS_INTERRUPTED
        meta["end_ts"] = _now_iso8601()
        _atomic_write(path, meta)


@safe_session_meta
@_serialized_session_meta
def update_session_meta_status(status: str, session_id: str | None = None) -> None:
    """Update the status and end_ts of the session metadata file.

    Args:
        status: One of "completed", "error", or "interrupted".
        session_id: Optional session identifier.
    """
    path = get_session_meta_path(session_id)
    meta = _read_meta(path)
    if meta is None:
        return

    meta["status"] = status
    if status in (STATUS_COMPLETED, STATUS_ERROR, STATUS_INTERRUPTED):
        meta["end_ts"] = _now_iso8601()
    _atomic_write(path, meta)


@safe_session_meta
@_serialized_session_meta
def update_session_meta_field(field: str, value, session_id: str | None = None) -> None:
    """Update an arbitrary field in the session metadata file.

    Args:
        field: Field name to update.
        value: New value for the field.
        session_id: Optional session identifier.
    """
    path = get_session_meta_path(session_id)
    meta = _read_meta(path)
    if meta is None:
        return

    meta[field] = value
    _atomic_write(path, meta)


def _parse_meta_session_id(path):
    """Return the session identifier encoded in a complete metadata filename."""
    name = os.path.basename(path)
    if name.endswith(".tmp"):
        return None
    prefix, separator, _ = name.rpartition(".session.meta")
    session_id, dot, pid = prefix.rpartition(".")
    if not separator or not dot or not pid.isdigit() or not session_id:
        return None
    return session_id


def _file_identity(path):
    """Capture the regular-file identity required for a safe later deletion."""
    try:
        current = _lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(current.st_mode):
        return None
    return (
        current.st_dev,
        current.st_ino,
        current.st_mode,
        current.st_size,
        current.st_mtime_ns,
    )


def _cleanable_session_ids(session_ids, activity_probe):
    """Return cleanup decisions for explicit session identifiers.

    One batch observation is used when the probe supports it, so a directory
    with hundreds of sessions is inventoried once instead of once per session.
    """
    ordered = tuple(sorted(set(session_ids)))
    if not ordered:
        return {}
    observe_many = getattr(type(activity_probe), "observe_many", None)
    if callable(observe_many):
        observations = activity_probe.observe_many(ordered)
        return {
            session_id: observations.get(session_id) is not None
            and observations[session_id].state == ActivityState.STOPPED
            for session_id in ordered
        }
    return {
        session_id: bool(activity_probe.can_clean(session_id))
        for session_id in ordered
    }


def _cleanable_sessions(paths, activity_probe):
    """Return cleanup decisions using one batch observation when supported."""
    session_ids = tuple(sorted({
        session_id
        for session_id in (_parse_meta_session_id(path) for path in paths)
        if session_id
    }))
    return _cleanable_session_ids(session_ids, activity_probe)


def _capture_cleanup_candidates(paths):
    """Capture valid metadata identities before cleanup authorization."""
    candidates = {}
    for path in paths:
        session_id = _parse_meta_session_id(path)
        identity = _file_identity(path)
        if session_id and identity is not None:
            candidates[path] = (session_id, identity)
    return candidates


def _remove_session_artifacts(meta_path):
    """Remove the diagnostic artifacts that belong to one removed metadata file.

    Session artifacts are retained on every exit path, including abnormal ones,
    so they must be reclaimed together with the metadata that authorizes their
    removal. Only regular files sharing the metadata basename are touched, and a
    symlink or a directory is left alone.
    """
    base = meta_path[: -len(f".{META_EXTENSION}")]
    removed = []
    for suffix in ARTIFACT_SUFFIXES:
        path = f"{base}.{suffix}"
        try:
            current = _lstat(path)
        except OSError:
            continue
        if not stat.S_ISREG(current.st_mode):
            continue
        try:
            os.remove(path)
            removed.append(path)
            logger.debug("Removed session artifact: %s", path)
        except OSError:
            continue
    return removed


def _remove_cleanable_meta(paths, candidates, decisions, message):
    """Delete authorized metadata only when its captured identity is unchanged."""
    removed = set()
    for path in paths:
        candidate = candidates.get(path)
        if candidate is None:
            continue
        session_id, identity = candidate
        if not decisions.get(session_id) or _file_identity(path) != identity:
            continue
        try:
            os.remove(path)
            removed.add(path)
            logger.debug(message, path)
        except OSError:
            continue
        _remove_session_artifacts(path)
    return removed


@safe_session_meta
@log_if_slow_decorator(
    threshold=SESSION_META_CLEANUP_SLOW_SECONDS,
    message="Session metadata cleanup exceeded startup latency threshold",
    level="critical",
    logger_obj=logger,
)
@_serialized_session_meta
def cleanup_session_meta_files(activity_probe=None) -> None:
    """Remove old session metadata files based on retention days and max count.

    Configuration:
      TOPSAILAI_SESSION_META_RETENTION_DAYS (default 7)
      TOPSAILAI_SESSION_META_MAX_COUNT (default 0, unlimited)
    """
    retention_days = env_tool.EnvReaderInstance.get(
        "TOPSAILAI_SESSION_META_RETENTION_DAYS",
        default=7,
        formatter=int,
    )
    max_count = env_tool.EnvReaderInstance.get(
        "TOPSAILAI_SESSION_META_MAX_COUNT",
        default=0,
        formatter=int,
    )

    directory = FOLDER_WORKSPACE_TASK
    activity_probe = activity_probe if activity_probe is not None else SessionActivityProbe((directory,))
    pattern = os.path.join(directory, f"*.{META_EXTENSION}")
    now = time.time()
    retention_seconds = retention_days * 86400 if retention_days > 0 else 0

    meta_files = []
    for path in glob.glob(pattern):
        try:
            if not os.path.isfile(path):
                continue
            basename = os.path.basename(path)
            if ".session.meta" not in basename:
                continue
            meta_files.append((path, os.path.getmtime(path)))
        except OSError:
            continue

    old_paths = [
        path for path, mtime in meta_files
        if retention_seconds > 0 and now - mtime > retention_seconds
    ]
    ordered_files = sorted(meta_files, key=lambda item: item[1])
    initial_excess_paths = []
    if max_count > 0 and len(ordered_files) > max_count:
        initial_excess_paths = [
            path for path, _ in ordered_files[: len(ordered_files) - max_count]
        ]
    candidate_paths = tuple(dict.fromkeys(old_paths + initial_excess_paths))
    candidates = _capture_cleanup_candidates(candidate_paths)
    decisions = _cleanable_sessions(candidates, activity_probe)
    removed = _remove_cleanable_meta(
        old_paths,
        candidates,
        decisions,
        "Removed old session meta file: %s",
    )
    surviving = [item for item in ordered_files if item[0] not in removed]

    if max_count > 0 and len(surviving) > max_count:
        excess_paths = [
            path for path, _ in surviving[: len(surviving) - max_count]
        ]
        _remove_cleanable_meta(
            excess_paths,
            candidates,
            decisions,
            "Removed excess session meta file: %s",
        )

    # Partial temporary records cannot prove stopped ownership; preserve them.
    tmp_pattern = os.path.join(directory, f"*.{META_EXTENSION}.tmp")
    for path in glob.glob(tmp_pattern):
        try:
            if not os.path.isfile(path):
                continue
            basename = os.path.basename(path)
            if ".session.meta.tmp" not in basename:
                continue
            if retention_seconds > 0 and now - os.path.getmtime(path) > retention_seconds:
                logger.debug("Preserved uncertain session meta temp file: %s", path)
        except OSError:
            continue


def _index_owner_records(directory):
    """Group every owner record in *directory* by its session identifier.

    The framework's own owner-record pattern is reused so this inventory cannot
    drift from the suffixes the activity probe recognizes. A name that the
    pattern rejects is not an owner record and is never a cleanup candidate.
    """
    grouped = {}
    try:
        entries = os.listdir(directory)
    except OSError:
        logger.warning("Cannot list the task directory %s", directory, exc_info=True)
        return grouped
    for name in entries:
        match = _OWNER_PATTERN.fullmatch(name)
        if match is None:
            continue
        grouped.setdefault(match.group(1), []).append(name)
    return grouped


def _orphan_cleanup_candidates(grouped, directory, now, retention_seconds):
    """Return expired owner records of sessions that have no metadata left.

    A session that still owns a metadata file is left to
    ``cleanup_session_meta_files``, which reclaims the metadata and its
    artifacts together. Only a session whose metadata is already gone is an
    orphan, and only its own expired records are candidates.

    The age gate is per file and is not optional. A session writes its
    statistics before its metadata, so a freshly started session briefly looks
    like an orphan; deleting on liveness alone would destroy a live session's
    statistics during that window.

    Each candidate carries the regular-file identity captured before the
    authorization pass, so a record rewritten or replaced while the probe runs
    cannot be deleted on stale evidence.
    """
    candidates = {}
    for session_id, names in grouped.items():
        if any(name.endswith(f".session.{META_EXTENSION}") for name in names):
            continue
        expired = []
        for name in names:
            path = os.path.join(directory, name)
            try:
                if now - os.path.getmtime(path) <= retention_seconds:
                    continue
            except OSError:
                continue
            identity = _file_identity(path)
            if identity is None:
                continue
            expired.append((path, identity))
        if expired:
            candidates[session_id] = expired
    return candidates


def _remove_orphan_records(candidates, decisions):
    """Delete authorized orphan records only when their identity is unchanged.

    Every path is re-identified immediately before removal, so a record that was
    rewritten, replaced, or turned into a symlink after the inventory pass is
    preserved. Non-regular files are skipped: a socket endpoint is owned by the
    channel that created it, not by this cleanup.
    """
    removed = []
    for session_id, entries in candidates.items():
        if not decisions.get(session_id):
            continue
        for path, identity in entries:
            if _file_identity(path) != identity:
                continue
            try:
                os.remove(path)
            except OSError:
                logger.warning("Cannot remove orphan session record %s", path, exc_info=True)
                continue
            removed.append(path)
            logger.debug("Removed orphan session record: %s", path)
    return removed


@safe_session_meta
@log_if_slow_decorator(
    threshold=SESSION_META_CLEANUP_SLOW_SECONDS,
    message="Orphan session cleanup exceeded startup latency threshold",
    level="critical",
    logger_obj=logger,
)
@_serialized_session_meta
def cleanup_orphan_session_files(activity_probe=None, directory=None,
                                 retention_days=None, now=None) -> list:
    """Remove expired owner records of sessions whose metadata is already gone.

    ``cleanup_session_meta_files`` iterates metadata files, so a session that
    lost its metadata is invisible to it and its remaining owner records stay on
    disk forever. This function covers exactly that population: sessions with no
    metadata file at all, whose every remaining record is expired and whose
    owners are all provably stopped.

    Configuration:
      TOPSAILAI_SESSION_META_RETENTION_DAYS (default 7)

    Args:
        activity_probe: Optional probe; one is built for *directory* when absent.
        directory: Task directory, defaulting to ``FOLDER_WORKSPACE_TASK``.
        retention_days: Age in days a record must exceed, defaulting to the
            configured retention. Zero or negative disables the cleanup.
        now: Reference timestamp, defaulting to the current time.

    Returns:
        list: Paths that were actually removed.
    """
    if retention_days is None:
        retention_days = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_SESSION_META_RETENTION_DAYS",
            default=7,
            formatter=int,
        )
    if retention_days <= 0:
        return []
    directory = directory or FOLDER_WORKSPACE_TASK
    reference = time.time() if now is None else now
    retention_seconds = retention_days * 86400
    activity_probe = activity_probe if activity_probe is not None else SessionActivityProbe((directory,))

    grouped = _index_owner_records(directory)
    candidates = _orphan_cleanup_candidates(grouped, directory, reference, retention_seconds)
    if not candidates:
        return []
    decisions = _cleanable_session_ids(tuple(candidates), activity_probe)
    removed = _remove_orphan_records(candidates, decisions)
    if removed:
        removed_set = set(removed)
        removed_sessions = {
            session_id for session_id, entries in candidates.items()
            if any(path in removed_set for path, _ in entries)
        }
        logger.info(
            "Removed %d orphan session record(s) across %d session(s)",
            len(removed), len(removed_sessions),
        )
    return removed
