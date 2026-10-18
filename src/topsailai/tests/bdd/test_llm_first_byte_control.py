"""Real socket plus production HTTP/SSE control acceptance. Author: DawsonLin."""
import json
import os
import socket
import threading
import time
from uuid import uuid4
from types import SimpleNamespace

import pytest
from pytest_bdd import given, when, then, parsers, scenarios

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.control_runtime import (
    ControlRoute, application_control_scope, LLMControlledInterruptError,
)
from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext
from topsailai.workspace.control_channel.server import ControlServer
from topsailai.workspace.control_handlers.llm_control import LLMControlHandler

scenarios("features/llm_first_byte_control.feature")


def send(path, payload):
    """Use the real JSONL Unix socket boundary with bounded receive time."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(path)
        client.sendall(json.dumps({"request_id": uuid4().hex, "action": "llm_control", "payload": payload}).encode() + b"\n")
        with client.makefile("rb") as reader:
            return json.loads(reader.readline())


@given(parsers.parse('a controlled mock LLM request waiting in "{phase}" with timeout "{timeout}"'), target_fixture="control_case")
def controlled_case(monkeypatch, tmp_path, request, phase, timeout):
    """Start actual OpenAI client, mock HTTP server, and authenticated control bus."""
    config = MockServerConfig(
        response_header_delays=(60, 60) if phase == "headers" else None,
        first_chunk_delays=(60, 60) if phase == "first_item" else None,
        stream_response_chunks=(("STALE",), ("FRESH",)),
    )
    resources = {}

    def cleanup():
        """Release exact resources even when fixture setup fails partway."""
        server = resources.get("server")
        if server is not None:
            for number in (1, 2):
                try:
                    server.lifecycle_capture.request_handle(number).release_delay()
                except KeyError:
                    pass
        worker = resources.get("worker")
        if worker is not None:
            worker.join(10)
        channel = resources.get("channel")
        if channel is not None:
            channel.stop()
        thread = resources.get("thread")
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(5)
        route = resources.get("route")
        if route is not None:
            from topsailai.ai_base.llm_control.control_recovery import RECOVERY_POOL
            with RECOVERY_POOL.lock:
                leases = tuple(RECOVERY_POOL.leases.values())
            for lease in leases:
                if lease.target.binding_id != route.binding_id or lease.owner is None:
                    continue
                owner = lease.owner
                for owned in (owner.create_thread, owner.fetch_thread, owner.cleanup_thread):
                    if owned is not None:
                        owned.join(5)
            route.reconcile()
        model = resources.get("model")
        if model is not None:
            model.release_all_llm_models()
        assert worker is None or not worker.is_alive()
        assert thread is None or not thread.is_alive()

    request.addfinalizer(cleanup)
    server = create_server(config)
    resources["server"] = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    resources["thread"] = thread
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    for key, value in {
        "OPENAI_API_BASE": base, "OPENAI_BASE_URL": base,
        "OPENAI_API_KEY": "mock-only", "OPENAI_MODEL": "control-mock",
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": timeout,
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE": "0",
        "TOPSAILAI_EVENTS_ENABLED": "0", "TOPSAILAI_INTERACTIVE_MODE": "0",
        "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
    }.items():
        monkeypatch.setenv(key, value)
    model = LLMModel()
    resources["model"] = model
    route = ControlRoute("wire", os.getpid(), model, interrupt_supported=True)
    resources["route"] = route
    agent_chat = SimpleNamespace(ai_agent=model, _llm_control_route=route)
    registry = ControlHandlerRegistry()
    registry.register(LLMControlHandler())
    temporary_root = next(parent for parent in tmp_path.parents if parent.name == ".tmp")
    path = str(temporary_root / (uuid4().hex[:12] + ".sock"))
    channel = ControlServer(path, registry, ControlContext(session_id="wire", pid=os.getpid(), agent_chat=agent_chat), timeout=0.1)
    resources["channel"] = channel
    channel.start()
    state = {"server": server, "model": model, "route": route, "path": path, "phase": phase, "outputs": []}
    model.send_content = state["outputs"].append

    def run():
        """Run the unmodified production retry loop under explicit app routing."""
        try:
            with application_control_scope(route):
                state["result"] = model.chat([{"role": "user", "content": "same request"}], for_stream=True, for_raw=True)
        except BaseException as error:
            state["error"] = error
        finally:
            state["done"].set()

    state["done"] = threading.Event()
    worker = threading.Thread(target=run, daemon=True)
    resources["worker"] = worker
    worker.start()
    assert server.lifecycle_capture.wait_for_request(1)
    assert server.lifecycle_capture.wait_for_phase(1, phase)
    yield state


@when(parsers.parse('the operator sends "{operation}" through the control socket'))
def command(control_case, operation):
    """Resolve current exact target and submit rather than select in the handler."""
    state = control_case
    view = send(state["path"], {"operation": "status"})
    state["before"] = view
    state["operation"] = operation
    state["at"] = time.monotonic()
    state["receipt"] = send(state["path"], {"operation": operation, "target": view["result"]["target"]})


@when(parsers.parse('the operator sends action-only "{operation}" through the control socket'))
@when(parsers.parse('the operator sends action-only "{operation}" with stable ID "{stable_id}" through the control socket'))
def automatic_command(control_case, operation, stable_id=None):
    """Submit no target and check the generated receipt over a real socket."""
    state = control_case
    state["operation"] = operation
    state["automatic"] = True
    state["at"] = time.monotonic()
    payload = {"operation": operation}
    if stable_id is not None:
        stable_id = stable_id + "-" + uuid4().hex
        payload["command_id"] = stable_id
    state["receipt"] = send(state["path"], payload)
    proposal = state["receipt"]["result"]["proposal"]
    if stable_id is None:
        assert len(proposal["command_id"]) == 32
    else:
        assert proposal["command_id"] == stable_id
    assert set(proposal["target"]) == {"binding_id", "generation", "invocation_id", "attempt_id"}


@then("the command is queued before coordinator acceptance")
def queued(control_case):
    """Socket receipt is pending, never a claim of terminal control victory."""
    assert control_case["receipt"]["result"]["state"] == "queued"


@then(parsers.parse('the request has the "{outcome}" outcome without stale output'))
def outcome(control_case, outcome):
    """Assert exact wire cardinality/payload and genuine production backoff."""
    state = control_case
    if outcome == "fresh retry":
        assert state["server"].lifecycle_capture.wait_for_request(2, timeout=8)
        assert state["server"].lifecycle_capture.wait_for_phase(2, state["phase"])
        if state.get("automatic"):
            original = state["receipt"]["result"]["proposal"]
            current = send(state["path"], {"operation": "status"})["result"]["target"]
            assert current != original["target"]
            replay = send(state["path"], {"operation": state["operation"],
                                         "command_id": original["command_id"]})
            assert replay["result"]["proposal"] == original
            assert replay["result"]["state"] != "queued"
        state["server"].lifecycle_capture.request_handle(2).release_delay()
    assert state["done"].wait(8)
    if outcome == "abandoned":
        assert isinstance(state.get("error"), LLMControlledInterruptError), state
        expected = 1
    else:
        assert "error" not in state, repr(state.get("error"))
        assert state["result"] == "FRESH"
        assert time.monotonic() - state["at"] >= 5
        expected = 2
    records = state["server"].request_body_capture.state()["request_bodies"]
    assert len(records) == expected
    if expected == 2:
        assert records[0]["body"] == records[1]["body"]
    assert not any("STALE" in item for item in state["outputs"])


@when('the first stable-ID command response is lost before socket delivery')
def lost_command_response(control_case, monkeypatch):
    """Drop a real dispatched receipt before any bytes reach the requesting peer."""
    import topsailai.workspace.control_channel.server as server_module

    state = control_case
    command_id = "lost-" + uuid4().hex
    dropped = threading.Event()
    original_send = server_module.send_bytes

    def suppress_once(connection, encoded):
        """Disarm before reporting loss; subsequent responses use real transport."""
        response = json.loads(encoded)
        proposal = (response.get("result") or {}).get("proposal", {})
        if proposal.get("command_id") == command_id and not dropped.is_set():
            state["receipt"] = response
            dropped.set()
            return False
        return original_send(connection, encoded)

    monkeypatch.setattr(server_module, "send_bytes", suppress_once)
    state["automatic"] = True
    state["operation"] = "force_retry"
    state["at"] = time.monotonic()
    before = send(state["path"], {"operation": "status"})["result"]["target"]
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(5)
        peer.connect(state["path"])
        peer.sendall(json.dumps({"request_id": uuid4().hex, "action": "llm_control",
                               "payload": {"operation": "force_retry",
                                           "command_id": command_id}}).encode() + b"\n")
        assert peer.recv(1) == b"", "first receipt unexpectedly reached caller"
    assert dropped.wait(5)
    assert state["receipt"]["result"]["proposal"]["target"] == before
    assert state["receipt"]["result"]["proposal"]["command_id"] == command_id
