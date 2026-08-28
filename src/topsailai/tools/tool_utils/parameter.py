"""String-first parameter coercion helpers for registered tools."""

import json
import math
from typing import Any


def invalid_request(parameter: str, value: Any, reason: str) -> dict:
    """Build a machine-readable tool parameter error."""
    return {
        "status": "invalid_request",
        "reason": f"invalid {parameter}={value!r}: {reason}",
    }


def resolve_str_param(value: Any, parameter: str) -> tuple[str | None, dict | None]:
    """Resolve a string parameter without changing or interpreting its content."""
    if not isinstance(value, str):
        return None, invalid_request(parameter, value, "must be a string")
    return value, None


def resolve_finite_int(value: Any, parameter: str) -> tuple[int | None, dict | None]:
    """Resolve a finite numeric value using the existing integer conversion semantics."""
    if value is None or isinstance(value, bool):
        return None, invalid_request(parameter, value, "must be a finite number")
    if isinstance(value, str) and not value.strip():
        return None, invalid_request(parameter, value, "must be a finite number")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None, invalid_request(parameter, value, "must be a finite number")
    if not math.isfinite(numeric):
        return None, invalid_request(parameter, value, "must be a finite number")
    return int(numeric), None


def resolve_int_flag(value: Any, parameter: str) -> tuple[bool | None, dict | None]:
    """Resolve an integer boolean flag, accepting only 1 and 0 or their string forms."""
    if isinstance(value, bool):
        return None, invalid_request(parameter, value, "must be integer 1 or 0")
    if isinstance(value, int):
        numeric = value
    elif isinstance(value, str):
        try:
            numeric = int(value.strip())
        except (TypeError, ValueError):
            return None, invalid_request(parameter, value, "must be integer 1 or 0")
    else:
        return None, invalid_request(parameter, value, "must be integer 1 or 0")
    if numeric not in (0, 1):
        return None, invalid_request(parameter, value, "must be integer 1 or 0")
    return numeric == 1, None


def resolve_json_container(
        value: Any,
        parameter: str,
        expected_type: type,
        allow_none: bool = False,
    ) -> tuple[Any, dict | None]:
    """Resolve a native or JSON-encoded list/dict parameter with strict type checking."""
    if value is None and allow_none:
        return None, None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None, invalid_request(
                parameter,
                value,
                f"must be valid JSON encoding a {expected_type.__name__}",
            )
    if not isinstance(parsed, expected_type):
        return None, invalid_request(parameter, value, f"must be a {expected_type.__name__}")
    return parsed, None


def resolve_str_list(value: Any, parameter: str) -> tuple[list | None, dict | None]:
    """Resolve a list or a string representing either one value or a JSON list."""
    if isinstance(value, list):
        return value, None
    if not isinstance(value, str):
        return None, invalid_request(parameter, value, "must be a list or string")
    if not value.strip():
        return None, invalid_request(parameter, value, "must be a non-empty string or list")
    if value.lstrip().startswith(("[", "{")):
        return resolve_json_container(value, parameter, list)
    return [value], None
