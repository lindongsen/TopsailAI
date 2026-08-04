"""
Unit tests for the control channel handler registry.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-03
Purpose: Test control channel handler registry
"""

import pytest

from topsailai.workspace.control_channel.handler import ControlHandler, ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest, ControlResponse


class EchoHandler(ControlHandler):
    """Test handler that echoes the payload."""

    @property
    def action(self) -> str:
        return "echo"

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        return ControlResponse(
            request_id=request.request_id,
            status="ok",
            result=request.payload,
        )


class ErrorHandler(ControlHandler):
    """Test handler that always raises."""

    @property
    def action(self) -> str:
        return "error"

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        raise RuntimeError("intentional failure")


class TestControlHandlerRegistry:
    """Tests for ControlHandlerRegistry."""

    def test_register_and_get(self):
        registry = ControlHandlerRegistry()
        handler = EchoHandler()
        registry.register(handler)
        assert registry.get("echo") is handler
        assert registry.is_registered("echo")

    def test_register_none_raises(self):
        registry = ControlHandlerRegistry()
        with pytest.raises(ValueError, match="handler cannot be None"):
            registry.register(None)

    def test_register_without_action_raises(self):
        registry = ControlHandlerRegistry()

        class NoActionHandler(ControlHandler):
            @property
            def action(self) -> str:
                return ""

            def handle(self, request, context):
                return ControlResponse(request_id="", status="ok")

        with pytest.raises(ValueError, match="handler must declare a non-empty action"):
            registry.register(NoActionHandler())

    def test_unregister(self):
        registry = ControlHandlerRegistry()
        handler = EchoHandler()
        registry.register(handler)
        removed = registry.unregister("echo")
        assert removed is handler
        assert not registry.is_registered("echo")

    def test_unregister_unknown_returns_none(self):
        registry = ControlHandlerRegistry()
        assert registry.unregister("unknown") is None

    def test_list_actions(self):
        registry = ControlHandlerRegistry()
        registry.register(EchoHandler())
        assert registry.list_actions() == ["echo"]

    def test_handle_known_action(self):
        registry = ControlHandlerRegistry()
        registry.register(EchoHandler())
        request = ControlRequest(request_id="r1", action="echo", payload={"msg": "hi"})
        response = registry.handle(request, ControlContext())
        assert response.request_id == "r1"
        assert response.status == "ok"
        assert response.result == {"msg": "hi"}

    def test_handle_unknown_action(self):
        registry = ControlHandlerRegistry()
        request = ControlRequest(request_id="r1", action="missing")
        response = registry.handle(request, ControlContext())
        assert response.request_id == "r1"
        assert response.status == "error"
        assert "unknown action" in response.error

    def test_handle_exception_returns_error(self):
        registry = ControlHandlerRegistry()
        registry.register(ErrorHandler())
        request = ControlRequest(request_id="r1", action="error")
        response = registry.handle(request, ControlContext())
        assert response.request_id == "r1"
        assert response.status == "error"
        assert "handler error" in response.error
        assert "intentional failure" in response.error
