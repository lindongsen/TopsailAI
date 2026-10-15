"""Production-boundary U3 first-byte deadline step definitions."""

import pytest
from pytest_bdd import given, then, when

from tests.bdd.llm_first_byte_deadline_harness import (
    production_deadline_scenario,
    request_bodies,
    server_config,
)

_CONTEXTS = {}


def _run(request, *, stream, timeout, raising, **config):
    """Execute one scenario through the production model and retain evidence."""
    context = production_deadline_scenario(
        request.getfixturevalue("monkeypatch"),
        stream=stream,
        timeout=timeout,
        raise_on_timeout=raising,
        server_config=server_config(stream=stream, **config),
    )
    data = context.__enter__()
    _CONTEXTS[request.node.nodeid] = {"context": context, **data}
    request.addfinalizer(lambda: context.__exit__(None, None, None))


def _data(request):
    """Return the current scenario evidence."""
    return _CONTEXTS[request.node.nodeid]


@given("a production U3 server with an empty first stream entry and delayed later content")
def empty_entry(request):
    """Run the mandatory empty decoded-entry case through LLMModel.chat."""
    _run(request, stream=True, timeout=0.1, raising=True,
         replies=("", "full answer"), after_first_delay=0.4)


@given("a production U3 server with a delayed first stream entry and a fresh retry result")
def delayed_stream(request):
    """Configure request one to exceed the first-entry deadline."""
    _run(request, stream=True, timeout=0.1, raising=True,
         replies=("stale", "fresh"), first_delay=0.4)


@given("a production U3 server with a delayed complete response and a fresh retry result")
def delayed_complete(request):
    """Configure a non-streaming request to exceed the complete-call deadline."""
    _run(request, stream=False, timeout=0.1, raising=True,
         replies=("stale", "fresh"), complete_delay=0.4)


@given("a production U3 server with a delayed original response")
def warning_response(request):
    """Configure warning-only continuation without retry."""
    _run(request, stream=False, timeout=0.1, raising=False,
         replies=("original",), complete_delay=0.4)


@given("a production U3 server with a delayed disabled response")
def disabled_response(request):
    """Disable the guard while retaining a delayed successful response."""
    _run(request, stream=False, timeout=0.0, raising=True,
         replies=("disabled",), complete_delay=0.2)


@given("a production U3 server with an on-time complete response")
def control_response(request):
    """Configure an ordinary on-time complete response."""
    _run(request, stream=False, timeout=0.5, raising=True, replies=("control",))


@given("a production U3 server with delayed streaming headers")
def delayed_headers(request):
    """Configure headers to arrive after the first-byte deadline."""
    _run(request, stream=True, timeout=0.1, raising=True, replies=("stale", "fresh"), header_delay=0.4)


@given("a production U3 server with cumulative delayed streaming content")
def cumulative_stream(request):
    """Configure warning-mode streaming whose creation and first-entry delays cross the deadline."""
    _run(request, stream=True, timeout=0.1, raising=False,
         header_delay=0.06, first_delay=0.06, replies=("full answer",))


@given("a production U3 server with raising cumulative delayed streaming content")
def raising_cumulative_delayed_stream(request):
    """Configure two individually-on-time delays whose sum exceeds the deadline."""
    _run(request, stream=True, timeout=0.1, raising=True,
         header_delay=0.06, first_delay=0.06, replies=("stale", "fresh"))


@given("a production U3 server with raising cumulative on-time streaming content")
def raising_cumulative_ontime_stream(request):
    """Configure cumulative creation and first-entry delays below the deadline."""
    _run(request, stream=True, timeout=0.1, raising=True,
         header_delay=0.03, first_delay=0.03, replies=("cumulative control",))


@given("a production U3 server with disabled streaming monitoring")
def disabled_stream(request):
    """Configure delayed streaming while disabling first-byte monitoring."""
    _run(request, stream=True, timeout=0.0, raising=True, after_first_delay=0.2)


@when("the production streaming completion is consumed")
def consume_stream(request):
    """Confirm that the production model was created and the stream was consumed."""
    assert _data(request)["model"] is not None


@when("the production complete completion is consumed")
def consume_complete(request):
    """Confirm that the production model was created and the response was consumed."""
    assert _data(request)["model"] is not None


@then("the empty entry is accepted and the complete streamed response is returned")
def empty_result(request):
    """Assert empty first entry caused neither retry nor truncation."""
    data = _data(request)
    assert data["result"] == "full answer"
    assert data["server"].config.stream_response_chunks == (("", "full answer"),)
    assert len(request_bodies(data["server"])) == 1
    assert data["warnings"] == []


@then("the second attempt result is returned and exactly two bodies are captured")
def retry_result(request):
    """Assert automatic retry and request-wire cardinality."""
    data = _data(request)
    assert data["result"] == "fresh"
    bodies = request_bodies(data["server"])
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert bodies[0] == data["expected_body"]
    assert bodies[1] == data["expected_body"]
    assert len(data["owners"]) == 2
    assert data["owners"][0] is not data["owners"][1]
    assert data["owners"][0]._abandoned is True
    assert data["owners"][1]._abandoned is False
    _assert_owner_ticket_isolation(data)

def _validate_owner_ticket_isolation(owners, tickets, snapshot, ledger):
    """Prove exact attribution from one synchronized, strict evidence snapshot."""
    assert len(tickets) == 2
    assert tickets[0][0] is owners[0]
    assert tickets[1][0] is owners[1]
    assert tickets[0][1] is not tickets[1][1]
    original_ticket = tickets[0][1]
    successor_ticket = tickets[1][1]
    ledger.validate(snapshot)
    events = [(record["operation"], record["initiator"], record["ticket"])
              for record in snapshot]
    callback_events = snapshot
    owner_set = set(owners)
    for operation, initiator, ticket in events:
        assert initiator in owner_set, (operation, initiator, ticket)
        expected = original_ticket if initiator is owners[0] else successor_ticket
        assert ticket is expected, (operation, initiator, ticket)
    for owner, ticket in tickets:
        owner_events = [event for event in events if event[1] is owner]
        assert owner_events
        assert "start" in {event[0] for event in owner_events}
    original_cleanup = [event for event in callback_events
                        if event["ticket"] is original_ticket
                        and event["operation"] == "finish"
                        and event["initiator"] is owners[0]
                        and event["abandoned_before"]
                        and event["expected_ticket"] is original_ticket]
    assert original_cleanup
    assert all(event["completed"] for event in original_cleanup)
    successor_finish = [event for event in callback_events
                        if event["ticket"] is successor_ticket
                        and event["operation"] == "finish"
                        and event["initiator"] is owners[1]]
    assert successor_finish
    assert any(event["completed"] for event in successor_finish)

def _assert_owner_ticket_isolation(data):
    """Wait, snapshot, strictly validate, then exercise recorder controls."""
    owners = data["owners"]
    tickets = data["timing_tickets"]
    cleanup_completed = data["cleanup_completed"]
    assert cleanup_completed[owners[0]].wait(5)
    snapshot = data["ledger"].snapshot()
    _validate_owner_ticket_isolation(owners, tickets, snapshot, data["ledger"])
    for event in snapshot:
        if event["raw_initiator"] is not None:
            assert event["raw_initiator"] is event["initiator"]

    from tests.bdd.llm_first_byte_deadline_harness import should_signal_timing_completion
    from tests.bdd.llm_first_byte_deadline_observation import ProvenanceLedger

    def delegate(ticket):
        """Return the target unchanged for harmless recorder controls."""
        return ticket

    class Owner:
        """Minimal abandoned owner used to make completion-gate controls sensitive."""

        def __init__(self, abandoned=False):
            self._abandoned = abandoned

    original_ticket = object()
    successor_ticket = object()

    negative = ProvenanceLedger()
    original_invocation = negative.begin()
    original_token = negative.bind(original_invocation)
    original_owner = Owner(abandoned=True)
    negative.register_owner(original_owner)
    negative.seal_ticket(original_ticket, original_owner)
    negative.reset(original_token)
    retained_token = negative.bind(original_invocation)
    negative.observe_callback("finish", delegate, successor_ticket, owner_override=None)
    negative.reset(retained_token)
    with pytest.raises(AssertionError):
        negative.validate()

    unattributed = ProvenanceLedger()
    unattributed.observe_callback("finish", delegate, successor_ticket, owner_override=None)
    with pytest.raises(AssertionError):
        unattributed.validate()

    wrong = ProvenanceLedger()
    wrong_invocation = wrong.begin()
    wrong_token = wrong.bind(wrong_invocation)
    wrong_owner = Owner(abandoned=True)
    wrong.register_owner(wrong_owner)
    wrong.seal_ticket(original_ticket, wrong_owner)
    wrong.observe_callback("finish", delegate, successor_ticket, owner_override=wrong_owner)
    with pytest.raises(AssertionError):
        wrong.validate()
    wrong_record = wrong.snapshot()[0]
    # The actual callback ticket differs from the expected ticket.
    assert not should_signal_timing_completion(wrong_record, original_ticket)
    # The gate target differs from the expected ticket even if it matches the callback.
    assert not should_signal_timing_completion(wrong_record, successor_ticket)
    wrong.reset(wrong_token)

    positive = ProvenanceLedger()
    positive_invocation = positive.begin()
    positive_token = positive.bind(positive_invocation)
    positive_owner = Owner(abandoned=True)
    positive.register_owner(positive_owner)
    positive.seal_ticket(original_ticket, positive_owner)
    positive.observe_callback("finish", delegate, original_ticket, owner_override=positive_owner)
    positive_record = positive.snapshot()[0]
    assert should_signal_timing_completion(positive_record, original_ticket)
    positive.reset(positive_token)

    conflicting = ProvenanceLedger()
    first = conflicting.begin()
    first_token = conflicting.bind(first)
    first_owner = Owner(abandoned=True)
    conflicting.register_owner(first_owner)
    conflicting.seal_ticket(original_ticket, first_owner)
    conflicting.reset(first_token)
    second = conflicting.begin()
    second_token = conflicting.bind(second)
    second_owner = Owner(abandoned=False)
    conflicting.register_owner(second_owner)
    conflicting.seal_ticket(successor_ticket, second_owner)
    conflicting.observe_callback("finish", delegate, successor_ticket, owner_override=first_owner)
    with pytest.raises(AssertionError):
        conflicting.validate()
    conflicting.reset(second_token)

    valid = ProvenanceLedger()
    valid_invocation = valid.begin()
    valid_token = valid.bind(valid_invocation)
    valid_owner = Owner(abandoned=True)
    valid.register_owner(valid_owner)
    valid.seal_ticket(original_ticket, valid_owner)
    valid.observe_callback("finish", delegate, original_ticket, owner_override=None)
    valid.validate()
    valid.reset(valid_token)

    pause_only = ProvenanceLedger()
    pause_invocation = pause_only.begin()
    pause_token = pause_only.bind(pause_invocation)
    pause_owner = Owner(abandoned=True)
    successor_owner = Owner(abandoned=False)
    pause_only.register_owner(pause_owner)
    pause_only.seal_ticket(original_ticket, pause_owner)
    pause_only.reset(pause_token)
    successor_token = pause_only.bind(pause_only.begin())
    pause_only.register_owner(successor_owner)
    pause_only.seal_ticket(successor_ticket, successor_owner)
    pause_only.reset(successor_token)
    pause_only.record_start(pause_owner, original_ticket)
    pause_only.record_start(successor_owner, successor_ticket)
    pause_only.observe_callback("pause", delegate, original_ticket, owner_override=pause_owner)
    pause_only.observe_callback("finish", delegate, successor_ticket, owner_override=successor_owner)
    pause_snapshot = pause_only.snapshot()
    pause_only.validate(pause_snapshot)
    with pytest.raises(AssertionError):
        _validate_owner_ticket_isolation(
            [pause_owner, successor_owner],
            [(pause_owner, original_ticket), (successor_owner, successor_ticket)],
            pause_snapshot,
            pause_only,
        )

    incomplete = ProvenanceLedger()
    incomplete_invocation = incomplete.begin()
    incomplete_token = incomplete.bind(incomplete_invocation)
    incomplete_owner = Owner(abandoned=True)
    incomplete.register_owner(incomplete_owner)
    incomplete.seal_ticket(original_ticket, incomplete_owner)

    def failing_delegate(ticket):
        """Raise without producing successful completion evidence."""
        raise RuntimeError("controlled callback failure")

    with pytest.raises(RuntimeError):
        incomplete.observe_callback("finish", failing_delegate, original_ticket,
                                    owner_override=incomplete_owner)
    with pytest.raises(AssertionError):
        incomplete.validate()
    incomplete.reset(incomplete_token)

@then("the warning-mode original result is returned with exactly one body")
def warning_result(request):
    """Assert warning mode continues the original request without retry."""
    data = _data(request)
    assert data["result"] == "original"
    assert len(request_bodies(data["server"])) == 1
    assert len(data["warnings"]) == 1


@then("the delayed stream continues with one warning and one body")
def warning_stream_result(request):
    """Assert streaming warning mode preserves all original content."""
    data = _data(request)
    assert data["result"] == "full answer"
    assert len(request_bodies(data["server"])) == 1
    assert len(data["warnings"]) == 1


@then("the delayed stream is returned without warnings and one body")
def disabled_stream_result(request):
    """Assert disabled streaming mode bypasses threshold handling."""
    data = _data(request)
    assert data["result"] == "full answer"
    assert len(request_bodies(data["server"])) == 1
    assert data["warnings"] == []


@then("the disabled result is returned with exactly one body")
def disabled_result(request):
    """Assert disabled mode preserves the unmonitored request."""
    data = _data(request)
    assert data["result"] == "disabled"
    bodies = request_bodies(data["server"])
    assert len(bodies) == 1
    assert bodies[0]["model"] == "u3-bdd-model"
    assert bodies[0]["messages"] == [{"role": "system", "content": ""}, {"role": "user", "content": "u3 production request"}]
    assert bodies[0]["stream"] is False
    assert data["warnings"] == []


@then("the control result is returned with exactly one body")
def control_result(request):
    """Assert an on-time request does not retry."""
    data = _data(request)
    assert data["result"] == "control"
    bodies = request_bodies(data["server"])
    assert len(bodies) == 1
    assert bodies[0]["model"] == "u3-bdd-model"
    assert bodies[0]["messages"] == [{"role": "system", "content": ""}, {"role": "user", "content": "u3 production request"}]
    assert bodies[0]["stream"] is False
    assert data["warnings"] == []

@then("the cumulative delayed stream retries with the fresh result")
def cumulative_raising_result(request):
    """Assert cumulative creation and first-entry delay triggers automatic retry."""
    data = _data(request)
    assert data["result"] == "fresh"
    bodies = request_bodies(data["server"])
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert bodies[0] == data["expected_body"]
    assert bodies[1] == data["expected_body"]
    assert len(data["owners"]) == 2
    assert data["owners"][0] is not data["owners"][1]
    assert data["owners"][0]._abandoned is True
    assert data["owners"][1]._abandoned is False
    _assert_owner_ticket_isolation(data)
    assert len(data["warnings"]) == 1


@then("the cumulative on-time stream completes without retry and without warnings")
def cumulative_raising_ontime_result(request):
    """Assert cumulative below-deadline control behavior."""
    data = _data(request)
    assert data["result"] == "cumulative control"
    assert len(request_bodies(data["server"])) == 1
    assert data["warnings"] == []
