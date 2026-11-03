"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Purpose: Unit tests for the per-model metrics hook module

  Features:
  - Agent-owned counters converted to per-attempt deltas
  - Model-owned token counters scoped to one model instance
  - Per-model baselines surviving a model switch
  - One-shot latch preventing double counting
  - Best-effort failure isolation on the execution thread
"""

import importlib.util
import json
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
    / "model_metrics.py"
)


def _load_module():
    """Import the hook module by file path, mirroring the Hook Point loader."""
    spec = importlib.util.spec_from_file_location("model_metrics_under_test", MODULE_PATH)
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


def _token_stat(prompt=0, completion=0, cached=0, first_byte_sum_ms=0.0, first_byte_count=0):
    """Build a TokenStat lookalike owned by one model instance."""
    return SimpleNamespace(
        total_count=prompt,
        total_completion_count=completion,
        total_cached_tokens=cached,
        first_byte_sum_ms=first_byte_sum_ms,
        first_byte_count=first_byte_count,
    )


def _model(name="Kimi-K2.5", token_stat=None):
    """Build an LLMModel lookalike with its own token tracker."""
    return SimpleNamespace(model_name=name, tokenStat=token_stat or _token_stat())


def _agent(model, tool_stat=None, request_stat=None):
    """Build an agent lookalike owning the shared trackers."""
    return SimpleNamespace(
        runtime=SimpleNamespace(
            tool_stat=tool_stat or _tool_stat(),
            llm_model=model,
        ),
        llm_request_stat=request_stat or _request_stat(),
    )


class _Service:
    """Capture offered payloads instead of writing files."""

    def __init__(self, result=True):
        self.offers = []
        self.result = result
        self.diagnostic = lambda category, name: True

    def offer(self, writer, line):
        self.offers.append((writer, line))
        return self.result


def _binding(service, model_id="mid-1", authorized=True, agent_id="aid-1"):
    """Build a Binding lookalike with the conversation-scoped baseline slot."""
    return SimpleNamespace(
        service=service,
        agent_id=agent_id,
        settle_authorized=lambda agent: authorized,
        model_id=lambda model: model_id,
    )


def _attempt(binding, sequence=1):
    """Build an Attempt lookalike carrying its binding and sequence."""
    return SimpleNamespace(binding=binding, sequence=sequence)


def _agent_chat(agent, session_id="sess-1"):
    """Build an AgentChat lookalike exposing the real session id."""
    return SimpleNamespace(
        ai_agent=agent,
        ctx_runtime_data=SimpleNamespace(session_id=session_id),
    )


def _run(metrics, agent_chat, binding, attempt=None, outcome="success"):
    """Invoke the hook with a silenced logger."""
    attempt = attempt or _attempt(binding)
    with patch.object(metrics, "logger"):
        return metrics.main(agent_chat=agent_chat, outcome=outcome, attempt=attempt)


def _payload(service):
    """Decode the most recently offered payload."""
    assert service.offers, "no payload was offered"
    return json.loads(service.offers[-1][1].decode("utf-8"))


def test_first_attempt_reports_full_snapshot_as_delta(metrics):
    """The first settled attempt has a zero baseline, so its delta is the snapshot."""
    service = _Service()
    binding = _binding(service)
    model = _model(token_stat=_token_stat(prompt=100, completion=20, cached=50,
                                          first_byte_sum_ms=900.0, first_byte_count=2))
    agent = _agent(model, _tool_stat(calls=3, errors=1, duration_sec=1.5),
                   _request_stat(requests=4, failures=1, duration_sec=2.0))

    assert _run(metrics, _agent_chat(agent), binding) is True

    payload = _payload(service)
    assert payload["turn_count"] == 1
    assert payload["tool_call_count"] == 3
    assert payload["tool_error_count"] == 1
    assert payload["llm_request_count"] == 4
    assert payload["llm_request_failure_count"] == 1
    assert payload["tool_duration_ms_sum"] == 1500
    assert payload["llm_request_duration_ms_sum"] == 2000
    assert payload["prompt_tokens"] == 100
    assert payload["completion_tokens"] == 20
    assert payload["cached_tokens"] == 50
    assert payload["first_byte_sum_ms"] == 900
    assert payload["first_byte_count"] == 2


def test_payload_carries_model_and_attempt_identity(metrics):
    """Attribute every delta to the model, session, agent and attempt."""
    service = _Service()
    binding = _binding(service, model_id="mid-9", agent_id="aid-7")
    agent = _agent(_model("DeepSeek-V3.2"))

    assert _run(metrics, _agent_chat(agent), binding, _attempt(binding, sequence=5)) is True

    payload = _payload(service)
    assert payload["schema_version"] == 1
    assert payload["model_name"] == "DeepSeek-V3.2"
    assert payload["model_instance_id"] == "mid-9"
    assert payload["session_id"] == "sess-1"
    assert payload["agent_instance_id"] == "aid-7"
    assert payload["attempt_seq"] == 5
    assert payload["outcome"] == "success"


def test_second_attempt_reports_only_the_increment(metrics):
    """Cumulative agent trackers must not be re-counted on the next attempt."""
    service = _Service()
    binding = _binding(service)
    model = _model()
    agent = _agent(model, _tool_stat(calls=2, errors=0, duration_sec=1.0),
                   _request_stat(requests=1, failures=0, duration_sec=0.5))

    assert _run(metrics, _agent_chat(agent), binding) is True
    agent.runtime.tool_stat = _tool_stat(calls=5, errors=2, duration_sec=2.5)
    agent.llm_request_stat = _request_stat(requests=3, failures=1, duration_sec=1.5)
    assert _run(metrics, _agent_chat(agent), binding) is True

    payload = _payload(service)
    assert payload["tool_call_count"] == 3
    assert payload["tool_error_count"] == 2
    assert payload["llm_request_count"] == 2
    assert payload["llm_request_failure_count"] == 1
    assert payload["tool_duration_ms_sum"] == 1500
    assert payload["llm_request_duration_ms_sum"] == 1000


def test_model_token_baseline_is_per_model_instance(metrics):
    """A model switch must not inherit the previous model's token baseline."""
    service = _Service()
    binding = _binding(service)
    first_model = _model("model-a", _token_stat(prompt=100))
    agent = _agent(first_model)

    assert _run(metrics, _agent_chat(agent), binding) is True
    assert _payload(service)["prompt_tokens"] == 100

    # A different model instance starts from its own zero baseline.
    second_model = _model("model-b", _token_stat(prompt=40))
    agent.runtime.llm_model = second_model
    binding.model_id = lambda model: "mid-2" if model is second_model else "mid-1"
    assert _run(metrics, _agent_chat(agent), binding) is True

    payload = _payload(service)
    assert payload["model_name"] == "model-b"
    assert payload["prompt_tokens"] == 40


def test_same_model_instance_accumulates_token_deltas(metrics):
    """Repeated attempts on one model report only the token increment."""
    service = _Service()
    binding = _binding(service)
    model = _model(token_stat=_token_stat(prompt=100, completion=10))
    agent = _agent(model)

    assert _run(metrics, _agent_chat(agent), binding) is True
    model.tokenStat = _token_stat(prompt=250, completion=30)
    assert _run(metrics, _agent_chat(agent), binding) is True

    payload = _payload(service)
    assert payload["prompt_tokens"] == 150
    assert payload["completion_tokens"] == 20


def test_agent_baseline_survives_model_switch(metrics):
    """Agent-owned counters keep one baseline even when the model changes."""
    service = _Service()
    binding = _binding(service)
    agent = _agent(_model("model-a"), _tool_stat(calls=4))

    assert _run(metrics, _agent_chat(agent), binding) is True
    agent.runtime.llm_model = _model("model-b")
    binding.model_id = lambda model: "mid-2"
    agent.runtime.tool_stat = _tool_stat(calls=6)
    assert _run(metrics, _agent_chat(agent), binding) is True

    payload = _payload(service)
    assert payload["tool_call_count"] == 2


def test_latch_prevents_double_counting(metrics):
    """A repeated invocation must not offer a second payload."""
    service = _Service()
    binding = _binding(service)
    agent = _agent(_model())
    attempt = _attempt(binding)

    assert _run(metrics, _agent_chat(agent), binding, attempt) is True
    assert _run(metrics, _agent_chat(agent), binding, attempt) is False
    assert len(service.offers) == 1


def test_missing_attempt_is_ignored(metrics):
    """Skip when no attempt token is supplied."""
    service = _Service()
    assert metrics.main(agent_chat=_agent_chat(_agent(_model())), outcome="success",
                        attempt=None) is False
    assert service.offers == []


def test_unauthorized_binding_is_ignored(metrics):
    """Skip when the binding does not authorize this agent and thread."""
    service = _Service()
    binding = _binding(service, authorized=False)
    assert _run(metrics, _agent_chat(_agent(_model())), binding) is False
    assert service.offers == []


def test_missing_session_is_ignored(metrics):
    """Skip runs without a real session id."""
    service = _Service()
    binding = _binding(service)
    assert _run(metrics, _agent_chat(_agent(_model()), session_id=""), binding) is False
    assert service.offers == []


def test_missing_model_is_ignored(metrics):
    """Skip when the runtime exposes no model."""
    service = _Service()
    binding = _binding(service)
    agent = SimpleNamespace(runtime=SimpleNamespace(tool_stat=None, llm_model=None),
                            llm_request_stat=None)
    assert _run(metrics, _agent_chat(agent), binding) is False
    assert service.offers == []


def test_blank_model_name_is_ignored(metrics):
    """Skip when the model name cannot identify a document."""
    service = _Service()
    binding = _binding(service)
    assert _run(metrics, _agent_chat(_agent(_model("   "))), binding) is False
    assert service.offers == []


def test_unregistered_model_identity_is_ignored(metrics):
    """Skip when the binding has no registered identity for the model."""
    service = _Service()
    binding = _binding(service)
    binding.model_id = lambda model: None
    assert _run(metrics, _agent_chat(_agent(_model())), binding) is False
    assert service.offers == []


def test_offer_rejection_is_reported(metrics):
    """Propagate a rejected offer as a failed observation."""
    service = _Service(result=False)
    binding = _binding(service)
    assert _run(metrics, _agent_chat(_agent(_model())), binding) is False


def test_exception_is_swallowed(metrics):
    """Never interrupt the Agent flow when the hook raises."""
    service = _Service()
    binding = _binding(service)

    def explode(agent):
        raise RuntimeError("boom")

    binding.settle_authorized = explode
    assert _run(metrics, _agent_chat(_agent(_model())), binding) is False


def test_writer_targets_the_model_document(metrics):
    """Hand the worker a writer bound to the current model's document."""
    service = _Service()
    binding = _binding(service)
    assert _run(metrics, _agent_chat(_agent(_model("Kimi-K2.5"))), binding) is True
    writer, _ = service.offers[0]
    assert writer.model_name == "Kimi-K2.5"
    assert writer.path.name.startswith("Kimi-K2.5.")
    assert writer.path.name.endswith(".model.stats.json")


def test_payload_is_framed_and_bounded(metrics):
    """Emit one newline-terminated line within the storage cap."""
    service = _Service()
    binding = _binding(service)
    assert _run(metrics, _agent_chat(_agent(_model())), binding) is True
    line = service.offers[0][1]
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    assert len(line) <= 4096


def test_negative_tracker_values_contribute_zero(metrics):
    """Reject invalid tracker values instead of corrupting totals."""
    service = _Service()
    binding = _binding(service)
    tool = SimpleNamespace(_call_sequence=-3, _error_count="x",
                           _execution_duration_sum_sec=-1.0)
    request = SimpleNamespace(_total_requests=None, _request_failures=-2,
                              _request_duration_sum_sec="bad")
    agent = _agent(_model(), tool, request)

    assert _run(metrics, _agent_chat(agent), binding) is True
    payload = _payload(service)
    assert payload["tool_call_count"] == 0
    assert payload["tool_error_count"] == 0
    assert payload["llm_request_count"] == 0
    assert payload["llm_request_failure_count"] == 0
    assert payload["tool_duration_ms_sum"] == 0
    assert payload["llm_request_duration_ms_sum"] == 0


def test_missing_token_tracker_contributes_zero(metrics):
    """Treat an absent token tracker as no token contribution."""
    service = _Service()
    binding = _binding(service)
    model = SimpleNamespace(model_name="Kimi-K2.5", tokenStat=None)
    assert _run(metrics, _agent_chat(_agent(model)), binding) is True
    payload = _payload(service)
    assert payload["prompt_tokens"] == 0
    assert payload["first_byte_count"] == 0


def test_baseline_is_stored_on_the_binding(metrics):
    """Keep the baseline on the conversation-scoped token, not the module."""
    service = _Service()
    binding = _binding(service)
    agent = _agent(_model(), _tool_stat(calls=2))

    assert _run(metrics, _agent_chat(agent), binding) is True
    baseline = getattr(binding, metrics.BASELINE_ATTR)
    assert baseline["agent"]["tool_call_count"] == 2
    assert baseline["models"]["mid-1"]["prompt_tokens"] == 0
