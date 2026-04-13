'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-29
  Purpose:
'''

from topsailai.tools import file_tool

FILE_RO_TOOLS = dict(
    read_file=file_tool.read_file,
    read_lines=file_tool.read_lines,
    check_files_existing=file_tool.check_files_existing,
    list_dirs=file_tool.list_dirs,
    read_files=file_tool.read_files,
)

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
