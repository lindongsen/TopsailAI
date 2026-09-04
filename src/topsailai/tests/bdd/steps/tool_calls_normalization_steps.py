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


@given(parsers.parse('the tool-calls normalization session "{session_id}" is seeded with tool result messages whose call ids are absent or blank'))
def given_tc_norm_seed_results_without_ids(tc_norm_ctx, session_id: str):
    """Persist invalid tool results whose owners cannot be identified."""
    tc_norm_ctx.seed_tool_results_without_ids(session_id)


@given(parsers.parse('the tool-calls normalization session "{session_id}" is seeded with one paired native tool result and two unowned tool results'))
def given_tc_norm_seed_paired_and_unowned(tc_norm_ctx, session_id: str):
    """Persist one valid native pair alongside two unowned tool results."""
    tc_norm_ctx.seed_paired_and_unowned_results(session_id)


@given(parsers.parse('the tool-calls normalization session "{session_id}" is seeded with ordinary non-native conversation messages'))
def given_tc_norm_seed_ordinary(tc_norm_ctx, session_id: str):
    """Persist tool-free traffic whose observation is a textual user message."""
    tc_norm_ctx.seed_ordinary_non_native(session_id)


@given("the non-native tool-calls mode skips both mode-gated earlier cleanup sites")
def given_tc_norm_earlier_sites_skipped(tc_norm_ctx):
    """Assert the gated producer helper and pre-chat hook are inert when disabled."""
    tc_norm_ctx.prove_earlier_sites_skipped_in_non_native_mode()


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


@then("the tool-calls normalization mock server received no tool result message with an absent or blank call id")
def then_tc_norm_no_result_without_id(tc_norm_ctx):
    """Assert the final request boundary removed unidentifiable tool results."""
    tool_messages = [
        message
        for message in tc_norm_ctx.received_messages()
        if message.get("role") == "tool"
    ]
    assert not any(not message.get("tool_call_id") for message in tool_messages)


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


@then("the non-native textual observation reaches the provider as a user message with its observation step")
def then_tc_norm_textual_observation_preserved(tc_norm_ctx):
    """Assert a textual ReAct observation is never mistaken for a tool result."""
    from tests.bdd.tool_calls_mock_harness import OBSERVATION_TEXT

    assert tc_norm_ctx.error is None, repr(tc_norm_ctx.error)
    observations = [
        message
        for message in tc_norm_ctx.received_messages()
        if message.get("content") == OBSERVATION_TEXT
    ]
    assert len(observations) == 1, observations
    assert observations[0].get("role") == "user", observations[0]
    assert observations[0].get("step_name") == "observation", observations[0]


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


@then("the non-native request boundary drops the unowned tool results and keeps the paired result")
def then_tc_norm_non_native_boundary_selective(tc_norm_ctx):
    """Assert the mode-independent boundary is selective rather than blanket-dropping."""
    from tests.bdd.tool_calls_mock_harness import (
        PAIRED_RESULT,
        UNOWNED_BLANK_ID_RESULT,
        UNOWNED_MISSING_ID_RESULT,
    )

    assert tc_norm_ctx.error is None, repr(tc_norm_ctx.error)
    tool_contents = [
        message.get("content")
        for message in tc_norm_ctx.received_messages()
        if message.get("role") == "tool"
    ]
    assert PAIRED_RESULT in tool_contents, tool_contents
    assert UNOWNED_MISSING_ID_RESULT not in tool_contents, tool_contents
    assert UNOWNED_BLANK_ID_RESULT not in tool_contents, tool_contents


@then("the non-native wire request carries no tool calls array and no tool result message")
def then_tc_norm_non_native_wire_has_no_tool_data(tc_norm_ctx):
    """Assert the sanitizer neither injects nor leaves any tool construct."""
    messages = tc_norm_ctx.received_messages()
    assert messages, "no server-received messages"
    assert not any("tool_calls" in message for message in messages), messages
    assert not any(
        message.get("role") == "tool" for message in messages
    ), messages


@then("the non-native ordinary conversation reaches the provider unchanged and in order")
def then_tc_norm_non_native_ordinary_untouched(tc_norm_ctx):
    """Assert every seeded non-tool message survives the sanitizer byte-for-byte."""
    assert tc_norm_ctx.error is None, repr(tc_norm_ctx.error)
    assert tc_norm_ctx.ordinary_expected
    body = tc_norm_ctx.state()["request_bodies"][-1]["body"]
    persisted = [
        (message.get("role"), message.get("content"))
        for message in body["messages"]
        if message.get("role") != "system"
        and message.get("content") not in (None, "", "continue the task")
    ]
    assert persisted == tc_norm_ctx.ordinary_expected, persisted


@then("the tool-calls normalization logs contain no tool arguments or tool result sentinel")
def then_tc_norm_no_sentinel_leak(caplog):
    """Assert neither harmless sentinel appears anywhere in captured logs."""
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "ARGS-SENTINEL-XYZ" not in log_text
    assert RESULT_SENTINEL not in log_text


@given("the tool-calls normalization mock server replies with thought final answer and a native tool call")
def given_tc_norm_mixed_native_response(tc_norm_ctx):
    """Script the production incident shape through the real provider boundary."""
    tc_norm_ctx.script_mixed_tool_response()


@given(parsers.parse('the tool-calls normalization session "{session_id}" is seeded with an unexecuted human decision call'))
def given_tc_norm_seed_dangling_human(tc_norm_ctx, session_id: str):
    """Persist a human decision call without creating its tool output."""
    tc_norm_ctx.seed_dangling_human_decision(session_id)


@when(parsers.parse('the tool-calls normalization session "{session_id}" continues with model "{model}"'))
def when_tc_norm_continue_with_model(tc_norm_ctx, session_id: str, model: str):
    """Continue dangling history after selecting a different provider model."""
    tc_norm_ctx.continue_with_model(session_id, "continue after model switch", model)


@when(parsers.parse('the tool-calls normalization session "{session_id}" is recovered and continues'))
def when_tc_norm_recover_session(tc_norm_ctx, session_id: str):
    """Reload persisted dangling history before issuing a real provider request."""
    tc_norm_ctx.recover_session(session_id, "continue after session recovery")


@then("the mixed native response executes its tool before the final answer can end the turn")
def then_tc_norm_mixed_response_executes_tool(tc_norm_ctx):
    """Prove the mixed response caused a follow-up request carrying its tool output."""
    state = tc_norm_ctx.state()
    assert len(state["request_bodies"]) == 2, state
    follow_up = state["request_bodies"][1]["body"]["messages"]
    assert any(message.get("tool_calls") for message in follow_up), follow_up
    assert any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == "call_bdd_runtime_1"
        for message in follow_up
    ), follow_up


@then("the dangling human decision reaches the provider as thought instead of a native tool call")
def then_tc_norm_dangling_human_is_thought(tc_norm_ctx):
    """Assert the call remains readable but cannot violate provider pairing."""
    assert tc_norm_ctx.dangling_call_id
    messages = tc_norm_ctx.state()["request_bodies"][-1]["body"]["messages"]
    matching = [
        message
        for message in messages
        if tc_norm_ctx.dangling_call_id in str(message.get("content"))
    ]
    assert len(matching) == 1, messages
    content = matching[0]["content"]
    assert "topsailai.thought" in content
    assert "human_tool-ask_decision" in content
    assert "tool_calls" not in matching[0]
    assert not any(
        tc_norm_ctx.dangling_call_id in str(message.get("tool_calls"))
        for message in messages
    ), messages


@then(parsers.parse('the selected tool-calls normalization model "{model}" reached the provider'))
def then_tc_norm_selected_model_received(tc_norm_ctx, model: str):
    """Assert the switched model name crossed the real HTTP request boundary."""
    body = tc_norm_ctx.state()["request_bodies"][-1]["body"]
    assert body["model"] == model, body
