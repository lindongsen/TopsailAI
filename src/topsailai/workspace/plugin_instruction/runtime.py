"""Read-only Instructions for the current Agent's public Runtime Data."""

from __future__ import annotations

import re
from typing import Any

from topsailai.workspace.plugin_instruction.base.cache import get_ai_agent


_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_DISPLAY_VALUE_FIELDS = (
    "phase",
    "failed_attempts",
    "next_retry_number",
    "threshold",
    "last_error_category",
)
_MAX_DISPLAY_VALUE_LENGTH = 120
_NO_RUNTIME = "No active Agent runtime."


def _get_runtime_data_store():
    """Return the current Agent's Runtime Data Store when available."""
    agent = get_ai_agent()
    runtime = getattr(agent, "runtime", None) if agent is not None else None
    return getattr(runtime, "runtime_data", None) if runtime is not None else None


def _valid_key(key: Any) -> bool:
    """Return whether a value is one exact namespaced runtime-state key."""
    return isinstance(key, str) and _KEY_PATTERN.fullmatch(key) is not None


def _display_label(field: str) -> str:
    """Convert one approved payload field to a human-readable label."""
    return field.replace("_", " ").capitalize()


def _display_value(value: Any) -> str:
    """Render one approved scalar value within a fixed character bound."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    if len(text) > _MAX_DISPLAY_VALUE_LENGTH:
        return text[:_MAX_DISPLAY_VALUE_LENGTH] + "..."
    return text


def _format_value(value: Any) -> list[str]:
    """Render only approved diagnostic fields from one public payload."""
    if not isinstance(value, dict):
        return []
    return [
        f"  {_display_label(field)}: {_display_value(value[field])}"
        for field in _DISPLAY_VALUE_FIELDS
        if field in value and isinstance(value[field], (str, int, float, bool))
    ]


def _format_active(snapshot) -> list[str]:
    """Format one detached active snapshot without internal ownership data."""
    lines = [snapshot.key, f"  Revision: {snapshot.revision}"]
    lines.extend(_format_value(snapshot.value))
    lines.append(f"  Updated at ms: {snapshot.updated_at_ms}")
    return lines


def _format_history(snapshot) -> list[str]:
    """Format one detached settled snapshot without internal ownership data."""
    lines = [snapshot.key, f"  Outcome: {_display_value(snapshot.outcome)}"]
    lines.extend(_format_value(snapshot.value))
    lines.extend((
        f"  Revision: {snapshot.revision}",
        f"  Settled at ms: {snapshot.settled_at_ms}",
    ))
    return lines


def show_runtime(*args) -> str:
    """Show all active public Runtime Data for the current Agent."""
    if args:
        return "Usage: /runtime"
    store = _get_runtime_data_store()
    if store is None:
        return _NO_RUNTIME
    snapshots = store.snapshot(public_only=True)
    if not snapshots:
        return "No active runtime states."
    lines = ["Active runtime states:"]
    for snapshot in snapshots:
        lines.extend(("", *_format_active(snapshot)))
    return "\n".join(lines)


def get_runtime(*args) -> str:
    """Show one active public Runtime Data state by exact key."""
    if len(args) != 1:
        return "Usage: /runtime.get <key>"
    key = args[0]
    if not _valid_key(key):
        return "Invalid runtime state key."
    store = _get_runtime_data_store()
    if store is None:
        return _NO_RUNTIME
    snapshot = store.get(key, public_only=True)
    if snapshot is None:
        return f"Runtime state not found: {key}"
    return "\n".join(_format_active(snapshot))


def show_runtime_history(*args) -> str:
    """Show bounded public Runtime Data history, optionally by exact key."""
    if len(args) > 1:
        return "Usage: /runtime.history [key]"
    key = args[0] if args else None
    if key is not None and not _valid_key(key):
        return "Invalid runtime state key."
    store = _get_runtime_data_store()
    if store is None:
        return _NO_RUNTIME
    snapshots = store.history(key, public_only=True)
    if not snapshots:
        return "No runtime state history."
    lines = ["Runtime state history:"]
    for snapshot in snapshots:
        lines.extend(("", *_format_history(snapshot)))
    return "\n".join(lines)


INSTRUCTIONS = {
    "runtime": show_runtime,
    "get": get_runtime,
    "history": show_runtime_history,
}
