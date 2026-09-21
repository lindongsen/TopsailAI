"""Step definitions for JEV decision-tool behavior."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from topsailai.tools import jev_tool
from topsailai.utils.thread_local_tool import ctxm_set_agent


class _Handler(BaseHTTPRequestHandler):
    """Serve a minimal JEV-compatible loopback endpoint."""

    def do_POST(self):
        """Capture a request and return the scenario response."""
        length = int(self.headers.get("Content-Length", "0"))
        self.server.requests.append(json.loads(self.rfile.read(length)))
        body = self.server.response_body
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        """Suppress loopback server logs."""


@pytest.fixture
def jev_world(monkeypatch):
    """Provide an isolated loopback service and runtime context."""
    world = SimpleNamespace(server=None, thread=None, agent=None, result=None)
    yield world
    if world.server:
        world.server.shutdown()
        world.server.server_close()
    if world.thread:
        world.thread.join(timeout=2)


def _start(world, monkeypatch, response):
    """Start and configure the owned loopback service."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    server.response_body = response
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    world.server, world.thread = server, thread
    monkeypatch.setenv("TOPSAILAI_JEV_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("TOPSAILAI_JEV_API_KEY", "bdd-key")
    monkeypatch.setenv("TOPSAILAI_JEV_MAX_RETRIES", "0")


@given("a private JEV-compatible server and configured tool")
def configured_server(jev_world, monkeypatch):
    """Configure a valid loopback response."""
    _start(jev_world, monkeypatch, {"model": "jev-latest", "answers": {"refund": {"type": "noul", "noul": 0.87}}, "usage": {"input_tokens": 5, "output_tokens": 1}})


@given("a private JEV-compatible server without a configured API key")
def server_without_key(jev_world, monkeypatch):
    """Start a server but remove its credential configuration."""
    _start(jev_world, monkeypatch, {})
    monkeypatch.delenv("TOPSAILAI_JEV_API_KEY", raising=False)


@given("a private JEV-compatible server returning a mismatched answer")
def mismatched_server(jev_world, monkeypatch):
    """Configure a schema-incompatible answer."""
    _start(jev_world, monkeypatch, {"model": "jev-latest", "answers": {"other": {"type": "noul", "noul": 1}}, "usage": {}})


@given("Agent2LLM history containing system user assistant and completed tool messages")
def rich_history(jev_world):
    """Create history with one complete native tool interaction."""
    jev_world.agent = SimpleNamespace(messages=[
        {"role": "system", "content": "hidden"},
        {"role": "user", "content": "Please refund the duplicate charge"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "duplicate confirmed"},
        {"role": "assistant", "content": "I found a duplicate"},
    ])


@given("Agent2LLM history containing one user message")
def simple_history(jev_world):
    """Create minimal eligible runtime history."""
    jev_world.agent = SimpleNamespace(messages=[{"role": "user", "content": "refund"}])


@when("the agent evaluates a noul refund question")
def evaluate_refund(jev_world):
    """Invoke the public tool within a real thread-local agent scope."""
    with ctxm_set_agent(jev_world.agent):
        jev_world.result = jev_tool.evaluate(json.dumps({"refund": {"type": "noul", "instructions": "Does the user request a refund?"}}))


@then("JEV receives the ordered eligible context without system messages")
def assert_context(jev_world):
    """Verify the real HTTP request context boundary."""
    messages = jev_world.server.requests[0]["state"]["agent2llm_messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "tool", "assistant"]


@then("the completed tool interaction remains paired")
def assert_pair(jev_world):
    """Verify declaration/result identity survives export."""
    messages = jev_world.server.requests[0]["state"]["agent2llm_messages"]
    assert messages[1]["tool_calls"][0]["id"] == messages[2]["tool_call_id"] == "c1"


@then("the numeric noul result is returned unchanged")
def assert_noul(jev_world):
    """Verify noul does not become a boolean."""
    assert jev_world.result["answers"]["refund"]["noul"] == 0.87


@then("the JEV request is rejected before network transport")
def assert_no_transport(jev_world):
    """Verify missing credentials fail closed."""
    assert jev_world.result["status"] == "invalid_request"
    assert jev_world.server.requests == []


@then("the tool returns an invalid response status")
def assert_invalid_response(jev_world):
    """Verify mismatched answers are rejected."""
    assert jev_world.result["status"] == "invalid_response"


@given("a private JEV-compatible server returning a score answer")
def score_server(jev_world, monkeypatch):
    """Configure a valid structured score response."""
    _start(jev_world, monkeypatch, {
        "model": "jev-latest",
        "answers": {
            "quality": {
                "type": "score",
                "score": 1.75,
                "legend": {"0": "poor", "1": "acceptable", "2": "good"},
                "probabilities": {"0": 0.05, "1": 0.15, "2": 0.8},
                "confidence": 0.65,
            }
        },
        "usage": {"input_tokens": 8, "output_tokens": 2},
    })


@when("the agent evaluates a response quality score")
def evaluate_score(jev_world):
    """Invoke a score question with ordered criteria levels."""
    question = {
        "quality": {
            "type": "score",
            "instructions": "Rate the response quality.",
            "criteria": ["poor", "acceptable", "good"],
        }
    }
    with ctxm_set_agent(jev_world.agent):
        jev_world.result = jev_tool.evaluate(json.dumps(question))


@then("JEV receives the ordered score criteria levels")
def assert_score_criteria(jev_world):
    """Verify criteria remain an ordered array on the wire."""
    criteria = jev_world.server.requests[0]["questions"]["quality"]["criteria"]
    assert criteria == ["poor", "acceptable", "good"]


@then("the structured score result is returned")
def assert_score_result(jev_world):
    """Verify a valid score answer passes response validation."""
    assert jev_world.result["status"] == "ok"
    assert jev_world.result["answers"]["quality"]["score"] == 1.75
