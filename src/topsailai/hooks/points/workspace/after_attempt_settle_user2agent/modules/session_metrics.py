"""Persist settled attempt execution metrics into the session row.

Author: DawsonLin

The statistics trackers accumulate for the whole conversation while one
``Binding`` also lives for the whole conversation, so the session row must
receive per-attempt deltas. The previous snapshot is therefore retained on the
binding token, which is the only object with exactly that lifetime.

This module runs on the execution thread, so every failure is best effort and
must never interrupt the Agent flow.
"""

from topsailai.logger.log_chat import logger
from topsailai.utils import db_io_tool

BASELINE_ATTR = "_session_metrics_baseline"
LATCH_ATTR = "_session_metrics_done"

# Tracker attribute -> baseline key. Durations stay in seconds here and are
# converted to integer milliseconds only when the delta is computed.
# ``_call_sequence`` counts every recorded call, while the duration counter only
# counts calls that carried a valid duration, so it is the accurate call total.
TOOL_COUNTERS = (
    ("_call_sequence", "tool_call_count"),
    ("_error_count", "tool_error_count"),
)
REQUEST_COUNTERS = (
    ("_total_requests", "llm_request_count"),
    ("_request_failures", "llm_request_failure_count"),
)
DURATION_KEYS = ("tool_duration_sec", "llm_request_duration_sec")


def _counter(tracker, name):
    """Read one non-negative integer counter without trusting its type."""
    value = getattr(tracker, name, 0)
    if type(value) is not int or value < 0:
        return 0
    return value


def _seconds(tracker, name):
    """Read one non-negative duration accumulator in seconds."""
    value = getattr(tracker, name, 0.0)
    if type(value) not in (int, float) or value < 0:
        return 0.0
    return float(value)


def _delta(current, previous):
    """Return a monotonic non-negative delta for one counter."""
    return current - previous if current > previous else 0


def _empty_baseline():
    """Return the zero baseline used before the first settled attempt."""
    baseline = {key: 0 for _, key in TOOL_COUNTERS}
    baseline.update({key: 0 for _, key in REQUEST_COUNTERS})
    baseline.update({key: 0.0 for key in DURATION_KEYS})
    return baseline


def _snapshot(agent):
    """Read the current cumulative tracker snapshot for one agent."""
    runtime = getattr(agent, "runtime", None)
    tool_stat = getattr(runtime, "tool_stat", None) if runtime is not None else None
    request_stat = getattr(agent, "llm_request_stat", None)
    snapshot = {}
    for name, key in TOOL_COUNTERS:
        snapshot[key] = _counter(tool_stat, name) if tool_stat is not None else 0
    snapshot["tool_duration_sec"] = (
        _seconds(tool_stat, "_execution_duration_sum_sec") if tool_stat is not None else 0.0
    )
    for name, key in REQUEST_COUNTERS:
        snapshot[key] = _counter(request_stat, name) if request_stat is not None else 0
    snapshot["llm_request_duration_sec"] = (
        _seconds(request_stat, "_request_duration_sum_sec") if request_stat is not None else 0.0
    )
    return snapshot


def _deltas(snapshot, baseline):
    """Convert two cumulative snapshots into one attempt's metric deltas."""
    return {
        "turn_count": 1,
        "tool_call_count": _delta(snapshot["tool_call_count"], baseline["tool_call_count"]),
        "tool_error_count": _delta(snapshot["tool_error_count"], baseline["tool_error_count"]),
        "llm_request_count": _delta(snapshot["llm_request_count"], baseline["llm_request_count"]),
        "llm_request_failure_count": _delta(
            snapshot["llm_request_failure_count"], baseline["llm_request_failure_count"]
        ),
        "tool_duration_ms_sum": int(
            round(_delta(snapshot["tool_duration_sec"], baseline["tool_duration_sec"]) * 1000)
        ),
        "llm_request_duration_ms_sum": int(
            round(
                _delta(
                    snapshot["llm_request_duration_sec"],
                    baseline["llm_request_duration_sec"],
                )
                * 1000
            )
        ),
    }


def main(*, agent_chat, outcome, attempt=None):
    """Accumulate this attempt's metric deltas once; failures stay best effort."""
    if attempt is None or getattr(attempt, LATCH_ATTR, False):
        return False
    binding = getattr(attempt, "binding", None)
    agent = getattr(agent_chat, "ai_agent", None)
    if binding is None or agent is None:
        return False
    try:
        if not binding.settle_authorized(agent):
            return False
        # ``Binding.session`` falls back to a placeholder, so resolve the real
        # session id from the runtime data and skip runs without a session.
        session_id = getattr(getattr(agent_chat, "ctx_runtime_data", None), "session_id", "")
        if not session_id:
            return False
        # Latch before the write so a repeated invocation cannot double count.
        setattr(attempt, LATCH_ATTR, True)
        snapshot = _snapshot(agent)
        baseline = getattr(binding, BASELINE_ATTR, None)
        if baseline is None:
            baseline = _empty_baseline()
        deltas = _deltas(snapshot, baseline)
        # Advance the baseline before the write so a failed write cannot
        # double count the same observation on the next attempt.
        setattr(binding, BASELINE_ATTR, snapshot)
        from topsailai.context import ctx_manager

        session_mgr = ctx_manager.get_session_manager()
        if session_mgr is None:
            return False
        return bool(session_mgr.accumulate_session_metrics(session_id=session_id, **deltas))
    except Exception as e:
        logger.warning("Session metrics accumulation failed", exc_info=True)
        if db_io_tool.is_db_io_failure(e):
            raise
        return False
