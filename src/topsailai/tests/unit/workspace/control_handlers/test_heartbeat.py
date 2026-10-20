"""Verify heartbeat identity, isolation, and automatic registration.

Author: DawsonLin
"""
import json
import os
import socket
from types import SimpleNamespace

import pytest

from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import (
    ControlContext, ControlRequest, encode_response,
)
from topsailai.workspace.control_handlers import register_control_handlers
from topsailai.workspace.control_handlers.heartbeat import HeartbeatHandler


def test_action():
    """Expose the heartbeat wire action without constructor arguments."""
    assert HeartbeatHandler().action == "heartbeat"


@pytest.mark.parametrize("session_id", ["session-example", None, ""])
def test_identity(session_id):
    """Return exact identity without requiring any agent runtime reference."""
    context = SimpleNamespace(session_id=session_id)
    request = ControlRequest("hb-001", "heartbeat")
    response = HeartbeatHandler().handle(request, context)
    assert response.request_id == "hb-001"
    assert response.status == "ok"
    assert response.error is None
    assert response.result == {
        "alive": True,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "session_id": session_id or None,
    }
    assert response.result["alive"] is True
    assert type(response.result["pid"]) is int
    assert isinstance(response.result["hostname"], str)
    assert response.result["hostname"]
    wire = encode_response(response)
    assert wire.endswith(b"\n")
    assert json.loads(wire)["result"] == response.result


def test_default_context():
    """Allow an absent agent and unavailable session in the normal context."""
    response = HeartbeatHandler().handle(ControlRequest("hb-002", "heartbeat"), ControlContext())
    assert response.status == "ok"
    assert response.result["session_id"] is None


def test_nonempty_payload():
    """Reject unsupported parameters before accessing runtime context."""
    response = HeartbeatHandler().handle(
        ControlRequest("hb-bad", "heartbeat", {"extra": False}), object(),
    )
    assert json.loads(encode_response(response)) == {
        "request_id": "hb-bad", "status": "error", "error": "invalid_payload",
    }
    assert response.result is None


def test_auto_discovery():
    """Discover heartbeat while retaining every previously registered action."""
    registry = ControlHandlerRegistry()
    register_control_handlers(registry)
    assert {
        "heartbeat", "call_instruction", "get_runtime_messages", "get_session_messages",
        "hard_interrupt", "soft_interrupt", "clear_interrupt", "llm_control",
    } <= set(registry.list_actions())
    response = registry.handle(ControlRequest("hb-registry", "heartbeat"), ControlContext())
    assert response.status == "ok"
    assert response.result["alive"] is True
