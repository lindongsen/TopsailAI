"""
Unit tests for topsailai.ai_base.llm_hooks.hook_before_chat.tool_call_pairing.

The hook is the request-boundary guard that drops orphaned ``role="tool"``
messages so providers never receive a ``function_call_output`` whose owning
assistant ``tool_calls`` message is missing.

Author: DawsonLin
Created: 2026-08-28
"""

import os
import unittest
from unittest.mock import patch, MagicMock

from openai.types.chat import ChatCompletionMessageFunctionToolCall

from topsailai.ai_base.llm_hooks.hook_before_chat.tool_call_pairing import (
    hook_execute,
)
from topsailai.ai_base.llm_hooks.executor import get_hooks_runtime
from topsailai.utils import message_tool


def _assistant_with_tool_calls(tool_call_id, as_object=False):
    """Build an assistant message carrying one tool call in the given shape."""
    if as_object:
        tool_calls = [
            ChatCompletionMessageFunctionToolCall(
                id=tool_call_id,
                function={"name": "cmd_tool-exec_cmd", "arguments": "{}"},
                type="function",
            )
        ]
    else:
        tool_calls = [{"id": tool_call_id, "function": {"name": "fn"}}]
    return {"role": "assistant", "content": None, "tool_calls": tool_calls}


class TestToolCallPairingHook(unittest.TestCase):
    """Test suite for the tool-call pairing pre-chat hook."""

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    def test_orphaned_tool_message_is_dropped(self):
        """A tool message without a preceding assistant tool_calls is dropped."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "thinking", "tool_calls": None},
            {"role": "tool", "content": "result", "tool_call_id": "call_orphan"},
        ]
        result = hook_execute(messages)
        self.assertEqual([m["role"] for m in result], ["system", "assistant"])

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    def test_intact_pair_is_preserved(self):
        """An assistant tool_calls message and its tool output are both kept."""
        messages = [
            _assistant_with_tool_calls("call_1"),
            {"role": "tool", "content": "result", "tool_call_id": "call_1"},
        ]
        result = hook_execute(messages)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["tool_call_id"], "call_1")

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    def test_pydantic_object_tool_calls_are_recognized(self):
        """OpenAI SDK pydantic tool-call objects provide the valid ids."""
        messages = [
            _assistant_with_tool_calls("call_obj", as_object=True),
            {"role": "tool", "content": "ok", "tool_call_id": "call_obj"},
            {"role": "tool", "content": "orphan", "tool_call_id": "call_gone"},
        ]
        result = hook_execute(messages)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["tool_call_id"], "call_obj")

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    def test_dict_tool_calls_are_recognized(self):
        """Plain dict tool-call entries provide the valid ids."""
        messages = [
            _assistant_with_tool_calls("call_dict"),
            {"role": "tool", "content": "ok", "tool_call_id": "call_dict"},
        ]
        result = hook_execute(messages)
        self.assertEqual(len(result), 2)

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    def test_only_orphan_removed_and_order_preserved(self):
        """Several pairs plus one orphan keeps every pair in original order."""
        messages = [
            {"role": "system", "content": "sys"},
            _assistant_with_tool_calls("call_a"),
            {"role": "tool", "content": "a", "tool_call_id": "call_a"},
            {"role": "tool", "content": "orphan", "tool_call_id": "call_orphan"},
            _assistant_with_tool_calls("call_b", as_object=True),
            {"role": "tool", "content": "b", "tool_call_id": "call_b"},
            {"role": "user", "content": "next"},
        ]
        result = hook_execute(messages)
        # Only the orphan tool message (index 3) may be removed; every other
        # message must survive in its original order.
        expected = [m for index, m in enumerate(messages) if index != 3]
        self.assertEqual(result, expected)
        self.assertNotIn("call_orphan", [m.get("tool_call_id") for m in result])

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    def test_messages_without_tool_calls_are_unchanged(self):
        """A plain conversation is returned with identical content and order."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = hook_execute(messages)
        self.assertEqual(result, messages)

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    def test_input_list_is_not_mutated(self):
        """The hook returns a new list and never mutates the caller's list."""
        messages = [
            {"role": "assistant", "content": "thinking"},
            {"role": "tool", "content": "orphan", "tool_call_id": "call_x"},
        ]
        original = list(messages)
        result = hook_execute(messages)
        self.assertEqual(messages, original)
        self.assertEqual(len(messages), 2)
        self.assertEqual(len(result), 1)

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "0"}, clear=True)
    def test_noop_when_tool_calls_disabled(self):
        """With native tool calls disabled the original list is returned."""
        messages = [
            {"role": "assistant", "content": "thinking"},
            {"role": "tool", "content": "orphan", "tool_call_id": "call_x"},
        ]
        result = hook_execute(messages)
        self.assertIs(result, messages)

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    def test_none_content_returns_none(self):
        """None content passes through untouched."""
        self.assertIsNone(hook_execute(None))

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    @patch(
        "topsailai.ai_base.llm_hooks.hook_before_chat.tool_call_pairing"
        ".message_tool.drop_orphaned_tool_messages",
        side_effect=RuntimeError("boom"),
    )
    def test_failure_returns_original_content(self, mock_drop):
        """A sanitizer failure never breaks the outgoing request."""
        messages = [{"role": "user", "content": "hi"}]
        result = hook_execute(messages)
        self.assertIs(result, messages)

    @patch.dict(os.environ, {"TOPSAILAI_USE_TOOL_CALLS": "1"}, clear=True)
    def test_dropped_message_is_logged(self):
        """Every dropped tool message is recorded with its tool_call_id."""
        from topsailai.ai_base.llm_hooks.hook_before_chat import tool_call_pairing

        messages = [
            {"role": "tool", "content": "orphan", "tool_call_id": "call_log_me"},
        ]
        mock_logger = MagicMock()
        with patch.object(tool_call_pairing, "logger", mock_logger):
            hook_execute(messages)
        mock_logger.warning.assert_called_once()
        self.assertIn("call_log_me", mock_logger.warning.call_args[0])


class TestToolCallPairingHookRegistration(unittest.TestCase):
    """Test suite for default registration of the pairing hook."""

    @patch.dict(os.environ, {"AI_MODEL": "gpt-5.6-sol"}, clear=True)
    def test_registered_in_default_before_chat_hooks(self):
        """The pairing hook is part of the default pre-chat hook list."""
        hooks = get_hooks_runtime("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", "content")
        self.assertIn(
            "topsailai.ai_base.llm_hooks.hook_before_chat.tool_call_pairing",
            hooks,
        )

    @patch.dict(os.environ, {"AI_MODEL": "gpt-5.6-sol"}, clear=True)
    def test_system_merge_hook_still_first(self):
        """Adding the pairing hook does not displace the system merge hook."""
        hooks = get_hooks_runtime("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", "content")
        self.assertEqual(
            hooks[0],
            "topsailai.ai_base.llm_hooks.hook_before_chat.only_one_system_message",
        )


class TestSharedHelper(unittest.TestCase):
    """Test suite for the shared message_tool pairing helper."""

    def test_helper_is_pure_and_returns_new_list(self):
        """The helper never returns or mutates the input list object."""
        messages = [{"role": "tool", "content": "orphan", "tool_call_id": "c1"}]
        result = message_tool.drop_orphaned_tool_messages(messages)
        self.assertIsNot(result, messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(result, [])

    def test_helper_with_empty_input(self):
        """Empty input yields an empty list."""
        self.assertEqual(message_tool.drop_orphaned_tool_messages([]), [])

    def test_extract_tool_call_ids_from_shapes(self):
        """Ids are read from dict entries, objects and None tool_calls."""
        self.assertEqual(
            message_tool.extract_tool_call_ids(
                {"tool_calls": [{"id": "a"}, {"id": "b"}]}
            ),
            ["a", "b"],
        )
        self.assertEqual(
            message_tool.extract_tool_call_ids(
                _assistant_with_tool_calls("obj_id", as_object=True)
            ),
            ["obj_id"],
        )
        self.assertEqual(message_tool.extract_tool_call_ids({"tool_calls": None}), [])
        self.assertEqual(message_tool.extract_tool_call_ids({"role": "user"}), [])


if __name__ == "__main__":
    unittest.main()
