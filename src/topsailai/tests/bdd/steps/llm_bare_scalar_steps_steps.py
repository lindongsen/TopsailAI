"""Real HTTP/SSE acceptance for a JSON array of bare scalar steps.

Author: DawsonLin

The incident this suite guards: a model answered with
``["fix: wait for the channel before the first inventory publish"]`` and the
whole User2Agent turn died with ``AttributeError: 'str' object has no attribute
'get'``. The scenario drives the real mock provider over HTTP/SSE so the client,
transport and parsing layers all stay inside the assertion boundary.
"""

import json
import threading
import urllib.request

import pytest
from pytest_bdd import given, parsers, then, when

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.llm_base import LLMModel


BARE_TEXT = "fix: wait for the channel before the first inventory publish"
BARE_PAYLOAD = json.dumps([BARE_TEXT])
TOOLS = [{"type": "function", "function": {
    "name": "bare_step_probe",
    "description": "Describe a bare-scalar step without executing commands",
    "parameters": {"type": "object", "properties": {}},
}}]


@pytest.fixture
def bare_scalar_ctx(monkeypatch):
    """Own one loopback provider, client and exact server thread per scenario."""
    server = create_server(MockServerConfig(
        port=0, stream_chunks=(BARE_PAYLOAD,), request_body_capacity=2,
    ))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    model = None
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}/v1"
        values = {
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "mock",
            "OPENAI_MODEL": "bare-scalar-mock",
            "TOPSAILAI_MODEL_SETTINGS": "",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        model = LLMModel()
        yield {"server": server, "model": model}
    finally:
        try:
            if model is not None:
                model.close()
        finally:
            server.shutdown()
            try:
                server.stop_handlers(timeout=5)
            finally:
                server.server_close()
                thread.join(timeout=5)
                assert not thread.is_alive(), "bare-scalar provider thread leaked"


@given(parsers.parse(
    'a provider that streams a bare-scalar step array in "{mode}" tool mode'
))
def given_bare_scalar_provider(bare_scalar_ctx, monkeypatch, mode):
    """Seed the incident payload and enable the production step-formatting path."""
    assert mode in {"native", "non-native"}
    monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS", "1" if mode == "native" else "0")
    bare_scalar_ctx["tools"] = TOOLS if mode == "native" else None
    bare_scalar_ctx["messages"] = [
        {"role": "system", "content": "Continue the task using topsailai.final_answer"},
        {"role": "user", "content": "Report the pending fix"},
    ]


@when("the conversation requests a streamed continuation")
def when_request_continuation(bare_scalar_ctx):
    """Send the real request without replacing request building or formatting."""
    bare_scalar_ctx["steps"] = bare_scalar_ctx["model"].chat(
        bare_scalar_ctx["messages"],
        for_stream=True,
        tools=bare_scalar_ctx["tools"],
    )


@then("the parsed steps are all objects with a thought step name")
def then_steps_are_thought_objects(bare_scalar_ctx):
    """Require the invariant that no consumer ever receives a non-object step."""
    steps = bare_scalar_ctx["steps"]
    assert isinstance(steps, list), steps
    assert steps, "the provider reply produced no steps"
    assert all(isinstance(step, dict) for step in steps), steps
    assert steps[0]["step_name"] == "thought", steps[0]


@then("the model text is preserved in the thought step")
def then_model_text_preserved(bare_scalar_ctx):
    """Require the model's text to survive instead of being discarded."""
    steps = bare_scalar_ctx["steps"]
    assert steps[0]["raw_text"] == BARE_TEXT, steps[0]


@then("the provider receives exactly one streamed request")
def then_provider_wire(bare_scalar_ctx):
    """Assert provider-side cardinality and streaming mode."""
    server = bare_scalar_ctx["server"]
    with urllib.request.urlopen(
        f"http://127.0.0.1:{server.server_port}/debug/state", timeout=3,
    ) as response:
        state = json.load(response)
    assert state["total_requests"] == 1, state
    assert len(state["request_bodies"]) == 1, state
    body = state["request_bodies"][0]["body"]
    assert body["stream"] is True
    assert body["model"] == "bare-scalar-mock"
    assert body["messages"] == bare_scalar_ctx["messages"]
