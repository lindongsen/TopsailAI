"""
Unit tests for workspace/control_handlers/instruction.py.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-06
Purpose: Verify the call_instruction control handler and its integration
with HookInstruction.call_instruction.
"""

from unittest.mock import MagicMock

import pytest

from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest
from topsailai.workspace.control_handlers import register_control_handlers
from topsailai.workspace.control_handlers.instruction import CallInstructionHandler


class TestCallInstructionHandler:
    @pytest.fixture
    def handler(self):
        return CallInstructionHandler()

    def test_action_name(self, handler):
        assert handler.action == "call_instruction"

    def test_handle_missing_instruction(self, handler):
        request = ControlRequest(request_id="c1", action="call_instruction", payload={})
        response = handler.handle(request, ControlContext())

        assert response.status == "error"
        assert "missing or invalid instruction" in response.error

    def test_handle_non_string_instruction(self, handler):
        request = ControlRequest(
            request_id="c2",
            action="call_instruction",
            payload={"instruction": 123},
        )
        response = handler.handle(request, ControlContext())

        assert response.status == "error"
        assert "missing or invalid instruction" in response.error

    def test_handle_no_agent_chat(self, handler):
        request = ControlRequest(
            request_id="c3",
            action="call_instruction",
            payload={"instruction": "/ctx.history"},
        )
        response = handler.handle(request, ControlContext())

        assert response.status == "error"
        assert "hook instruction is not available" in response.error

    def test_handle_agent_chat_without_hook_instruction(self, handler):
        class FakeAgentChat:
            pass

        request = ControlRequest(
            request_id="c4",
            action="call_instruction",
            payload={"instruction": "/ctx.history"},
        )
        response = handler.handle(request, ControlContext(agent_chat=FakeAgentChat()))

        assert response.status == "error"
        assert "hook instruction is not available" in response.error

    def test_handle_hook_instruction_without_call_instruction(self, handler):
        class FakeHookInstruction:
            pass

        class FakeAgentChat:
            hook_instruction = FakeHookInstruction()

        request = ControlRequest(
            request_id="c5",
            action="call_instruction",
            payload={"instruction": "/ctx.history"},
        )
        response = handler.handle(request, ControlContext(agent_chat=FakeAgentChat()))

        assert response.status == "error"
        assert "does not support call_instruction" in response.error

    def test_handle_invalid_args_type(self, handler):
        class FakeHookInstruction:
            def call_instruction(self, *args, **kwargs):
                return "ok"

        class FakeAgentChat:
            hook_instruction = FakeHookInstruction()

        request = ControlRequest(
            request_id="c6",
            action="call_instruction",
            payload={"instruction": "/ctx.history", "args": "not-a-list"},
        )
        response = handler.handle(request, ControlContext(agent_chat=FakeAgentChat()))

        assert response.status == "error"
        assert "args must be a list" in response.error

    def test_handle_invalid_kwargs_type(self, handler):
        class FakeHookInstruction:
            def call_instruction(self, *args, **kwargs):
                return "ok"

        class FakeAgentChat:
            hook_instruction = FakeHookInstruction()

        request = ControlRequest(
            request_id="c7",
            action="call_instruction",
            payload={"instruction": "/ctx.history", "kwargs": "not-a-dict"},
        )
        response = handler.handle(request, ControlContext(agent_chat=FakeAgentChat()))

        assert response.status == "error"
        assert "kwargs must be an object" in response.error

    def test_handle_success(self, handler):
        mock_instruction = MagicMock()
        mock_instruction.call_instruction.return_value = {"count": 3}

        class FakeAgentChat:
            hook_instruction = mock_instruction

        request = ControlRequest(
            request_id="c8",
            action="call_instruction",
            payload={
                "instruction": "/ctx.history",
                "args": ["arg1"],
                "kwargs": {"key": "value"},
            },
        )
        response = handler.handle(request, ControlContext(agent_chat=FakeAgentChat()))

        assert response.status == "ok"
        assert response.result == {"count": 3}
        mock_instruction.call_instruction.assert_called_once_with(
            "/ctx.history", "arg1", key="value"
        )

    def test_handle_instruction_raises(self, handler):
        mock_instruction = MagicMock()
        mock_instruction.call_instruction.side_effect = RuntimeError("boom")

        class FakeAgentChat:
            hook_instruction = mock_instruction

        request = ControlRequest(
            request_id="c9",
            action="call_instruction",
            payload={"instruction": "/ctx.history"},
        )
        response = handler.handle(request, ControlContext(agent_chat=FakeAgentChat()))

        assert response.status == "error"
        assert "instruction failed" in response.error
        assert "boom" in response.error


class TestAutoDiscovery:
    def test_register_control_handlers_discovers_call_instruction(self):
        registry = ControlHandlerRegistry()
        register_control_handlers(registry)

        assert registry.is_registered("call_instruction")
        assert isinstance(registry.get("call_instruction"), CallInstructionHandler)
