"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Purpose: Unit tests for the settled-attempt session metrics hook module

  Features:
  - Per-attempt delta computation from cumulative tracker snapshots
  - Baseline lifetime bound to the conversation-scoped Binding token
  - One-shot latch preventing double counting
  - Best-effort failure isolation on the execution thread
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "hooks"
    / "points"
    / "workspace"
    / "after_attempt_settle_user2agent"
    / "modules"
    / "session_metrics.py"
)


def _load_module():
    """Import the hook module by file path, mirroring the Hook Point loader."""
    spec = importlib.util.spec_from_file_location("session_metrics_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="metrics")
def fixture_metrics():
    """Provide a freshly imported hook module per test."""
    return _load_module()


def _tool_stat(calls=0, errors=0, duration_sec=0.0):
    """Build a ToolStat lookalike exposing the cumulative counters."""
    return SimpleNamespace(
        _call_sequence=calls,
        _error_count=errors,
        _execution_duration_sum_sec=duration_sec,
    )


def _request_stat(requests=0, failures=0, duration_sec=0.0):
    """Build an LLMRequestStat lookalike exposing the cumulative counters."""
    return SimpleNamespace(
        _total_requests=requests,
        _request_failures=failures,
        _request_duration_sum_sec=duration_sec,
    )


def _agent(tool_stat=None, request_stat=None):
    """Build an agent lookalike with runtime tool stats and request stats."""
    return SimpleNamespace(
        runtime=SimpleNamespace(tool_stat=tool_stat or _tool_stat()),
        llm_request_stat=request_stat or _request_stat(),
    )


def _binding(session="sess-1", authorized=True):
    """Build a Binding lookalike with the conversation-scoped baseline slot."""
    return SimpleNamespace(
        session=session,
        settle_authorized=lambda agent: authorized,
    )


def _attempt(binding):
    """Build an Attempt lookalike carrying its binding."""
    return SimpleNamespace(binding=binding)


def _agent_chat(agent, session_id="sess-1"):
    """Build an AgentChat lookalike exposing the real session id."""
    return SimpleNamespace(
        ai_agent=agent,
        ctx_runtime_data=SimpleNamespace(session_id=session_id),
    )


class _Recorder:
    """Capture accumulate_session_metrics calls instead of touching a database."""

    def __init__(self, result=True):
        self.calls = []
        self.result = result

    def accumulate_session_metrics(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _run(metrics, agent_chat, binding, recorder, attempt=None):
    """Invoke the hook with a patched session manager factory."""
    attempt = attempt or _attempt(binding)
    with patch.object(metrics, "logger"), patch(
        "topsailai.context.ctx_manager.get_session_manager", return_value=recorder
    ):
        return metrics.main(agent_chat=agent_chat, outcome="success", attempt=attempt)


def test_first_attempt_reports_full_snapshot_as_delta(metrics):
    """The first settled attempt has a zero baseline, so its delta is the snapshot."""
    binding = _binding()
    agent = _agent(_tool_stat(calls=3, errors=1, duration_sec=1.5),
                   _request_stat(requests=4, failures=1, duration_sec=2.0))
    recorder = _Recorder()

    assert _run(metrics, _agent_chat(agent), binding, recorder) is True

    assert recorder.calls == [{
        "session_id": "sess-1",
        "turn_count": 1,
        "tool_call_count": 3,
        "tool_error_count": 1,
        "llm_request_count": 4,
        "llm_request_failure_count": 1,
        "tool_duration_ms_sum": 1500,
        "llm_request_duration_ms_sum": 2000,
    }]


def test_second_attempt_reports_only_the_increment(metrics):
    """Cumulative trackers must not be re-counted on the next settled attempt."""
    binding = _binding()
    recorder = _Recorder()

    first = _agent(_tool_stat(calls=2, errors=0, duration_sec=1.0),
                   _request_stat(requests=1, failures=0, duration_sec=0.5))
    _run(metrics, _agent_chat(first), binding, recorder)

    second = _agent(_tool_stat(calls=5, errors=2, duration_sec=2.5),
                    _request_stat(requests=3, failures=1, duration_sec=1.5))
    _run(metrics, _agent_chat(second), binding, recorder)

    assert recorder.calls[1] == {
        "session_id": "sess-1",
        "turn_count": 1,
        "tool_call_count": 3,
        "tool_error_count": 2,
        "llm_request_count": 2,
        "llm_request_failure_count": 1,
        "tool_duration_ms_sum": 1500,
        "llm_request_duration_ms_sum": 1000,
    }


def test_repeated_invocation_is_latched(metrics):
    """A second invocation for the same attempt must not double count."""
    binding = _binding()
    agent = _agent(_tool_stat(calls=1))
    recorder = _Recorder()
    attempt = _attempt(binding)

    _run(metrics, _agent_chat(agent), binding, recorder, attempt=attempt)
    _run(metrics, _agent_chat(agent), binding, recorder, attempt=attempt)

    assert len(recorder.calls) == 1


def test_missing_attempt_is_ignored(metrics):
    """Runs without an admitted attempt must not write metrics."""
    recorder = _Recorder()
    with patch.object(metrics, "logger"), patch(
        "topsailai.context.ctx_manager.get_session_manager", return_value=recorder
    ):
        assert metrics.main(agent_chat=_agent_chat(_agent()), outcome="success",
                            attempt=None) is False
    assert recorder.calls == []


def test_unauthorized_binding_is_ignored(metrics):
    """A binding that does not own the agent must not write metrics."""
    recorder = _Recorder()
    binding = _binding(authorized=False)

    assert _run(metrics, _agent_chat(_agent()), binding, recorder) is False
    assert recorder.calls == []


def test_missing_session_id_is_ignored(metrics):
    """The Binding placeholder must not be used as a session id."""
    recorder = _Recorder()
    binding = _binding(session="topsailai")

    assert _run(metrics, _agent_chat(_agent(), session_id=""), binding, recorder) is False
    assert recorder.calls == []


def test_baseline_advances_even_when_the_write_fails(metrics):
    """A failed write must not cause the same observation to be counted twice."""
    binding = _binding()
    failing = _Recorder(result=False)
    agent = _agent(_tool_stat(calls=2))

    assert _run(metrics, _agent_chat(agent), binding, failing) is False
    assert getattr(binding, metrics.BASELINE_ATTR)["tool_call_count"] == 2

    succeeding = _Recorder()
    _run(metrics, _agent_chat(agent), binding, succeeding)
    assert succeeding.calls[0]["tool_call_count"] == 0


def test_storage_failure_is_swallowed(metrics):
    """An exception from the session manager must not interrupt the Agent flow."""
    binding = _binding()

    class _Boom:
        def accumulate_session_metrics(self, **kwargs):
            raise RuntimeError("database unavailable")

    with patch.object(metrics, "logger") as logger, patch(
        "topsailai.context.ctx_manager.get_session_manager", return_value=_Boom()
    ):
        assert metrics.main(agent_chat=_agent_chat(_agent()), outcome="success",
                            attempt=_attempt(binding)) is False
    logger.warning.assert_called_once()


def test_missing_session_manager_is_ignored(metrics):
    """An unavailable session manager must not raise."""
    binding = _binding()
    with patch.object(metrics, "logger"), patch(
        "topsailai.context.ctx_manager.get_session_manager", return_value=None
    ):
        assert metrics.main(agent_chat=_agent_chat(_agent()), outcome="success",
                            attempt=_attempt(binding)) is False


def test_non_monotonic_snapshot_yields_zero_delta(metrics):
    """A tracker reset must not produce a negative delta."""
    binding = _binding()
    recorder = _Recorder()

    _run(metrics, _agent_chat(_agent(_tool_stat(calls=5, errors=3))), binding, recorder)
    _run(metrics, _agent_chat(_agent(_tool_stat(calls=1, errors=0))), binding, recorder)

    assert recorder.calls[1]["tool_call_count"] == 0
    assert recorder.calls[1]["tool_error_count"] == 0


def test_malformed_counters_are_treated_as_zero(metrics):
    """Non-integer or negative tracker values must not corrupt the delta."""
    binding = _binding()
    recorder = _Recorder()
    agent = _agent(
        SimpleNamespace(_call_sequence="7", _error_count=-2,
                        _execution_duration_sum_sec="1.0"),
        SimpleNamespace(_total_requests=None, _request_failures=1.5,
                        _request_duration_sum_sec=-3.0),
    )

    _run(metrics, _agent_chat(agent), binding, recorder)

    assert recorder.calls[0]["tool_call_count"] == 0
    assert recorder.calls[0]["tool_error_count"] == 0
    assert recorder.calls[0]["llm_request_count"] == 0
    assert recorder.calls[0]["llm_request_failure_count"] == 0
    assert recorder.calls[0]["tool_duration_ms_sum"] == 0
    assert recorder.calls[0]["llm_request_duration_ms_sum"] == 0


def test_missing_trackers_are_treated_as_zero(metrics):
    """An agent without statistics trackers must still settle one turn."""
    binding = _binding()
    recorder = _Recorder()
    agent = SimpleNamespace(runtime=None, llm_request_stat=None)

    _run(metrics, _agent_chat(agent), binding, recorder)

    assert recorder.calls[0]["turn_count"] == 1
    assert recorder.calls[0]["tool_call_count"] == 0
