"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Purpose: Unit tests for session metric accumulation and the tool error counter

  Features:
  - Atomic additive accumulation of settled attempt metric deltas
  - Negative delta normalization and unknown-session handling
  - O(1) tool error counter independent of record pruning
"""

import pytest

from topsailai.context.session_manager.__base import SessionData
from topsailai.context.session_manager.sql import SessionSQLAlchemy
from topsailai.context.tool_stat import ToolStat

METRIC_COLUMNS = (
    "turn_count",
    "tool_call_count",
    "tool_error_count",
    "llm_request_count",
    "llm_request_failure_count",
    "tool_duration_ms_sum",
    "llm_request_duration_ms_sum",
)


@pytest.fixture(name="storage")
def fixture_storage(tmp_path):
    """Provide an isolated SQLite-backed session storage."""
    return SessionSQLAlchemy(f"sqlite:///{tmp_path / 'session_metrics.db'}")


def _create_session(storage, session_id="sess-metrics"):
    """Create one session row and return its identifier."""
    assert storage.create_session(SessionData(session_id=session_id, task="metrics task")) is True
    return session_id

def _metrics(storage, session_id):
    """Read the stored metric columns for one session."""
    session = storage.get_session(session_id)
    assert session is not None
    return {name: getattr(session, name) for name in METRIC_COLUMNS}


def test_new_session_starts_with_zero_metrics(storage):
    """A freshly created session must expose zeroed metric columns."""
    session_id = _create_session(storage)
    assert _metrics(storage, session_id) == {name: 0 for name in METRIC_COLUMNS}


def test_accumulate_adds_each_delta(storage):
    """One settled attempt must add every supplied delta."""
    session_id = _create_session(storage)

    assert storage.accumulate_session_metrics(
        session_id=session_id,
        turn_count=1,
        tool_call_count=3,
        tool_error_count=1,
        llm_request_count=4,
        llm_request_failure_count=2,
        tool_duration_ms_sum=1500,
        llm_request_duration_ms_sum=2500,
    ) is True

    assert _metrics(storage, session_id) == {
        "turn_count": 1,
        "tool_call_count": 3,
        "tool_error_count": 1,
        "llm_request_count": 4,
        "llm_request_failure_count": 2,
        "tool_duration_ms_sum": 1500,
        "llm_request_duration_ms_sum": 2500,
    }


def test_accumulate_is_additive_across_attempts(storage):
    """Repeated settlements must accumulate rather than overwrite."""
    session_id = _create_session(storage)

    for _ in range(3):
        storage.accumulate_session_metrics(
            session_id=session_id, turn_count=1, tool_call_count=2,
            tool_duration_ms_sum=100,
        )

    metrics = _metrics(storage, session_id)
    assert metrics["turn_count"] == 3
    assert metrics["tool_call_count"] == 6
    assert metrics["tool_duration_ms_sum"] == 300


def test_negative_deltas_are_normalized(storage):
    """Misreported negative deltas must not subtract from session totals."""
    session_id = _create_session(storage)
    storage.accumulate_session_metrics(session_id=session_id, turn_count=1,
                                       tool_call_count=5)

    storage.accumulate_session_metrics(
        session_id=session_id, turn_count=-1, tool_call_count=-5,
        tool_error_count=-2, llm_request_count=-1,
        llm_request_failure_count=-1, tool_duration_ms_sum=-100,
        llm_request_duration_ms_sum=-100,
    )

    metrics = _metrics(storage, session_id)
    assert metrics["turn_count"] == 1
    assert metrics["tool_call_count"] == 5
    assert metrics["tool_error_count"] == 0
    assert metrics["tool_duration_ms_sum"] == 0


def test_unknown_session_returns_false(storage):
    """Accumulating into a missing session must report failure without raising."""
    assert storage.accumulate_session_metrics(session_id="missing", turn_count=1) is False


def test_empty_session_id_returns_false(storage):
    """An empty session id must be rejected before any database work."""
    assert storage.accumulate_session_metrics(session_id="", turn_count=1) is False


def test_zero_deltas_do_not_touch_update_time(storage):
    """An all-zero settlement must leave update_time unchanged."""
    session_id = _create_session(storage)
    before = storage.get_session(session_id).update_time

    assert storage.accumulate_session_metrics(session_id=session_id) is True

    assert storage.get_session(session_id).update_time == before


def test_accumulate_does_not_disturb_token_totals(storage):
    """Metric accumulation must not alter the existing token columns."""
    session_id = _create_session(storage)
    storage.accumulate_session_tokens(session_id, 10, 4, 6)

    storage.accumulate_session_metrics(session_id=session_id, turn_count=1)

    session = storage.get_session(session_id)
    assert session.total_tokens == 10
    assert session.total_cached_tokens == 4
    assert session.total_completion_tokens == 6


def test_error_counter_counts_only_errors():
    """The O(1) error counter must count error records only."""
    stat = ToolStat()
    stat.record("tool_a", error="boom")
    stat.record("tool_b")
    stat.record("tool_c", error="fail")

    assert stat._error_count == 2


def test_error_counter_survives_record_pruning():
    """The error counter must not depend on retained records."""
    stat = ToolStat(max_records=2)
    for index in range(5):
        stat.record(f"tool_{index}", error="boom")

    assert len(stat._tool_calls) == 2
    assert stat._error_count == 5


def test_error_counter_resets_on_full_clear():
    """A full clear must reset the error counter."""
    stat = ToolStat()
    stat.record("tool_a", error="boom")
    stat.clear()

    assert stat._error_count == 0


def test_error_counter_resets_on_reset():
    """A reset must reset the error counter."""
    stat = ToolStat()
    stat.record("tool_a", error="boom")
    stat.reset()

    assert stat._error_count == 0


def test_partial_clear_subtracts_only_that_tool_errors():
    """Clearing one tool must remove exactly its own error records."""
    stat = ToolStat()
    stat.record("tool_a", error="boom")
    stat.record("tool_a")
    stat.record("tool_b", error="fail")

    stat.clear("tool_a")

    assert stat._error_count == 1
    assert [call["tool_call"] for call in stat._tool_calls] == ["tool_b"]


def test_partial_clear_never_goes_negative():
    """A partial clear must clamp the counter at zero."""
    stat = ToolStat()
    stat.record("tool_a", error="boom")
    stat._error_count = 0

    stat.clear("tool_a")

    assert stat._error_count == 0
