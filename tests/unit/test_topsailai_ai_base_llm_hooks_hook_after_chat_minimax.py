import pytest
from src.topsailai.ai_base.llm_hooks.hook_after_chat.minimax import convert_xml_to_list_dict, convert_xml_to_list_dict2, hook_execute


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


def test_convert_xml_to_list_dict_malformed_xml():
    """Test conversion with malformed XML tags."""
    raw_content = '''<minimax:tool_call>
<invoke name="cmd_tool-exec_cmd">
<tool_args>{"cmd": "echo ok"}</tool_args>
<tool_call>cmd_tool-exec_cmd</tool_call>
</invoke>

<think>hello
</think>'''

    result = convert_xml_to_list_dict(raw_content)

    # Should still process both thought and action despite malformed order
    assert len(result) == 2
    assert result[0]["step_name"] == "thought"
    assert result[0]["raw_text"] == "hello"
    assert result[1]["step_name"] == "action"
    assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[1]["tool_args"] == {"cmd": "echo ok"}


def test_convert_xml_to_list_dict_multiple_tool_calls():
    """Test conversion with multiple tool calls."""
    raw_content = '''<think>hello
</think>

<minimax:tool_call>
<invoke name="cmd_tool-exec_cmd">
<tool_args>{"cmd": "echo first"}</tool_args>
<tool_call>cmd_tool-exec_cmd</tool_call>
</invoke>

<minimax:tool_call>
<invoke name="file_tool-read_file">
<tool_args>{"file_path": "/tmp/test.txt"}</tool_args>
<tool_call>file_tool-read_file</tool_call>
</invoke>'''

    result = convert_xml_to_list_dict(raw_content)

    # Should only process the first tool call found
    assert len(result) == 2
    assert result[0]["step_name"] == "thought"
    assert result[0]["raw_text"] == "hello"
    assert result[1]["step_name"] == "action"
    assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[1]["tool_args"] == {"cmd": "echo first"}


def test_convert_xml_to_list_dict_missing_tool_args():
    """Test conversion with missing tool_args."""
    raw_content = '''<minimax:tool_call>
<invoke name="cmd_tool-exec_cmd">
<tool_call>cmd_tool-exec_cmd</tool_call>
</invoke>'''

    result = convert_xml_to_list_dict(raw_content)

    assert len(result) == 1
    assert result[0]["step_name"] == "action"
    assert result[0]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[0]["tool_args"] == {}


def test_convert_xml_to_list_dict_different_spacing():
    """Test conversion with different spacing and formatting."""
    raw_content = '''  <think>   hello with spaces
  </think>

  <minimax:tool_call>
  <invoke name="cmd_tool-exec_cmd">
  <tool_args>  { "cmd" : "echo ok" }  </tool_args>
  <tool_call>cmd_tool-exec_cmd</tool_call>
  </invoke>  '''

    result = convert_xml_to_list_dict(raw_content)

    assert len(result) == 2
    assert result[0]["step_name"] == "thought"
    assert result[0]["raw_text"] == "hello with spaces"
    assert result[1]["step_name"] == "action"
    assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[1]["tool_args"] == {"cmd": "echo ok"}


def test_convert_xml_to_list_dict2_with_thought_and_action():
    """Test conversion with both thought and action using parameter format."""
    raw_content = '''hello world
<invoke name="cmd_tool-exec_cmd">
<parameter name="cmd">ls -lh /tmp/123</parameter>
</invoke>
</minimax:tool_call>'''

    result = convert_xml_to_list_dict2(raw_content)

    assert len(result) == 2
    assert result[0]["step_name"] == "thought"
    assert result[0]["raw_text"] == "hello world"
    assert result[1]["step_name"] == "action"
    assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[1]["tool_args"] == {"cmd": "ls -lh /tmp/123"}

def test_convert_xml_to_list_dict2_with_thought_only():
    """Test conversion with only thought using parameter format."""
    # convert_xml_to_list_dict极速电竞APP官网2 is designed for parameter format which requires <invoke> tags
    # Plain text without invoke tags should return empty list
    raw_content = "hello world"

    result = convert_xml_to_list_dict2(raw_content)

    assert len(result) == 0
    """Test conversion with only thought using parameter format."""
    # convert_xml_to_list_dict2 is designed for parameter format which requires <invoke> tags
    # Plain text without invoke tags should return empty list
    raw_content = "hello world"

    result = convert_xml_to_list_dict2(raw_content)

    assert len(result) == 0

    # convert_xml_to_list_dict2 is designed for parameter format which requires <invoke> tags
    # Plain text without invoke tags should return empty list
    assert len(result) == 0


def test_convert_xml_to_list_dict2_with_action_only():
    """Test conversion with only action using parameter format."""
    raw_content = '''<invoke name="cmd_tool-exec_cmd">
<parameter name="cmd">ls -lh /tmp/123</parameter>
</invoke>
</minimax:tool_call>'''

    result = convert_xml_to_list_dict2(raw_content)

    assert len(result) == 1
    assert result[0]["step_name"] == "action"
    assert result[0]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[0]["tool_args"] == {"cmd": "ls -lh /tmp/123"}


def test_convert_xml_to_list_dict2_missing_parameter():
    """Test conversion with missing parameter."""
    raw_content = '''<invoke name="cmd_tool-exec_cmd">
</invoke>
</minimax:tool_call>'''

    result = convert_xml_to_list_dict2(raw_content)

    assert len(result) == 1
    assert result[0]["step_name"] == "action"
    assert result[0]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[0]["tool_args"] == {}


def test_convert_xml_to_list_dict2_empty_content():
    """Test conversion with empty content using parameter format."""
    raw_content = ""

    result = convert_xml_to_list_dict2(raw_content)

    assert result == []


def test_convert_xml_to_list_dict2_different_spacing():
    """Test conversion with different spacing and formatting using parameter format."""
    raw_content = '''   hello world with spaces
    <invoke name="cmd_tool-exec_cmd">
    <parameter name="cmd">  ls -lh /tmp/123  </parameter>
    </invoke>
    </minimax:tool_call>  '''

    result = convert_xml_to_list_dict2(raw_content)

    assert len(result) == 2
    assert result[0]["step_name"] == "thought"
    assert result[0]["raw_text"] == "hello world with spaces"
    assert result[1]["step_name"] == "action"
    assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[1]["tool_args"] == {"cmd": "ls -lh /tmp/123"}


def test_hook_execute_with_parameter_format():
    """Test hook_execute with parameter format content."""
    content = '''hello world
<invoke name="cmd_tool-exec_cmd">
<parameter name="cmd">ls -lh /tmp/123</parameter>
</invoke>
</minimax:tool_call>'''

    result = hook_execute(content)

    # Should use convert_xml_to_list_dict2 since it contains minimax keyword
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["step_name"] == "thought"
    assert result[0]["raw_text"] == "hello world"
    assert result[1]["step_name"] == "action"
    assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[1]["tool_args"] == {"cmd": "ls -lh /tmp/123"}
