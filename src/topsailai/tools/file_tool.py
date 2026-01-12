'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-18
  Purpose:
'''

# pylint: disable=C0209

import os
import traceback

from topsailai.context import ctx_safe
from topsailai.utils import (
    text_tool,
    print_tool,
    env_tool,
)

# lower of letter
WHITE_LIST_NO_TRUNCATE_EXT = [
    # flags
    "done", "whole",
    # settings
    "md", "manifest", "conf", "yaml", "config", "cfg", "rc", "cnf", "xml", "pem", "json",
    "tpl",
    # devlang
    "py", "go", "c", "c++", "sh", "cmd",
] + (
        env_tool.EnvReaderInstance.get_list_str(
            "TOPSAILAI_FILE_WHITE_LIST_NO_TRUNCATE_EXT",
            to_lower=True,
        ) or []
    )

# all of file extentions is white
if '*' in WHITE_LIST_NO_TRUNCATE_EXT:
    WHITE_LIST_NO_TRUNCATE_EXT = ['*']

# all of files need truncate
if '!*' in WHITE_LIST_NO_TRUNCATE_EXT:
    WHITE_LIST_NO_TRUNCATE_EXT = []

def is_need_truncate(file_ext:str) -> bool:
    if not WHITE_LIST_NO_TRUNCATE_EXT:
        return True

    if '*' in WHITE_LIST_NO_TRUNCATE_EXT:
        return False
    if file_ext.lower() in WHITE_LIST_NO_TRUNCATE_EXT:
        return False

    return True


def write_file(file_path:str, content:str, seek:int=0, to_insert:bool=False):
    """Write content to a file with flexible positioning options.

    This function allows writing content to a file with various positioning modes:
    - Standard overwrite mode (to_insert=False)
    - Insert mode (to_insert=True) where content is inserted at the specified position
    - Support for positive and negative seek positions

    Args:
        file_path (str): The path to the file to write to
        content (str): The content to write to the file
        seek (int, optional): Position to start writing from. Defaults to 0.
            - Positive values: seek from start of file, position=min(seek, len(existing_content))
            - Negative values: seek from end of file
            - 0: start of file
            if file no exists, `seek` still is 0, just write content at position 0.
        to_insert (bool, optional): If True, insert content at seek position without
                                   overwriting existing content. If False, overwrite
                                   content starting at seek position. Defaults to False.

    Returns:
        str: Empty string on success, error message string on failure

    Raises:
        This function catches all exceptions and returns them as strings rather than raising

    Examples:
        # Overwrite entire file
        write_file("test.txt", "new content")

        # Append to end of file
        write_file("test.txt", "appended", seek=-1, to_insert=True)

        # Insert at position 10
        write_file("test.txt", "inserted", seek=10, to_insert=True)

        # Overwrite from position 5
        write_file("test.txt", "overwrite", seek=5, to_insert=False)
    """
    try:
        if to_insert:
            # Insert mode: read existing content, insert at position, then write back
            if os.path.exists(file_path):

                if seek == -1:
                    return append_file(file_path, content)

                with open(file_path, "r") as fd:
                    existing_content = fd.read()

                # Handle negative seek (from end)
                if seek < 0:
                    position = max(0, len(existing_content) + seek + 1)  # +1 to append after last character
                else:
                    position = min(seek, len(existing_content))

                # Insert the content
                new_content = existing_content[:position] + content + existing_content[position:]

                with open(file_path, "w") as fd:
                    fd.write(new_content)
            else:
                # File doesn't exist, create with content
                with open(file_path, "w") as fd:
                    fd.write(content)
        else:
            # Overwrite mode: simple approach - just write the content
            # For complex positioning, we'll handle it differently
            if seek == 0:
                # Simple overwrite from beginning
                with open(file_path, "w") as fd:
                    fd.write(content)
            else:
                # For non-zero seek, we need to handle positioning
                if os.path.exists(file_path):
                    with open(file_path, "r") as fd:
                        existing_content = fd.read()

                    # Handle negative seek (from end)
                    if seek < 0:
                        position = max(0, len(existing_content) + seek)  # For overwrite mode, no +1 adjustment
                    else:
                        position = min(seek, len(existing_content))

                    # Replace content starting at position
                    if position + len(content) <= len(existing_content):
                        new_content = existing_content[:position] + content + existing_content[position + len(content):]
                    else:
                        # Extend the file with the new content
                        new_content = existing_content[:position] + content

                    with open(file_path, "w") as fd:
                        fd.write(new_content)
                else:
                    # For overwrite mode on non-existent file, just write content at position 0
                    with open(file_path, "w") as fd:
                        fd.write(content)
    except Exception as e:
        return str(e)
    return ""

def _do_step_read_bytes(fd, size:int):
    """ read in a certain block size order.

    return bytes.
    """
    offset = 1024

    if size > 0 and size <= offset:
        return fd.read(size)

    content = b""
    count = 0
    while True:
        _data = fd.read(offset)
        if not _data:
            break
        content += _data
        count += offset

        if size > 0:
            if count >= size:
                break
            remaining_size = size - count
            if remaining_size <= offset:
                content += fd.read(remaining_size)
                return content

        if ctx_safe.is_need_truncate(count):
            break
    if size > 0:
        return content[:size]
    return content

def read_file(file_path:str, seek:int=0, size:int=-1):
    """ read a file and output file content.

    Args:
        file_path: string, the file path;
        seek: int, read from this offset, default is 0;
        size: int, -1 for all, default is -1;

    Return:
        string for ok, None for failed.

    Attention:
    - When it is explicitly required to read the complete file, these parameters are not needed: seek, size.
    - When the file extension is not in white list, the file reading process may be (force to truncate).
      - white list: {WHITE_LIST_NO_TRUNCATE_EXT}
    """
    file_path_lower = file_path.lower()
    file_ext = file_path_lower.rsplit('.', 1)[-1]

    try:
        with open(file_path, "rb") as fd:
            if seek < 0:
                fd.seek(seek, 2)
            else:
                fd.seek(seek)

            if is_need_truncate(file_ext):
                content = _do_step_read_bytes(fd, size)
                content = ctx_safe.truncate_message(content)
            else:
                content = fd.read(size)
            content = text_tool.safe_decode(content)

            # context limit
            if is_need_truncate(file_ext):
                content = ctx_safe.truncate_message(content)

            return content
    except Exception:
        print_tool.print_error(traceback.format_exc())
        return None
# finish doc
read_file.__doc__ = read_file.__doc__.format(
    WHITE_LIST_NO_TRUNCATE_EXT=WHITE_LIST_NO_TRUNCATE_EXT,
)

def append_file(file_path: str, content: str):
    """ append content to file.

    Args:
        file_path: string, the file path;
        content: string

    Return (str): null for ok
    """
    try:
        with open(file_path, "a+") as fd:
            fd.write(content)
    except Exception as e:
        return str(e)
    return ""

def exists_file(file_path:str):
    """ check the file or folder if exists.

    Args:
        file_path: string, one file or one folder.

    Return: bool, True for existing.
    """
    return os.path.exists(file_path)

def check_files_existing(**files):
    """ check multiple files or folders if exist.

    Args:
        **files: keyword arguments, each key is a name (string), value is the file or folder path (string) to check existence.

    Return:
        dict of str to bool, where keys are the provided names, values are True if the path exists, False otherwise.

    Example:
        check_files_existing(
            file1="path1",
            file2="path2",
            ...
        )
    """
    results = {}
    for fname, fpath in files.items():
        results[fname] = os.path.exists(fpath)
    return results

def mkdirs(dirs):
    """make folders.

    Args:
        dirs: list, multiple folders.

    Returns:
        raise an Error if error, else return true.
    """
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    return True


TOOLS = dict(
    write_file=write_file,
    read_file=read_file,
    append_file=append_file,
    check_files_existing=check_files_existing,
    mkdirs=mkdirs,
)

TOOLS_INFO = dict(
    check_files_existing={
        "type": "function",
        "function": {
            "name": "",
            "description": check_files_existing.__doc__,
            "parameters": {
                "type": "object",
            }
        }
    },
)
