"""Real HTTP/SSE attempt lifecycle acceptance. Author: DawsonLin."""

import json
import re
import threading
import time
import urllib.request
from types import SimpleNamespace

import pytest
from pytest_bdd import given, when, then, parsers, scenarios

import topsailai.ai_base.llm_base as llm
import topsailai.hooks as hooks
from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.llm_pool.openai_client_pool import OpenAIClientConfig

scenarios("features/llm_chat_attempt_lifecycle.feature")


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    """Own the mock listener, plugins, pooled client leases and teardown."""
    case = SimpleNamespace(root=tmp_path, model=None, server=None, thread=None)
    monkeypatch.setattr(hooks, "_point_configuration", ())
    yield case
    if case.model is not None:
        case.model.release_all_llm_models()
    if case.server is not None:
        case.server.shutdown()
        case.server.server_close()
        case.thread.join(5)
        assert not case.thread.is_alive()


@given(parsers.parse("a real {transport} provider and {behavior} observation Modules"))
def setup(lifecycle, monkeypatch, transport, behavior):
    """Point production clients solely at loopback and install real file Modules."""
    case = lifecycle
    case.stream = transport != "HTTP"
    case.retry = transport == "retry"
    case.server = create_server(MockServerConfig(
        port=0, reply="wire-success", stream_chunks=("wire-", "success"),
        stream_http_error_responses=((503, "temporary"),) if case.retry else None))
    case.thread = threading.Thread(target=case.server.serve_forever, daemon=True)
    case.thread.start()
    host, port = case.server.server_address
    values = {"OPENAI_API_BASE": f"http://{host}:{port}/v1",
              "OPENAI_BASE_URL": f"http://{host}:{port}/v1",
              "OPENAI_API_KEY": "credential-sentinel", "OPENAI_MODEL": "mock-attempt",
              "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
              "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0", "DEBUG": "0"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    case.sleeps = []
    monkeypatch.setattr(llm, "time", SimpleNamespace(monotonic=time.monotonic, sleep=case.sleeps.append))
    case.journal = case.root / "observations.jsonl"
    plugin = case.root / "observer.py"
    plugin.write_text(
        "import json\nfrom pathlib import Path\ndef main(**payload):\n"
        f"    with Path({str(case.journal)!r}).open('a') as output:\n"
        "        output.write(json.dumps(payload) + '\\n')\n" +
        ("    raise TypeError('observer retry-shaped failure')\n" if behavior == "failing" else ""))
    hooks.initialize_hook_points({f"hook__aibase__{phase}__llm_chat_attempt":
                                 {"modules": str(plugin)} for phase in ("before", "after", "error")})
    original_options = OpenAIClientConfig.constructor_kwargs

    def sdk_options(config):
        """Expose outer chat retries without SDK-internal request retries."""
        return {**original_options(config), "max_retries": 0}

    monkeypatch.setattr(OpenAIClientConfig, "constructor_kwargs", sdk_options)
    case.model = llm.LLMModel()
    assert case.model.model._client.max_retries == 0
    case.messages = [{"role": "user", "content": "private-prompt-sentinel"}]


@when(parsers.parse("chat completes in {mode} mode"))
def run_chat(lifecycle, mode):
    """Run the actual SDK creation, stream consumption, validation and formatting."""
    case = lifecycle
    case.mode = mode
    case.result = case.model.chat(case.messages, for_stream=case.stream,
                                  for_raw=mode == "raw", for_response=mode == "response_and_parsed")
    assert case.model.chat_model._client.max_retries == 0
    case.events = [json.loads(line) for line in case.journal.read_text().splitlines()]
    host, port = case.server.server_address
    with urllib.request.urlopen(f"http://{host}:{port}/debug/state", timeout=5) as response:
        case.state = json.load(response)


def check_wire(case, count):
    """Assert exact request cardinality/body and payload privacy at the wire seam."""
    assert case.state["total_requests"] == count
    bodies = [record["body"] for record in case.state["request_bodies"]]
    assert len(bodies) == count
    for body in bodies:
        assert body["messages"] == [{"role": "system", "content": ""}, *case.messages]
        assert body["stream"] is case.stream
        assert body["model"] == "mock-attempt"
    assert all(body == bodies[0] for body in bodies)
    encoded = json.dumps(case.events)
    for secret in ("private-prompt-sentinel", "credential-sentinel", "wire-success", "loop_attempts"):
        assert secret not in encoded
    assert len({event["operation_id"] for event in case.events}) == 1
    assert re.fullmatch("[0-9a-f]{32}", case.events[0]["operation_id"])
    common = {"schema_version", "operation_id", "attempt_number", "point_name", "outcome", "stream", "return_mode"}
    for event in case.events:
        expected = common | ({"duration_sec"} if event["outcome"] != "before" else set())
        expected |= {"error_category"} if event["outcome"] == "error" else set()
        assert set(event) == expected
        assert event["return_mode"] == case.mode and event["stream"] is case.stream
    if case.mode == "raw":
        assert case.result == "wire-success"
    elif case.mode == "response_and_parsed":
        assert case.result[0] is not None and case.result[1]
    else:
        assert case.result


@then("one successful attempt and one exact provider request are observed")
def success(lifecycle):
    """No retry occurs even with broken observation Modules."""
    check_wire(lifecycle, 1)
    assert [event["outcome"] for event in lifecycle.events] == ["before", "success"]
    assert [event["attempt_number"] for event in lifecycle.events] == [1, 1]
    assert lifecycle.sleeps == []


@then("two numbered attempts have exclusive error and success terminals")
def retry(lifecycle):
    """The original 503 retry remains one failure then one complete SSE success."""
    check_wire(lifecycle, 2)
    assert [event["outcome"] for event in lifecycle.events] == ["before", "error", "before", "success"]
    assert [event["attempt_number"] for event in lifecycle.events] == [1, 1, 2, 2]
    assert lifecycle.events[1]["error_category"] == "LLMProviderInternalServerError"
    assert lifecycle.sleeps == [5]
