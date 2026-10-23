"""Strict data-only LLM attempt metadata contracts. Author: DawsonLin."""

import json
import math
import re

from topsailai.hooks.validation import validate_payload

COMMON_PROPERTIES = {
    "schema_version": {"type": "integer"},
    "operation_id": {"type": "string"},
    "attempt_number": {"type": "integer"},
    "point_name": {"type": "string"},
    "outcome": {"type": "string"},
    "stream": {"type": "boolean"},
    "return_mode": {"type": "string"},
}


def build_attempt_payload(payload, *, point, loop_attempts):
    """Validate exact scalar metadata and detach it without dispatching Hooks."""
    fields = set(point.definition.payload_schema["properties"])
    if type(payload) is not dict or set(payload) != fields:
        raise ValueError("invalid_attempt_fields")
    if type(loop_attempts) is not int or loop_attempts < 1:
        raise ValueError("invalid_attempt_limit")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("invalid_schema_version")
    operation = payload["operation_id"]
    if type(operation) is not str or re.fullmatch(r"[0-9a-f]{32}", operation) is None:
        raise ValueError("invalid_operation_id")
    attempt = payload["attempt_number"]
    if type(attempt) is not int or not 1 <= attempt <= loop_attempts:
        raise ValueError("invalid_attempt_number")
    if type(payload["point_name"]) is not str or payload["point_name"] != point.name:
        raise ValueError("invalid_point_name")
    if type(payload["outcome"]) is not str or payload["outcome"] != point.phase:
        raise ValueError("invalid_outcome")
    if type(payload["stream"]) is not bool:
        raise ValueError("invalid_stream")
    mode = payload["return_mode"]
    if type(mode) is not str or mode not in ("raw", "parsed", "response_and_parsed"):
        raise ValueError("invalid_return_mode")
    if "duration_sec" in fields:
        _validate_duration(payload["duration_sec"])
    if "error_category" in fields:
        category = payload["error_category"]
        if type(category) is not str or not 1 <= len(category) <= 128:
            raise ValueError("invalid_error_category")
    # Exact scalars above prevent custom serializers or live-object traversal.
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 8192:
        raise ValueError("attempt_payload_too_large")
    return validate_payload(point.definition, payload)


def _validate_duration(value):
    """Reject booleans, non-finite floats and negative monotonic durations."""
    if type(value) not in (int, float) or value < 0:
        raise ValueError("invalid_duration")
    if type(value) is float and not math.isfinite(value):
        raise ValueError("invalid_duration")
