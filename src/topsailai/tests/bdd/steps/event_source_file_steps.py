"""Acceptance steps that assert on the real on-disk events file.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-13
Purpose: Verify the production file backend records every real event source
"""

import json

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.event_source_file_extended_harness import ExtendedEventSourceHarness
from tests.bdd.event_source_file_harness import EventSourceFileHarness


@pytest.fixture
def events_file_state(bdd_tmp_path, monkeypatch):
    """Own one harness, its events file, and its mock provider."""
    harness = EventSourceFileHarness(monkeypatch, bdd_tmp_path)
    try:
        yield harness
    finally:
        harness.close()


@given("an events file owned by this scenario", target_fixture="events_file_state")
def events_file_owned(events_file_state):
    """Use the default enabled harness."""
    return events_file_state


@given(
    "an events file owned by this scenario with events disabled",
    target_fixture="events_file_state",
)
def events_file_disabled(bdd_tmp_path, monkeypatch):
    """Use a harness whose event recording is switched off."""
    harness = EventSourceFileHarness(monkeypatch, bdd_tmp_path, enabled=False)
    try:
        yield harness
    finally:
        harness.close()


@when("a real LLM request completes successfully")
def real_llm_request(events_file_state):
    """Drive the real OpenAI-compatible client against the mock provider."""
    events_file_state.send_llm_request()


@when(parsers.parse('a real LLM request is stopped by "{exception_type}"'))
def real_llm_request_interrupted(events_file_state, exception_type):
    """Drive the real chat lifecycle until its interrupt checkpoint raises."""
    events_file_state.interrupt_llm_request(exception_type)


@when("a real tool call executes successfully")
def real_tool_call(events_file_state):
    """Drive the real decorated tool entry point."""
    events_file_state.execute_tool()


@when("a real approval request is approved by the human")
def real_approval(events_file_state):
    """Drive the real approval ASK branch and approve it from another thread."""
    events_file_state.approve_tool()


@then(parsers.parse('the events file holds exactly one "{event_type}" record'))
def exactly_one_record(events_file_state, event_type):
    """Assert the file holds exactly one record of the requested type."""
    records = events_file_state.of_type(event_type)
    assert len(records) == 1, [
        (record["event_type"], record["payload"]) for record in events_file_state.events()
    ]


@then("both LLM request records share one operation id")
def llm_operation_ids_match(events_file_state):
    """Assert the start and end records belong to the same logical request."""
    start = events_file_state.of_type("llm.request.start")[0]["payload"]
    end = events_file_state.of_type("llm.request.end")[0]["payload"]
    assert start["operation_id"] == end["operation_id"]
    assert start["operation_id"]


@then(parsers.parse('the LLM request end record reports outcome "{outcome}"'))
def llm_end_outcome(events_file_state, outcome):
    """Assert the terminal outcome category written to disk."""
    end = events_file_state.of_type("llm.request.end")[0]["payload"]
    assert end["outcome"] == outcome, end


@then(parsers.parse('the LLM request end record reports error category "{category}"'))
def llm_end_error_category(events_file_state, category):
    """Assert the terminal record names the exception that ended the request."""
    end = events_file_state.of_type("llm.request.end")[0]["payload"]
    assert end["error_category"] == category, end


@then("the LLM request end record reports zero attempts")
def llm_end_zero_attempts(events_file_state):
    """Assert no provider request was sent before the interrupt fired."""
    end = events_file_state.of_type("llm.request.end")[0]["payload"]
    assert end["attempt_count"] == 0, end


@then("the tool call end record reports success")
def tool_call_success(events_file_state):
    """Assert the tool result was recorded as a success."""
    end = events_file_state.of_type("tool_call.end")[0]["payload"]
    assert end["success"] is True, end
    assert end["tool_name"] == "bdd_tool", end


@then("both approval records share one instance id")
def approval_instance_ids_match(events_file_state):
    """Assert the request and decision records can be paired."""
    request = events_file_state.of_type("tool_approval.request")[0]["payload"]
    decision = events_file_state.of_type("tool_approval.decision")[0]["payload"]
    assert request["instance_id"] == decision["instance_id"]
    assert request["instance_id"] == events_file_state.approval_instance_id


@then(parsers.parse('the approval decision record reports status "{status}"'))
def approval_decision_status(events_file_state, status):
    """Assert the recorded decision is the human's real answer."""
    decision = events_file_state.of_type("tool_approval.decision")[0]["payload"]
    assert decision["status"] == status, decision


@then("no LLM request record contains the prompt text")
def llm_records_exclude_prompt(events_file_state):
    """Assert prompt text never reaches the operational event file."""
    records = [
        record
        for record in events_file_state.events()
        if record["event_type"].startswith("llm.request.")
    ]
    assert records
    for record in records:
        assert events_file_state.prompt_text not in json.dumps(record, ensure_ascii=False)


@then("no approval record contains the tool argument")
def approval_records_exclude_arguments(events_file_state):
    """Assert tool arguments never reach the approval event records."""
    records = [
        record
        for record in events_file_state.events()
        if record["event_type"].startswith("tool_approval.")
    ]
    assert records
    for record in records:
        assert events_file_state.tool_argument not in json.dumps(record, ensure_ascii=False)


@then("no events file was written")
def no_events_file(events_file_state):
    """Assert a disabled collector writes nothing to disk."""
    events_file_state.flush()
    assert not events_file_state.events_path.exists()


@given(
    "an events file owned by this scenario with raw response events enabled",
    target_fixture="events_file_state",
)
def events_file_raw_enabled(bdd_tmp_path, monkeypatch):
    """Use a harness that records raw LLM response events."""
    harness = ExtendedEventSourceHarness(
        monkeypatch, bdd_tmp_path, response_events_enabled=True
    )
    try:
        yield harness
    finally:
        harness.close()


@given(
    "an events file owned by this scenario with a repeated tool-call warning rule",
    target_fixture="events_file_state",
)
def events_file_tool_warning(bdd_tmp_path, monkeypatch):
    """Use a harness with one rule that warns after the first repeat."""
    rules = json.dumps(
        [
            {
                "tool_call": "bdd_tool",
                "max_calls": 1,
                "window_seconds": 60,
                "warning": "repeated {tool_call} count={count}",
            }
        ]
    )
    harness = ExtendedEventSourceHarness(
        monkeypatch, bdd_tmp_path, tool_warning_rules=rules
    )
    try:
        yield harness
    finally:
        harness.close()


@given(
    "an events file owned by this scenario with thought line-pattern detection enabled",
    target_fixture="events_file_state",
)
def events_file_thought_pattern(bdd_tmp_path, monkeypatch):
    """Use a harness with one enabled thought line-pattern rule."""
    rules = json.dumps(
        [
            {
                "pattern": "TODO",
                "line_ratio": 0.5,
                "min_lines": 2,
                "warning": "abnormal thought lines",
            }
        ]
    )
    harness = ExtendedEventSourceHarness(
        monkeypatch,
        bdd_tmp_path,
        thought_pattern_enabled=True,
        thought_pattern_rules=rules,
    )
    try:
        yield harness
    finally:
        harness.close()


@when("the same real tool call executes twice")
def real_tool_call_twice(events_file_state):
    """Drive the real decorated tool entry point twice under one agent."""
    events_file_state.execute_tool_repeatedly(2)


@when("a real thought evaluation matches the configured pattern")
def real_thought_evaluation(events_file_state):
    """Drive the real thought line-pattern evaluation."""
    events_file_state.evaluate_thought("TODO one\nTODO two\nTODO three")


@then("the raw response record reports the reply content")
def raw_response_content(events_file_state):
    """Assert the recorded response carries the provider reply text."""
    record = events_file_state.of_type("llm.response.raw")[0]["payload"]
    assert record["content"] == "bdd reply", record
    assert record["model"] == "bdd-event-model", record


@then("the raw response record omits the raw provider object")
def raw_response_omits_raw(events_file_state):
    """Assert the raw provider object is excluded when the switch is off."""
    record = events_file_state.of_type("llm.response.raw")[0]["payload"]
    assert "raw_response" not in record, record


@then("the tool-call warning record reports the tool name and count")
def tool_warning_fields(events_file_state):
    """Assert the warning names the tool and the observed call count."""
    record = events_file_state.of_type("tool_call.warning")[0]["payload"]
    assert record["tool_call"] == "bdd_tool", record
    assert record["count"] == 2, record
    assert record["max_calls"] == 1, record


@then("the thought warning record reports the matched pattern")
def thought_warning_fields(events_file_state):
    """Assert the warning names the pattern that fired."""
    record = events_file_state.of_type("thought.line_pattern.warning")[0]["payload"]
    assert record["patterns"] == ["TODO"], record
    assert record["step_type"] == "thought", record
    assert record["hit_count"] == 1, record
