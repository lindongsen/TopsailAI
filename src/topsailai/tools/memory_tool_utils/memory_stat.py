"""Observable usage statistics for story memories."""

import hashlib
import json
import logging
import os
import time
from typing import Callable

from topsailai.utils import time_tool
from topsailai.workspace import lock_tool

logger = logging.getLogger(__name__)

STAT_VERSION = 1
STAT_FOLDER = ".stats"
EVENT_FIELDS = {
    "read": ("read_count", "last_read_at"),
    "cite": ("cite_count", "last_cited_at"),
    "query": ("query_count", "last_queried_at"),
    "update": ("update_count", "last_updated_at"),
}


def get_memory_id(memory_file: str) -> str:
    """Return the canonical memory identifier for a resolved Markdown file."""
    return os.path.basename(memory_file)


def get_stat_file(workspace: str, memory_id: str) -> str:
    """Return the stat JSON path for a canonical memory identifier."""
    encoded_id = hashlib.sha256(memory_id.encode("utf-8")).hexdigest()
    return os.path.join(workspace, "story", STAT_FOLDER, encoded_id + ".json")


def _new_stat(memory_id: str, timestamp: str) -> dict:
    return {
        "version": STAT_VERSION,
        "memory_id": memory_id,
        "read_count": 0,
        "cite_count": 0,
        "query_count": 0,
        "update_count": 0,
        "created_at": timestamp,
        "last_read_at": None,
        "last_cited_at": None,
        "last_queried_at": None,
        "last_updated_at": None,
        "last_activity_at": timestamp,
    }


def _validate_stat(stat: dict, memory_id: str) -> dict:
    """Validate persisted identity and required v1 fields."""
    if not isinstance(stat, dict):
        raise ValueError("memory stat must be a JSON object")
    if stat.get("version") != STAT_VERSION:
        raise ValueError(f"unsupported memory stat version: {stat.get('version')}")
    if stat.get("memory_id") != memory_id:
        raise ValueError("memory stat identity mismatch")
    for count_field, timestamp_field in EVENT_FIELDS.values():
        count = stat.get(count_field)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError(f"invalid memory stat counter: {count_field}")
        if timestamp_field not in stat:
            raise ValueError(f"missing memory stat timestamp: {timestamp_field}")
    for field in ("created_at", "last_activity_at"):
        if not isinstance(stat.get(field), str) or not stat[field]:
            raise ValueError(f"invalid memory stat timestamp: {field}")
    return stat


def _lock_name(memory_id: str) -> str:
    digest = hashlib.sha256(memory_id.encode("utf-8")).hexdigest()
    return "memory_stat_" + digest


READ_RETRY_ATTEMPTS = 3
READ_RETRY_DELAY_SECONDS = 0.05


def read_memory_stat_file(
    stat_file: str, memory_id: str | None = None
) -> dict | None:
    """Read and validate one stat file without rebuilding or modifying it.

    When ``memory_id`` is omitted, the persisted identity is used for schema
    validation. Callers that know the expected identity should pass it so an
    identity mismatch is surfaced as ``ValueError``. Missing files return
    ``None``; malformed JSON and invalid records propagate their exceptions.
    """
    try:
        with open(stat_file, encoding="utf-8") as fd:
            stat = json.load(fd)
    except FileNotFoundError:
        return None
    expected_id = memory_id
    if expected_id is None and isinstance(stat, dict):
        expected_id = stat.get("memory_id")
    return _validate_stat(stat, expected_id or "")


def _read_stat_file(stat_file: str, memory_id: str) -> dict | None:
    """Read one stat file through the non-rebuilding validated primitive."""
    return read_memory_stat_file(stat_file, memory_id)


def _read_stat_file_with_retry(stat_file: str, memory_id: str) -> dict | None:
    """Retry corrupt reads briefly before reporting persistent corruption."""
    for attempt in range(READ_RETRY_ATTEMPTS):
        try:
            return _read_stat_file(stat_file, memory_id)
        except (json.JSONDecodeError, ValueError):
            if attempt + 1 < READ_RETRY_ATTEMPTS:
                time.sleep(READ_RETRY_DELAY_SECONDS)
    raise ValueError("memory stat remains corrupt after retries")


def read_memory_stat(workspace: str, memory_id: str) -> dict | None:
    """Read a validated stat, rebuilding persistent corruption under lock."""
    stat_file = get_stat_file(workspace, memory_id)
    try:
        return _read_stat_file_with_retry(stat_file, memory_id)
    except ValueError:
        logger.warning("rebuild corrupt memory stat: [%s]", stat_file)
        return ensure_memory_stat(workspace, memory_id)


def _write_stat(stat_file: str, stat: dict) -> None:
    """Write a stat directly while its caller holds the per-memory lock."""
    os.makedirs(os.path.dirname(stat_file), exist_ok=True)
    with open(stat_file, "w", encoding="utf-8") as fd:
        json.dump(stat, fd, ensure_ascii=False, indent=2, sort_keys=True)
        fd.write("\n")
        fd.flush()


def mutate_memory_stat(
    workspace: str,
    memory_id: str,
    mutation: Callable[[dict, str], None] | None = None,
) -> dict:
    """Create or mutate a stat while holding its stable lock."""
    stat_file = get_stat_file(workspace, memory_id)
    with lock_tool.FileLock(_lock_name(memory_id), delete_on_release=False):
        timestamp = time_tool.get_current_local_datetime_with_offset()
        try:
            stat = _read_stat_file(stat_file, memory_id)
        except (json.JSONDecodeError, ValueError):
            stat = None
        stat = stat or _new_stat(memory_id, timestamp)
        if mutation:
            mutation(stat, timestamp)
        _validate_stat(stat, memory_id)
        _write_stat(stat_file, stat)
        return stat


def ensure_memory_stat(workspace: str, memory_id: str) -> dict:
    """Ensure a zero-count stat exists for a newly written memory."""
    return mutate_memory_stat(workspace, memory_id)


def record_memory_event(workspace: str, memory_id: str, event: str) -> dict:
    """Increment one activity counter and refresh its timestamps."""
    if event not in EVENT_FIELDS:
        raise ValueError(f"unsupported memory stat event: {event}")
    count_field, timestamp_field = EVENT_FIELDS[event]

    def increment(stat: dict, timestamp: str) -> None:
        stat[count_field] += 1
        stat[timestamp_field] = timestamp
        stat["last_activity_at"] = timestamp

    return mutate_memory_stat(workspace, memory_id, increment)


def delete_memory_stat(workspace: str, memory_id: str) -> bool:
    """Delete a stat first; non-missing errors propagate to stop memory deletion."""
    stat_file = get_stat_file(workspace, memory_id)
    with lock_tool.FileLock(_lock_name(memory_id), delete_on_release=False):
        try:
            os.remove(stat_file)
            logger.info("delete memory stat: [%s]", stat_file)
            return True
        except FileNotFoundError:
            logger.debug("memory stat already absent: [%s]", stat_file)
            return False
        except OSError:
            logger.exception("failed to delete memory stat: [%s]", stat_file)
            raise
