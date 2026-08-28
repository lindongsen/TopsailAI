'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-06-16
Purpose:
'''

import os

from ..tool_utils.parameter import resolve_str_param

def get_file_size(file_path:str) -> int:
    """
    Get file size in bytes

    Args:
        file_path (str)
    """
    file_path, error = resolve_str_param(file_path, "file_path")
    if error:
        return error
    return os.path.getsize(file_path)


TOOLS = dict(
    get_file_size=get_file_size,
)
