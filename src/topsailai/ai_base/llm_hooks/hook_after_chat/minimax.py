'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-01-29
Purpose: Convert XML-like content from Minimax to standard format
'''

import json
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Union

def convert_xml_to_list_dict(raw_content: str) -> List[Dict[str, Any]]:
    """
    Convert XML-like content to a list of dictionaries

    Example input1 (raw_content):
    ```
    <think>hello
    </think>


    <minimax:tool_call>
    <invoke name="cmd-tool-exec_cmd">
    <tool_args>{"cmd": "echo ok"}</tool_args>
    <tool_call>cmd_tool-exec_cmd</tool_call>
    </invoke>

    ```

    Example output1:
    ```
    [
    {"step_name":"thought", "raw_text": "hello"},
    {"step_name":"action", "tool_call":"cmd_tool-exec_cmd","tool_args":{"cmd":"echo ok"}}
    ]
    ```

    Example input2:
    ```
        <minimax:tool_call>
        tool_call: "file_readonly_tool-read_files"
        tool_args: {"file1": "/tmp/1.txt"}
    ```

    Example input3:
    ```
        <minimax:tool_call>
        <tool_call>"file_readonly_tool-read_files"</tool_call>
        <tool_args>{"file1": "/tmp/1.txt"}</tool_args>
    ```

    Example output2:
    ```
    [
        {
            "step_name": "action",
            "tool_call": "file_readonly_tool-read_files",
            "tool_args": {"file1": "/tmp/1.txt"}
        }
    ]
    ```

    Args:
        raw_content: Raw XML-like string content

    Returns:
        List[Dict[str, Any]]: Converted list of dictionaries
    """
    result = []

    # Find <think> tag content
    think_start = raw_content.find("<think>")
    think_end = raw_content.find("</think>", think_start + 7)

    if think_start != -1 and think_end != -1:
        think_content = raw_content[think_start + 7:think_end].strip()
        if think_content:  # Only add if content is not empty
            result.append({
                "step_name": "thought",
                "raw_text": think_content
            })

    # Find <invoke> tag content
    invoke_start = raw_content.find("<invoke name=")
    if invoke_start != -1:
        # Extract tool call name
        name_start = raw_content.find('"', invoke_start + 13) + 1
        name_end = raw_content.find('"', name_start)
        tool_call_name = raw_content[name_start:name_end]

        # Extract tool_args
        tool_args_start = raw_content.find('<tool_args>', invoke_start)
        tool_args_end = raw_content.find('</tool_args>', invoke_start)

        if tool_args_start != -1 and tool_args_end != -1:
            tool_args_start += len('<tool_args>')
            tool_args_str = raw_content[tool_args_start:tool_args_end].strip()
            try:
                tool_args = json.loads(tool_args_str)
            except json.JSONDecodeError:
                # If JSON parsing fails, use empty dict
                tool_args = {}
        else:
            tool_args = {}

        # Add action step
        result.append({
            "step_name": "action",
            "tool_call": tool_call_name,
            "tool_args": tool_args
        })

    return result

def convert_xml_to_list_dict2(raw_content: str) -> List[Dict[str, Any]]:
    """
    Convert XML-like content to a list of dictionaries (version 2)

    ## case
    Example input (raw_content):
    ```
    hello world
    <invoke name="cmd_tool-exec_cmd">
    <parameter name="cmd">ls -lh /tmp/123</parameter>
    </invoke>
    </minimax:tool_call>
    ```

    Example output:
    ```
    [
        {"step_name":"thought", "raw_text": "hello world"},
        {"step_name":"action", "tool_call":"cmd_tool-exec_cmd","tool_args":{"cmd":"ls -lh /tmp/123"}}
    ]
    ```

    ## case
    Example input (raw_content)
    ```
    <invoke name="file_tool-read_file">
    <parameter name="file_path">/tmp/123.txt</parameter>
    </invoke>
    </minimax:tool_call>
    ```

    Example output:
    ```
    [
        {"step_name": "action", "tool_call": "file_tool-read_file", "tool_args": {"file_path":"/tmp/123.txt"}}
    ]
    ```

    Args:
        raw_content: Raw XML-like string content

    Returns:
        List[Dict[str, Any]]: Converted list of dictionaries
    """
    result = []

    # Extract text content before the invoke tag (thought content)
    invoke_start = raw_content.find('<invoke')
    if invoke_start > 0:
        thought_content = raw_content[:invoke_start].strip()
        if thought_content:  # Only add if content is not empty
            result.append({
                "step_name": "thought",
                "raw_text": thought_content
            })

    # Find <invoke> tag content
    invoke_start = raw_content.find('<invoke name=')
    if invoke_start != -1:
        # Extract tool call name
        name_start = raw_content.find('"', invoke_start + 13) + 1
        name_end = raw_content.find('"', name_start)
        tool_call_name = raw_content[name_start:name_end]

        # Extract all parameters
        tool_args = {}
        param_pos = invoke_start

        while True:
            # Find the next parameter tag
            param_start = raw_content.find('<parameter name="', param_pos)
            if param_start == -1:
                break

            # Extract parameter name
            name_start = param_start + len('<parameter name="')
            name_end = raw_content.find('"', name_start)
            param_name = raw_content[name_start:name_end]

            # Extract parameter value
            value_start = raw_content.find('>', name_end) + 1
            value_end = raw_content.find('</parameter>', value_start)
            param_value = raw_content[value_start:value_end].strip()

            # Add to tool_args
            tool_args[param_name] = param_value

            # Move position for next search
            param_pos = value_end + len('</parameter>')

        # Add action step
        result.append({
            "step_name": "action",
            "tool_call": tool_call_name,
            "tool_args": tool_args
        })

    return result


def convert_tool_call_case1(content) -> List[Dict[str, Any]]:
    """Convert tool call content to list of dictionaries

    input example1 (single block with name and args):
        [TOOL_CALL]
        file_readonly_tool-list_dirs
        [TOOL_ARGS]
        {"dirs": ["/tmp/123"]}
        [/TOOL_CALL]

    input example2 (separate blocks for name and args):
        [TOOL_CALL]
        file_readonly_tool-list_dirs
        [/TOOL_CALL]
        [TOOL_CALL]
        [TOOL_ARGS]
        {"dirs": ["/tmp/123"]}
        [/TOOL_CALL]

    input example3 (missing [/TOOL_CALL]):
        [TOOL_CALL]
        file_readonly_tool-list_dirs
        [TOOL_ARGS]
        {"dirs": ["/tmp/123"]}

    input example4 (JSON object directly):
        [TOOL_CALL]
        {
            "tool_call": "file_readonly_tool-list_dirs",
            "tool_args": {"dirs": ["/tmp/123"]}
        }
        [/TOOL_CALL]

    input example5:
        [TOOL_CALL]
        file_readonly_tool-list_dirs
        [/TOOL_CALL]
        [TOOL_ARGS]
        {"dirs": ["/tmp/123"]}
        [/TOOL_ARGS]

    output same:
        [
            {
                "step_name": "action",
                "tool_call": "file_readonly_tool-list_dirs",
                "tool_args": {"dirs": ["/tmp/123"]}
            }
        ]

    Args:
        content (str): Raw content with tool call markers

    Returns:
        List[Dict[str, Any]]: List of action dictionaries
    """
    result = []

    # Track pending tool call (name only, waiting for args)
    pending_tool_call_name = None

    # Parse all [TOOL_CALL] blocks
    tool_call_start = 0
    while True:
        tool_call_start = content.find('[TOOL_CALL]', tool_call_start)
        if tool_call_start == -1:
            break

        # Find the end of this [TOOL_CALL] block
        tool_call_end = content.find('[/TOOL_CALL]', tool_call_start)

        # If no closing tag found (example3), use end of content
        if tool_call_end == -1:
            block_content = content[tool_call_start + len('[TOOL_CALL]'):].strip()
            # Only process if there's content
            if not block_content:
                break
        else:
            # Extract content inside this [TOOL_CALL] block
            block_content = content[tool_call_start + len('[TOOL_CALL]'):tool_call_end]

        # Check if this block has [TOOL_ARGS]
        tool_args_marker = block_content.find('[TOOL_ARGS]')

        if tool_args_marker != -1:
            # This block has [TOOL_ARGS]
            tool_call_name = None
            tool_args_str = ""

            if pending_tool_call_name is not None:
                # Use the pending tool name and ignore any name in this block
                tool_call_name = pending_tool_call_name
                pending_tool_call_name = None
            else:
                # Extract name before [TOOL_ARGS]
                name_part = block_content[:tool_args_marker].strip()
                if name_part:
                    tool_call_name = name_part

            # Extract tool args
            tool_args_start = tool_args_marker + len('[TOOL_ARGS]')
            tool_args_str = block_content[tool_args_start:].strip()

            try:
                tool_args = json.loads(tool_args_str) if tool_args_str else {}
            except json.JSONDecodeError:
                tool_args = {}

            # Add action step if we have a tool name
            if tool_call_name:
                result.append({
                    "step_name": "action",
                    "tool_call": tool_call_name,
                    "tool_args": tool_args
                })
        else:
            # This block has no [TOOL_ARGS]
            block_stripped = block_content.strip()

            # Check if the content is a JSON object (example4)
            if block_stripped.startswith('{'):
                try:
                    json_data = json.loads(block_stripped)
                    if isinstance(json_data, dict):
                        tool_call = json_data.get('tool_call', '')
                        tool_args = json_data.get('tool_args', {})
                        if tool_call:
                            result.append({
                                "step_name": "action",
                                "tool_call": tool_call,
                                "tool_args": tool_args
                            })
                except json.JSONDecodeError:
                    pass
            else:
                # This is just a tool name definition
                tool_name = block_stripped
                if tool_name:
                    # Check if there's already a pending tool waiting for args
                    # If so, add it with empty args first
                    if pending_tool_call_name is not None:
                        result.append({
                            "step_name": "action",
                            "tool_call": pending_tool_call_name,
                            "tool_args": {}
                        })
                    # Set new pending tool name
                    pending_tool_call_name = tool_name

        # Move past this block
        if tool_call_end != -1:
            tool_call_start = tool_call_end + len('[/TOOL_CALL]')
        else:
            # No closing tag found, end of processing
            break

    # Handle standalone [TOOL_ARGS] blocks (example5)
    tool_args_start = 0
    while True:
        tool_args_start = content.find('[TOOL_ARGS]', tool_args_start)
        if tool_args_start == -1:
            break

        # Check if this [TOOL_ARGS] is inside a [TOOL_CALL] block
        # by checking if there's a [TOOL_CALL] before it
        preceding_tool_call = content.rfind('[TOOL_CALL]', 0, tool_args_start)

        is_inside_tool_call = False
        if preceding_tool_call != -1:
            following_close = content.find('[/TOOL_CALL]', preceding_tool_call)
            if following_close != -1 and following_close > tool_args_start:
                is_inside_tool_call = True

        if not is_inside_tool_call:
            # This is a standalone [TOOL_ARGS] block
            tool_args_end = content.find('[/TOOL_ARGS]', tool_args_start)
            if tool_args_end != -1:
                tool_args_str = content[tool_args_start + len('[TOOL_ARGS]'):tool_args_end].strip()
                try:
                    tool_args = json.loads(tool_args_str) if tool_args_str else {}
                except json.JSONDecodeError:
                    tool_args = {}

                if pending_tool_call_name:
                    result.append({
                        "step_name": "action",
                        "tool_call": pending_tool_call_name,
                        "tool_args": tool_args
                    })
                    pending_tool_call_name = None

            tool_args_start = tool_args_end + len('[/TOOL_ARGS]') if tool_args_end != -1 else tool_args_start + len('[TOOL_ARGS]')
        else:
            tool_args_start += len('[TOOL_ARGS]')

    return result


def hook_execute(content: Any) -> Union[List[Dict[str, Any]], str, Any]:
    if not isinstance(content, str):
        return content
    if 'minimax' in content:
        if '<tool_call>' in content:
            return convert_xml_to_list_dict(content)
        return (
            convert_xml_to_list_dict2(content)
        )

    if "[TOOL_CALL]" in content:
        new_content = convert_tool_call_case1(content)
        if new_content:
            return new_content

        # case: '=>' is ':'
        if " => " in content:
            content = content.replace(" => ", ":")
            new_content = convert_tool_call_case1(content)
            if new_content:
                return new_content

    return content
