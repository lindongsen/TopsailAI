"""
Unit tests for the control channel protocol layer.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-03
Purpose: Test control channel protocol encoding/decoding
"""

import json

import pytest

from topsailai.workspace.control_channel.exceptions import ControlProtocolError
from topsailai.workspace.control_channel.protocol import (
    ControlContext,
    ControlRequest,
    ControlResponse,
    decode_request,
    encode_response,
)


class TestEncodeResponse:
    """Tests for encode_response."""

    def test_encode_ok_without_result(self):
        response = ControlResponse(request_id="r1", status="ok")
        raw = encode_response(response)
        data = json.loads(raw.decode("utf-8"))
        assert data == {"request_id": "r1", "status": "ok"}

    def test_encode_ok_with_result(self):
        response = ControlResponse(request_id="r2", status="ok", result={"count": 3})
        raw = encode_response(response)
        data = json.loads(raw.decode("utf-8"))
        assert data["request_id"] == "r2"
        assert data["status"] == "ok"
        assert data["result"] == {"count": 3}

    def test_encode_error(self):
        response = ControlResponse(request_id="r3", status="error", error="boom")
        raw = encode_response(response)
        data = json.loads(raw.decode("utf-8"))
        assert data["request_id"] == "r3"
        assert data["status"] == "error"
        assert data["error"] == "boom"

    def test_encode_ends_with_newline(self):
        response = ControlResponse(request_id="r1", status="ok")
        raw = encode_response(response)
        assert raw.endswith(b"\n")

    def test_encode_unicode(self):
        response = ControlResponse(request_id="r1", status="ok", result="中文")
        raw = encode_response(response)
        assert "中文".encode("utf-8") in raw


class TestDecodeRequest:
    """Tests for decode_request."""

    def test_decode_valid_request(self):
        raw = '{"request_id":"r1","action":"status","payload":{}}'
        request = decode_request(raw)
        assert request.request_id == "r1"
        assert request.action == "status"
        assert request.payload == {}

    def test_decode_request_with_payload(self):
        raw = '{"request_id":"r2","action":"echo","payload":{"msg":"hello"}}'
        request = decode_request(raw)
        assert request.request_id == "r2"
        assert request.action == "echo"
        assert request.payload == {"msg": "hello"}

    def test_decode_missing_payload_defaults_to_empty_dict(self):
        raw = '{"request_id":"r3","action":"ping"}'
        request = decode_request(raw)
        assert request.payload == {}

    def test_decode_invalid_json(self):
        with pytest.raises(ControlProtocolError) as exc_info:
            decode_request("not json")
        assert "invalid json" in str(exc_info.value)
        assert exc_info.value.request_id == ""

    def test_decode_not_an_object(self):
        with pytest.raises(ControlProtocolError) as exc_info:
            decode_request('["request_id","r1"]')
        assert "message must be a JSON object" in str(exc_info.value)

    def test_decode_missing_request_id(self):
        with pytest.raises(ControlProtocolError) as exc_info:
            decode_request('{"action":"status"}')
        assert "missing request_id" in str(exc_info.value)
        assert exc_info.value.request_id == ""

    def test_decode_missing_action(self):
        with pytest.raises(ControlProtocolError) as exc_info:
            decode_request('{"request_id":"r1"}')
        assert "missing action" in str(exc_info.value)
        assert exc_info.value.request_id == "r1"

    def test_decode_payload_not_object(self):
        with pytest.raises(ControlProtocolError) as exc_info:
            decode_request('{"request_id":"r1","action":"echo","payload":"hello"}')
        assert "payload must be a JSON object" in str(exc_info.value)
        assert exc_info.value.request_id == "r1"


class TestControlContext:
    """Tests for ControlContext dataclass."""

    def test_default_context(self):
        ctx = ControlContext()
        assert ctx.session_id is None
        assert ctx.ai_agent is None
        assert ctx.ctx_runtime_data is None
        assert ctx.agent_chat is None
        assert ctx.control_event is None

    def test_context_with_values(self):
        ctx = ControlContext(
            session_id="s1",
            ai_agent="agent",
            ctx_runtime_data="ctx",
            agent_chat="chat",
            control_event="event",
        )
        assert ctx.session_id == "s1"
        assert ctx.ai_agent == "agent"
        assert ctx.ctx_runtime_data == "ctx"
        assert ctx.agent_chat == "chat"
        assert ctx.control_event == "event"
