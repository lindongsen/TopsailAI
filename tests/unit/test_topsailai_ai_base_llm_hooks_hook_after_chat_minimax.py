import pytest
from src.topsailai.ai_base.llm_hooks.hook_after_chat.minimax import convert_xml_to_list_dict, hook_execute


def test_convert_xml_to_list_dict_with_thought_and_action():
    """Test conversion with both thought and action."""
    raw_content = '''<think>hello
</think>

<minimax:tool_call>
<invoke name="cmd_tool-exec_cmd">
<tool_args>{"cmd": "echo ok"}</tool_args>
<tool_call>cmd_tool-exec_cmd</tool_call>
</invoke>'''
    
    result = convert_xml_to_list_dict(raw_content)
    
    assert len(result) == 2
    assert result[0]["step_name"] == "thought"
    assert result[0]["raw_text"] == "hello"
    assert result[1]["step_name"] == "action"
    assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[1]["tool_args"] == {"cmd": "echo ok"}


def test_convert_xml_to_list_dict_with_thought_only():
    """Test conversion with only thought."""
    raw_content = '''<think>hello
</think>'''
    
    result = convert_xml_to_list_dict(raw_content)
    
    assert len(result) == 1
    assert result[0]["step_name"] == "thought"
    assert result[0]["raw_text"] == "hello"


def test_convert_xml_to_list_dict_with_action_only():
    """Test conversion with only action."""
    raw_content = '''<minimax:tool_call>
<invoke name="cmd_tool-exec_cmd">
<tool_args>{"cmd": "echo ok"}</tool_args>
<tool_call>cmd_tool-exec_cmd</tool_call>
</invoke>'''
    
    result = convert_xml_to_list_dict(raw_content)
    
    assert len(result) == 1
    assert result[0]["step_name"] == "action"
    assert result[0]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[0]["tool_args"] == {"cmd": "echo ok"}


def test_convert_xml_to_list_dict_with_invalid_json():
    """Test conversion with invalid JSON in tool_args."""
    raw_content = '''<minimax:tool_call>
<invoke name="cmd_tool-exec_cmd">
<tool_args>invalid json</tool_args>
<tool_call>cmd_tool-exec_cmd</tool_call>
</invoke>'''
    
    result = convert_xml_to_list_dict(raw_content)
    
    assert len(result) == 1
    assert result[0]["step_name"] == "action"
    assert result[0]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[0]["tool_args"] == {}


def test_convert_xml_to_list_dict_empty_content():
    """Test conversion with empty content."""
    raw_content = ""
    
    result = convert_xml_to_list_dict(raw_content)
    
    assert result == []


def test_hook_execute_with_minimax():
    """Test hook_execute with minimax content."""
    content = '''<think>hello
</think>

<minimax:tool_call>
<invoke name="cmd_tool-exec_cmd">
<tool_args>{"cmd": "echo ok"}</tool_args>
<tool_call>cmd_tool-exec_cmd</tool_call>
</invoke>'''
    
    result = hook_execute(content)
    
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["step_name"] == "thought"
    assert result[0]["raw_text"] == "hello"
    assert result[1]["step_name"] == "action"
    assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[1]["tool_args"] == {"cmd": "echo ok"}


def test_hook_execute_without_minimax():
    """Test hook_execute without minimax content."""
    content = "Hello world"
    
    result = hook_execute(content)
    
    assert result == "Hello world"


def test_hook_execute_with_non_string():
    """Test hook_execute with non-string content."""
    content = ["test"]
    
    result = hook_execute(content)
    
    assert result == ["test"]
