"""
Unit tests for workspace/control_handlers/message.py.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-04
Purpose: Verify message-related control handlers and auto-discovery
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

from topsailai.workspace.control_channel.handler import ControlHandler, ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest
from topsailai.workspace.control_handlers import register_control_handlers
from topsailai.workspace.control_handlers.message import (
    GetRuntimeMessagesHandler,
    GetSessionMessagesHandler,
    serialize_message,
)


class TestSerializeMessage:
    def test_dict_returned_as_is(self):
        assert serialize_message({"role": "user", "content": "hi"}) == {
            "role": "user",
            "content": "hi",
        }

    def test_none_returns_none(self):
        assert serialize_message(None) is None

    def test_to_dict_priority(self):
        class Msg:
            def to_dict(self):
                return {"kind": "to_dict"}

        assert serialize_message(Msg()) == {"kind": "to_dict"}

    def test_dataclass_fallback(self):
        from dataclasses import dataclass

        @dataclass
        class Msg:
            role: str
            content: str

        assert serialize_message(Msg("user", "hello")) == {
            "role": "user",
            "content": "hello",
        }

    def test_object_dict_fallback(self):
        class Msg:
            def __init__(self):
                self.role = "assistant"

        assert serialize_message(Msg()) == {"role": "assistant"}

    def test_str_fallback(self):
        class Msg:
            pass

        result = serialize_message(Msg())
        assert "Msg" in result


class TestGetRuntimeMessagesHandler:
    @pytest.fixture
    def handler(self):
        return GetRuntimeMessagesHandler()

    def test_action_name(self, handler):
        assert handler.action == "get_runtime_messages"

    def test_handle_returns_messages(self, handler, monkeypatch):
        class FakeAgent:
            messages = [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ]

        monkeypatch.setattr(
            "topsailai.workspace.control_handlers.message.get_agent_object",
            lambda: FakeAgent(),
        )

        request = ControlRequest(request_id="r1", action="get_runtime_messages", payload={})
        response = handler.handle(request, ControlContext())

        assert response.status == "ok"
        assert response.result["count"] == 2
        assert response.result["messages"] == FakeAgent.messages
        assert response.error is None

    def test_handle_uses_agent_chat_context_when_thread_local_is_unavailable(
        self, handler, monkeypatch
    ):
        class FakeAgent:
            messages = [{"role": "user", "content": "from context"}]

        class FakeAgentChat:
            ai_agent = FakeAgent()

        monkeypatch.setattr(
            "topsailai.workspace.control_handlers.message.get_agent_object",
            lambda: None,
        )

        request = ControlRequest(request_id="r-context", action="get_runtime_messages", payload={})
        response = handler.handle(request, ControlContext(agent_chat=FakeAgentChat()))

        assert response.status == "ok"
        assert response.result["messages"] == FakeAgent.messages

    def test_handle_no_agent(self, handler, monkeypatch):
        monkeypatch.setattr(
            "topsailai.workspace.control_handlers.message.get_agent_object",
            lambda: None,
        )

        request = ControlRequest(request_id="r2", action="get_runtime_messages", payload={})
        response = handler.handle(request, ControlContext())

        assert response.status == "error"
        assert "no active agent" in response.error

    def test_handle_agent_without_messages(self, handler, monkeypatch):
        class FakeAgent:
            pass

        monkeypatch.setattr(
            "topsailai.workspace.control_handlers.message.get_agent_object",
            lambda: FakeAgent(),
        )

        request = ControlRequest(request_id="r3", action="get_runtime_messages", payload={})
        response = handler.handle(request, ControlContext())

        assert response.status == "error"
        assert "no messages attribute" in response.error


class TestGetSessionMessagesHandler:
    @pytest.fixture
    def handler(self):
        return GetSessionMessagesHandler()

    def test_action_name(self, handler):
        assert handler.action == "get_session_messages"

    def test_handle_missing_session_id(self, handler):
        request = ControlRequest(request_id="s1", action="get_session_messages", payload={})
        response = handler.handle(request, ControlContext())

        assert response.status == "error"
        assert "missing or empty session_id" in response.error

    def test_handle_empty_session_id(self, handler):
        request = ControlRequest(
            request_id="s2",
            action="get_session_messages",
            payload={"session_id": ""},
        )
        response = handler.handle(request, ControlContext())

        assert response.status == "error"
        assert "missing or empty session_id" in response.error

    def test_handle_session_not_found(self, handler, monkeypatch):
        class FakeSessionManager:
            def exists_session(self, session_id):
                return False

        monkeypatch.setattr(
            "topsailai.workspace.control_handlers.message.get_session_manager",
            lambda: FakeSessionManager(),
        )

        request = ControlRequest(
            request_id="s3",
            action="get_session_messages",
            payload={"session_id": "missing-session"},
        )
        response = handler.handle(request, ControlContext())

        assert response.status == "error"
        assert "session not found" in response.error

    def test_handle_success_with_session_manager(self, handler, monkeypatch):
        class FakeSessionManager:
            def exists_session(self, session_id):
                return True

            def retrieve_messages(self, session_id):
                return [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ]

        monkeypatch.setattr(
            "topsailai.workspace.control_handlers.message.get_session_manager",
            lambda: FakeSessionManager(),
        )

        request = ControlRequest(
            request_id="s4",
            action="get_session_messages",
            payload={"session_id": "abc-123"},
        )
        response = handler.handle(request, ControlContext())

        assert response.status == "ok"
        assert response.result["count"] == 2
        assert response.result["messages"][0]["role"] == "user"

    def test_handle_prefers_context_session_manager(self, handler, monkeypatch):
        class FakeContextSessionManager:
            def exists_session(self, session_id):
                return True

            def retrieve_messages(self, session_id):
                return [{"role": "user", "content": "from context"}]

        class FakeGlobalSessionManager:
            def exists_session(self, session_id):
                return True

            def retrieve_messages(self, session_id):
                return [{"role": "user", "content": "from global"}]

        monkeypatch.setattr(
            "topsailai.workspace.control_handlers.message.get_session_manager",
            lambda: FakeGlobalSessionManager(),
        )

        context = ControlContext()
        context.session_mgr = FakeContextSessionManager()

        request = ControlRequest(
            request_id="s5",
            action="get_session_messages",
            payload={"session_id": "ctx-session"},
        )
        response = handler.handle(request, context)

        assert response.status == "ok"
        assert response.result["messages"][0]["content"] == "from context"


class TestAutoDiscovery:
    def test_register_control_handlers_discovers_both_actions(self):
        registry = ControlHandlerRegistry()
        register_control_handlers(registry)

        actions = registry.list_actions()
        assert "get_runtime_messages" in actions
        assert "get_session_messages" in actions

    def test_register_control_handlers_no_manual_imports_needed(self):
        registry = ControlHandlerRegistry()
        register_control_handlers(registry)

        runtime_handler = registry.get("get_runtime_messages")
        assert isinstance(runtime_handler, GetRuntimeMessagesHandler)

        session_handler = registry.get("get_session_messages")
        assert isinstance(session_handler, GetSessionMessagesHandler)

    def test_discover_skips_modules_without_handlers(self, monkeypatch, tmp_path):
        from topsailai.workspace.control_handlers import _discover_handler_classes

        # Create a temporary package directory with a module that has no handlers.
        fake_dir = tmp_path / "fake_handlers"
        fake_dir.mkdir()
        (fake_dir / "empty.py").write_text("# no handlers here\n")

        classes = _discover_handler_classes(str(fake_dir), "fake_handlers")
        assert classes == []

    def test_discover_collects_handler_from_module(self, tmp_path):
        from topsailai.workspace.control_handlers import _discover_handler_classes

        fake_dir = tmp_path / "fake_handlers"
        fake_dir.mkdir()
        (fake_dir / "dummy.py").write_text(
            "from topsailai.workspace.control_channel.handler import ControlHandler\n"
            "from topsailai.workspace.control_channel.protocol import ControlRequest, ControlResponse, ControlContext\n"
            "class DummyHandler(ControlHandler):\n"
            "    @property\n"
            "    def action(self):\n"
            "        return 'dummy'\n"
            "    def handle(self, request, context):\n"
            "        return ControlResponse(request_id=request.request_id, status='ok')\n"
        )

        # Make the temp directory importable by adding an __init__.py and sys.path entry.
        (fake_dir / "__init__.py").write_text("")
        sys.path.insert(0, str(tmp_path))
        try:
            classes = _discover_handler_classes(str(fake_dir), "fake_handlers")
        finally:
            sys.path.pop(0)

        assert len(classes) == 1
        assert classes[0].__name__ == "DummyHandler"

    def test_duplicate_action_keys_raise_on_register(self):
        registry = ControlHandlerRegistry()
        registry.register(GetRuntimeMessagesHandler())

        # A second handler claiming the same action should raise.
        with pytest.raises(ValueError):
            registry.register(GetRuntimeMessagesHandler())
