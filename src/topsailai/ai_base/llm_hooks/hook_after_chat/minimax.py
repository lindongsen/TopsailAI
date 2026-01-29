'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-29
  Purpose: Convert XML-like content from Minimax to standard format
'''

import json
import xml.etree.ElementTree as ET
from typing import List, Dict, Any

def convert_xml_to_list_dict(raw_content: str) -> List[Dict[str, Any]]:
    """
    Convert XML-like content to a list of dictionaries

    Example input (raw_content):
    ```
    <think>hello
    </think>


    <minimax:tool_call>
    <invoke name="cmd_tool-exec_cmd">
    <tool_args>{"cmd": "echo ok"}</tool_args>
    <tool_call>cmd_tool-exec_cmd</tool_call>
    </invoke>

    ```

    Example output:
    ```
    [
    {"step_name":"thought", "raw_text": "hello"},
    {"step_name":"action", "tool_call":"cmd_tool-exec_cmd","tool_args":{"cmd":"echo ok"}}
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
    think_end = raw_content.find("</think>")

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


def hook_execute(content) -> list[dict]|str:
    if not isinstance(content, str):
        return content
    if 'minimax' in content:
        return convert_xml_to_list_dict(content)
    return content