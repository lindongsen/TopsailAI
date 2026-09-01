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
import time
from datetime import datetime

from topsailai.utils import env_tool
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK

logger = logging.getLogger(__name__)

META_VERSION = 1
META_EXTENSION = "meta"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_INTERRUPTED = "interrupted"


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


def _now_iso8601() -> str:
    """Return the current local timestamp in ISO 8601 format."""
    return datetime.now().isoformat()


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
def create_session_meta(session_id: str | None = None, ai_agent=None) -> str | None:
    """Create the initial session metadata file.

    This function is best-effort: failures are logged and None is returned.

    Args:
        session_id: Optional session identifier.
        ai_agent: Optional AI agent instance to extract agent metadata.

    Returns:
        Path to the created metadata file, or None on failure.
    """
    path = get_session_meta_path(session_id)
    meta_basename = os.path.basename(path)

    resolved_session_id = session_id or env_tool.get_session_id() or ""
    project_workspace = os.getenv("TOPSAILAI_PROJECT_WORKSPACE") or ""
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
        "pid": os.getpid(),
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


@safe_session_meta
def cleanup_session_meta_files() -> None:
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
        except Exception:
            continue

    # Delete files older than retention period
    surviving = []
    for path, mtime in meta_files:
        if retention_seconds > 0 and now - mtime > retention_seconds:
            try:
                os.remove(path)
                logger.debug("Removed old session meta file: %s", path)
            except Exception:
                pass
            continue
        surviving.append((path, mtime))

    # Enforce max count
    if max_count > 0 and len(surviving) > max_count:
        surviving.sort(key=lambda item: item[1])
        for path, _ in surviving[: len(surviving) - max_count]:
            try:
                os.remove(path)
                logger.debug("Removed excess session meta file: %s", path)
            except Exception:
                pass

    # Remove orphaned temporary files (e.g. *.session.meta.tmp) left behind by
    # a failed atomic write. These are partial writes with no matching .meta
    # file, so they are safe to prune once older than the retention period.
    tmp_pattern = os.path.join(directory, f"*.{META_EXTENSION}.tmp")
    for path in glob.glob(tmp_pattern):
        try:
            if not os.path.isfile(path):
                continue
            basename = os.path.basename(path)
            if ".session.meta.tmp" not in basename:
                continue
            if retention_seconds > 0 and now - os.path.getmtime(path) > retention_seconds:
                os.remove(path)
                logger.debug("Removed orphaned session meta temp file: %s", path)
        except Exception:
            pass
