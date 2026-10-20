"""Real control-channel heartbeat steps. Author: DawsonLin."""

import copy
import json
import os
import socket
import threading
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from cli_topsailai.runtime_control import send_control_request
from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext
from topsailai.workspace.control_channel.server import ControlServer
from topsailai.workspace.control_handlers import register_control_handlers


class ObservedControlServer(ControlServer):
    """Track owned connection threads without replacing dispatch or transport."""

    def __init__(self, *args, **kwargs):
        """Keep scenario-local connection ownership records."""
        super().__init__(*args, **kwargs)
        self.connections = []

    def _handle_connection(self, conn):
        """Observe the real worker while preserving production behavior."""
        self.connections.append(threading.current_thread())
        super()._handle_connection(conn)


def exchange(state, action="heartbeat", payload=None, request_id="hb-关联-001"):
    """Send one real JSONL frame and read to EOF with bounded client I/O."""
    request = {"request_id": request_id, "action": action, "payload": payload or {}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(state.path))
        client.sendall(json.dumps(request).encode("utf-8") + b"\n")
        client.shutdown(socket.SHUT_WR)
        with client.makefile("rb") as reader:
            frame = reader.readline(65536)
            assert frame.endswith(b"\n")
            response = json.loads(frame)
            assert reader.read(1) == b""
    assert response["request_id"] == request_id
    return response


@pytest.fixture
def heartbeat_state(bdd_tmp_path):
    """Stop only owned service resources and preserve unrelated scenario data."""
    sentinel = bdd_tmp_path / "unrelated.txt"
    sentinel.write_text("keep", encoding="utf-8")
    state = SimpleNamespace(path=bdd_tmp_path / "hb.sock", server=None)
    try:
        yield state
    finally:
        if state.server is not None:
            state.server.stop()
            assert not state.server.is_running()
            for thread in state.server.connections:
                thread.join(timeout=2)
                assert not thread.is_alive()
            assert not state.path.exists()
        assert sentinel.read_text(encoding="utf-8") == "keep"


@given(parsers.parse('a heartbeat control server with session "{session}"'))
def heartbeat_server(heartbeat_state, session):
    """Start the real service with discovery and passive conversation sentinels."""
    state = heartbeat_state
    state.session = {"missing": None, "empty": ""}.get(session, session)
    state.agent = SimpleNamespace(messages=[{"role": "user", "content": ["runtime"]}])
    state.runtime = SimpleNamespace(
        messages=[{"role": "user", "content": ["session"]}],
        session_id=state.session, metadata={"turn": 7},
    )
    state.context = ControlContext(
        session_id=state.session, pid=-1, ai_agent=state.agent,
        ctx_runtime_data=state.runtime,
    )
    state.snapshot = copy.deepcopy((vars(state.agent), vars(state.runtime)))
    state.context_fields = vars(state.context).copy()
    state.message_ids = (id(state.agent.messages), id(state.runtime.messages))
    registry = ControlHandlerRegistry()
    register_control_handlers(registry)
    assert registry.is_registered("heartbeat")
    state.server = ObservedControlServer(str(state.path), registry, state.context, timeout=0.1)
    state.server.start()
    assert state.server.is_running()


@when("the operator probes heartbeat through JSONL and the CLI transport")
def probe_identity(heartbeat_state):
    """Exercise explicit wire correlation and the production CLI client."""
    heartbeat_state.response = exchange(heartbeat_state)
    success, response = send_control_request(str(heartbeat_state.path), "heartbeat", {}, 2)
    assert success is True
    assert response["request_id"]
    assert response["result"] == heartbeat_state.response["result"]


@then("the heartbeat echoes the request and reports the serving identity")
def identity_result(heartbeat_state):
    """Require exact process and host identity, not context PID or truthy values."""
    response = heartbeat_state.response
    assert response["request_id"] == "hb-关联-001"
    assert response["status"] == "ok"
    assert response["result"] == {
        "alive": True, "pid": os.getpid(), "hostname": socket.gethostname(),
        "session_id": heartbeat_state.session or None,
    }
    assert response["result"]["alive"] is True
    assert type(response["result"]["pid"]) is int
    assert response["result"]["hostname"]


@when("the operator sends three heartbeat probes")
def repeated_probes(heartbeat_state):
    """Send distinct requests to the same live service."""
    heartbeat_state.responses = [exchange(heartbeat_state, request_id=f"repeat-{i}") for i in range(3)]


@then("every heartbeat succeeds without changing conversation state")
def unchanged_state(heartbeat_state):
    """Compare nested state and original context references after real dispatch."""
    state = heartbeat_state
    assert all(response["status"] == "ok" and response["result"]["alive"] is True
               for response in state.responses)
    assert (vars(state.agent), vars(state.runtime)) == state.snapshot
    assert vars(state.context) == state.context_fields
    assert (id(state.agent.messages), id(state.runtime.messages)) == state.message_ids


@when("the operator stops the responsive heartbeat server")
def stop_server(heartbeat_state):
    """Prove responsiveness before stopping the exact owned endpoint."""
    assert exchange(heartbeat_state)["status"] == "ok"
    heartbeat_state.server.stop()


@then("a new heartbeat connection fails at the transport boundary")
def stopped_transport(heartbeat_state):
    """Assert endpoint failure only; never infer serving-process death."""
    assert not heartbeat_state.path.exists()
    with pytest.raises((FileNotFoundError, ConnectionRefusedError)):
        exchange(heartbeat_state)
    success, response = send_control_request(str(heartbeat_state.path), "heartbeat", {}, 2)
    assert success is False
    assert response == {"error": "control endpoint missing"}


@when("the operator sends a heartbeat with a nonempty payload")
def invalid_probe(heartbeat_state):
    """Exercise handler rejection through the actual protocol decoder."""
    heartbeat_state.response = exchange(heartbeat_state, payload={"unexpected": True})


@then("the heartbeat response rejects the payload without reporting false liveness")
def invalid_result(heartbeat_state):
    """Reject a business error without converting it to a negative heartbeat."""
    assert heartbeat_state.response == {
        "request_id": "hb-关联-001", "status": "error", "error": "invalid_payload",
    }


@when("the operator sends an unknown heartbeat action")
def unknown_probe(heartbeat_state):
    """Bypass client allowlisting to test real server registry rejection."""
    heartbeat_state.response = exchange(heartbeat_state, action="heartbeat_missing")


@then("the control server reports the unknown action")
def unknown_result(heartbeat_state):
    """Keep unknown-action diagnostics and correlation stable."""
    assert heartbeat_state.response == {
        "request_id": "hb-关联-001", "status": "error",
        "error": "unknown action: heartbeat_missing",
    }
