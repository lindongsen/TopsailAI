"""Bounded durable JSONL outbox for the external mem-graph consumer."""

import hashlib
import json
import logging
import os
import tempfile

from topsailai.workspace import lock_tool

logger = logging.getLogger(__name__)

OUTBOX_FOLDER = ".sync"
OUTBOX_FILE = "mem_graph_outbox.jsonl"
DEFAULT_MAX_ENTRIES = 1000
DEFAULT_MAX_BYTES = 10485760


def get_outbox_file(workspace: str) -> str:
    """Return the workspace-scoped outbox path."""
    return os.path.join(workspace, "story", OUTBOX_FOLDER, OUTBOX_FILE)


def _positive_env_int(name: str, default: int) -> int:
    """Read one positive integer limit with a safe default."""
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _lock_name(workspace: str) -> str:
    """Build a stable lock name for one workspace outbox."""
    digest = hashlib.sha256(os.path.abspath(workspace).encode("utf-8")).hexdigest()
    return "mem_graph_sync_outbox_" + digest


def _read_unlocked(path: str) -> list[dict]:
    """Read valid JSON-object records while skipping corrupt lines."""
    try:
        with open(path, encoding="utf-8") as stream:
            lines = stream.readlines()
    except FileNotFoundError:
        return []
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            logger.warning("skip invalid mem-graph outbox record")
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _bounded(records: list[dict]) -> list[dict]:
    """Retain newest records within configured count and byte limits."""
    max_entries = _positive_env_int(
        "TOPSAILAI_MEMORY_SYNC_OUTBOX_MAX_ENTRIES", DEFAULT_MAX_ENTRIES
    )
    max_bytes = _positive_env_int(
        "TOPSAILAI_MEMORY_SYNC_OUTBOX_MAX_BYTES", DEFAULT_MAX_BYTES
    )
    selected = []
    size = 0
    for record in reversed(records[-max_entries:]):
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        encoded_size = len(encoded.encode("utf-8"))
        if selected and size + encoded_size > max_bytes:
            break
        if encoded_size > max_bytes:
            logger.warning("drop oversized mem-graph outbox record")
            continue
        selected.append(record)
        size += encoded_size
    selected.reverse()
    return selected


def _write_unlocked(path: str, records: list[dict]) -> None:
    """Atomically replace the outbox with bounded records."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=OUTBOX_FILE + ".", suffix=".tmp", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            for record in _bounded(records):
                json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            logger.info("delete temporary mem-graph outbox: [%s]", temp_path)


def enqueue(workspace: str, event: dict) -> None:
    """Append one event unless the exact event is already pending."""
    path = get_outbox_file(workspace)
    with lock_tool.FileLock(_lock_name(workspace), delete_on_release=False):
        records = _read_unlocked(path)
        if event not in records:
            records.append(event)
        _write_unlocked(path, records)


def read(workspace: str) -> list[dict]:
    """Return a stable snapshot of pending events."""
    path = get_outbox_file(workspace)
    with lock_tool.FileLock(_lock_name(workspace), delete_on_release=False):
        return _read_unlocked(path)


def replace(workspace: str, events: list[dict]) -> None:
    """Replace pending events after a retry pass."""
    path = get_outbox_file(workspace)
    with lock_tool.FileLock(_lock_name(workspace), delete_on_release=False):
        _write_unlocked(path, events)
