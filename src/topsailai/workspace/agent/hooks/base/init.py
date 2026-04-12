'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose:
'''

from topsailai.utils.module_tool import (
    get_function_map,
)

HOOKS = get_function_map(
    "topsailai.workspace.agent.hooks",
    key="HOOKS",
)

def get_hooks(key_prefix:str) -> list:
    """ return hook func list """
    result = []
    for hook_name, hook_func in HOOKS.items():
        if hook_name.startswith(key_prefix):
            result.append(hook_func)
    return result
