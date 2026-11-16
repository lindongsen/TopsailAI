"""Data-only heavy-task warning validation.

Author: DawsonLin
"""

from topsailai.hooks.points.workspace.after_heavy_task_warning.point import (
    POINT,
)
from topsailai.hooks.validation import validate_payload

_FIELDS = frozenset(POINT.definition.payload_schema["properties"])


def build_payload(payload):
    """Return detached validated metadata; reject missing or unknown fields."""
    if type(payload) is not dict or set(payload) != _FIELDS:
        raise ValueError("invalid_heavy_task_warning_fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("invalid_schema_version")
    _validate_count(payload["continuous_summary_times"], "invalid_continuous_summary_times")
    _validate_count(payload["threshold"], "invalid_threshold")
    return validate_payload(POINT.definition, payload)


def _validate_count(value, error):
    """Reject booleans and negative counters; only real integers are accepted."""
    if type(value) is not int or value < 0:
        raise ValueError(error)


__all__ = ["build_payload"]
