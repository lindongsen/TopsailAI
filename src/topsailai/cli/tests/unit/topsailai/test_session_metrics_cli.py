"""CLI session metric exposure: every metric must reach both output modes.

Author: DawsonLin

The human requirement is that ``--json`` emits all fields by default without
deliberate suppression, and that the human-readable card shows the same set.
"""

import json
import sys
from pathlib import Path

import pytest

CLI_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CLI_ROOT))
sys.path.insert(0, str(CLI_ROOT.parent))

from cli_topsailai.session_metrics import METRIC_FIELDS, session_metrics
from topsailai.context.session_manager import SessionData

EXPECTED_METRICS = {
    "turn_total_count", "turn_failure_count", "turn_back_count", "turn_interrupt_count",
    "summary_count", "llm_request_count", "llm_request_failure_count",
    "response_content_errors", "tool_call_count", "tool_error_count",
    "tool_duration_ms_sum", "llm_request_duration_ms_sum", "first_byte_count",
    "first_byte_sum_ms", "requests_per_minute_max", "max_prompt_tokens",
    "heavy_task_warning_count", "heavy_task_block_count",
}


def _session(**overrides):
    """Build a fully populated SessionData for output assertions."""
    values = dict(
        session_id="s1", task="t", turn_count=7, turn_failure_count=2,
        turn_back_count=1, turn_interrupt_count=1, summary_count=4,
        llm_request_count=30, llm_request_failure_count=3,
        response_content_errors=2, tool_call_count=50, tool_error_count=5,
        tool_duration_ms_sum=1200, llm_request_duration_ms_sum=9000,
        first_byte_count=4, first_byte_sum_ms=2000, requests_per_minute_max=9,
        max_prompt_tokens=88000, heavy_task_warning_count=2,
        heavy_task_block_count=1, model_name="Kimi-K2.5",
    )
    values.update(overrides)
    return SessionData(**values)


def test_metric_field_list_covers_every_metric():
    """The shared field list must contain every metric the CLI promises."""
    assert {name for name, _, _ in METRIC_FIELDS} == EXPECTED_METRICS


def test_turn_total_count_is_the_display_alias_of_turn_count():
    """The database keeps one total column; the CLI names it explicitly."""
    metrics = session_metrics(_session())
    assert metrics["turn_total_count"] == 7


def test_first_byte_average_is_derived_from_sum_and_count():
    """The average must be computed once, in the shared helper."""
    metrics = session_metrics(_session())
    assert metrics["first_byte_avg_ms"] == 500.0


def test_first_byte_average_is_zero_without_samples():
    """No samples must not divide by zero."""
    metrics = session_metrics(_session(first_byte_count=0, first_byte_sum_ms=0))
    assert metrics["first_byte_avg_ms"] == 0.0


def test_session_info_json_emits_every_metric():
    """``topsailai_session_info --json`` must not suppress any metric."""
    import topsailai_session_info

    payload = topsailai_session_info._session_to_dict(_session(), "/tmp", running=False)
    assert EXPECTED_METRICS <= set(payload)
    assert payload["turn_total_count"] == 7
    assert payload["model_name"] == "Kimi-K2.5"
    # The payload must be JSON serializable as-is.
    json.loads(json.dumps(payload))


def test_list_sessions_json_emits_every_metric():
    """``ai_list_sessions --json`` must not suppress any metric."""
    import ai_list_sessions

    payload = ai_list_sessions._session_to_dict(_session())
    assert EXPECTED_METRICS <= set(payload)
    assert payload["turn_total_count"] == 7
    json.loads(json.dumps(payload))


def test_session_info_card_shows_every_metric():
    """The human-readable card must show the same metric set."""
    import topsailai_session_info

    text = topsailai_session_info._format_session(_session(), "/tmp", False, running=False)
    for name in EXPECTED_METRICS:
        assert name in text, name


def test_list_sessions_card_shows_every_metric():
    """The list card must show the same metric set."""
    import ai_list_sessions

    text = ai_list_sessions._format_session(_session(), 1, 120, False)
    for name in EXPECTED_METRICS:
        assert name in text, name
