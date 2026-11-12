"""Data-only LLM request failure report validation. Author: DawsonLin."""

import json
import math
import re

from topsailai.hooks.points.aibase.after_llm_request_failures.point import (
    FAILURE_MESSAGE_MAX_CHARS,
    MAX_FAILURES,
    MESSAGE_MAX_CHARS,
    POINT,
)
from topsailai.hooks.validation import validate_payload

_FIELDS = frozenset(POINT.definition.payload_schema["properties"])
_FAILURE_FIELDS = frozenset(
    POINT.definition.payload_schema["properties"]["failures"]["items"]["properties"]
)
_OUTCOMES = frozenset({"success", "failed", "aborted"})
_OPERATION_ID = re.compile(r"[0-9a-f]{32}\Z")


def build_payload(payload):
    """Return detached validated metadata; reject missing or unknown fields."""
    if type(payload) is not dict or set(payload) != _FIELDS:
        raise ValueError("invalid_failure_report_fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("invalid_schema_version")
    _validate_operation_id(payload["operation_id"])
    if type(payload["outcome"]) is not str or payload["outcome"] not in _OUTCOMES:
        raise ValueError("invalid_outcome")
    failures = payload["failures"]
    if type(failures) is not list or len(failures) > MAX_FAILURES:
        raise ValueError("invalid_failures")
    for failure in failures:
        _validate_failure(failure)
    _validate_counts(payload, failures)
    _validate_elapsed(payload["elapsed_sec"])
    # Exact scalars above prevent custom serializers or live-object traversal.
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 65536:
        raise ValueError("failure_report_too_large")
    return validate_payload(POINT.definition, payload)


def _validate_operation_id(value):
    """Accept an unbound request or the exact 32-character lowercase hex id."""
    if type(value) is not str:
        raise ValueError("invalid_operation_id")
    if value and _OPERATION_ID.fullmatch(value) is None:
        raise ValueError("invalid_operation_id")


def _validate_failure(failure):
    """Validate one recorded failure without accepting extra fields."""
    if type(failure) is not dict or set(failure) != _FAILURE_FIELDS:
        raise ValueError("invalid_failure_fields")
    attempt = failure["attempt"]
    if type(attempt) is not int or attempt < 1:
        raise ValueError("invalid_failure_attempt")
    category = failure["error"]
    if type(category) is not str or not 1 <= len(category) <= 128:
        raise ValueError("invalid_failure_error")
    message = failure["message"]
    if type(message) is not str or len(message) > MESSAGE_MAX_CHARS:
        raise ValueError("invalid_failure_message")
    if "\n" in message or "\r" in message:
        raise ValueError("invalid_failure_message")
    _validate_elapsed(failure["duration_sec"])


def _validate_counts(payload, failures):
    """Require the aggregate counters to agree with the recorded failures."""
    failed_attempts = payload["failed_attempts"]
    if type(failed_attempts) is not int or failed_attempts != len(failures):
        raise ValueError("invalid_failed_attempts")
    last_attempt = payload["last_failed_attempt"]
    expected_last = failures[-1]["attempt"] if failures else 0
    if type(last_attempt) is not int or last_attempt != expected_last:
        raise ValueError("invalid_last_failed_attempt")
    dropped = payload["dropped_failures"]
    if type(dropped) is not int or dropped < 0:
        raise ValueError("invalid_dropped_failures")


def _validate_elapsed(value):
    """Reject booleans, non-finite floats and negative monotonic durations."""
    if type(value) not in (int, float) or value < 0:
        raise ValueError("invalid_elapsed")
    if type(value) is float and not math.isfinite(value):
        raise ValueError("invalid_elapsed")


__all__ = ["build_payload", "FAILURE_MESSAGE_MAX_CHARS"]
