'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-21
  Purpose:
'''

import os

from topsailai.utils.module_tool import (
    get_function_map,
    get_external_function_map,
)


INSTRUCTIONS = get_function_map("topsailai.workspace.plugin_instruction", key="INSTRUCTIONS")

def expand_plugin_instructions():
    """ expand instructions by external plugins """
    env_plugin_instructions = os.getenv("TOPSAILAI_PLUGIN_INSTRUCTIONS")
    if not env_plugin_instructions:
        return
    for plugin_path in env_plugin_instructions.split(';'):
        _instructions = get_external_function_map(
            plugin_path, "INSTRUCTIONS",
        )
        if _instructions:
            INSTRUCTIONS.update(_instructions)

    return

# init
expand_plugin_instructions()
