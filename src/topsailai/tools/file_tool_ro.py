'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-29
  Purpose:
'''

from . import file_tool

TOOLS = dict(
    read_file=file_tool.read_file,
    check_files_existing=file_tool.check_files_existing,
)

FLAG_TOOL_ENABLED = False
