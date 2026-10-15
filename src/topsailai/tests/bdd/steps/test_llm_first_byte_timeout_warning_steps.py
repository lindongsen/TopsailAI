"""Steps for warning-only first-byte continuity acceptance."""

from pytest_bdd import given, then, when

from tests.bdd.llm_first_byte_warning_observation import WarningObservation
from tests.bdd.llm_first_byte_deadline_harness import (
    production_deadline_scenario,
    request_bodies,
    server_config,
)

_CONTEXTS = {}


def _cleanup_context(nodeid, context):
    """Close one scenario and always release its retained context reference."""
    try:
        context.__exit__(None, None, None)
    finally:
        _CONTEXTS.pop(nodeid, None)


def _run(request, **config):
    """Run one warning-only real HTTP/SSE scenario."""
    cumulative_check = config.pop("cumulative_check", False)
    observation = WarningObservation()
    context = production_deadline_scenario(
        request.getfixturevalue("monkeypatch"),
        stream=True, timeout=config.pop("timeout", 0.2),
        raise_on_timeout=False, server_config=server_config(stream=True, **config),
        observation=observation,
    )
    data = context.__enter__()
    data["cumulative_check"] = cumulative_check
    _CONTEXTS[request.node.nodeid] = {"context": context, **data}

    def cleanup():
        """Always release the scenario context and remove its global reference."""
        _cleanup_context(request.node.nodeid, context)

    request.addfinalizer(cleanup)


def _data(request):
    """Return the scenario evidence."""
    return _CONTEXTS[request.node.nodeid]


@given("a production U4 server with warning-only delayed streaming headers")
def delayed_headers(request):
    """Delay response headers beyond the shared first-byte budget."""
    _run(request, timeout=0.1, header_delay=0.2, replies=("full ", "answer"),
         after_first_delay=0.01)


@given("a production U4 server with warning-only delayed first entry")
def delayed_first(request):
    """Delay the first decoded entry beyond the shared first-byte budget."""
    _run(request, timeout=0.1, first_delay=0.2, replies=("full ", "answer"),
         after_first_delay=0.01)


@given("a production U4 server with warning-only cumulative delay")
def cumulative(request):
    """Cross the budget through independent header and first-entry delays."""
    _run(request, timeout=1.0, header_delay=0.6, first_delay=0.6,
         replies=("full ", "answer"), after_first_delay=0.01,
         cumulative_check=True)


@given("a production U4 server with warning-only cross-phase delay")
def cross_phase(request):
    """Warn during late creation, then delay first entry under the same budget."""
    _run(request, timeout=1.0, header_delay=1.2, first_delay=0.4,
         replies=("full ", "answer"), after_first_delay=0.01)


@given("a production U4 server with warning-only provider error then recovery")
def provider_error(request):
    """Delay the first attempt, return a real SSE error, then recover."""
    _run(request, timeout=1.0, first_delay=1.2, replies=("recovered ", "answer"),
         after_first_delay=0.01, stream_errors=("u4 genuine provider failure", None))




@given("a production U4 server with warning-only on-time streaming")
def on_time(request):
    """Provide an on-time multi-entry control response."""
    _run(request, timeout=0.2, replies=("full ", "answer"), after_first_delay=0.01)


@when("the U4 streaming completion is consumed")
def consume(request):
    """Ensure the production response was consumed before assertions."""
    assert _data(request)["model"] is not None


@then("the U4 original stream is complete with one request and one warning")
def warning_result(request):
    """Assert exact original response and wire request evidence."""
    data = _data(request)
    assert data["result"] == "full answer"
    assert request_bodies(data["server"]) == [data["expected_body"]]
    assert len(data["owners"]) == 1
    assert len(data["warnings"]) == 1
    checkpoints = data["observation"].events_for("warning_checkpoint")
    assert checkpoints and checkpoints[0]["close_count"] == 0
    assert all(state is False for state in checkpoints[0]["owner_states"])
    phases = data["observation"].phase_events()
    assert [phase["label"] for phase in phases] == ["create", "first_item"]
    if data["cumulative_check"]:
        assert phases[0]["published_at"] < phases[0]["deadline"] <= phases[1]["published_at"]
        assert phases[0]["completed_at"] < phases[0]["deadline"]
        assert phases[0]["budget"] is phases[1]["budget"]
        assert phases[0]["deadline"] == phases[1]["deadline"]
        origin = phases[0]["deadline"] - phases[0]["timeout"]
        assert origin <= phases[0]["completed_at"] < phases[0]["deadline"]
        assert phases[0]["completed_at"] - origin < phases[0]["timeout"]
        assert phases[1]["published_at"] - phases[0]["published_at"] < phases[0]["timeout"]
    responses = data["observation"].events_for("response")
    closes = data["observation"].events_for("stream_close_after")
    extracts = data["observation"].events_for("extract")
    assert responses and closes and extracts
    assert responses[0]["raw"] is closes[0]["raw"]
    close_before = data["observation"].events_for("stream_close_before")
    assert len(closes) == len(close_before) == 1
    assert closes[0]["raw"] is close_before[0]["raw"]
    assert max(event["at"] for event in extracts) <= close_before[0]["at"]
    assert data["observation"].events_for("warning_checkpoint")[0]["close_count"] == 0


@then("the U4 original stream is complete with one request and no warning")
def control_result(request):
    """Assert the on-time control has no threshold warning and closes once."""
    data = _data(request)
    assert data["result"] == "full answer"
    assert request_bodies(data["server"]) == [data["expected_body"]]
    assert len(data["owners"]) == 1
    assert data["warnings"] == []
    phases = data["observation"].phase_events()
    assert [phase["label"] for phase in phases] == ["create", "first_item"]
    data["observation"].assert_settled(data["owners"])
    responses = data["observation"].events_for("response")
    close_before = data["observation"].events_for("stream_close_before")
    closes = data["observation"].events_for("stream_close_after")
    extracts = data["observation"].events_for("extract")
    assert len(responses) == len(close_before) == len(closes) == 1
    assert responses[0]["owner"] is close_before[0]["owner"] is closes[0]["owner"]
    assert responses[0]["raw"] is close_before[0]["raw"] is closes[0]["raw"]
    assert extracts
    assert max(event["at"] for event in extracts) <= close_before[0]["at"] <= closes[0]["at"]

@then("the U4 cross-phase stream has one shared warning")
def cross_phase_result(request):
    """Prove late creation and delayed first entry share one budget and warning."""
    data = _data(request)
    assert data["result"] == "full answer"
    assert request_bodies(data["server"]) == [data["expected_body"]]
    assert len(data["warnings"]) == 1
    phases = data["observation"].phase_events()
    assert [phase["label"] for phase in phases] == ["create", "first_item"]
    assert phases[0]["budget"] is phases[1]["budget"]
    assert phases[0]["budget_id"] == phases[1]["budget_id"]
    assert phases[0]["deadline"] == phases[1]["deadline"]
    assert phases[0]["published_at"] >= phases[0]["deadline"]
    assert data["warning_events"]
    assert data["warning_events"][0][1] <= phases[0]["published_at"]
    assert phases[0]["published_at"] < phases[1]["published_at"]
    assert phases[0]["published_at"] - phases[0]["completed_at"] < phases[0]["timeout"]
    assert phases[1]["published_at"] - phases[0]["published_at"] < phases[0]["timeout"]
    assert phases[0]["abandoned_before"] is False
    assert phases[1]["abandoned_before"] is False
    data["observation"].assert_settled(data["owners"])
    responses = data["observation"].events_for("response")
    closes = data["observation"].events_for("stream_close_after")
    assert responses and closes
    assert responses[0]["raw"] is closes[0]["raw"]
    assert len(closes) == len({id(item["raw"]) for item in closes}) == 1
    extracts = data["observation"].events_for("extract")
    close_before = data["observation"].events_for("stream_close_before")
    assert extracts and close_before
    assert max(event["at"] for event in extracts) <= min(event["at"] for event in close_before)


@then("the U4 recovered stream has two identical requests and one warning")
def provider_error_result(request):
    """Assert the provider error follows normal retry handling."""
    data = _data(request)
    assert data["result"] == "recovered answer"
    bodies = request_bodies(data["server"])
    assert len(bodies) == 2
    assert bodies[0] == data["expected_body"]
    assert bodies[1] == data["expected_body"]
    assert len(data["warnings"]) == 1
    assert len(data["owners"]) == 2
    data["observation"].assert_settled(data["owners"])
    errors = data["observation"].events_for("error")
    translations = data["observation"].events_for("translate")
    assert errors and translations
    assert errors[0]["error"] is not None
    assert "timeout" not in type(errors[0]["error"]).__name__.lower()
    assert type(errors[0]["error"]).__name__ != "TypeError"
    import openai

    assert isinstance(errors[0]["error"], openai.APIError)
    matching = [event for event in translations
                if event["translated"] is errors[0]["error"]]
    assert matching and matching[0]["original"] is errors[0]["error"]
    assert matching[0]["at"] <= errors[0]["at"]
    assert data["warning_events"][0][1] <= translations[0]["at"]
    assert "u4 genuine provider failure" in str(errors[0]["error"])
    closes = data["observation"].events_for("stream_close_after")
    close_before = data["observation"].events_for("stream_close_before")
    assert len(closes) == len(close_before) == 2
    responses = data["observation"].events_for("response")
    assert len(responses) == len(closes) == len(data["owners"])
    response_pairs = {(event["owner"], event["raw"]) for event in responses}
    close_pairs = {(event["owner"], event["raw"]) for event in closes}
    assert response_pairs == close_pairs
    assert all(sum(event["raw"] is close["raw"] for close in close_before) == 1
               for event in responses)
    error_owner = errors[0]["owner"]
    assert error_owner is data["owners"][0]
    owner_tickets = dict(data["timing_tickets"])
    assert owner_tickets[error_owner] is not owner_tickets[data["owners"][1]]
    extracts = data["observation"].events_for("extract")
    recovered = [event["content"] for event in extracts if event["content"]]
    assert recovered[-2:] == ["recovered ", "answer"]
    assert errors[0]["at"] < close_before[0]["at"]
    recovery_extracts = [event for event in extracts
                         if event["content"] in {"recovered ", "answer"}]
    assert max(event["at"] for event in recovery_extracts) <= min(
        event["at"] for event in close_before
        if event["owner"] is data["owners"][1]
    )
