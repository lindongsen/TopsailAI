'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-23
  Purpose:
'''

from topsailai.tools.base.init import (
    TOOLS,
    TOOLS_INFO,
    TOOL_PROMPT,
    CONN_CHAR,
    is_tool_enabled,
)
from topsailai.utils import (
    module_tool,
    format_tool,
    print_tool,
    env_tool,
)


def add_tool(name:str, func):
    """ add a tool before creating agent instance. """
    assert callable(func), f"invalid function: {func}"
    if not name:
        name = "aiagent_tool" + CONN_CHAR + func.__name__
    TOOLS[name] = func
    return

def get_tools_by_module(module_path:str, key:str="TOOLS") -> dict:
    """
    Get tool map, key is tool_name, value is func

    Args:
        module_path (str): import path e.g. topsailai.tools.xxx

    Returns:
        dict:
    """
    m = module_tool.get_mod(module_path)
    name_prefix = module_path.rsplit('.', 1)[-1]
    _tools = getattr(m, key)
    tool_map = {}
    for name, func in _tools.items():
        tool_name = name_prefix + CONN_CHAR + name
        tool_map[tool_name] = func
    return tool_map

def get_tool_prompt(tools_name:list=None, tools_map:dict=None):
    """
    :tools_name: list_str;
    :tools_map: dict, key is tool name, value is function.

    return tool_prompt for tools """
    tools_doc = {}

    if tools_name:
        for tool_name in format_tool.to_list(tools_name, to_ignore_none=True):
            if tool_name in TOOLS:
                tools_doc[tool_name] = TOOLS[tool_name].__doc__

    if tools_map:
        for tool_name, tool_func in tools_map.items():
            tools_doc[tool_name] = tool_func.__doc__

    if not tools_doc:
        return ""

    return TOOL_PROMPT.format(
        __TOOLS__=print_tool.format_dict_to_md(tools_doc)
    )

def expand_plugin_tools(tools=None, tools_info=None):
    """ expand tools by external plugins """
    # Use provided dicts or fall back to global TOOLS/TOOLS_INFO
    _tools = tools if tools is not None else TOOLS
    _tools_info = tools_info if tools_info is not None else TOOLS_INFO

    env_plugin_tools = env_tool.EnvReaderInstance.get_list_str("TOPSAILAI_PLUGIN_TOOLS", separator='') or \
        env_tool.EnvReaderInstance.get_list_str("PLUGIN_TOOLS", separator='')
    if not env_plugin_tools:
        return
    for plugin_path in env_plugin_tools:
        _new_tools = module_tool.get_external_function_map(
            plugin_path, "TOOLS",
            conn_char=CONN_CHAR,
            hook_check=is_tool_enabled,
            need_module_log=False,
        )
        if _new_tools:
            _tools.update(_new_tools)

        _new_tools_info = module_tool.get_external_function_map(
            plugin_path, "TOOLS_INFO",
            conn_char=CONN_CHAR,
            hook_check=is_tool_enabled,
            need_module_log=False,
        )
        if _new_tools_info:
            _tools_info.update(_new_tools_info)

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
