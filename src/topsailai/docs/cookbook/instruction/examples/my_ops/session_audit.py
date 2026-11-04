"""Session audit helpers exposed as /session_audit.* slash instructions."""

# Dict form: the key is the action name, so this module registers
# /session_audit.stats and /session_audit.events.
#
# Scenario: a session misbehaved and you want to know what ran on this host.
# Dumping the raw metadata and event files into the LLM context is expensive and
# usually truncated, so both actions read the real files under
# FOLDER_WORKSPACE_TASK and print a bounded summary for you instead.

import json
from collections import Counter
from pathlib import Path

from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK

MAX_ITEMS = 20


def _meta_files() -> list[Path]:
    """Return the session metadata files, newest first.

    Returns:
        The metadata paths sorted by modification time, newest first. A file
        that disappears between listing and stat is skipped.
    """
    folder = Path(FOLDER_WORKSPACE_TASK)
    if not folder.is_dir():
        return []

    found = []
    for path in folder.glob("*.session.meta"):
        try:
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue
    found.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in found]


def _load_meta(path: Path) -> dict:
    """Load one metadata file, tolerating a partially written record.

    Args:
        path: The metadata file path.

    Returns:
        The decoded record, or an empty mapping when it cannot be read.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_limit(limit: str) -> int | None:
    """Convert the limit argument, which always arrives as a string.

    Args:
        limit: A decimal string.

    Returns:
        The bounded positive limit, or None when the value is invalid.
    """
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return min(value, MAX_ITEMS)


def stats(limit: str = "10") -> str:
    """Summarize the sessions recorded on this host.

    Args:
        limit: How many recent sessions to list, as a decimal string. Capped at 20.

    Returns:
        Status and model counts, then the most recent sessions, or an error message.
    """
    shown = _parse_limit(limit)
    if shown is None:
        return "error: limit must be a positive integer"

    files = _meta_files()
    if not files:
        return f"no session metadata under {FOLDER_WORKSPACE_TASK}"

    records = [(path, _load_meta(path)) for path in files]
    statuses = Counter(rec.get("status", "unknown") for _, rec in records)
    models = Counter(rec.get("model_name", "unknown") for _, rec in records)

    lines = [f"sessions: {len(records)}"]
    lines.append("status: " + ", ".join(f"{k}={v}" for k, v in statuses.most_common()))
    lines.append("model: " + ", ".join(f"{k}={v}" for k, v in models.most_common()))
    lines.append(f"recent (limit={shown}):")
    for path, rec in records[:shown]:
        lines.append(
            f"  {rec.get('session_id', path.stem)}"
            f" status={rec.get('status', 'unknown')}"
            f" name={rec.get('session_name') or '-'}"
            f" model={rec.get('model_name', 'unknown')}"
        )
    return "\n".join(lines)


def events(session_id: str = "", limit: str = "10") -> str:
    """Count the recorded events of one session.

    Args:
        session_id: The session id to inspect. Empty means the newest session.
        limit: How many event types to list, as a decimal string. Capped at 20.

    Returns:
        The event type counts, or an error message.
    """
    shown = _parse_limit(limit)
    if shown is None:
        return "error: limit must be a positive integer"

    files = _meta_files()
    if not files:
        return f"no session metadata under {FOLDER_WORKSPACE_TASK}"

    target = None
    for path in files:
        record = _load_meta(path)
        if not session_id or record.get("session_id") == session_id:
            target = (path, record)
            break
    if target is None:
        return f"no session found for id={session_id}"

    path, record = target
    events_name = (record.get("files") or {}).get("events", "")
    if not events_name:
        return f"session {record.get('session_id', path.stem)} has no events file recorded"

    events_path = Path(FOLDER_WORKSPACE_TASK) / events_name
    if not events_path.is_file():
        return f"events file missing: {events_path}"

    counts = Counter()
    total = 0
    try:
        with events_path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    counts[json.loads(line).get("event_type", "unknown")] += 1
                except json.JSONDecodeError:
                    counts["<unparsed>"] += 1
    except OSError as exc:
        return f"error: {exc}"

    lines = [f"session: {record.get('session_id', path.stem)} events={total}"]
    for name, count in counts.most_common(shown):
        lines.append(f"  {name}={count}")
    return "\n".join(lines)


INSTRUCTIONS = {
    "stats": stats,
    "events": events,
}
