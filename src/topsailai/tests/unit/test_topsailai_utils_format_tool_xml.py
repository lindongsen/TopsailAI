"""
Unit tests for format_tool_xml module.

Test cases for the format_xml function which parses XML content
into step dictionaries with thought/action blocks.

Author: mm-m25
"""

import pytest
from src.topsailai.utils.format_tool_xml import format_xml


class TestFormatXml:
    """Test suite for format_xml function."""

    def test_format_xml_valid_thought_and_action(self):
        """Parse valid XML with both thought and action blocks."""
        xml_content = """
        <thought>
        hello
        </thought>

        <action>
        {"tool_call": "cmd_tool-exec_cmd", "tool_args": {"cmd": "echo ok"}}
        </action>
        """
        result = format_xml(xml_content)
        assert len(result) == 2
        assert result[0]["step_name"] == "thought"
        assert result[0]["raw_text"] == "hello"
        assert result[1]["step_name"] == "action"
        assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
        assert result[1]["tool_args"] == {"cmd": "echo ok"}
        assert "raw_text" not in result[1]

    def test_format_xml_thought_only(self):
        """Parse XML with only thought block (no action)."""
        xml_content = "<thought>This is a thought</thought>"
        result = format_xml(xml_content)
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"
        assert result[0]["raw_text"] == "This is a thought"

    def test_format_xml_action_only(self):
        """Parse XML with only action block (no thought)."""
        xml_content = '<action>{"tool_call": "test_tool", "tool_args": {}}</action>'
        result = format_xml(xml_content)
        assert len(result) == 1
        assert result[0]["step_name"] == "action"
        assert result[0]["tool_call"] == "test_tool"
        assert result[0]["tool_args"] == {}

    def test_format_xml_invalid_xml(self):
        """Parse invalid/malformed XML returns empty list."""
        xml_content = "<thought>unclosed tag"
        result = format_xml(xml_content)
        assert result == []

    def test_format_xml_empty_string(self):
        """Parse empty string returns empty list."""
        result = format_xml("")
        assert result == []

    def test_format_xml_empty_element_text(self):
        """Parse XML with empty element text results in raw_text being empty string."""
        xml_content = "<thought></thought>"
        result = format_xml(xml_content)
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"
        assert result[0]["raw_text"] == ""

    def test_format_xml_action_with_valid_json(self):
        """Parse action block with valid JSON extracts tool_call and tool_args."""
        xml_content = '''
        <action>
        {"tool_call": "file_tool-read_file", "tool_args": {"file_path": "/test.txt"}}
        </action>
        '''
        result = format_xml(xml_content)
        assert len(result) == 1
        assert result[0]["step_name"] == "action"
        assert result[0]["tool_call"] == "file_tool-read_file"
        assert result[0]["tool_args"] == {"file_path": "/test.txt"}
        assert "raw_text" not in result[0]

    def test_format_xml_action_with_invalid_json(self):
        """Parse action block with invalid JSON falls back to raw_text."""
        xml_content = "<action>not valid json content</action>"
        result = format_xml(xml_content)
        assert len(result) == 1
        assert result[0]["step_name"] == "action"
        assert result[0]["raw_text"] == "not valid json content"
        assert "tool_call" not in result[0]
        assert "tool_args" not in result[0]

    def test_format_xml_multiple_thought_blocks(self):
        """Parse XML with multiple thought blocks."""
        xml_content = """
        <thought>First thought</thought>
        <thought>Second thought</thought>
        <thought>Third thought</thought>
        """
        result = format_xml(xml_content)
        assert len(result) == 3
        assert result[0]["step_name"] == "thought"
        assert result[0]["raw_text"] == "First thought"
        assert result[1]["step_name"] == "thought"
        assert result[1]["raw_text"] == "Second thought"
        assert result[2]["step_name"] == "thought"
        assert result[2]["raw_text"] == "Third thought"

    def test_format_xml_whitespace_stripped(self):
        """Parse XML with whitespace in element text is stripped correctly."""
        xml_content = """
        <thought>
            Leading and trailing whitespace should be removed
        </thought>
        """
        result = format_xml(xml_content)
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"
        assert result[0]["raw_text"] == "Leading and trailing whitespace should be removed"
