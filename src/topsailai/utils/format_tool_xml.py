'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-29
  Purpose:
'''

import json
import xml.etree.ElementTree as ET
from typing import Any


def format_xml(content: str) -> list[dict[str, Any]]:
    """
    Parse XML content and convert it to a list of dictionaries.

    Args:
        content: XML content string containing thought/action blocks

    Returns:
        List of dictionaries with step information

    Example:
        Input XML:
        ```
        <thought>
        hello
        </thought>

        <action>
        {"tool_call": "cmd_tool-exec_cmd", "tool_args": {"cmd": "echo ok"}}
        </action>
        ```

        Output:
        [
          {
            "step_name": "thought",
            "raw_text": "hello"
          },
          {
            "step_name": "action",
            "tool_call": "cmd_tool-exec_cmd",
            "tool_args": {"cmd": "echo ok"}
          }
        ]
    """
    result = []

    # Wrap content in a root element to parse multiple top-level elements
    wrapped_content = f"<root>{content}</root>"

    try:
        root = ET.fromstring(wrapped_content)
    except ET.ParseError:
        return result

    for element in root:
        step_name = element.tag
        raw_text = element.text.strip() if element.text else ""

        step_dict = {"step_name": step_name}

        # Try to parse the content as JSON for action elements
        if raw_text:
            try:
                json_data = json.loads(raw_text)
                step_dict["tool_call"] = json_data.get("tool_call")
                step_dict["tool_args"] = json_data.get("tool_args")
            except (json.JSONDecodeError, AttributeError):
                step_dict["raw_text"] = raw_text
        else:
            step_dict["raw_text"] = raw_text

        result.append(step_dict)

    return result
