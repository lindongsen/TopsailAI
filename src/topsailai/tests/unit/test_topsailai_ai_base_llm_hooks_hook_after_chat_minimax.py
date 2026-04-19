"""
Unit tests for topsailai.ai_base.llm_hooks.hook_after_chat.minimax module.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-19
Purpose: Test MiniMax LLM hook - convert minimax XML format to standard format
"""

import pytest
from topsailai.ai_base.llm_hooks.hook_after_chat.minimax import (
    convert_xml_to_list_dict,
    convert_xml_to_list_dict2,
    convert_tool_call_case1,
    hook_execute,
)


class TestConvertXmlToListDict:
    """Test convert_xml_to_list_dict function - handles <tool_call> format"""

    def test_basic_tool_call_conversion(self):
        """Test basic minimax XML tool call format with <tool_call> tags"""
        content = '''
    <tool_call>cmd_tool-exec_cmd</tool_call>
    <tool_args>{"cmd": "echo ok"}</tool_args>
        '''
        result = convert_xml_to_list_dict(content)
        
        assert isinstance(result, list)

    def test_tool_call_with_minimax_marker(self):
        """Test minimax marker triggers conversion"""
        content = 'minimax content\n<tool_call>cmd_tool-exec_cmd</tool_call>\n<tool_args>{"cmd":"echo ok"}</tool_args>'
        result = convert_xml_to_list_dict(content)
        
        assert isinstance(result, list)

    def test_empty_content(self):
        """Test with empty content string"""
        result = convert_xml_to_list_dict("")
        assert result == []

    def test_no_tool_calls_in_content(self):
        """Test content without tool call markers"""
        result = convert_xml_to_list_dict("Just some regular text without tool calls")
        assert result == []


class TestConvertXmlToListDict2:
    """Test convert_xml_to_list_dict2 function"""

    def test_basic_conversion(self):
        """Test basic conversion"""
        content = "minimax content"
        result = convert_xml_to_list_dict2(content)
        
        assert isinstance(result, list)

    def test_empty_content(self):
        """Test with empty content"""
        result = convert_xml_to_list_dict2("")
        assert result == []


class TestConvertToolCallCase1:
    """Test convert_tool_call_case1 function - handles [TOOL_CALL] format"""

    def test_basic_tool_call_conversion(self):
        """Test basic [TOOL_CALL] format conversion"""
        content = '''[TOOL_CALL]
file_readonly_tool-list_dirs
[TOOL_ARGS]
{"dirs": ["/tmp/123"]}
[/TOOL_CALL]'''
        result = convert_tool_call_case1(content)
        
        assert len(result) == 1
        assert result[0]["step_name"] == "action"
        assert result[0]["tool_call"] == "file_readonly_tool-list_dirs"
        assert result[0]["tool_args"] == {"dirs": ["/tmp/123"]}

    def test_multiple_tool_calls(self):
        """Test multiple tool calls"""
        content = '''[TOOL_CALL]
test_tool1
[TOOL_ARGS]
{"key": "value1"}
[/TOOL_CALL]
[TOOL_CALL]
test_tool2
[TOOL_ARGS]
{"key": "value2"}
[/TOOL_CALL]'''
        result = convert_tool_call_case1(content)
        
        assert len(result) == 2
        assert result[0]["tool_call"] == "test_tool1"
        assert result[1]["tool_call"] == "test_tool2"

    def test_empty_content(self):
        """Test with empty content"""
        result = convert_tool_call_case1("")
        assert result == []

    def test_no_tool_calls(self):
        """Test content without [TOOL_CALL] markers"""
        result = convert_tool_call_case1("Just some regular text")
        assert result == []


class TestHookExecute:
    """Test hook_execute function"""

    def test_execute_with_minimax_and_tool_call(self):
        """Test hook_execute processes minimax content with <tool_call>"""
        content = '''minimax content
<tool_call>test</tool_call>
<tool_args>{}</tool_args>'''
        result = hook_execute(content)
        
        assert isinstance(result, list)

    def test_execute_with_tool_call_bracket_format(self):
        """Test hook_execute processes [TOOL_CALL] format"""
        content = '''[TOOL_CALL]
test_tool
[TOOL_ARGS]
{}
[/TOOL_CALL]'''
        result = hook_execute(content)
        
        assert isinstance(result, list)
        assert len(result) == 1

    def test_execute_without_tool_calls_returns_original(self):
        """Test hook_execute returns original string when no tool calls"""
        content = "Just some regular text without tool calls"
        result = hook_execute(content)
        
        assert result == content

    def test_execute_with_empty_string(self):
        """Test hook_execute with empty string returns empty string"""
        result = hook_execute("")
        assert result == ""

    def test_execute_with_non_string_input(self):
        """Test hook_execute handles non-string input"""
        result = hook_execute(123)
        assert result == 123
        
        result = hook_execute(None)
        assert result is None


class TestHookExecuteEdgeCases:
    """Test hook_execute edge cases"""

    def test_execute_with_only_whitespace(self):
        """Test hook_execute with only whitespace"""
        result = hook_execute("   ")
        # Whitespace stripped, convert_xml_to_list_dict returns [],
        # so hook_execute returns empty string
        assert result == ""

    def test_execute_with_minimax_marker_only(self):
        """Test hook_execute with minimax marker but no tool calls"""
        content = "minimax content without tool calls"
        result = hook_execute(content)
        
        # Returns list from convert_xml_to_list_dict2
        assert isinstance(result, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
