"""
Unit tests for topsailai.ai_base.llm_hooks.hook_after_chat.kimi module.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-19
Purpose: Test Kimi LLM hook - convert kimi format to standard format
"""

import pytest
from topsailai.ai_base.llm_control.exception import ModelServiceError
from topsailai.ai_base.llm_control.message import format_response
from topsailai.ai_base.llm_hooks.hook_after_chat.kimi import (
    convert_to_list_dict,
    hook_execute,
)

class TestConvertToListDict:
    """Test convert_to_list_dict function"""

    def test_basic_tool_call_conversion(self):
        """Test basic kimi tool call format conversion"""
        content = '<|tool_calls_section_begin|><|tool_call_begin|>functions.ctx_tool-retrieve_msg:4<|tool_call_argument_begin|>{"msg_id":"8099aefe5e6fcfb862b3d296a1cd9d80"}<|tool_call_end|><|tool_calls_section_end|>'
        result = convert_to_list_dict(content)
        
        assert len(result) == 1
        assert result[0]["step_name"] == "action"
        assert result[0]["tool_call"] == "ctx_tool-retrieve_msg"
        assert result[0]["tool_args"] == {"msg_id": "8099aefe5e6fcfb862b3d296a1cd9d80"}

    def test_tool_call_with_whitespace(self):
        """Test kimi tool call with variable whitespace"""
        content = '  <|tool_calls_section_begin|>   <|tool_call_begin|>  functions.file_tool-read_file:1  <|tool_call_argument_begin|>  {"file_path":"/tmp/test.txt"}  <|tool_call_end|>    <|tool_calls_section_end|>  '
        result = convert_to_list_dict(content)
        
        assert len(result) == 1
        assert result[0]["tool_call"] == "file_tool-read_file"
        assert result[0]["tool_args"] == {"file_path": "/tmp/test.txt"}

    def test_multiple_tool_calls_in_separate_sections(self):
        """Test multiple tool calls in separate sections"""
        content = '<|tool_calls_section_begin|><|tool_call_begin|>functions.cmd_tool-exec_cmd:1<|tool_call_argument_begin|>{"cmd":"echo ok"}<|tool_call_end|><|tool_calls_section_end|><|tool_calls_section_begin|><|tool_call_begin|>functions.file_tool-read_file:2<|tool_call_argument_begin|>{"file_path":"/tmp/1.txt"}<|tool_call_end|><|tool_calls_section_end|>'
        result = convert_to_list_dict(content)
        
        assert len(result) == 2
        assert result[0]["tool_call"] == "cmd_tool-exec_cmd"
        assert result[1]["tool_call"] == "file_tool-read_file"

    def test_empty_tool_name_skipped(self):
        """Test that empty tool names are skipped"""
        content = '<|tool_calls_section_begin|><|tool_call_begin|>functions.:1<|tool_call_argument_begin|>{}<|tool_call_end|><|tool_calls_section_end|>'
        result = convert_to_list_dict(content)
        
        assert len(result) == 0

    def test_invalid_json_args(self):
        """Test invalid JSON does not become a tool call with empty arguments"""
        content = '<|tool_calls_section_begin|><|tool_call_begin|>functions.test_tool:1<|tool_call_argument_begin|>{invalid json}<|tool_call_end|><|tool_calls_section_end|>'

        assert convert_to_list_dict(content) == []
        with pytest.raises(ModelServiceError):
            hook_execute(content)

    def test_empty_content(self):
        """Test with empty content string"""
        result = convert_to_list_dict("")
        assert result == []

    def test_no_tool_calls_in_content(self):
        """Test content without tool call markers"""
        result = convert_to_list_dict("Just some regular text without tool calls")
        assert result == []

    def test_tool_name_with_hyphen(self):
        """Test tool name containing hyphen"""
        content = '<|tool_calls_section_begin|><|tool_call_begin|>functions.file-readonly-tool:1<|tool_call_argument_begin|>{}<|tool_call_end|><|tool_calls_section_end|>'
        result = convert_to_list_dict(content)
        
        assert len(result) == 1
        assert result[0]["tool_call"] == "file-readonly-tool"

    @pytest.mark.parametrize(
        "tail",
        [
            "<|tool_call_end|><|tool_calls_section_end|>",
            "<|tool_call_argument_end|><|tool_call_end|>",
            "",
            '\n{"tool_args":{"ignored":true},"tool_call":"cmd_tool-exec_cmd"}',
        ],
    )
    def test_preserves_arguments_for_supported_kimi_tails(self, tail, monkeypatch):
        """Test complete, argument-end, missing-tail, and repeated-output formats"""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        arguments = {"nested": {"items": [1, {"value": 'quoted "{text}"'}]}}
        content = (
            "<|tool_calls_section_begin|><|tool_call_begin|>"
            "functions.cmd_tool-exec_cmd:23<|tool_call_argument_begin|>"
            '{"cmd":"run","timeout":120,"nested":{"items":[1,{"value":"quoted \\\"{text}\\\""}]}}'
            f"{tail}"
        )

        result = format_response(content)

        assert result == [{
            "step_name": "action",
            "tool_call": "cmd_tool-exec_cmd",
            "tool_args": {"cmd": "run", "timeout": 120, **arguments},
        }]



class TestHookExecute:
    """Test hook_execute function"""

    def test_execute_with_tool_calls(self):
        """Test hook_execute returns list when tool calls found"""
        content = '<|tool_calls_section_begin|><|tool_call_begin|>functions.test:1<|tool_call_argument_begin|>{}<|tool_call_end|><|tool_calls_section_end|>'
        result = hook_execute(content)
        
        assert isinstance(result, list)
        assert len(result) == 1

    def test_execute_without_tool_calls(self):
        """Test hook_execute returns original string when no tool calls"""
        content = "Just some regular text"
        result = hook_execute(content)
        
        assert result == content

    def test_execute_strips_whitespace(self):
        """Test hook_execute strips leading/trailing whitespace"""
        content = '   <|tool_calls_section_begin|><|tool_call_begin|>functions.test:1<|tool_call_argument_begin|>{}<|tool_call_end|><|tool_calls_section_end|>   '
        result = hook_execute(content)
        
        assert isinstance(result, list)

    def test_execute_with_empty_string(self):
        """Test hook_execute with empty string returns empty string (not list)"""
        result = hook_execute("")
        # Empty string stripped is still empty, convert_to_list_dict returns [],
        # so hook_execute returns the stripped content (empty string)
        assert result == ""

    def test_execute_with_only_whitespace(self):
        """Test hook_execute with only whitespace returns empty string"""
        result = hook_execute("   ")
        # Whitespace stripped becomes empty, convert_to_list_dict returns [],
        # so hook_execute returns empty string
        assert result == ""


class TestHookExecuteEdgeCases:
    """Test hook_execute edge cases"""

    def test_execute_with_partial_markers(self):
        """Test hook_execute with partial markers raises ModelServiceError"""
        content = "<|tool_calls_section_begin|> but no end"
        with pytest.raises(ModelServiceError):
            hook_execute(content)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
