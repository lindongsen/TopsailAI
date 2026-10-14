"""Unit tests for history-replay semantic message projection."""

import unittest

from topsailai.utils.history_replay_message import (
    history_replay_semantic_projection,
)


class TestHistoryReplaySemanticProjection(unittest.TestCase):
    """Verify the explicit top-level semantic-field contract."""

    def test_projection_contains_exact_allowlist(self):
        """Only the six declared business fields are projected."""
        fields = {"role", "content", "name", "tool_calls", "tool_call_id", "function_call"}
        message = {field: {"value": field} for field in fields}
        message.update({"create_time": "now", "storage_revision": 2})
        projected = history_replay_semantic_projection(message)
        self.assertEqual(set(projected), fields)
        for field in fields:
            self.assertIs(projected[field], message[field])

    def test_projection_preserves_business_key_presence(self):
        """Missing keys remain missing and explicit None remains present."""
        for field in ("role", "content", "name", "tool_calls", "tool_call_id", "function_call"):
            with self.subTest(field=field):
                message = {"role": "user", "content": "same", field: None}
                projected = history_replay_semantic_projection(message)
                self.assertIn(field, projected)
                self.assertIsNone(projected[field])
                missing = dict(message)
                missing.pop(field)
                self.assertNotIn(field, history_replay_semantic_projection(missing))

    def test_projection_preserves_nested_values_without_mutation(self):
        """Nested business values remain intact and input is not replaced."""
        import copy
        nested = {"id": "call", "function": {"arguments": {"value": 1}}}
        message = {"role": "assistant", "content": [{"type": "text"}], "tool_calls": [nested]}
        baseline = copy.deepcopy(message)
        projected = history_replay_semantic_projection(message)
        self.assertIsNot(projected, message)
        self.assertIs(projected["tool_calls"], message["tool_calls"])
        self.assertEqual(message, baseline)

    def test_projection_preserves_non_dict_behavior(self):
        """Non-dictionary inputs pass through unchanged."""
        for value in (None, "message", ["message"]):
            self.assertIs(history_replay_semantic_projection(value), value)

    def test_replay_projection_does_not_change_global_equality(self):
        """Projection is local and does not alter full-message equality."""
        from topsailai.utils.message_tool import message_equal
        first = {"role": "user", "content": "same", "storage_revision": 1}
        second = {"role": "user", "content": "same", "storage_revision": 2}
        self.assertFalse(message_equal(first, second))
        self.assertTrue(message_equal(
            history_replay_semantic_projection(first),
            history_replay_semantic_projection(second),
        ))
        structured = {"role": "user", "content": [{"type": "text", "text": "same"}]}
        structured_copy = {"role": "user", "content": [{"type": "text", "text": "same"}]}
        self.assertTrue(message_equal(structured, structured_copy))
        self.assertFalse(message_equal(structured, {"role": "user", "content": "same"}))
        serialized = "{\"role\": \"user\", \"content\": \"same\"}"
        self.assertTrue(message_equal(serialized, serialized))
        self.assertTrue(message_equal(serialized, {"role": "user", "content": "same"}))
        structured_serialized = "{\"role\": \"user\", \"content\": [{\"type\": \"text\", \"text\": \"same\"}]}"
        self.assertTrue(message_equal(structured_serialized, structured))


