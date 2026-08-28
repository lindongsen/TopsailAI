"""
Unit tests for the tool-call pairing helpers in utils/message_tool.py.

The helpers own two invariants used by both context layers and by the
request-boundary pre-chat hook:

- assistant ``tool_calls`` ids are readable from every production shape;
- a count-based preserved tail window never starts on a tool observation whose
  owning assistant message is summarized away.

Author: DawsonLin
Created: 2026-08-28
"""

import json
import unittest
from unittest.mock import MagicMock

from openai.types.chat import ChatCompletionMessageFunctionToolCall

from topsailai.utils import message_tool


def _assistant(tool_call_id, as_object=False):
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


def _tool(tool_call_id):
    """Build a tool observation for the given call id."""
    return {"role": "tool", "content": f"result-{tool_call_id}", "tool_call_id": tool_call_id}


class TestExtractToolCallIds(unittest.TestCase):
    """Test suite for extract_tool_call_ids."""

    def test_dict_tool_calls(self):
        """Plain dict tool-call entries expose their ids."""
        msg = _assistant("call_a")
        self.assertEqual(message_tool.extract_tool_call_ids(msg), ["call_a"])

    def test_pydantic_tool_calls(self):
        """OpenAI SDK pydantic tool-call objects expose their ids."""
        msg = _assistant("call_b", as_object=True)
        self.assertEqual(message_tool.extract_tool_call_ids(msg), ["call_b"])

    def test_multiple_ids_keep_declaration_order(self):
        """Several tool calls keep their original order."""
        msg = {
            "role": "assistant",
            "tool_calls": [{"id": "call_1"}, {"id": "call_2"}],
        }
        self.assertEqual(
            message_tool.extract_tool_call_ids(msg), ["call_1", "call_2"]
        )

    def test_empty_tool_calls_returns_empty_list(self):
        """An empty ``tool_calls`` list yields no ids."""
        self.assertEqual(
            message_tool.extract_tool_call_ids({"role": "assistant", "tool_calls": []}),
            [],
        )

    def test_falsy_tool_calls_returns_empty_list(self):
        """``tool_calls=None`` and missing keys yield no ids."""
        self.assertEqual(
            message_tool.extract_tool_call_ids({"role": "assistant", "tool_calls": None}),
            [],
        )
        self.assertEqual(message_tool.extract_tool_call_ids({"role": "user"}), [])

    def test_model_dump_fallback_is_used(self):
        """An entry without ``id`` but with ``model_dump`` falls back to it."""

        class _DumpOnlyToolCall:
            """Tool-call stub that only exposes ``model_dump``."""

            def model_dump(self):
                return {"id": "call_dump"}

        msg = {"role": "assistant", "tool_calls": [_DumpOnlyToolCall()]}
        self.assertEqual(message_tool.extract_tool_call_ids(msg), ["call_dump"])

    def test_object_message_tool_calls_attribute(self):
        """Object-shaped messages expose ids through the attribute."""
        msg = _assistant("call_obj")
        self.assertEqual(message_tool.extract_tool_call_ids(msg), ["call_obj"])

    def test_object_message_without_dict_shape(self):
        """Object-shaped messages expose ids through the attribute branch."""

        class _Msg:
            """Message stub exposing ``role`` and ``tool_calls`` attributes."""

            role = "assistant"

            def __init__(self, tool_calls):
                self.tool_calls = tool_calls

        msg = _Msg([{"id": "call_attr"}])
        self.assertEqual(message_tool.extract_tool_call_ids(msg), ["call_attr"])

    def test_empty_id_entries_are_skipped(self):
        """Entries without an id contribute nothing."""
        msg = {"role": "assistant", "tool_calls": [{"id": ""}, {"id": "call_x"}]}
        self.assertEqual(message_tool.extract_tool_call_ids(msg), ["call_x"])


class TestExpandTailStartForToolPairing(unittest.TestCase):
    """Test suite for expand_tail_start_for_tool_pairing."""

    def test_owner_outside_window_is_pulled_in(self):
        """The incident shape: owner at -5 and its tool output at -4."""
        messages = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "old"},
            {"role": "user", "content": "question"},
            _assistant("call_sJRQx5pXlYGYW7c6yqkUeUeB"),
            _tool("call_sJRQx5pXlYGYW7c6yqkUeUeB"),
            {"role": "user", "content": "next"},
            _assistant("call_Jz7vI5aLS7kLSHTHSiz4cv6x"),
            _tool("call_Jz7vI5aLS7kLSHTHSiz4cv6x"),
        ]
        # tail_offset_to_keep=4 -> original start index 4 (the orphan tool).
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, len(messages) - 4, min_start=2
        )
        self.assertEqual(start, 3)
        self.assertEqual(messages[start]["role"], "assistant")

    def test_paired_window_is_left_untouched(self):
        """A window that already contains the owner is not expanded."""
        messages = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "old"},
            _assistant("call_1"),
            _tool("call_1"),
            {"role": "user", "content": "next"},
        ]
        # Window starts on the assistant carrying the call, so it is already
        # pair-atomic and must stay where the count-based slice put it.
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, len(messages) - 3, min_start=1
        )
        self.assertEqual(start, 2)

    def test_no_tool_messages_is_noop(self):
        """A plain conversation keeps the count-based window."""
        messages = [
            {"role": "user", "content": f"m{i}"} for i in range(6)
        ]
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, len(messages) - 2, min_start=0
        )
        self.assertEqual(start, 4)

    def test_owner_below_floor_is_not_pulled_in(self):
        """Expansion never crosses into the summarized region."""
        messages = [
            _assistant("call_1"),
            _tool("call_1"),
            {"role": "user", "content": "next"},
            {"role": "assistant", "content": "tail"},
        ]
        # Owner sits at index 0 while the floor is 2 -> start stays at 2.
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, 2, min_start=2
        )
        self.assertEqual(start, 2)

    def test_earliest_owner_wins(self):
        """Expanding to the earliest missing owner covers the others too."""
        messages = [
            {"role": "user", "content": "task"},
            _assistant("call_a"),
            _tool("call_a"),
            _assistant("call_b"),
            _tool("call_b"),
            {"role": "user", "content": "tail"},
        ]
        # Window starts on the second tool output; the earliest missing owner
        # needed by the window is index 3, which also covers index 4.
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, 4, min_start=1
        )
        self.assertEqual(start, 3)

    def test_json_string_messages_are_supported(self):
        """Session-layer messages stored as JSON strings are readable."""
        messages = [
            json.dumps({"role": "user", "content": "task"}),
            json.dumps(_assistant("call_s")),
            json.dumps(_tool("call_s")),
            json.dumps({"role": "user", "content": "tail"}),
        ]
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, 2, min_start=1
        )
        self.assertEqual(start, 1)

    def test_object_messages_are_supported(self):
        """Object-shaped messages are readable through attributes."""

        class _Msg:
            """Minimal message object exposing the pairing attributes."""

            def __init__(self, role, tool_calls=None, tool_call_id=None):
                self.role = role
                self.tool_calls = tool_calls
                self.tool_call_id = tool_call_id

        messages = [
            _Msg("user"),
            _Msg("assistant", tool_calls=[{"id": "call_o"}]),
            _Msg("tool", tool_call_id="call_o"),
            _Msg("user"),
        ]
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, 2, min_start=1
        )
        self.assertEqual(start, 1)

    def test_empty_messages_returns_clamped_start(self):
        """An empty message list never produces a negative or huge index."""
        self.assertEqual(message_tool.expand_tail_start_for_tool_pairing([], 0), 0)
        self.assertEqual(message_tool.expand_tail_start_for_tool_pairing([], -3), 0)

    def test_negative_start_is_clamped_to_zero(self):
        """A negative start is clamped before any pairing lookup."""
        messages = [
            _assistant("call_1"),
            _tool("call_1"),
        ]
        self.assertEqual(
            message_tool.expand_tail_start_for_tool_pairing(messages, -1, min_start=0),
            0,
        )

    def test_start_beyond_length_is_clamped(self):
        """A start above the list length is clamped to the length."""
        messages = [
            _assistant("call_1"),
            _tool("call_1"),
        ]
        self.assertEqual(
            message_tool.expand_tail_start_for_tool_pairing(messages, 9, min_start=0),
            2,
        )

    def test_unpaired_tool_without_owner_is_left_alone(self):
        """A tool message whose owner is nowhere in the list is not expanded."""
        messages = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "plain"},
            _tool("call_nowhere"),
            {"role": "user", "content": "tail"},
        ]
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, 2, min_start=1
        )
        self.assertEqual(start, 2)

    def test_tool_message_without_id_is_left_alone(self):
        """A tool message without ``tool_call_id`` needs no expansion."""
        messages = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "plain"},
            {"role": "tool", "content": "no id"},
            {"role": "user", "content": "tail"},
        ]
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, 2, min_start=1
        )
        self.assertEqual(start, 2)

    def test_unreadable_message_entries_are_skipped(self):
        """Non-message entries cannot break the pairing scan."""
        messages = [
            {"role": "user", "content": "task"},
            "not a message",
            _tool("call_missing"),
            {"role": "user", "content": "tail"},
        ]
        start = message_tool.expand_tail_start_for_tool_pairing(
            messages, 2, min_start=1
        )
        self.assertEqual(start, 2)


class TestExpandIndexesForToolPairing(unittest.TestCase):
    """Test suite for expand_indexes_for_tool_pairing."""

    def test_assistant_index_pulls_its_tool_replies(self):
        """Deleting the assistant message must also delete its observations."""
        messages = [
            {"role": "user", "content": "task"},
            _assistant("call_A"),
            _tool("call_A"),
            {"role": "user", "content": "next"},
        ]
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [1]),
            [1, 2],
        )

    def test_tool_index_pulls_owner_and_sibling_replies(self):
        """Deleting one observation must delete the whole call group."""
        # One assistant declaring two parallel tool calls, hence two replies.
        owner = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_A", "function": {"name": "fn"}},
                {"id": "call_B", "function": {"name": "fn"}},
            ],
        }
        messages = [
            {"role": "user", "content": "task"},
            owner,
            _tool("call_A"),
            _tool("call_B"),
            {"role": "user", "content": "next"},
        ]
        # Selecting the second sibling still removes the owner and the first
        # sibling, so no partial group can survive.
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [3]),
            [1, 2, 3],
        )

    def test_plain_message_is_not_over_deleted(self):
        """Roles without tool pairing keep the exact requested index."""
        messages = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "answer", "tool_calls": None},
            {"role": "user", "content": "next"},
        ]
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [1]),
            [1],
        )

    def test_mixed_selection_is_deduplicated_and_sorted(self):
        """Several selections collapse into one ordered unique set."""
        messages = [
            _assistant("call_A"),
            _tool("call_A"),
            {"role": "user", "content": "middle"},
            _assistant("call_B"),
            _tool("call_B"),
        ]
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [4, 0, 2, 0]),
            [0, 1, 2, 3, 4],
        )

    def test_pydantic_tool_calls_shape_is_expanded(self):
        """The real production shape stores SDK objects in ``tool_calls``."""
        messages = [
            _assistant("call_A", as_object=True),
            _tool("call_A"),
        ]
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [0]),
            [0, 1],
        )

    def test_stringified_tool_calls_is_not_expanded(self):
        """Persisted session messages stringify ``tool_calls`` and cannot pair."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": "[{'id': 'call_A'}]"},
            _tool("call_A"),
        ]
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [0]),
            [0],
        )

    def test_out_of_range_and_invalid_indexes_are_preserved(self):
        """Callers keep their previous filtering behaviour for bad indexes."""
        messages = [
            _assistant("call_A"),
            _tool("call_A"),
        ]
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [99, -1]),
            [-1, 99],
        )
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, ["1", 2.5]),
            [2.5, "1"],
        )

    def test_empty_indexes_return_empty_list(self):
        """No request means no work."""
        self.assertEqual(message_tool.expand_indexes_for_tool_pairing([], []), [])
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing([_tool("call_A")], []),
            [],
        )

    def test_empty_messages_return_requested_indexes(self):
        """Without messages there is nothing to pair, indexes pass through."""
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing([], [3, 1]),
            [1, 3],
        )

    def test_orphan_tool_without_owner_is_left_alone(self):
        """An already orphaned observation gains no owner by expansion."""
        messages = [
            {"role": "user", "content": "task"},
            _tool("call_missing"),
        ]
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [1]),
            [1],
        )

    def test_unreadable_message_entries_are_skipped(self):
        """Non-message entries must not raise during expansion."""
        messages = ["not a message", {"role": "user", "content": "task"}]
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [0, 1]),
            [0, 1],
        )

    def test_extra_indexes_are_logged(self):
        """Every deletion pulled in by pairing must leave a log record."""
        messages = [
            _assistant("call_A"),
            _tool("call_A"),
        ]
        logger = MagicMock()
        message_tool.expand_indexes_for_tool_pairing(messages, [0], logger)
        logger.warning.assert_called_once()
        logged = logger.warning.call_args.args
        self.assertIn("call_A", str(messages))
        self.assertIn([1], logged)

    def test_missing_logger_does_not_raise(self):
        """Logging is optional and must never break pruning."""
        messages = [
            _assistant("call_A"),
            _tool("call_A"),
        ]
        self.assertEqual(
            message_tool.expand_indexes_for_tool_pairing(messages, [1], None),
            [0, 1],
        )



if __name__ == "__main__":
    unittest.main()
