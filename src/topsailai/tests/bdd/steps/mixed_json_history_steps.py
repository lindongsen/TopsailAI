"""Real HTTP/SSE acceptance for preserved mixed JSON conversation history.

Author: DawsonLin
"""

import json
import threading
import urllib.request

import pytest
from pytest_bdd import given, parsers, then, when

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.llm_base import LLMModel


HISTORY = json.dumps([{"cmd": "echo history-marker", "timeout": 120},
                      {"step_name": "action"}])
REPLY = "The conversation continued successfully"
TOOLS = [{"type": "function", "function": {
    "name": "history_probe", "description": "Describe history without executing commands",
    "parameters": {"type": "object", "properties": {}},
}}]


@pytest.fixture
def mixed_history_ctx(monkeypatch):
    """Own one loopback provider, client and exact server thread per scenario."""
    server = create_server(MockServerConfig(
        port=0, stream_chunks=(REPLY,), request_body_capacity=2,
    ))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    model = None
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}/v1"
        values = {
            "OPENAI_API_BASE": base_url, "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "mock", "OPENAI_MODEL": "mixed-history-mock",
            "TOPSAILAI_MODEL_SETTINGS": "", "TOPSAILAI_INTERACTIVE_MODE": "0",
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
                assert not thread.is_alive(), "mixed-history provider thread leaked"


@given(parsers.parse('a mixed JSON history conversation using "{mode}" tool mode'))
def given_mixed_history(mixed_history_ctx, monkeypatch, mode):
    """Seed the incident history and enable the production step-formatting path."""
    assert mode in {"native", "non-native"}
    monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS", "1" if mode == "native" else "0")
    mixed_history_ctx["tools"] = TOOLS if mode == "native" else None
    mixed_history_ctx["messages"] = [
        {"role": "system", "content": "Continue the task using topsailai.final_answer"},
        {"role": "user", "content": "Inspect the previous command"},
        {"role": "assistant", "content": HISTORY},
        {"role": "user", "content": "Continue without running the command"},
    ]


@when("the conversation requests a streamed continuation")
def when_continue_mixed_history(mixed_history_ctx):
    """Send the real request without replacing request building or formatting."""
    mixed_history_ctx["reply"] = mixed_history_ctx["model"].chat(
        mixed_history_ctx["messages"], for_raw=True, for_stream=True,
        tools=mixed_history_ctx["tools"],
    )


@then("the mixed JSON conversation receives the provider reply")
def then_mixed_history_reply(mixed_history_ctx):
    """Require the complete provider response, not merely absence of an error."""
    assert mixed_history_ctx["reply"] == REPLY


@then("the provider receives exactly one streamed request with the original history")
def then_mixed_history_wire(mixed_history_ctx):
    """Assert provider-side cardinality, mode and unchanged ordered history."""
    server = mixed_history_ctx["server"]
    with urllib.request.urlopen(
        f"http://127.0.0.1:{server.server_port}/debug/state", timeout=3,
    ) as response:
        state = json.load(response)
    assert state["total_requests"] == 1, state
    assert len(state["request_bodies"]) == 1, state
    body = state["request_bodies"][0]["body"]
    assert body["stream"] is True
    assert body["model"] == "mixed-history-mock"
    assert body["messages"] == mixed_history_ctx["messages"]
    assert body["messages"][2]["content"] == HISTORY
    if mixed_history_ctx["tools"]:
        assert body["tools"] == TOOLS
    else:
        assert "tools" not in body
