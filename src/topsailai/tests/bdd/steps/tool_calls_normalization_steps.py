"""Unique BDD steps for tool-call persistence and wire normalization."""

from __future__ import annotations

import logging
import re
from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.tool_calls_mock_harness import (
    LEGACY_CALL_ID,
    LEGACY_REPR,
    RESULT_SENTINEL,
    ToolCallsScenario,
)


@pytest.fixture
def tc_norm_ctx(tmp_path, monkeypatch):
    """Yield one isolated scenario and enforce exact server-thread teardown."""
    context = ToolCallsScenario(tmp_path, monkeypatch)
    yield context
    context.close()


@given("a tool-calls normalization environment with a private mock LLM server")
def given_tc_norm_env(tc_norm_ctx):
    """Provide a private real-HTTP mock provider and temporary SQLite store."""
    assert tc_norm_ctx.server_owner.thread.is_alive()


@given(parsers.parse('the tool-calls normalization session "{session_id}" is seeded with a structured assistant tool call message and its tool result'))
def given_tc_norm_seed_structured(tc_norm_ctx, session_id: str):
    """Persist an SDK-like structured call and result through public APIs."""
    tc_norm_ctx.seed_structured(session_id)


@given(parsers.parse('the tool-calls normalization session "{session_id}" is seeded with legacy malformed repr tool calls and its tool result'))
def given_tc_norm_seed_legacy(tc_norm_ctx, session_id: str):
    """Persist a faithful pre-fix malformed call and result through public APIs."""
    tc_norm_ctx.seed_legacy(session_id)


@given(parsers.parse('the tool-calls normalization replacement hook "{hook_name}" injects malformed tool calls'))
def given_tc_norm_replacement_hook(tc_norm_ctx, hook_name: str):
    """Install a configured replacement hook that records its own execution."""
    tc_norm_ctx.install_replacement_hook(hook_name)


@given(parsers.parse('the tool-calls normalization mock server replies with tool calls to "{tool_names}"'))
def given_tc_norm_server_tool_reply(tc_norm_ctx, tool_names: str):
    """Script one native assistant response containing one or more calls."""
    tc_norm_ctx.script_tool_calls(tool_names)


@given("the tool-calls normalization parallel tool calls mode is enabled")
def given_tc_norm_parallel_mode(tc_norm_ctx):
    """Enable the public parallel-tool configuration for this scenario only."""
    tc_norm_ctx.monkeypatch.setenv("TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS", "1")


@when(parsers.parse('the tool-calls normalization session "{session_id}" continues the conversation with "{message}"'))
def when_tc_norm_continue(tc_norm_ctx, caplog, session_id: str, message: str):
    """Drive a real provider request while capturing warning-level observations."""
    caplog.set_level(logging.WARNING)
    tc_norm_ctx.continue_conversation(session_id, message)


@when("the native tool-calls incident is produced by the framework, degraded during persistence, and replayed")
def when_tc_norm_reproduce_native_incident(tc_norm_ctx):
    """Drive native production, historical degradation, and native replay."""
    tc_norm_ctx.reproduce_native_incident()


@when("the tool-calls normalization Agent2LLM context is forced through real summarization before the conversation continues")
def when_tc_norm_summarize_and_continue(tc_norm_ctx):
    """Drive a real summary request followed by a rebuilt-context request."""
    tc_norm_ctx.summarize_and_continue("bdd_tc_summarize")


@then("the tool-calls normalization summarization and continuation requests are both observed")
def then_tc_norm_summary_and_continuation_observed(tc_norm_ctx):
    """Assert real summarization rebuilt context before the second request."""
    assert tc_norm_ctx.error is None, repr(tc_norm_ctx.error)
    assert tc_norm_ctx.summary_answer
    assert tc_norm_ctx.summary_before_count == 3
    assert tc_norm_ctx.summary_after_count == 1
    assert tc_norm_ctx.summary_agent.messages[0]["content"] == tc_norm_ctx.summary_answer
    state = tc_norm_ctx.state()
    assert state["total_requests"] == 2, state
    assert len(state["request_bodies"]) == 2, state
    assert state["dropped_request_body_count"] == 0, state
    first_messages = state["request_bodies"][0]["body"]["messages"]
    second_messages = state["request_bodies"][1]["body"]["messages"]
    assert "Conversation Analyst and Summarization Specialist" in str(first_messages)
    assert any(
        message.get("content") == "continue after summarization"
        for message in first_messages
    )
    assert any(message.get("role") == "assistant" for message in second_messages)
    assert "continue with the rebuilt context" in str(second_messages)


@then("the native incident assistant call and tool result were produced by the framework")
def then_tc_norm_native_messages_were_framework_produced(tc_norm_ctx):
    """Prove S7 obtained its native pair from AgentRun rather than a seed."""
    assert tc_norm_ctx.error is None, repr(tc_norm_ctx.error)
    assert tc_norm_ctx.native_framework_produced
    assert tc_norm_ctx.native_legacy_repr
    assert tc_norm_ctx.result


@then("the native incident requests all include native tool definitions")
def then_tc_norm_native_requests_include_tools(tc_norm_ctx):
    """Assert every provider request ran with explicit native tool schemas."""
    state = tc_norm_ctx.state()
    assert state["request_bodies"], state
    for record in state["request_bodies"]:
        tools = record["body"].get("tools")
        assert isinstance(tools, list) and tools, record
        assert any(tool.get("function", {}).get("name") == "safe_tool" for tool in tools)


@then(parsers.parse("the tool-calls normalization mock server received exactly {count:d} completion requests"))
def then_tc_norm_request_count(tc_norm_ctx, count: int):
    """Assert the provider-side request count, including tool-loop follow-ups."""
    state = tc_norm_ctx.state()
    assert state["total_requests"] == count, state
    assert len(state["request_bodies"]) == count, state


@then("the tool-calls normalization conversation completes without a bad request error")
def then_tc_norm_no_bad_request(tc_norm_ctx):
    """Assert that the real HTTP conversation returned without an exception."""
    assert tc_norm_ctx.error is None, repr(tc_norm_ctx.error)
    assert tc_norm_ctx.result


@then("every tool calls array the tool-calls normalization mock server received is a JSON array of objects with id, type and function")
def then_tc_norm_tool_calls_object_shaped(tc_norm_ctx):
    """Assert every captured call is structured and runtime results are paired."""
    arrays = [
        message["tool_calls"]
        for message in tc_norm_ctx.received_messages()
        if "tool_calls" in message
    ]
    assert arrays, "no server-received tool_calls arrays"
    for tool_calls in arrays:
        assert isinstance(tool_calls, list) and tool_calls
        for tool_call in tool_calls:
            assert isinstance(tool_call, dict), tool_call
            assert isinstance(tool_call.get("id"), str) and tool_call["id"]
            assert tool_call.get("type") == "function"
            function = tool_call.get("function")
            assert isinstance(function, dict) and function.get("name")
            assert isinstance(function.get("arguments"), str)
    if tc_norm_ctx.scripted_tool_names:
        expected_ids = {
            f"call_bdd_runtime_{index}"
            for index in range(1, len(tc_norm_ctx.scripted_tool_names) + 1)
        }
        received_ids = {
            message.get("tool_call_id")
            for message in tc_norm_ctx.received_messages()
            if message.get("role") == "tool"
        }
        assert expected_ids <= received_ids, (expected_ids, received_ids)


@then("the tool-calls normalization mock server received no malformed tool calls value")
def then_tc_norm_no_malformed(tc_norm_ctx):
    """Prove malformed input existed or ran, yet did not cross the wire boundary."""
    if tc_norm_ctx.seeded_malformed:
        assert tc_norm_ctx.seeded_malformed
    if tc_norm_ctx.hook_marker is not None:
        injected = tc_norm_ctx.hook_marker.read_text(encoding="utf-8")
        assert injected == LEGACY_REPR
    for message in tc_norm_ctx.received_messages():
        tool_calls: Any = message.get("tool_calls")
        assert not isinstance(tool_calls, str), message
        if isinstance(tool_calls, list):
            assert not any(isinstance(item, str) for item in tool_calls), message
        assert LEGACY_REPR not in str(tool_calls)
        if tc_norm_ctx.native_legacy_repr:
            assert tc_norm_ctx.native_legacy_repr not in str(tool_calls)


@then("the tool-calls normalization mock server received no ownerless tool result message")
def then_tc_norm_no_ownerless_result(tc_norm_ctx):
    """Assert the result lost its malformed owner and was safely dropped."""
    assert tc_norm_ctx.seeded_malformed
    assert not any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == LEGACY_CALL_ID
        for message in tc_norm_ctx.received_messages()
    )


@then("the native incident mock server received no ownerless tool result message")
def then_tc_norm_native_no_ownerless_result(tc_norm_ctx):
    """Assert S7 never sends the degraded native result without its owner."""
    assert tc_norm_ctx.seeded_malformed
    assert tc_norm_ctx.native_legacy_repr
    assert tc_norm_ctx.native_call_id
    state = tc_norm_ctx.state()
    replay_messages = state["request_bodies"][-1]["body"]["messages"]
    assert not any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == tc_norm_ctx.native_call_id
        for message in replay_messages
    )


@then("the tool-calls normalization logs contain the degradation warning with only index and type")
def then_tc_norm_warning_bounded(caplog):
    """Assert one bounded warning exposes only structural diagnostic fields."""
    warnings = [
        record.getMessage()
        for record in caplog.records
        if "strip malformed assistant tool_calls" in record.getMessage()
    ]
    assert len(warnings) == 1, warnings
    assert re.fullmatch(
        r"strip malformed assistant tool_calls: index=\d+ type=str",
        warnings[0],
    ), warnings[0]


@then("the tool-calls normalization logs contain no tool arguments or tool result sentinel")
def then_tc_norm_no_sentinel_leak(caplog):
    """Assert neither harmless sentinel appears anywhere in captured logs."""
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "ARGS-SENTINEL-XYZ" not in log_text
    assert RESULT_SENTINEL not in log_text
