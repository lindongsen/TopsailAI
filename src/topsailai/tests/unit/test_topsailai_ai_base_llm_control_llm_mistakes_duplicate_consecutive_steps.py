"""
Test module for duplicate_consecutive_steps mistake fixer.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-27
Purpose: Unit tests for the standalone deduplication logic and its wrapper.
"""

import pytest
from unittest.mock import patch

from topsailai.ai_base.llm_control.llm_mistakes.duplicate_consecutive_steps import (
    _normalize_action_item,
    _remove_consecutive_duplicate_actions,
    fix_duplicate_consecutive_steps,
)


class TestNormalizeActionItem:
    """Test suite for _normalize_action_item."""

    def test_valid_action(self):
        """Verify a valid action item produces a stable signature."""
        item = {
            "step_name": "action",
            "tool_call": "file_tool-read_file",
            "tool_args": {"files": ["/tmp/1.txt"]},
        }
        sig = _normalize_action_item(item)
        assert sig == (
            "file_tool-read_file",
            '{"files":["/tmp/1.txt"]}',
        )

    def test_non_action_step(self):
        """Verify non-action steps return None."""
        assert _normalize_action_item({"step_name": "thought", "raw_text": "x"}) is None

    def test_missing_step_name(self):
        """Verify items without step_name return None."""
        assert _normalize_action_item({"tool_call": "x", "tool_args": {}}) is None

    def test_missing_tool_call(self):
        """Verify action items without tool_call return None."""
        assert _normalize_action_item({"step_name": "action", "tool_args": {}}) is None

    def test_non_dict_item(self):
        """Verify non-dict items return None."""
        assert _normalize_action_item("not a dict") is None

    def test_key_order_independence(self):
        """Verify tool_args key order does not affect the signature."""
        item1 = {
            "step_name": "action",
            "tool_call": "x",
            "tool_args": {"a": 1, "b": 2},
        }
        item2 = {
            "step_name": "action",
            "tool_call": "x",
            "tool_args": {"b": 2, "a": 1},
        }
        assert _normalize_action_item(item1) == _normalize_action_item(item2)

    def test_whitespace_independence(self):
        """Verify string whitespace inside tool_args is preserved in normalization."""
        item = {
            "step_name": "action",
            "tool_call": "x",
            "tool_args": {"msg": " hello "},
        }
        sig = _normalize_action_item(item)
        assert sig == ("x", '{"msg":" hello "}')


class TestRemoveConsecutiveDuplicateActions:
    """Test suite for _remove_consecutive_duplicate_actions."""

    def test_empty_list(self):
        """Verify empty list returns None."""
        assert _remove_consecutive_duplicate_actions([]) is None

    def test_single_item(self):
        """Verify single-item list returns None."""
        assert _remove_consecutive_duplicate_actions([{"step_name": "action"}]) is None

    def test_two_duplicate_actions(self):
        """Verify one of two duplicate actions is removed."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
        ]
        result = _remove_consecutive_duplicate_actions(response)
        assert result == [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
        ]

    def test_three_consecutive_duplicate_actions(self):
        """Verify sliding-window deletion removes earlier duplicates."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
        ]
        result = _remove_consecutive_duplicate_actions(response)
        assert result == [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
        ]

    def test_example_from_requirement(self):
        """Verify the exact example from the requirement."""
        response = [
            {"step_name": "thought", "raw_text": "think"},
            {"step_name": "action", "tool_call": "a", "tool_args": {"id": 1}},
            {"step_name": "action", "tool_call": "a", "tool_args": {"id": 1}},
            {"step_name": "action", "tool_call": "a", "tool_args": {"id": 1}},
            {"step_name": "action", "tool_call": "b", "tool_args": {"id": 2}},
            {"step_name": "action", "tool_call": "b", "tool_args": {"id": 2}},
        ]
        result = _remove_consecutive_duplicate_actions(response)
        assert result == [
            {"step_name": "thought", "raw_text": "think"},
            {"step_name": "action", "tool_call": "a", "tool_args": {"id": 1}},
            {"step_name": "action", "tool_call": "b", "tool_args": {"id": 2}},
        ]

    def test_non_duplicate_actions_preserved(self):
        """Verify different consecutive actions are preserved."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "y", "tool_args": {"b": 2}},
        ]
        assert _remove_consecutive_duplicate_actions(response) is None

    def test_mixed_step_types(self):
        """Verify duplicate thoughts are not removed."""
        response = [
            {"step_name": "thought", "raw_text": "same"},
            {"step_name": "thought", "raw_text": "same"},
            {"step_name": "action", "tool_call": "x", "tool_args": {}},
            {"step_name": "action", "tool_call": "x", "tool_args": {}},
        ]
        result = _remove_consecutive_duplicate_actions(response)
        assert result == [
            {"step_name": "thought", "raw_text": "same"},
            {"step_name": "thought", "raw_text": "same"},
            {"step_name": "action", "tool_call": "x", "tool_args": {}},
        ]

    def test_non_consecutive_duplicates_preserved(self):
        """Verify non-consecutive duplicate actions are preserved."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "y", "tool_args": {"b": 2}},
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
        ]
        assert _remove_consecutive_duplicate_actions(response) is None

    def test_formatting_differences_normalized(self):
        """Verify equivalent tool_args with different formatting are deduplicated."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": {"files": ["/tmp/1.txt"]}},
            {"step_name": "action", "tool_call": "x", "tool_args": {"files": ["/tmp/1.txt"]}},
        ]
        result = _remove_consecutive_duplicate_actions(response)
        assert len(result) == 1

    def test_action_without_tool_args(self):
        """Verify action items without tool_args are not compared as duplicates."""
        response = [
            {"step_name": "action", "tool_call": "x"},
            {"step_name": "action", "tool_call": "x"},
        ]
        # Both normalize to ("x", "{}"), so they are considered duplicates.
        result = _remove_consecutive_duplicate_actions(response)
        assert len(result) == 1

    def test_preserves_extra_fields(self):
        """Verify extra fields on action items are preserved after dedup."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": {}, "extra": 1},
            {"step_name": "action", "tool_call": "x", "tool_args": {}, "extra": 2},
        ]
        result = _remove_consecutive_duplicate_actions(response)
        assert result == [
            {"step_name": "action", "tool_call": "x", "tool_args": {}, "extra": 2},
        ]
    def test_tool_args_as_list(self):
        """Verify list tool_args are normalized and compared correctly."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": []},
            {"step_name": "action", "tool_call": "x", "tool_args": []},
            {"step_name": "action", "tool_call": "x", "tool_args": [1]},
        ]
        result = _remove_consecutive_duplicate_actions(response)
        assert result == [
            {"step_name": "action", "tool_call": "x", "tool_args": []},
            {"step_name": "action", "tool_call": "x", "tool_args": [1]},
        ]

    def test_empty_tool_call_not_duplicate(self):
        """Verify empty-string tool_call is treated as a valid call name."""
        response = [
            {"step_name": "action", "tool_call": "", "tool_args": {}},
            {"step_name": "action", "tool_call": "", "tool_args": {}},
        ]
        result = _remove_consecutive_duplicate_actions(response)
        assert result == [
            {"step_name": "action", "tool_call": "", "tool_args": {}},
        ]

    def test_none_tool_call_ignored(self):
        """Verify action items with None tool_call are ignored by dedup."""
        response = [
            {"step_name": "action", "tool_call": None, "tool_args": {}},
            {"step_name": "action", "tool_call": None, "tool_args": {}},
            {"step_name": "action", "tool_call": "x", "tool_args": {}},
        ]
        # None tool_call actions are not valid action signatures, so no
        # consecutive duplicates are detected and the function returns None.
        assert _remove_consecutive_duplicate_actions(response) is None

    def test_mixed_step_types_partial_match(self):
        """Verify only consecutive action pairs are deduplicated in mixed lists."""
        response = [
            {"step_name": "thought", "raw_text": "same"},
            {"step_name": "thought", "raw_text": "same"},
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "y", "tool_args": {"b": 2}},
            {"step_name": "inquiry", "raw_text": "ask"},
            {"step_name": "inquiry", "raw_text": "ask"},
            {"step_name": "action", "tool_call": "y", "tool_args": {"b": 2}},
            {"step_name": "action", "tool_call": "y", "tool_args": {"b": 2}},
        ]
        result = _remove_consecutive_duplicate_actions(response)
        assert result == [
            {"step_name": "thought", "raw_text": "same"},
            {"step_name": "thought", "raw_text": "same"},
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "y", "tool_args": {"b": 2}},
            {"step_name": "inquiry", "raw_text": "ask"},
            {"step_name": "inquiry", "raw_text": "ask"},
            {"step_name": "action", "tool_call": "y", "tool_args": {"b": 2}},
        ]



class TestFixDuplicateConsecutiveSteps:
    """Test suite for the public fixer wrapper."""

    def test_returns_none_for_non_list(self):
        """Verify non-list input returns None."""
        assert fix_duplicate_consecutive_steps("string") is None

    def test_returns_none_when_no_duplicates(self):
        """Verify no-change input returns None."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "y", "tool_args": {"b": 2}},
        ]
        assert fix_duplicate_consecutive_steps(response) is None

    def test_returns_deduplicated_list(self):
        """Verify duplicate actions are removed through the public wrapper."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
        ]
        result = fix_duplicate_consecutive_steps(response)
        assert result == [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
        ]

    def test_exception_is_caught_and_logged(self):
        """Verify exceptions do not propagate and the original list is returned."""
        response = [
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
            {"step_name": "action", "tool_call": "x", "tool_args": {"a": 1}},
        ]
        with patch(
            "topsailai.ai_base.llm_control.llm_mistakes.duplicate_consecutive_steps._remove_consecutive_duplicate_actions",
            side_effect=RuntimeError("boom"),
        ):
            result = fix_duplicate_consecutive_steps(response)

        assert result is response
