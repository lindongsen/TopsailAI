import pytest
import json
from collections import OrderedDict
from src.topsailai.utils.format_tool import (
    to_list,
    fix_llm_mistakes,
    parse_topsailai_format,
    format_dict_to_list,
    to_topsailai_format
)


class TestToList:
    """Test cases for to_list function"""

    def test_to_list_list(self):
        """Test converting list to list"""
        result = to_list([1, 2, 3])
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_to_list_tuple(self):
        """Test converting tuple to list"""
        result = to_list((1, 2, 3))
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_to_list_set(self):
        """Test converting set to list"""
        result = to_list({1, 2, 3})
        assert sorted(result) == [1, 2, 3]
        assert isinstance(result, list)

    def test_to_list_single_value(self):
        """Test converting single value to list"""
        result = to_list(42)
        assert result == [42]
        assert isinstance(result, list)

    def test_to_list_none(self):
        """Test converting None to list"""
        result = to_list(None)
        assert result == [None]
        assert isinstance(result, list)

    def test_to_list_none_ignore(self):
        """Test converting None with ignore_none=True"""
        result = to_list(None, to_ignore_none=True)
        assert result is None

    def test_to_list_empty_list(self):
        """Test converting empty list"""
        result = to_list([])
        assert result == []
        assert isinstance(result, list)


class TestFixLLMMistakes:
    """Test cases for fix_llm_mistakes function"""

    def test_fix_llm_mistakes_no_issues(self):
        """Test text with correct formatting"""
        text = "\ntopsailai.thought\nHello\ntopsailai.action\nWorld"
        result = fix_llm_mistakes(text)
        assert result == text

    def test_fix_llm_mistakes_missing_newline_before(self):
        """Test missing newline before step marker"""
        text = "xtopsailai.thought\nHello"
        result = fix_llm_mistakes(text)
        assert result == "x\ntopsailai.thought\nHello"

    def test_fix_llm_mistakes_missing_newline_after(self):
        """Test missing newline after step marker"""
        text = "\ntopsailai.thoughtHello"
        result = fix_llm_mistakes(text)
        assert result == "\ntopsailai.thought\nHello"

    def test_fix_llm_mistakes_start_with_step(self):
        """Test text starting with step marker"""
        text = "topsailai.thoughtHello"
        result = fix_llm_mistakes(text)
        assert result == "topsailai.thought\nHello"

    def test_fix_llm_mistakes_multiple_step_keys(self):
        """Test with multiple step keys"""
        text = "xtopsailai.actionHello"
        result = fix_llm_mistakes(text, step_keys=("thought", "action"))
        assert result == "xtopsailai.actionHello"


class TestParseTopsailaiFormat:
    """Test cases for parse_topsailai_format function"""

    def test_parse_topsailai_format_single_step(self):
        """Test parsing single step"""
        text = "topsailai.thought\nHello World"
        result = parse_topsailai_format(text)
        expected = OrderedDict([("thought", "Hello World")])
        assert result == expected

    def test_parse_topsailai_format_multiple_steps(self):
        """Test parsing multiple steps"""
        text = "topsailai.thought\nThinking\ntopsailai.action\nDoing"
        result = parse_topsailai_format(text)
        expected = OrderedDict([("thought", "Thinking"), ("action", "Doing")])
        assert result == expected

    def test_parse_topsailai_format_empty_content(self):
        """Test parsing step with empty content"""
        text = "topsailai.thought\n\ntopsailai.action\nAction"
        result = parse_topsailai_format(text)
        expected = OrderedDict([("thought", ""), ("action", "Action")])
        assert result == expected

    def test_parse_topsailai_format_multiline_content(self):
        """Test parsing step with multiline content"""
        text = "topsailai.thought\nLine 1\nLine 2\ntopsailai.action\nAction"
        result = parse_topsailai_format(text)
        expected = OrderedDict([("thought", "Line 1\nLine 2"), ("action", "Action")])
        assert result == expected

    def test_parse_topsailai_format_empty_input(self):
        """Test parsing empty input"""
        result = parse_topsailai_format("")
        assert result == OrderedDict()


class TestFormatDictToList:
    """Test cases for format_dict_to_list function"""

    def test_format_dict_to_list_basic(self):
        """Test basic dictionary conversion"""
        d = {"a": 1, "b": 2}
        result = format_dict_to_list(d, "name", "value")
        expected = [
            {"name": "a", "value": 1},
            {"name": "b", "value": 2}
        ]
        assert result == expected

    def test_format_dict_to_list_empty(self):
        """Test empty dictionary conversion"""
        result = format_dict_to_list({}, "name", "value")
        assert result == []

    def test_format_dict_to_list_nested_values(self):
        """Test dictionary with nested values"""
        d = {"key1": {"nested": "value1"}, "key2": [1, 2, 3]}
        result = format_dict_to_list(d, "id", "data")
        expected = [
            {"id": "key1", "data": {"nested": "value1"}},
            {"id": "key2", "data": [1, 2, 3]}
        ]
        assert result == expected


class TestToTopsailaiFormat:
    """Test cases for to_topsailai_format function"""

    def test_to_topsailai_format_string_input(self):
        """Test string input (should return as-is if key not found)"""
        result = to_topsailai_format("plain text", "step", "text")
        assert result == "plain text"

    def test_to_topsailai_format_dict_list(self):
        """Test list of dictionaries input"""
        content = [{"step": "thought", "text": "Thinking"}]
        result = to_topsailai_format(content, "step", "text")
        expected = "topsailai.thought\nThinking\n\n"
        assert result == expected

    def test_to_topsailai_format_multiple_dicts(self):
        """Test multiple dictionaries input"""
        content = [
            {"step": "thought", "text": "Thinking"},
            {"step": "action", "text": "Doing"}
        ]
        result = to_topsailai_format(content, "step", "text")
        expected = "topsailai.thought\nThinking\n\ntopsailai.action\nDoing\n\n"
        assert result == expected

    def test_to_topsailai_format_with_extra_fields(self):
        """Test with additional fields beyond key and value"""
        content = [{"step": "thought", "text": "Thinking", "timestamp": "2025-01-01"}]
        result = to_topsailai_format(content, "step", "text")
        # Should include the extra field as JSON
        assert "timestamp" in result
        assert "2025-01-01" in result

    def test_to_topsailai_format_for_print_complex_values(self):
        """Test for_print=True with complex values"""
        content = [{"step": "thought", "text": {"complex": "data"}}]
        result = to_topsailai_format(content, "step", "text", for_print=True)
        # Should serialize complex values to JSON
        assert '"complex": "data"' in result

    def test_to_topsailai_format_string_with_key(self):
        """Test string input containing the key"""
        content = '{"step": "thought", "text": "Thinking"}'
        result = to_topsailai_format(content, "step", "text")
        expected = "topsailai.thought\nThinking\n\n"
        assert result == expected
