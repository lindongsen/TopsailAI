"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-19
  Purpose: Convert content from kimi to standard format
  Example:
    content:    <|tool_calls_section_begin|>       <|tool_call_begin|>    functions.ctx_tool-retrieve_msg:4    <|tool_call_argument_begin|>     {"msg_id":"8099aefe5e6fcfb862b3d296a1cd9d80"}    <|tool_call_end|>       <|tool_calls_section_end|>
    expected: [{"step_name":"action", "tool_call":"ctx_tool-retrieve_msg","tool_args":{"msg_id":"8099aefe5e6fcfb862b3d296a1cd9d80"}}]
"""

import re
import json


def convert_to_list_dict(content: str) -> list[dict]:
    """
    Parse kimi function call format and convert to list of dicts.

    Pattern: <optional_whitespace> <|tool_calls_section_begin|> <optional_whitespace> <|tool_call_begin|> <optional_whitespace>functions.tool_name:id<optional_whitespace> <|tool_call_argument_begin|> <optional_whitespace>{json_args}<optional_whitespace> <|tool_call_end|> <optional_whitespace> <|tool_calls_section_end|> <optional_whitespace>
    """
    result = []

    # Pattern to match kimi function calls with flexible whitespace
    # Matches:  <|tool_calls_section_begin|>   <|tool_call_begin|>  functions.tool_name:id  <|tool_call_argument_begin|>  {json_args}  <|tool_call_end|>    <|tool_calls_section_end|>
    # Whitespace around markers is now optional/variable using \s*
    pattern = r'\s*<\|tool_calls_section_begin\|>\s*<\|tool_call_begin\|>\s*functions\.([\w-]+):(\w+)\s*<\|tool_call_argument_begin\|>\s*(\{[^}]*\})\s*<\|tool_call_end\|>\s*<\|tool_calls_section_end\|>\s*'

    matches = re.findall(pattern, content)

    for match in matches:
        tool_name = match[0].strip()
        if not tool_name:
            continue

        json_str = match[2]

        try:
            tool_args = json.loads(json_str)
        except json.JSONDecodeError:
            tool_args = {}

        result.append({
            "step_name": "action",
            "tool_call": tool_name,
            "tool_args": tool_args
        })

    return result


def hook_execute(content) -> list[dict] | str:
    """
    Execute hook to convert kimi content to standard format.

    Returns list of dicts if function calls found, otherwise returns original content.
    """
    if isinstance(content, str):
        content = content.strip()

    result = convert_to_list_dict(content)

    if result:
        return result

    return content
