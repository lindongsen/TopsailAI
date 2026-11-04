#!/usr/bin/env python3
"""Mirror one successful memory write into a team knowledge index.

Scenario: a team keeps its durable notes in the agent's memory, but the same
notes must be discoverable from a shared index that other tooling reads. The
index is a separate artifact with its own retention rule, so it cannot live
inside the memory folder. This consumer receives one memory event on stdin and
rewrites a bounded index document, so the index never grows without limit.
"""

import json
import os
import sys
from pathlib import Path

INDEX_ENV = "TOPSAILAI_COOKBOOK_INDEX_FILE"
MAX_ENTRIES = 50
REQUIRED_FIELDS = ("schema_version", "event", "memory_id", "title", "timestamp")


def _index_path() -> Path:
    """Return the absolute index path selected by the operator.

    Returns:
        The index file path.

    Raises:
        ValueError: When the variable is unset or not absolute.
    """
    raw = os.getenv(INDEX_ENV, "").strip()
    if not raw or not os.path.isabs(raw):
        raise ValueError(f"{INDEX_ENV} must name an absolute file path")
    return Path(raw)


def _read_index(path: Path) -> list[dict]:
    """Load the existing index entries, tolerating a missing or broken file.

    Args:
        path: The index file path.

    Returns:
        The stored entries, or an empty list when the file cannot be used.
    """
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return entries if isinstance(entries, list) else []


def _validate(event: dict) -> str:
    """Return an error message when the event cannot be indexed.

    Args:
        event: The decoded stdin payload.

    Returns:
        An empty string when the payload is usable, otherwise the reason.
    """
    missing = [name for name in REQUIRED_FIELDS if name not in event]
    if missing:
        return f"missing fields: {','.join(missing)}"
    if event["event"] not in ("create", "update"):
        return f"unsupported event: {event['event']}"
    return ""


def main() -> int:
    """Read one memory event and rewrite the bounded index document.

    Returns:
        0 on success, 2 when the payload or configuration is unusable.
    """
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"error: invalid stdin JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(event, dict):
        print("error: stdin must contain one JSON object", file=sys.stderr)
        return 2

    reason = _validate(event)
    if reason:
        print(f"error: {reason}", file=sys.stderr)
        return 2

    try:
        path = _index_path()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    entries = [item for item in _read_index(path) if item.get("memory_id") != event["memory_id"]]
    entries.append(
        {
            "memory_id": event["memory_id"],
            "title": event["title"],
            "event": event["event"],
            "version": event.get("version"),
            "timestamp": event["timestamp"],
        }
    )
    entries = entries[-MAX_ENTRIES:]

    document = {"schema_version": 1, "entries": entries}
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(f"indexed memory_id={event['memory_id']} entries={len(entries)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
