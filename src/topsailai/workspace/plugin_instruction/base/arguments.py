"""Shared named-parameter parsing for slash Instructions.

Terminal dispatch delivers named parameters as keyword arguments, while the
control channel forwards them as positional `name=value` strings. Both forms are
normalized here so one Instruction behaves identically on every transport.
"""

from __future__ import annotations

from topsailai.utils import env_tool, json_tool


JSON_PARAM = "json"
USAGE_UNKNOWN_PARAMETER = "unknown_parameter"
USAGE_TOO_MANY_ARGUMENTS = "too_many_arguments"
USAGE_MISSING_KEY = "missing_key"


def split_named_parameters(args: tuple, kwargs: dict) -> tuple[list, str | None]:
    """Flatten both argument forms into ordered `(name, value)` segments.

    A positional token may carry several `;`-separated named parameters, so each
    token is split before parsing. A segment without `=` is kept as a positional
    value with a `None` name, which lets the caller decide whether a bare value
    is meaningful.

    Returns:
        A `(segments, error)` pair. `error` is a stable token when an argument is
        not a string, and `None` otherwise.
    """
    segments = []
    for name, value in kwargs.items():
        segments.append((name, value))
    for item in args:
        if not isinstance(item, str):
            return [], USAGE_UNKNOWN_PARAMETER
        if not item.strip():
            # An explicitly empty positional argument is an invalid key, not a
            # missing one, so it must reach key validation unchanged.
            segments.append((None, item))
            continue
        for segment in item.split(";"):
            if not segment.strip():
                continue
            if "=" not in segment:
                segments.append((None, segment.strip()))
                continue
            name, value = segment.split("=", 1)
            segments.append((name.strip(), value.strip()))
    return segments, None


def resolve_json_flag(segments: list) -> bool:
    """Return whether the `json` flag requests structured output.

    Resolution happens before any other validation so every later error is
    rendered in the format the caller asked for. Truthiness reuses the shared
    environment convention, so `json=0` and an absent flag are equivalent.
    """
    json_enabled = False
    for name, value in segments:
        if name == JSON_PARAM:
            json_enabled = env_tool.is_true(value)
    return json_enabled


def json_dump(payload: dict) -> str:
    """Serialize one JSON response as a stable, human-readable string."""
    return json_tool.safe_json_dump(payload, indent=2)


def error_response(error: str, usage: str, json_enabled: bool) -> str:
    """Render one argument error as structured JSON or a plain usage line."""
    if json_enabled:
        return json_dump({"ok": False, "error": error, "usage": usage})
    return usage
