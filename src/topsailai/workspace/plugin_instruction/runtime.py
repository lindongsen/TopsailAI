"""Read-only Instructions for the current Agent's public Runtime Data."""

from __future__ import annotations

import re
from typing import Any

from topsailai.utils import env_tool, json_tool
from topsailai.workspace.plugin_instruction.base.cache import get_ai_agent


_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_DISPLAY_VALUE_FIELDS = (
    "phase",
    "failed_attempts",
    "next_retry_number",
    "threshold",
    "last_error_category",
    "dropped_total",
    "delivered_total",
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


_JSON_PARAM = "json"
_USAGE_UNKNOWN_PARAMETER = "unknown_parameter"
_USAGE_TOO_MANY_ARGUMENTS = "too_many_arguments"
_USAGE_MISSING_KEY = "missing_key"


def _json_dump(payload: dict) -> str:
    """Serialize one JSON response as a stable, human-readable string."""
    return json_tool.safe_json_dump(payload, indent=2)


def _error_response(error: str, usage: str, json_enabled: bool) -> str:
    """Render one argument error as structured JSON or a plain usage line."""
    if json_enabled:
        return _json_dump({"ok": False, "error": error, "usage": usage})
    return usage


def _invalid_key(json_enabled: bool) -> str:
    """Render the invalid-key contract in the requested output format."""
    if json_enabled:
        return _json_dump({"ok": False, "error": "invalid_key"})
    return "Invalid runtime state key."


def _no_runtime(json_enabled: bool) -> str:
    """Render the no-Agent contract in the requested output format."""
    if json_enabled:
        return _json_dump({"ok": False, "error": "no_runtime"})
    return _NO_RUNTIME


def _not_found(key: str, json_enabled: bool) -> str:
    """Render the not-found contract without disclosing private state."""
    if json_enabled:
        return _json_dump({"ok": False, "error": "not_found", "key": key})
    return f"Runtime state not found: {key}"


def _public_value(value: Any) -> dict:
    """Return only approved diagnostic fields from one public payload."""
    if not isinstance(value, dict):
        return {}
    return {
        field: value[field]
        for field in _DISPLAY_VALUE_FIELDS
        if field in value and isinstance(value[field], (str, int, float, bool))
    }


def _active_entry(snapshot) -> dict:
    """Build one active JSON entry without internal ownership data."""
    return {
        "key": snapshot.key,
        "revision": snapshot.revision,
        "updated_at_ms": snapshot.updated_at_ms,
        "value": _public_value(snapshot.value),
    }


def _history_entry(snapshot) -> dict:
    """Build one settled JSON entry without internal ownership data."""
    return {
        "key": snapshot.key,
        "outcome": snapshot.outcome,
        "revision": snapshot.revision,
        "settled_at_ms": snapshot.settled_at_ms,
        "value": _public_value(snapshot.value),
    }


def _split_named_parameter(item: str) -> tuple[str, str] | None:
    """Split one `name=value` token, returning None when it has no separator."""
    if "=" not in item:
        return None
    name, value = item.split("=", 1)
    return name.strip(), value.strip()


def _normalize_arguments(
    args: tuple,
    kwargs: dict,
    *,
    allow_key: bool,
    key_required: bool,
) -> tuple[str | None, bool, str | None]:
    """Resolve the optional key and the `json` flag from either argument form.

    Terminal dispatch delivers named parameters as keyword arguments, while the
    control channel forwards them as positional `name=value` strings. Both forms
    are accepted so one Instruction behaves identically on every transport.

    Returns:
        A `(key, json_enabled, error)` triple. `error` is a stable token when the
        arguments are unusable, and `None` otherwise.
    """
    segments = []
    for name, value in kwargs.items():
        segments.append((name, value))
    for item in args:
        if not isinstance(item, str):
            return None, False, _USAGE_UNKNOWN_PARAMETER
        if not item.strip():
            # An explicitly empty positional argument is an invalid key, not a
            # missing one, so it must reach key validation unchanged.
            segments.append((None, item))
            continue
        # One forwarded token may carry several `;`-separated named parameters.
        for segment in item.split(";"):
            if not segment.strip():
                continue
            pair = _split_named_parameter(segment)
            if pair is None:
                segments.append((None, segment.strip()))
            else:
                segments.append(pair)

    # Resolve the output format first so every later error uses that format.
    json_enabled = False
    for name, value in segments:
        if name == _JSON_PARAM:
            json_enabled = env_tool.is_true(value)

    key = None
    positional = []
    for name, value in segments:
        if name == _JSON_PARAM:
            continue
        if name is None:
            positional.append(value)
        elif name == "key" and allow_key:
            key = value
        else:
            return None, json_enabled, _USAGE_UNKNOWN_PARAMETER

    if positional:
        if key is not None or not allow_key or len(positional) > 1:
            return None, json_enabled, _USAGE_TOO_MANY_ARGUMENTS
        key = positional[0]

    if key_required and key is None:
        return None, json_enabled, _USAGE_MISSING_KEY
    return key, json_enabled, None


def show_runtime(*args, **kwargs) -> str:
    """Show all active public Runtime Data for the current Agent."""
    _, json_enabled, error = _normalize_arguments(
        args, kwargs, allow_key=False, key_required=False,
    )
    if error:
        return _error_response(error, "Usage: /runtime [json=1]", json_enabled)
    store = _get_runtime_data_store()
    if store is None:
        return _no_runtime(json_enabled)
    snapshots = store.snapshot(public_only=True)
    if json_enabled:
        return _json_dump({
            "ok": True,
            "active": [_active_entry(snapshot) for snapshot in snapshots],
        })
    if not snapshots:
        return "No active runtime states."
    lines = ["Active runtime states:"]
    for snapshot in snapshots:
        lines.extend(("", *_format_active(snapshot)))
    return "\n".join(lines)


def get_runtime(*args, **kwargs) -> str:
    """Show one active public Runtime Data state by exact key."""
    key, json_enabled, error = _normalize_arguments(
        args, kwargs, allow_key=True, key_required=True,
    )
    if error:
        return _error_response(
            error, "Usage: /runtime.get <key> [json=1]", json_enabled,
        )
    if not _valid_key(key):
        return _invalid_key(json_enabled)
    store = _get_runtime_data_store()
    if store is None:
        return _no_runtime(json_enabled)
    snapshot = store.get(key, public_only=True)
    if snapshot is None:
        return _not_found(key, json_enabled)
    if json_enabled:
        return _json_dump({"ok": True, "active": _active_entry(snapshot)})
    return "\n".join(_format_active(snapshot))


def show_runtime_history(*args, **kwargs) -> str:
    """Show bounded public Runtime Data history, optionally by exact key."""
    key, json_enabled, error = _normalize_arguments(
        args, kwargs, allow_key=True, key_required=False,
    )
    if error:
        return _error_response(
            error, "Usage: /runtime.history [key] [json=1]", json_enabled,
        )
    if key is not None and not _valid_key(key):
        return _invalid_key(json_enabled)
    store = _get_runtime_data_store()
    if store is None:
        return _no_runtime(json_enabled)
    snapshots = store.history(key, public_only=True)
    if json_enabled:
        return _json_dump({
            "ok": True,
            "history": [_history_entry(snapshot) for snapshot in snapshots],
        })
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
