'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-18
  Purpose: import all of tools to support AI-Agent.
'''

import os

from topsailai.utils import (
    module_tool,
    format_tool,
    print_tool,
    env_tool,
)

CONN_CHAR = env_tool.EnvReaderInstance.get("TOPSAILAI_TOOL_CONN_CHAR", "-") or "-"

# key is tool_name, value is function
TOOLS = module_tool.get_function_map("topsailai.tools", "TOOLS", conn_char=CONN_CHAR)

# key is tool_name, value is dict
# Value Example:
# {
#     "type": "function",
#     "function": {
#         "name": "get_current_weather",
#         "description": "获取指定城市的当前天气",
#         "parameters": {
#             "type": "object",
#             "properties": {
#                 "location": {
#                     "type": "string",
#                     "description": "城市名称"
#                 },
#                 "unit": {
#                     "type": "string",
#                     "enum": ["celsius", "fahrenheit"],
#                     "description": "温度单位"
#                 }
#             },
#             "required": ["location"]
#         }
#     }
# }
TOOLS_INFO = module_tool.get_function_map("topsailai.tools", "TOOLS_INFO", conn_char=CONN_CHAR)


TOOL_PROMPT = """
---
# TOOLS
Attention: You MUST use the tool name (completely), e.g. whole name is 'x_tool%sy_func', you cannot use 'y_func'.
{__TOOLS__}
---
""" % CONN_CHAR

def get_tool_prompt(tools_name:list=None, tools_map:dict=None):
    """
    :tools_name: list_str;
    :tools_map: dict, key is tool name, value is function.

    return tool_prompt for tools """
    tools_doc = {}

    if tools_name:
        for tool_name in format_tool.to_list(tools_name, to_ignore_none=True):
            tools_doc[tool_name] = TOOLS[tool_name].__doc__

    if tools_map:
        for tool_name, tool_func in tools_map.items():
            tools_doc[tool_name] = tool_func.__doc__

    if not tools_doc:
        return ""

    return TOOL_PROMPT.format(
        __TOOLS__=print_tool.format_dict_to_md(tools_doc)
    )

def expand_plugin_tools():
    """ expand tools by external plugins """
    env_plugin_tools = os.getenv("PLUGIN_TOOLS")
    if not env_plugin_tools:
        return
    for plugin_path in env_plugin_tools.split(';'):
        _tools = module_tool.get_external_function_map(plugin_path, "TOOLS", conn_char=CONN_CHAR)
        if _tools:
            TOOLS.update(_tools)

        _tools_info = module_tool.get_external_function_map(plugin_path, "TOOLS_INFO", conn_char=CONN_CHAR)
        if _tools_info:
            TOOLS_INFO.update(_tools_info)

    return

def generate_tool_info(tool_name, tool_description):
    result = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": tool_description,
            "parameters": {
                "type": "object",
            }
        }
    }
    return result

def get_tools_for_chat(tools_map:dict) -> dict:
    """ return tools info """
    result = {}
    for tool_name in list(tools_map.keys()):
        if tool_name in TOOLS_INFO:
            result[tool_name] = TOOLS_INFO[tool_name]
            result[tool_name]["function"]["name"] = tool_name
            continue
        if tool_name in TOOLS:
            result[tool_name] = generate_tool_info(tool_name, TOOLS[tool_name].__doc__)

    return result

def format_tools_map(tools_map:dict, prefix_name:str) -> dict:
    """format tool name.

    Args:
        tools_map (dict): key is toolname
        prefix_name (str): toolname starts with this.

    Return new tools_map.
    """
    if prefix_name[-1] != ".":
        prefix_name += "."

    new_tools_map = {}
    for key in tools_map:
        raw_key = key
        if not key.startswith(prefix_name):
            key = prefix_name + key
        new_tools_map[key] = tools_map[raw_key]
    return new_tools_map


# init
expand_plugin_tools()
