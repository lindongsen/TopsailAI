"""Shared session metric extraction for the TopsailAI CLI.

Author: DawsonLin

Both ``topsailai_session_info`` and ``ai_list_sessions`` must expose the same
metric set, so the field list lives here once. Adding a metric column means
editing this module only, which keeps the two commands from drifting apart.

``turn_total_count`` is a display alias for the stored ``turn_count`` column:
the database keeps one total-turns column, and the CLI names it explicitly so a
reader cannot confuse it with the per-outcome breakdown.
"""

from typing import Any

# (display name, SessionData attribute, default) in display order.
METRIC_FIELDS = (
    ("turn_total_count", "turn_count", 0),
    ("turn_failure_count", "turn_failure_count", 0),
    ("turn_back_count", "turn_back_count", 0),
    ("turn_interrupt_count", "turn_interrupt_count", 0),
    ("summary_count", "summary_count", 0),
    ("llm_request_count", "llm_request_count", 0),
    ("llm_request_failure_count", "llm_request_failure_count", 0),
    ("response_content_errors", "response_content_errors", 0),
    ("tool_call_count", "tool_call_count", 0),
    ("tool_error_count", "tool_error_count", 0),
    ("tool_duration_ms_sum", "tool_duration_ms_sum", 0),
    ("llm_request_duration_ms_sum", "llm_request_duration_ms_sum", 0),
    ("first_byte_count", "first_byte_count", 0),
    ("first_byte_sum_ms", "first_byte_sum_ms", 0),
    ("requests_per_minute_max", "requests_per_minute_max", 0),
    ("max_prompt_tokens", "max_prompt_tokens", 0),
    ("heavy_task_warning_count", "heavy_task_warning_count", 0),
    ("heavy_task_block_count", "heavy_task_block_count", 0),
)


def _int_value(session: Any, attribute: str, default: int = 0) -> int:
    """Read one integer metric without trusting the stored type."""
    value = getattr(session, attribute, default)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def session_metrics(session: Any) -> dict:
    """Return every session metric as a plain dictionary.

    The result is additive: callers merge it into their own payload, so a new
    metric appears in both the human-readable and the JSON output at once.
    """
    metrics = {
        name: _int_value(session, attribute, default)
        for name, attribute, default in METRIC_FIELDS
    }
    # Derived values are computed here so both commands agree on the formula.
    first_byte_count = metrics["first_byte_count"]
    metrics["first_byte_avg_ms"] = (
        round(metrics["first_byte_sum_ms"] / first_byte_count, 2)
        if first_byte_count else 0.0
    )
    metrics["model_name"] = str(getattr(session, "model_name", "") or "")
    return metrics


__all__ = ["METRIC_FIELDS", "session_metrics"]
