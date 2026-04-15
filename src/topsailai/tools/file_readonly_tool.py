'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-29
  Purpose:
'''

from topsailai.tools import file_tool
from topsailai.tools.file_tool import FILE_RO_TOOLS


TOOLS = {}
TOOLS.update(FILE_RO_TOOLS)

FLAG_TOOL_ENABLED = False

def reload():
    """ Reload TOOLS """
    # avoid duplicate
    from topsailai.tools.base.init import is_tool_enabled
    if is_tool_enabled(file_tool):
        TOOLS.clear()
    return

reload()
