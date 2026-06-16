'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-06-16
Purpose:
'''

import os

def get_file_size(file_path:str) -> int:
    """
    Get file size in bytes

    Args:
        file_path (str)
    """
    return os.path.getsize(file_path)


TOOLS = dict(
    get_file_size=get_file_size,
)
