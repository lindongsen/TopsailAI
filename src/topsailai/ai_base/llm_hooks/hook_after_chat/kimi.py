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
    #
    # IMPORTANT: The JSON arguments may contain nested {} structures (e.g., Go code with struct{}, if{}, func(){}).
    # Using non-greedy .*? between markers, then extract JSON by finding balanced braces.
    pattern = r'\s*<\|tool_call_begin\|>\s*functions\.([\w-]+):(\w+)\s*<\|tool_call_argument_begin\|>\s*(.+?)\s*<\|tool_call_end\|>'

    matches = re.findall(pattern, content, re.DOTALL)

    for match in matches:
        tool_name = match[0].strip()
        if not tool_name:
            continue

        # The JSON args are captured between <|tool_call_argument_begin|> and <|tool_call_end|>
        # We need to extract the JSON object from potentially nested content
        raw_args = match[2].strip()

        # Try to parse the raw content as JSON directly first
        json_str = None
        try:
            # Try parsing the whole thing as JSON
            parsed = json.loads(raw_args)
            json_str = raw_args
            tool_args = parsed
        except json.JSONDecodeError:
            # If direct parsing fails, try to extract JSON object by finding balanced braces
            # Find the first { and last } to extract the JSON object
            first_brace = raw_args.find('{')
            last_brace = raw_args.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                potential_json = raw_args[first_brace:last_brace + 1]
                try:
                    tool_args = json.loads(potential_json)
                    json_str = potential_json
                except json.JSONDecodeError:
                    tool_args = {}
            else:
                tool_args = {}

        if json_str is None:
            json_str = raw_args

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
