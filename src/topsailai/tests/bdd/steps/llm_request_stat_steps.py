"""Unique BDD steps for execution-context LLM request statistics."""

import pytest
from pytest_bdd import given, then, when

from tests.bdd.llm_request_stat_harness import LLMRequestStatScenario


@pytest.fixture
def llm_request_stat_ctx(monkeypatch):
    """Yield one isolated real-HTTP request-statistics scenario."""
    context = LLMRequestStatScenario(monkeypatch)
    yield context
    context.close()


@given("an LLM request statistics environment with a private mock LLM server")
def given_llm_request_stat_environment(llm_request_stat_ctx):
    """Provide a running private provider and real OpenAI-compatible client."""
    assert llm_request_stat_ctx.server_thread.is_alive()


@when("one non-streaming LLM request is sent through the real client")
def when_llm_request_stat_request_sent(llm_request_stat_ctx):
    """Issue one real HTTP request through ``LLMModel``."""
    llm_request_stat_ctx.send_request()


@then("the LLM request statistics mock server received exactly 1 completion request")
def then_llm_request_stat_server_count(llm_request_stat_ctx):
    """Assert the provider observed exactly one completion request."""
    state = llm_request_stat_ctx.state()
    assert state["total_requests"] == 1, state
    assert len(state["request_bodies"]) == 1, state


@then("the LLM request statistics request body contains the user message")
def then_llm_request_stat_body_contains_message(llm_request_stat_ctx):
    """Assert the real request body crossed the HTTP boundary."""
    state = llm_request_stat_ctx.state()
    messages = state["request_bodies"][0]["body"]["messages"]
    assert {"role": "user", "content": "count this real request"} in messages


@then("the execution-context LLM total and RPM each increased by 1")
def then_llm_request_stat_snapshot_increased(llm_request_stat_ctx):
    """Assert both execution-context counters include the server-observed attempt."""
    before = llm_request_stat_ctx.before
    after = llm_request_stat_ctx.after
    assert after is not None
    assert after["total_requests"] == before["total_requests"] + 1
    assert after["requests_per_minute"] == before["requests_per_minute"] + 1


@then("one full-response duration sample has complete aggregate metrics")
def then_llm_request_duration_snapshot_is_complete(llm_request_stat_ctx):
    """Assert one completed request produces all full-response duration fields."""
    after = llm_request_stat_ctx.after
    assert after is not None
    assert after["request_duration_count"] == 1
    duration_fields = (
        "request_duration_min_sec",
        "request_duration_avg_sec",
        "request_duration_max_sec",
        "request_duration_p95_sec",
    )
    values = [after[field] for field in duration_fields]
    assert all(value is not None and value >= 0 for value in values)
    assert len(set(values)) == 1


@then(
    "each Thinking log has exactly one complete LLM request statistics output "
    "immediately before it"
)
def then_llm_request_stat_output_precedes_thinking(llm_request_stat_ctx):
    """Assert exactly one complete snapshot immediately precedes each Thinking log."""
    outputs = llm_request_stat_ctx.visible_output
    stat_indexes = [
        index
        for index, output in enumerate(outputs)
        if output.startswith("[LLMRequestStat]")
    ]
    thinking_indexes = [
        index for index, output in enumerate(outputs) if output == "Thinking..."
    ]
    assert len(stat_indexes) == len(thinking_indexes), outputs
    assert thinking_indexes, outputs
    assert stat_indexes == [index - 1 for index in thinking_indexes], outputs
    for index in stat_indexes:
        for field in (
            "total_requests",
            "requests_per_minute",
            "request_successes",
            "request_failures",
            "response_content_errors",
            "request_duration_count",
            "request_duration_min_sec",
            "request_duration_avg_sec",
            "request_duration_max_sec",
            "request_duration_p95_sec",
        ):
            assert field in outputs[index]


@when("one invalid non-streaming LLM response is received through the real client")
def when_invalid_llm_request_stat_response(llm_request_stat_ctx):
    """Issue one real request that receives invalid response content."""
    llm_request_stat_ctx.send_invalid_request()


@when("one unknown native tool call is received through the real client")
def when_unknown_native_tool_request_stat_call(llm_request_stat_ctx):
    """Issue a real native-tool request with an unknown tool response."""
    llm_request_stat_ctx.send_unknown_native_tool()


@then("the execution-context LLM total and failures each increased by 1")
def then_llm_request_stat_failure_increased(llm_request_stat_ctx):
    """Assert the invalid response counted as one failed request."""
    before = llm_request_stat_ctx.before
    after = llm_request_stat_ctx.after
    assert after is not None
    assert after["total_requests"] == before["total_requests"] + 1
    assert after["request_failures"] == before["request_failures"] + 1


@then("the execution-context LLM successes and content errors did not increase")
def then_llm_request_stat_failure_other_outcomes_unchanged(llm_request_stat_ctx):
    """Assert invalid response handling does not create other outcomes."""
    before = llm_request_stat_ctx.before
    after = llm_request_stat_ctx.after
    assert after is not None
    assert after["request_successes"] == before["request_successes"]
    assert after["response_content_errors"] == before["response_content_errors"]


@then("the LLM request statistics mock server received exactly 2 completion requests")
def then_llm_request_stat_server_count_two(llm_request_stat_ctx):
    """Assert the native tool loop crossed the provider boundary twice."""
    state = llm_request_stat_ctx.state()
    assert state["total_requests"] == 2, state
    assert len(state["request_bodies"]) == 2, state


@then("the execution-context LLM total and successes each increased by 2")
def then_llm_request_stat_two_successes(llm_request_stat_ctx):
    """Assert both provider responses in the tool loop succeeded."""
    before = llm_request_stat_ctx.before
    after = llm_request_stat_ctx.after
    assert after is not None
    assert after["total_requests"] == before["total_requests"] + 2
    assert after["request_successes"] == before["request_successes"] + 2


@then("the execution-context LLM failures did not increase")
def then_llm_request_stat_two_successes_failures_unchanged(llm_request_stat_ctx):
    """Assert unknown-tool content errors are not request failures."""
    before = llm_request_stat_ctx.before
    after = llm_request_stat_ctx.after
    assert after is not None
    assert after["request_failures"] == before["request_failures"]


@then("the execution-context LLM content errors increased by 1")
def then_llm_request_stat_content_error_increased(llm_request_stat_ctx):
    """Assert the unknown tool produced one independent content error."""
    before = llm_request_stat_ctx.before
    after = llm_request_stat_ctx.after
    assert after is not None
    assert after["response_content_errors"] == before["response_content_errors"] + 1
