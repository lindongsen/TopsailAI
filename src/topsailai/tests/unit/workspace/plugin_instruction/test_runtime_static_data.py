"""Unit tests for the `/runtime.static-data` plugin instruction."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from topsailai.workspace.context.instruction import ContextRuntimeInstructions
from topsailai.workspace.plugin_instruction import runtime


def _agent(messages=None, tools=None, total_calls=0):
    """Build a minimal active agent exposing only directly readable facts."""
    return SimpleNamespace(
        messages=[] if messages is None else messages,
        llm_model=SimpleNamespace(model_name="test-model", max_tokens=1000),
        available_tools={} if tools is None else tools,
        runtime=SimpleNamespace(tool_stat=SimpleNamespace(total_calls=total_calls)),
    )


def _runtime(agent=None, messages=None, session_id="session-1"):
    """Build a runtime whose derived-value helpers fail if they are ever used."""
    return SimpleNamespace(
        ai_agent=_agent() if agent is None else agent,
        messages=[] if messages is None else messages,
        session_id=session_id,
        del_session_message_by_ids=MagicMock(),
        _get_current_tokens=MagicMock(
            side_effect=AssertionError("static data must not count tokens"),
        ),
        _classify_context_watermark=MagicMock(
            side_effect=AssertionError("static data must not classify a watermark"),
        ),
    )


def test_static_data_is_registered_exactly_once():
    """Register the command only through the context-bound instruction map."""
    instructions = ContextRuntimeInstructions(MagicMock()).instructions

    assert "runtime.static-data" in instructions
    assert instructions["runtime.static-data"].__self__.__class__ is (
        ContextRuntimeInstructions
    )
    # The plugin map must stay free of the name, because HookInstruction
    # appends registrations and a second one would run the handler twice.
    assert "static-data" not in runtime.INSTRUCTIONS
    assert set(runtime.INSTRUCTIONS) == {"runtime", "get", "history"}


def test_static_data_reports_both_message_counts_by_direct_read():
    """Report both layer counts without invoking any derived-value helper."""
    agent = _agent(
        messages=[{"role": "system"}, {"role": "user"}],
        tools={"a": 1, "b": 2, "c": 3},
        total_calls=7,
    )
    ctx_runtime_data = _runtime(agent=agent, messages=[{"role": "user"}])

    report = runtime.static_data(ctx_runtime_data)

    assert "Agent2LLM:\n  Messages: 2" in report
    assert "User2Agent:\n  Messages: 1" in report
    assert "Available: 3" in report
    assert "Total calls: 7" in report
    assert "Model: test-model" in report
    assert "Model maximum tokens: 1,000" in report
    ctx_runtime_data._get_current_tokens.assert_not_called()
    ctx_runtime_data._classify_context_watermark.assert_not_called()


def test_static_data_json_reports_the_same_facts():
    """Expose the documented document shape for programmatic consumers."""
    agent = _agent(
        messages=[{"role": "system"}, {"role": "user"}],
        tools={"a": 1, "b": 2, "c": 3},
        total_calls=7,
    )
    ctx_runtime_data = _runtime(agent=agent, messages=[{"role": "user"}])

    payload = json.loads(runtime.static_data(ctx_runtime_data, json="1"))

    assert payload == {
        "ok": True,
        "session": {"id": "session-1", "ephemeral": False},
        "model": {"name": "test-model", "max_tokens": 1000},
        "agent2llm": {"messages": 2},
        "user2agent": {"messages": 1},
        "tools": {"available": 3},
        "tool_calls": {"total": 7},
    }
    ctx_runtime_data._get_current_tokens.assert_not_called()
    ctx_runtime_data._classify_context_watermark.assert_not_called()


def test_static_data_text_and_json_share_one_payload():
    """Derive every fact once so the two renderings cannot disagree."""
    ctx_runtime_data = _runtime(
        agent=_agent(messages=[{"role": "user"}], tools={"a": 1}, total_calls=2),
        messages=[{"role": "user"}, {"role": "user"}],
    )

    payload = json.loads(runtime.static_data(ctx_runtime_data, json="1"))
    report = runtime.static_data(ctx_runtime_data)

    assert f"Messages: {payload['agent2llm']['messages']}" in report
    assert f"Messages: {payload['user2agent']['messages']}" in report
    assert f"Available: {payload['tools']['available']}" in report
    assert f"Total calls: {payload['tool_calls']['total']}" in report


def test_static_data_marks_an_ephemeral_session():
    """Report an unsaved session without inventing an identifier."""
    ctx_runtime_data = _runtime(session_id="")

    payload = json.loads(runtime.static_data(ctx_runtime_data, json="1"))

    assert payload["session"] == {"id": "", "ephemeral": True}
    assert "Session: (ephemeral/unsaved session)" in runtime.static_data(
        ctx_runtime_data
    )


@pytest.mark.parametrize(
    "missing, key, expected",
    [
        ("messages", "agent2llm", {"messages": 0}),
        ("available_tools", "tools", {"available": 0}),
    ],
)
def test_static_data_counts_missing_collections_as_zero(missing, key, expected):
    """Report `0` for an absent collection instead of raising."""
    agent = _agent()
    setattr(agent, missing, None)

    payload = json.loads(runtime.static_data(_runtime(agent=agent), json="1"))

    assert payload[key] == expected


def test_static_data_tolerates_a_missing_tool_stat():
    """Report `0` tool calls when the runtime exposes no statistics object."""
    agent = _agent()
    agent.runtime = SimpleNamespace()

    payload = json.loads(runtime.static_data(_runtime(agent=agent), json="1"))

    assert payload["tool_calls"] == {"total": 0}


def test_static_data_reports_no_runtime_without_an_agent(monkeypatch):
    """Return the shared no-runtime contract in both formats."""
    monkeypatch.setattr(runtime, "get_ai_agent", lambda: None)

    assert runtime.static_data(None) == "No active Agent runtime."
    assert json.loads(runtime.static_data(None, json="1")) == {
        "ok": False,
        "error": "no_runtime",
    }


def test_static_data_falls_back_to_the_bound_agent(monkeypatch):
    """Resolve the Agent from the instruction cache when no runtime is passed."""
    agent = _agent(messages=[{"role": "user"}])
    monkeypatch.setattr(runtime, "get_ai_agent", lambda: agent)

    payload = json.loads(runtime.static_data(None, json="1"))

    assert payload["agent2llm"] == {"messages": 1}
    assert payload["user2agent"] == {"messages": 0}


def test_static_data_json_zero_equals_absent_flag():
    """Treat `json=0` exactly like an omitted flag."""
    ctx_runtime_data = _runtime()

    assert runtime.static_data(ctx_runtime_data, json="0") == runtime.static_data(
        ctx_runtime_data
    )


@pytest.mark.parametrize(
    "args, expected_error",
    [
        (("yaml=1",), "unknown_parameter"),
        (("a", "b"), "too_many_arguments"),
        (("key=llm.request.retrying",), "unknown_parameter"),
    ],
)
def test_static_data_reports_structured_argument_errors(args, expected_error):
    """Report machine-readable tokens instead of silently ignoring arguments."""
    payload = json.loads(runtime.static_data(_runtime(), *args, json="1"))

    assert payload["ok"] is False
    assert payload["error"] == expected_error
    assert payload["usage"] == "Usage: /runtime.static-data [json=1]"


def test_static_data_reports_text_usage_for_unknown_parameter():
    """Render the usage line in text mode for an unusable argument."""
    assert runtime.static_data(_runtime(), "yaml=1") == (
        "Usage: /runtime.static-data [json=1]"
    )


def test_static_data_accepts_the_forwarded_named_parameter_form():
    """Accept the control-channel form where one token carries every parameter."""
    ctx_runtime_data = _runtime()

    forwarded = json.loads(runtime.static_data(ctx_runtime_data, "json=1"))
    keyword = json.loads(runtime.static_data(ctx_runtime_data, json="1"))

    assert forwarded == keyword


def test_bound_handler_supplies_the_context_runtime_data():
    """Bind the handler to the chat's runtime data instead of the global cache."""
    ctx_runtime_data = _runtime(messages=[{"role": "user"}])
    instructions = ContextRuntimeInstructions(ctx_runtime_data).instructions

    payload = json.loads(instructions["runtime.static-data"]("json=1"))

    assert payload["user2agent"] == {"messages": 1}
    assert payload["session"]["id"] == "session-1"


def test_bound_handler_keeps_text_mode_unchanged():
    """Forward no flag in text mode so the default rendering is used."""
    ctx_runtime_data = _runtime()
    instructions = ContextRuntimeInstructions(ctx_runtime_data).instructions

    assert instructions["runtime.static-data"]() == runtime.static_data(
        ctx_runtime_data
    )


def test_static_data_never_reports_token_counts():
    """Keep token estimates out of this entry; they belong to `/agent.tokens`."""
    ctx_runtime_data = _runtime(agent=_agent(messages=[{"role": "user"}]))

    report = runtime.static_data(ctx_runtime_data)
    payload = json.loads(runtime.static_data(ctx_runtime_data, json="1"))

    assert "token" not in report.lower().replace("model maximum tokens", "")
    assert "estimated_tokens" not in json.dumps(payload)
    assert "watermark" not in json.dumps(payload)
