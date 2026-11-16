"""Persist extended settled-attempt metrics into the session row.

Author: DawsonLin

This module owns the Tier 1 and Tier 2 session metrics that are not covered by
``session_metrics.py``: response-content errors, first-byte latency, peak request
rate, the per-outcome turn breakdown, the peak prompt size and the model name.

The statistics trackers accumulate for the whole conversation while one
``Binding`` also lives for the whole conversation, so additive counters must be
written as per-attempt deltas. Peak counters are not deltas: the storage layer
keeps the larger value, so the current cumulative peak is passed directly.

This module runs on the execution thread, so every failure is best effort and
must never interrupt the Agent flow.
"""

from topsailai.logger.log_chat import logger

BASELINE_ATTR = "_session_metrics_ext_baseline"
LATCH_ATTR = "_session_metrics_ext_done"

# Additive tracker attribute -> baseline key. The tracker differs per counter:
# response-content errors live on the request tracker, while first-byte latency
# lives on the token tracker.
REQUEST_COUNTERS = (
    ("_response_content_errors", "response_content_errors"),
)
TOKEN_COUNTERS = (
    ("first_byte_count", "first_byte_count"),
)

# ``outcome`` value -> additive session column. ``success`` has no dedicated
# column because ``turn_count`` already counts every settled attempt.
OUTCOME_COLUMNS = {
    "failure": "turn_failure_count",
    "back": "turn_back_count",
    "interrupt": "turn_interrupt_count",
}


def _counter(tracker, name):
    """Read one non-negative integer counter without trusting its type."""
    value = getattr(tracker, name, 0)
    if type(value) is not int or value < 0:
        return 0
    return value


def _milliseconds(tracker, name):
    """Read one non-negative millisecond accumulator without converting units."""
    value = getattr(tracker, name, 0.0)
    if type(value) not in (int, float) or value < 0:
        return 0.0
    return float(value)


def _delta(current, previous):
    """Return a monotonic non-negative delta for one counter."""
    return current - previous if current > previous else 0


def _empty_baseline():
    """Return the zero baseline used before the first settled attempt."""
    baseline = {key: 0 for _, key in REQUEST_COUNTERS}
    baseline.update({key: 0 for _, key in TOKEN_COUNTERS})
    baseline["first_byte_sum_ms"] = 0
    return baseline


def _snapshot(agent):
    """Read the current cumulative tracker snapshot for one agent."""
    runtime = getattr(agent, "runtime", None)
    token_stat = getattr(runtime, "token_stat", None) if runtime is not None else None
    request_stat = getattr(agent, "llm_request_stat", None)
    snapshot = {}
    for name, key in REQUEST_COUNTERS:
        snapshot[key] = _counter(request_stat, name) if request_stat is not None else 0
    for name, key in TOKEN_COUNTERS:
        snapshot[key] = _counter(token_stat, name) if token_stat is not None else 0
    snapshot["first_byte_sum_ms"] = int(
        round(_milliseconds(token_stat, "first_byte_sum_ms"))
    )
    return snapshot


def _peaks(agent):
    """Read the peak and last-write values that must not be summed."""
    runtime = getattr(agent, "runtime", None)
    token_stat = getattr(runtime, "token_stat", None) if runtime is not None else None
    request_stat = getattr(agent, "llm_request_stat", None)
    model_name = ""
    if runtime is not None:
        try:
            model_name = str(getattr(runtime.llm_model, "model_name", "") or "")
        except Exception:
            # A released agent must not turn a statistics write into a failure.
            model_name = ""
    return {
        "requests_per_minute_max": (
            _counter(request_stat, "_requests_per_minute_max")
            if request_stat is not None else 0
        ),
        "max_prompt_tokens": (
            _counter(token_stat, "current_prompt_tokens")
            if token_stat is not None else 0
        ),
        "model_name": model_name,
    }


def _deltas(snapshot, baseline):
    """Convert two cumulative snapshots into one attempt's additive deltas."""
    return {
        "response_content_errors": _delta(
            snapshot["response_content_errors"], baseline["response_content_errors"]
        ),
        "first_byte_count": _delta(
            snapshot["first_byte_count"], baseline["first_byte_count"]
        ),
        "first_byte_sum_ms": _delta(
            snapshot["first_byte_sum_ms"], baseline["first_byte_sum_ms"]
        ),
    }


def main(*, agent_chat, outcome, attempt=None):
    """Accumulate this attempt's extended metric deltas once; failures stay best effort."""
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
        deltas.update(_peaks(agent))
        outcome_column = OUTCOME_COLUMNS.get(outcome)
        if outcome_column:
            deltas[outcome_column] = 1
        # Advance the baseline before the write so a failed write cannot
        # double count the same observation on the next attempt.
        setattr(binding, BASELINE_ATTR, snapshot)
        from topsailai.context import ctx_manager

        session_mgr = ctx_manager.get_session_manager()
        if session_mgr is None:
            return False
        return bool(session_mgr.accumulate_session_metrics(session_id=session_id, **deltas))
    except Exception:
        # Session metrics are statistics, not conversation content, so a failed
        # write is logged and skipped instead of ending the process.
        logger.warning("Session metrics extension accumulation failed", exc_info=True)
        return False


__all__ = ["main", "BASELINE_ATTR", "LATCH_ATTR"]
