'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-18
  Purpose: import all of tools to support AI-Agent.
  Keywords:
  - TOOLS, dict, key is tool name, value is callable func
  - FLAG_TOOL_ENABLED, bool
  - TOOLS_INFO, dict, key is tool name, value is dict for spec.
'''

from topsailai.utils import (
    module_tool,
    env_tool,
)

CONN_CHAR = env_tool.EnvReaderInstance.get("TOPSAILAI_TOOL_CONN_CHAR", "-") or "-"

ENABLED_TOOLS = env_tool.EnvReaderInstance.get_list_str("ENABLED_TOOLS", separator='')

def is_tool_enabled(tool_mod):
    """ checking if enables the tool by variable: FLAG_TOOL_ENABLED """
    try:
        if getattr(tool_mod, "FLAG_TOOL_ENABLED") is False:
            if not ENABLED_TOOLS:
                return False
            tool_name = tool_mod.__name__.split('.')[-1]
            return tool_name in ENABLED_TOOLS
    except:
        pass
    return True

# key is tool_name, value is function
TOOLS = module_tool.get_function_map(
    "topsailai.tools", "TOOLS",
    conn_char=CONN_CHAR,
    hook_check=is_tool_enabled,
    need_module_log=False,
)

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
TOOLS_INFO = module_tool.get_function_map(
    "topsailai.tools",
    "TOOLS_INFO",
    conn_char=CONN_CHAR,
    hook_check=is_tool_enabled,
    need_module_log=False,
)


TOOL_PROMPT = """
---
# TOOLS
Attention: You MUST use the tool name (completely), e.g. whole name is 'x_tool%sy_func', you cannot use 'y_func'.
{__TOOLS__}
---
""" % CONN_CHAR
