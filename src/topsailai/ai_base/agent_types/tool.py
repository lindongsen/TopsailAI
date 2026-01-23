'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-23
  Purpose:
'''

def get_tool_func(tool_map:dict, tool_name:str):
    """get a callable func.

    Compatible connection characters to avoid mistakes made by LLM.

    Args:
        tool_map (dict): key is tool_name, value is tool_func
        tool_name (str):
    """
    if not tool_map or not tool_name:
        return None

    tool_name = tool_name.strip()
    if not tool_name:
        return None

    if tool_name in tool_map:
        return tool_map[tool_name]

    new_tool_name = tool_name.replace('.', '-')
    for _tool_name in tool_map:
        if _tool_name.replace('.', '-').strip() == new_tool_name:
            return tool_map[_tool_name]

    return None
