"""Unit tests for read-only Runtime Data Instructions."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from topsailai.ai_base.runtime_data import RuntimeDataStore
from topsailai.workspace.plugin_instruction import runtime


@pytest.fixture
def store(monkeypatch):
    """Bind one real bounded Store to the active Instruction Agent."""
    runtime_store = RuntimeDataStore(history_capacity=3, clock_ms=iter(range(100, 1000)).__next__)
    agent = SimpleNamespace(runtime=SimpleNamespace(runtime_data=runtime_store))
    monkeypatch.setattr(runtime, "get_ai_agent", lambda: agent)
    return runtime_store


def _retry_value(attempts=3, **extra):
    """Build one representative retry-state payload."""
    return {
        "phase": "fault_retrying",
        "failed_attempts": attempts,
        "next_retry_number": attempts,
        "threshold": 3,
        "last_error_category": "LLMNullResponseError",
        **extra,
    }


def test_runtime_commands_are_registered_exactly_once():
    """Expose the three approved names without a runtime.runtime duplicate."""
    from topsailai.workspace.plugin_instruction.base.init import INSTRUCTIONS

    assert INSTRUCTIONS["runtime"] is runtime.show_runtime
    assert INSTRUCTIONS["runtime.get"] is runtime.get_runtime
    assert INSTRUCTIONS["runtime.history"] is runtime.show_runtime_history
    assert "runtime.runtime" not in INSTRUCTIONS
    assert sum(key in INSTRUCTIONS for key in ("runtime", "runtime.get", "runtime.history")) == 3
    assert "agent.tokens" not in INSTRUCTIONS
    assert "env.get" in INSTRUCTIONS


def test_runtime_lists_only_public_active_states(store):
    """Render public state while omitting private state and internal ownership."""
    store.activate("llm.request.retrying", "public-owner", _retry_value(), public=True)
    store.activate(
        "tool.approval.waiting",
        "private-owner",
        {"credential": "private-sentinel"},
        public=False,
    )

    result = runtime.show_runtime()

    assert "Active runtime states:" in result
    assert "llm.request.retrying" in result
    assert "Failed attempts: 3" in result
    assert "Threshold: 3" in result
    assert "LLMNullResponseError" in result
    assert "tool.approval.waiting" not in result
    assert "private-sentinel" not in result
    assert "public-owner" not in result
    assert "private-owner" not in result


def test_runtime_empty_after_settlement(store):
    """Remove settled state from the active listing."""
    lease = store.activate("llm.request.retrying", "request-1", _retry_value())
    assert store.deactivate(lease, outcome="recovered") is True

    assert runtime.show_runtime() == "No active runtime states."


def test_runtime_get_returns_public_state(store):
    """Return one exact public state with stable diagnostic fields."""
    store.activate("llm.request.retrying", "request-1", _retry_value(4))

    result = runtime.get_runtime("llm.request.retrying")

    assert result.startswith("llm.request.retrying\n")
    assert "Revision: 1" in result
    assert "Failed attempts: 4" in result
    assert "Updated at ms:" in result


@pytest.mark.parametrize(
    "args, expected",
    [
        ((), "Usage: /runtime.get <key> [json=1]"),
        (("llm.request.retrying", "extra"), "Usage: /runtime.get <key> [json=1]"),
        (("",), "Invalid runtime state key."),
        (("LLM.retrying",), "Invalid runtime state key."),
        (("llm\n.retrying",), "Invalid runtime state key."),
    ],
)
def test_runtime_get_validates_arguments_without_store_query(store, monkeypatch, args, expected):
    """Reject missing, extra, or malformed key arguments before querying."""
    spy = MagicMock(wraps=store)
    monkeypatch.setattr(runtime, "_get_runtime_data_store", lambda: spy)

    assert runtime.get_runtime(*args) == expected
    spy.get.assert_not_called()


def test_runtime_get_hides_private_state_as_not_found(store):
    """Do not disclose whether a requested private state exists."""
    store.activate("tool.approval.waiting", "request-1", {"phase": "hidden"}, public=False)

    assert runtime.get_runtime("tool.approval.waiting") == (
        "Runtime state not found: tool.approval.waiting"
    )
    assert runtime.get_runtime("tool.approval.missing") == (
        "Runtime state not found: tool.approval.missing"
    )


def test_runtime_history_is_bounded_public_and_filterable(store):
    """Render only retained public records and filter by exact key."""
    keys = (
        "context.summary.running",
        "tool.approval.waiting",
        "agent.pause.waiting",
        "llm.request.retrying",
        "context.summary.running",
    )
    for index, key in enumerate(keys):
        lease = store.activate(
            key,
            f"request-{index}",
            _retry_value(index + 1, credential=f"secret-{index}"),
            public=index != 3,
        )
        store.deactivate(lease, outcome="recovered")

    result = runtime.show_runtime_history()

    assert "request-0" not in result
    assert "tool.approval.waiting" not in result
    assert "agent.pause.waiting" in result
    assert "context.summary.running" in result
    assert "llm.request.retrying" not in result
    assert "secret-" not in result
    assert result.count("Outcome: recovered") == 2

    filtered = runtime.show_runtime_history("context.summary.running")
    assert filtered.count("context.summary.running") == 1
    assert "agent.pause.waiting" not in filtered


def test_runtime_history_empty_and_argument_contract(store):
    """Return stable empty, usage, and invalid-key responses."""
    assert runtime.show_runtime_history() == "No runtime state history."
    assert runtime.show_runtime_history("a.b", "extra") == (
        "Usage: /runtime.history [key] [json=1]"
    )
    assert runtime.show_runtime_history("invalid") == "Invalid runtime state key."


def test_runtime_instructions_report_missing_agent(monkeypatch):
    """Return one no-runtime contract without creating fallback state."""
    monkeypatch.setattr(runtime, "get_ai_agent", lambda: None)

    assert runtime.show_runtime() == "No active Agent runtime."
    assert runtime.get_runtime("llm.request.retrying") == "No active Agent runtime."
    assert runtime.show_runtime_history() == "No active Agent runtime."


def test_runtime_output_uses_allowlist_and_bounds_scalar_values(store):
    """Omit arbitrary payload fields and bound approved text values."""
    long_category = "E" * 200
    value = _retry_value(
        last_error_category=long_category,
        prompt="prompt-sentinel",
        response="response-sentinel",
        api_key="credential-sentinel",
        exception="complete-exception-sentinel",
        nested={"text": "nested-sentinel"},
    )
    store.activate("llm.request.retrying", "lease-token-sentinel", value)

    result = runtime.show_runtime()

    assert "E" * 120 + "..." in result
    for sentinel in (
        "prompt-sentinel",
        "response-sentinel",
        "credential-sentinel",
        "complete-exception-sentinel",
        "nested-sentinel",
        "lease-token-sentinel",
    ):
        assert sentinel not in result


def test_runtime_queries_are_read_only(store, monkeypatch):
    """Use only detached query methods and preserve Store state across queries."""
    lease = store.activate("llm.request.retrying", "request-1", _retry_value())
    before = store.get("llm.request.retrying")
    spy = MagicMock(wraps=store)
    monkeypatch.setattr(runtime, "_get_runtime_data_store", lambda: spy)

    runtime.show_runtime()
    runtime.get_runtime("llm.request.retrying")
    runtime.show_runtime_history()

    spy.activate.assert_not_called()
    spy.update.assert_not_called()
    spy.deactivate.assert_not_called()
    assert store.get("llm.request.retrying") == before
    assert store.history() == ()
    assert store.deactivate(lease, outcome="recovered") is True


def test_runtime_root_rejects_arguments(store):
    """Keep the root command free of positional arguments."""
    assert runtime.show_runtime("unexpected") == "Usage: /runtime [json=1]"


def test_runtime_json_output_is_valid_and_allowlisted(store):
    """Emit parseable JSON that keeps the text-mode allowlist and bounds."""
    store.activate(
        "llm.request.retrying",
        "lease-token-sentinel",
        _retry_value(
            prompt="prompt-sentinel",
            api_key="credential-sentinel",
            nested={"text": "nested-sentinel"},
        ),
    )

    payload = json.loads(runtime.show_runtime(json="1"))

    assert payload["ok"] is True
    assert len(payload["active"]) == 1
    entry = payload["active"][0]
    assert entry["key"] == "llm.request.retrying"
    assert entry["revision"] == 1
    assert entry["updated_at_ms"] == 100
    assert entry["value"] == {
        "phase": "fault_retrying",
        "failed_attempts": 3,
        "next_retry_number": 3,
        "threshold": 3,
        "last_error_category": "LLMNullResponseError",
    }
    for sentinel in (
        "prompt-sentinel",
        "credential-sentinel",
        "nested-sentinel",
        "lease-token-sentinel",
        "owner_id",
    ):
        assert sentinel not in json.dumps(payload)


def test_runtime_json_get_and_history_shapes(store):
    """Return one active object and one bounded history list in JSON mode."""
    lease = store.activate("llm.request.retrying", "request-1", _retry_value())
    assert store.deactivate(lease, outcome="recovered") is True
    store.activate("llm.request.retrying", "request-2", _retry_value(4))

    active = json.loads(runtime.get_runtime("llm.request.retrying", json="1"))
    assert active["ok"] is True
    assert active["active"]["value"]["failed_attempts"] == 4

    history = json.loads(runtime.show_runtime_history(json="1"))
    assert history["ok"] is True
    assert len(history["history"]) == 1
    assert history["history"][0]["outcome"] == "recovered"
    assert history["history"][0]["settled_at_ms"] == 101


def test_runtime_json_accepts_forwarded_named_parameters(store):
    """Accept the control-channel form where one token carries every parameter."""
    store.activate("llm.request.retrying", "request-1", _retry_value())

    forwarded = json.loads(runtime.get_runtime("key=llm.request.retrying;json=1"))
    assert forwarded["ok"] is True
    assert forwarded["active"]["key"] == "llm.request.retrying"

    positional = json.loads(runtime.get_runtime("llm.request.retrying", "json=1"))
    assert positional["ok"] is True


def test_runtime_json_disabled_matches_text_output(store):
    """Treat `json=0` exactly like an omitted flag."""
    store.activate("llm.request.retrying", "request-1", _retry_value())

    assert runtime.show_runtime(json="0") == runtime.show_runtime()
    assert runtime.get_runtime("llm.request.retrying", json="0") == (
        runtime.get_runtime("llm.request.retrying")
    )
    assert runtime.show_runtime_history(json="0") == runtime.show_runtime_history()


@pytest.mark.parametrize(
    "call, expected_error",
    [
        (lambda: runtime.get_runtime(json="1"), "missing_key"),
        (lambda: runtime.get_runtime("BAD", json="1"), "invalid_key"),
        (lambda: runtime.get_runtime("a.b", json="1"), "not_found"),
        (lambda: runtime.show_runtime("yaml=1;json=1"), "unknown_parameter"),
        (lambda: runtime.get_runtime("a.b", "c.d", json="1"), "too_many_arguments"),
    ],
)
def test_runtime_json_reports_structured_errors(store, call, expected_error):
    """Report machine-readable error tokens instead of human sentences."""
    payload = json.loads(call())

    assert payload["ok"] is False
    assert payload["error"] == expected_error


def test_runtime_json_reports_missing_agent(monkeypatch):
    """Report the no-runtime contract as a structured error."""
    monkeypatch.setattr(runtime, "get_ai_agent", lambda: None)

    payload = json.loads(runtime.show_runtime(json="1"))

    assert payload == {"ok": False, "error": "no_runtime"}
