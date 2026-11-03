"""Accumulate settled attempt metrics into one cumulative document per model.

Author: DawsonLin

The session row records conversation totals, while this module records the same
work attributed to the model that performed it. ``TokenStat`` is owned by one
``LLMModel`` instance, so token totals are already model-scoped; the tool and
request trackers are owned by the agent and stay cumulative across a model
switch, so their baseline is advanced on every attempt and the resulting delta
belongs to the model active during that attempt.

This module runs on the execution thread, so it performs no I/O itself: the
delta is handed to the process statistics worker, and every failure is best
effort and must never interrupt the Agent flow.
"""

import json

from topsailai.logger.log_chat import logger
from topsailai.workspace.model_stats_writer import ModelStatsWriter

BASELINE_ATTR = "_model_metrics_baseline"
LATCH_ATTR = "_model_metrics_done"

# Agent-owned cumulative counters: the delta belongs to the current model.
AGENT_COUNTERS = (
    ("_call_sequence", "tool_call_count"),
    ("_error_count", "tool_error_count"),
    ("_total_requests", "llm_request_count"),
    ("_request_failures", "llm_request_failure_count"),
)
AGENT_DURATIONS = (
    ("_execution_duration_sum_sec", "tool_duration_ms_sum"),
    ("_request_duration_sum_sec", "llm_request_duration_ms_sum"),
)
# Model-instance-owned cumulative counters: already scoped to one model.
MODEL_COUNTERS = (
    ("total_count", "prompt_tokens"),
    ("total_completion_count", "completion_tokens"),
    ("total_cached_tokens", "cached_tokens"),
    ("first_byte_count", "first_byte_count"),
)
MODEL_DURATIONS = (("first_byte_sum_ms", "first_byte_sum_ms"),)


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


def _agent_snapshot(agent):
    """Read the agent-owned cumulative counters shared by every model."""
    runtime = getattr(agent, "runtime", None)
    tool_stat = getattr(runtime, "tool_stat", None) if runtime is not None else None
    request_stat = getattr(agent, "llm_request_stat", None)
    snapshot = {}
    for name, key in AGENT_COUNTERS:
        tracker = tool_stat if key.startswith("tool_") else request_stat
        snapshot[key] = _counter(tracker, name) if tracker is not None else 0
    for name, key in AGENT_DURATIONS:
        tracker = tool_stat if key.startswith("tool_") else request_stat
        snapshot[key] = int(round(_seconds(tracker, name) * 1000)) if tracker is not None else 0
    return snapshot


def _model_snapshot(model):
    """Read the token counters owned by one model instance."""
    token_stat = getattr(model, "tokenStat", None)
    snapshot = {}
    for name, key in MODEL_COUNTERS:
        snapshot[key] = _counter(token_stat, name) if token_stat is not None else 0
    for name, key in MODEL_DURATIONS:
        snapshot[key] = int(round(_seconds(token_stat, name))) if token_stat is not None else 0
    return snapshot


def _empty_baseline():
    """Return the zero baseline used before the first settled attempt."""
    baseline = {"agent": {}, "models": {}}
    baseline["agent"].update({key: 0 for _, key in AGENT_COUNTERS})
    baseline["agent"].update({key: 0 for _, key in AGENT_DURATIONS})
    return baseline


def _agent_deltas(snapshot, baseline):
    """Convert two cumulative agent snapshots into one attempt's deltas."""
    return {key: _delta(snapshot[key], baseline.get(key, 0)) for key in snapshot}


def _model_deltas(snapshot, baseline):
    """Convert two cumulative model snapshots into one attempt's deltas."""
    return {key: _delta(snapshot[key], baseline.get(key, 0)) for key in snapshot}


def _payload(model_name, model_id, session_id, agent_id, sequence, outcome, deltas):
    """Build the framed delta document handed to the storage worker."""
    document = {
        "schema_version": 1,
        "model_name": model_name,
        "model_instance_id": model_id,
        "session_id": session_id,
        "agent_instance_id": agent_id,
        "attempt_seq": sequence,
        "outcome": outcome,
    }
    document.update(deltas)
    document["turn_count"] = 1
    line = (
        json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return line if len(line) <= 4096 else None


def main(*, agent_chat, outcome, attempt=None):
    """Accumulate this attempt's per-model deltas once; failures stay best effort."""
    if attempt is None or getattr(attempt, LATCH_ATTR, False):
        return False
    binding = getattr(attempt, "binding", None)
    agent = getattr(agent_chat, "ai_agent", None)
    if binding is None or agent is None:
        return False
    try:
        if not binding.settle_authorized(agent):
            return False
        runtime = getattr(agent, "runtime", None)
        model = getattr(runtime, "llm_model", None) if runtime is not None else None
        if model is None:
            return False
        model_name = getattr(model, "model_name", "")
        if type(model_name) is not str or not model_name.strip():
            return False
        model_id = binding.model_id(model)
        if model_id is None:
            return False
        session_id = getattr(getattr(agent_chat, "ctx_runtime_data", None), "session_id", "")
        if not session_id:
            return False
        # Latch before the write so a repeated invocation cannot double count.
        setattr(attempt, LATCH_ATTR, True)
        baseline = getattr(binding, BASELINE_ATTR, None)
        if baseline is None:
            baseline = _empty_baseline()
        agent_now = _agent_snapshot(agent)
        model_now = _model_snapshot(model)
        deltas = _agent_deltas(agent_now, baseline["agent"])
        deltas.update(_model_deltas(model_now, baseline["models"].get(model_id, {})))
        # Advance both baselines before the write so a failed write cannot
        # double count the same observation on the next attempt.
        baseline["agent"] = agent_now
        baseline["models"][model_id] = model_now
        setattr(binding, BASELINE_ATTR, baseline)
        line = _payload(
            model_name, model_id, session_id, binding.agent_id,
            attempt.sequence, outcome, deltas,
        )
        if line is None:
            return False
        writer = ModelStatsWriter(model_name, diagnostic=binding.service.diagnostic)
        return bool(binding.service.offer(writer, line))
    except Exception:
        logger.warning("Model metrics accumulation failed", exc_info=True)
        return False
