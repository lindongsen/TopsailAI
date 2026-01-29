'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-29
  Purpose:
'''

from topsailai.utils import (
    module_tool,
    env_tool,
)

def hook_execute(key:str, content:str) -> list[dict]|str:
    """ execute hooks

    Args:
        key (str): e.g TOPSAILAI_HOOK_AFTER_LLM_CHAT
        content (str): content from llm

    Returns:
        list[dict]|str
    """
    hooks = env_tool.EnvReaderInstance.get_list_str(key)
    if not hooks:
        return content
    for hook_path in hooks:
        hook_func = module_tool.get_var(hook_path, "hook_execute")
        if hook_func:
            content = hook_func(content)
    return content
