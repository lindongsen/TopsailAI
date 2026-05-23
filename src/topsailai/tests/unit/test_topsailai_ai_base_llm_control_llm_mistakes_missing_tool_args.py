"""
Unit tests for topsailai.ai_base.llm_control.llm_mistakes.missing_tool_args
"""

import pytest
import simplejson

from topsailai.ai_base.llm_control.llm_mistakes.missing_tool_args import (
    fix_raw_text,
    fix_mistake1,
    fix_mistake2,
    MISTAKES,
)


class TestFixRawText:
    """Tests for fix_raw_text function."""

    def test_string_input_with_extra_args(self):
        """Test fixing a JSON string with tool_call and extra args."""
        raw_text = '{"step_name": "action", "tool_call": "xxx", "arg1": "value1", "arg2": "value2"}'
        result = fix_raw_text(raw_text)
        expected = {
            "step_name": "action",
            "tool_call": "xxx",
            "tool_args": {
                "arg1": "value1",
                "arg2": "value2",
            },
        }
        assert simplejson.loads(result) == expected

    def test_dict_input_with_extra_args(self):
        """Test fixing a dict with tool_call and extra args."""
        raw_text = {
            "step_name": "action",
            "tool_call": "xxx",
            "arg1": "value1",
            "arg2": "value2",
        }
        result = fix_raw_text(raw_text)
        expected = {
            "step_name": "action",
            "tool_call": "xxx",
            "tool_args": {
                "arg1": "value1",
                "arg2": "value2",
            },
        }
        assert result == expected

    def test_already_has_tool_args(self):
        """Test input that already has tool_args is not modified."""
        raw_text = {
            "step_name": "action",
            "tool_call": "xxx",
            "tool_args": {"arg1": "value1"},
        }
        result = fix_raw_text(raw_text)
        assert result == raw_text

    def test_no_tool_call(self):
        """Test input without tool_call returns the dict unchanged."""
        raw_text = {"step_name": "action", "arg1": "value1"}
        result = fix_raw_text(raw_text)
        assert result == raw_text

    def test_invalid_json_string(self):
        """Test invalid JSON string returns None."""
        raw_text = "not valid json"
        result = fix_raw_text(raw_text)
        assert result is None

    def test_empty_dict(self):
        """Test empty dict returns None."""
        result = fix_raw_text({})
        assert result is None

    def test_empty_string(self):
        """Test empty string returns None."""
        result = fix_raw_text("")
        assert result is None

    def test_non_dict_non_str(self):
        """Test non-dict, non-str input returns None."""
        result = fix_raw_text(123)
        assert result is None

    def test_only_step_name_and_tool_call(self):
        """Test dict with only step_name and tool_call produces empty tool_args."""
        raw_text = {"step_name": "action", "tool_call": "xxx"}
        result = fix_raw_text(raw_text)
        expected = {
            "step_name": "action",
            "tool_call": "xxx",
            "tool_args": {},
        }
        assert result == expected

    def test_multiple_extra_args(self):
        """Test multiple extra args are all wrapped into tool_args."""
        raw_text = {
            "step_name": "action",
            "tool_call": "xxx",
            "a": 1,
            "b": 2,
            "c": 3,
        }
        result = fix_raw_text(raw_text)
        expected = {
            "step_name": "action",
            "tool_call": "xxx",
            "tool_args": {"a": 1, "b": 2, "c": 3},
        }
        assert result == expected


class TestFixMistake1:
    """Tests for fix_mistake1 function."""

    def test_case1_direct_keys(self):
        """Test case1: direct keys in message dict."""
        message = [{
            "step_name": "action",
            "tool_call": "xxx",
            "arg1": "value1",
            "arg2": "value2",
        }]
        result = fix_mistake1(message)
        expected = [{
            "step_name": "action",
            "tool_call": "xxx",
            "tool_args": {
                "arg1": "value1",
                "arg2": "value2",
            },
        }]
        assert result == expected

    def test_case2_raw_text_with_extra_args(self):
        """Test case2: raw_text contains missing tool_args."""
        message = [{
            "step_name": "action",
            "raw_text": {
                "tool_call": "xxx",
                "arg1": "value1",
                "arg2": "value2",
            },
        }]
        result = fix_mistake1(message)
        expected = [{
            "step_name": "action",
            "raw_text": {
                "tool_call": "xxx",
                "tool_args": {
                    "arg1": "value1",
                    "arg2": "value2",
                },
            },
        }]
        assert result == expected

    def test_no_mistake_already_has_tool_args(self):
        """Test message already has tool_args is not modified."""
        message = [{
            "step_name": "action",
            "tool_call": "xxx",
            "tool_args": {"arg1": "value1"},
        }]
        result = fix_mistake1(message)
        assert result == message

    def test_non_list_input(self):
        """Test non-list input is returned as-is."""
        message = {"step_name": "action", "tool_call": "xxx"}
        result = fix_mistake1(message)
        assert result == message

    def test_empty_list(self):
        """Test empty list is returned as-is."""
        message = []
        result = fix_mistake1(message)
        assert result == message

    def test_list_with_multiple_items(self):
        """Test list with multiple items is returned as-is."""
        message = [
            {"step_name": "action", "tool_call": "xxx"},
            {"step_name": "action", "tool_call": "yyy"},
        ]
        result = fix_mistake1(message)
        assert result == message

    def test_not_action_step_name(self):
        """Test dict without step_name='action' is not modified."""
        message = [{
            "step_name": "thought",
            "tool_call": "xxx",
            "arg1": "value1",
        }]
        result = fix_mistake1(message)
        assert result == message

    def test_no_tool_call(self):
        """Test dict without tool_call is not modified."""
        message = [{
            "step_name": "action",
            "arg1": "value1",
        }]
        result = fix_mistake1(message)
        assert result == message

    def test_raw_text_string_with_mistake(self):
        """Test raw_text as string with missing tool_args is fixed."""
        message = [{
            "step_name": "action",
            "raw_text": '{"tool_call": "xxx", "arg1": "value1"}',
        }]
        result = fix_mistake1(message)
        expected_raw = {"tool_call": "xxx", "tool_args": {"arg1": "value1"}}
        assert simplejson.loads(result[0]["raw_text"]) == expected_raw

    def test_kwargs_ignored(self):
        """Test extra kwargs are ignored."""
        message = [{
            "step_name": "action",
            "tool_call": "xxx",
            "arg1": "value1",
        }]
        result = fix_mistake1(message, extra_param="ignored")
        expected = [{
            "step_name": "action",
            "tool_call": "xxx",
            "tool_args": {"arg1": "value1"},
        }]
        assert result == expected


class TestFixMistake2:
    """Tests for fix_mistake2 function."""

    def test_string_with_action_tags(self):
        """Test string containing <action> tags is fixed."""
        message = 'hello\n<action>\n{"tool_call": "xxx", "arg1": "value1"}\n</action>'
        result = fix_mistake2(message)
        assert result[0]["step_name"] == "action"
        parsed = simplejson.loads(result[0]["raw_text"])
        assert parsed == {"tool_call": "xxx", "tool_args": {"arg1": "value1"}}

    def test_string_starting_with_action(self):
        """Test string starting with <action> is fixed."""
        message = '<action>\n{"tool_call": "xxx", "arg1": "value1"}\n</action>'
        result = fix_mistake2(message)
        assert result[0]["step_name"] == "action"
        parsed = simplejson.loads(result[0]["raw_text"])
        assert parsed == {"tool_call": "xxx", "tool_args": {"arg1": "value1"}}

    def test_string_without_action_tags(self):
        """Test string without <action> tags returns None."""
        message = "hello world"
        result = fix_mistake2(message)
        assert result is None

    def test_list_with_raw_text_containing_action(self):
        """Test list with raw_text containing <action> tags."""
        message = [{
            "step_name": "action",
            "raw_text": '<action>\n{"tool_call": "xxx", "arg1": "value1"}\n</action>',
        }]
        result = fix_mistake2(message)
        assert len(result) == 2
        assert result[0]["step_name"] == "action"
        assert result[0]["raw_text"] == '<action>\n{"tool_call": "xxx", "arg1": "value1"}\n</action>'
        assert result[1]["step_name"] == "action"
        parsed = simplejson.loads(result[1]["raw_text"])
        assert parsed == {"tool_call": "xxx", "tool_args": {"arg1": "value1"}}

    def test_list_without_action_in_raw_text(self):
        """Test list without <action> in raw_text returns None."""
        message = [{
            "step_name": "action",
            "raw_text": "hello world",
        }]
        result = fix_mistake2(message)
        assert result is None

    def test_non_string_non_list(self):
        """Test non-string, non-list input returns None."""
        result = fix_mistake2(123)
        assert result is None

    def test_empty_string(self):
        """Test empty string returns None."""
        result = fix_mistake2("")
        assert result is None

    def test_action_without_closing_tag(self):
        """Test string with <action> but no </action> returns None."""
        message = '<action>\n{"tool_call": "xxx"}'
        result = fix_mistake2(message)
        assert result is None

    def test_list_with_multiple_items(self):
        """Test list with multiple items returns None."""
        message = [
            {"step_name": "action", "raw_text": "hello"},
            {"step_name": "action", "raw_text": "world"},
        ]
        result = fix_mistake2(message)
        assert result is None

    def test_raw_text_already_has_tool_args(self):
        """Test raw_text with <action> but already has tool_args returns None."""
        message = '<action>\n{"tool_call": "xxx", "tool_args": {"arg1": "value1"}}\n</action>'
        result = fix_mistake2(message)
        assert result is None


class TestMistakesDict:
    """Tests for MISTAKES dictionary."""

    def test_contains_fix_mistake1(self):
        """Test MISTAKES contains fix_mistake1."""
        assert "fix_mistake1" in MISTAKES
        assert MISTAKES["fix_mistake1"] == fix_mistake1

    def test_contains_fix_mistake2(self):
        """Test MISTAKES contains fix_mistake2."""
        assert "fix_mistake2" in MISTAKES
        assert MISTAKES["fix_mistake2"] == fix_mistake2

    def test_mistakes_length(self):
        """Test MISTAKES has exactly 2 entries."""
        assert len(MISTAKES) == 2
