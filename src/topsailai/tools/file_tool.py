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
    format_tool,
    json_tool,
    file_tool as _file_tool,
)

from topsailai.tools.file_tool_utils import (
    file_read_line,
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
    "ts",
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
        seek (int, optional): bytes, Position to start writing from. Defaults to 0.
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
    seek = int(seek)
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

                _file_tool.write_text(file_path, new_content)
            else:
                # File doesn't exist, create with content
                _file_tool.write_text(file_path, content)
        else:
            # Overwrite mode: simple approach - just write the content
            # For complex positioning, we'll handle it differently
            if seek == 0:
                # Simple overwrite from beginning
                _file_tool.write_text(file_path, content)
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

                    _file_tool.write_text(file_path, new_content)
                else:
                    # For overwrite mode on non-existent file, just write content at position 0
                    _file_tool.write_text(file_path, content)
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
        seek: int, bytes, read from this offset, default is 0;
        size: int, bytes, -1 for all, default is -1;

    Return:
        file content or error message

    Attention:
    - When it is explicitly required to read the complete file, these parameters are not needed: seek, size.
    - When the file extension is not in white list, the file reading process may be (force to truncate).
      - white list: {WHITE_LIST_NO_TRUNCATE_EXT}
    """
    seek = int(seek)
    size = int(size)

    file_path_lower = file_path.lower()
    file_ext = file_path_lower.rsplit('.', 1)[-1]

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

# finish doc
read_file.__doc__ = read_file.__doc__.format(
    WHITE_LIST_NO_TRUNCATE_EXT=WHITE_LIST_NO_TRUNCATE_EXT,
)


def append_file(file_path: str, content: str) -> bool:
    """ append content to file.

    Args:
        file_path: string, the file path;
        content: string

    Return (bool): True for ok
    """
    return _file_tool.append_data(file_path, content)

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
    for d in format_tool.to_list(dirs):
        assert d[0] == "/", f"require absolute path: {d}"
        os.makedirs(d, exist_ok=True)
    return True

def replace_lines_in_file(file_path: str, lines: list[tuple[int, str]], **_):
    """
    Replace specific lines in a file based on line numbers (start from 1).

    IMPORTANT LOGIC:
    To ensure code integrity and indentation, do not replace lines individually
    if they are part of a logical block (e.g., a function, a loop, or a class).
    Instead, replace the entire block containing the change in a single operation.

    Args:
        file_path (str): Path to the file to modify
        lines (list[tuple[int, str]]): List of tuples where each tuple contains:
            - line_number (int): The 1-based line number to replace
            - content (str): The new content for that line, pass null str will delete this line

    Returns:
        str: file content on success, error message on failure
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            raise Exception(f"File not found: {file_path}")

        # json str
        if isinstance(lines, str):
            lines = json_tool.json_load(lines)

        # Read the entire file content to preserve line endings
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        # Split content into lines while preserving line endings
        lines_content = content.splitlines(keepends=True)

        # If the file doesn't end with a newline, the last line won't have line ending
        # So we need to handle this case
        if lines_content and not lines_content[-1].endswith(('\n', '\r', '\r\n')):
            # Last line doesn't have line ending, so we'll add it temporarily
            lines_content[-1] = lines_content[-1] + '\n'
            last_line_no_ending = True
        else:
            last_line_no_ending = False

        # Track which lines have been modified to handle last_line_no_ending correctly
        modified_last_line = False
        # Collect indices of lines to delete (where content is empty string or None)
        lines_to_delete = set()

        # Replace the specified lines
        for line_item in lines:
            if isinstance(line_item, dict):
                line_num = line_item["line_number"]
                new_content = line_item["content"]
            else:
                line_num, new_content = line_item

            line_num = int(line_num)
            # Convert to 0-based index
            index = line_num - 1

            if 0 <= index < len(lines_content):
                # Track if we're modifying the last line
                if index == len(lines_content) - 1:
                    modified_last_line = True

                # Handle empty/None content - mark for deletion
                if new_content == "" or new_content is None:
                    lines_to_delete.add(index)
                else:
                    # Get the original line ending from the original content (before we added temporary \n)
                    original_line = lines_content[index]
                    original_line_ending = original_line[len(original_line.rstrip()):]

                    # Check if new_content already has a line ending
                    if new_content.endswith(('\n', '\r\n', '\r')):
                        # New content already has line ending, use it as is
                        # Don't add original_line_ending to avoid double line endings
                        lines_content[index] = new_content
                    else:
                        # new_content has no line ending, preserve the original line ending
                        lines_content[index] = new_content + original_line_ending

        # Remove lines marked for deletion
        for index in lines_to_delete:
            lines_content[index] = ""

        # If last line originally didn't have ending, handle the temporary newline we added
        if last_line_no_ending and lines_content:
            if modified_last_line:
                # The last line was modified, check if it ends with \n
                # If it does, we need to remove it because the original had no ending
                if lines_content[-1].endswith('\n'):
                    lines_content[-1] = lines_content[-1][:-1]
            else:
                # The last line was not modified, remove the temporary newline we added
                if lines_content[-1].endswith('\n'):
                    lines_content[-1] = lines_content[-1][:-1]

        # Write the modified content back to the file
        new_content = ''.join(lines_content)
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(new_content)
            file.flush()
        return new_content
    except Exception as e:
        return str(e)

def insert_data_to_file(file_path: str, data: str, line_num: int, before_or_after: str = "after"):
    """
    Insert data(ends with newline) to file before/after line number.

    Args:
        file_path (str): Path to the file to modify
        data (str): Data to insert
        line_num (int): Line number to insert before/after (1-based)
        before_or_after (str, optional): Whether to insert "before" or "after" the line. Defaults to "after".

    Returns:
        str: file content on success, error message on failure
    """
    # Validate before_or_after parameter
    if before_or_after not in ("before", "after"):
        raise ValueError(f"before_or_after must be 'before' or 'after', got '{before_or_after}'")

    # Ensure data ends with newline if it doesn't already
    if data and not data.endswith('\n'):
        data += '\n'

    # Read existing lines
    with open(file_path, 'r') as f:
        lines = f.readlines()

    line_num = int(line_num)

    # Calculate insertion index (0-based)
    # line_num is 1-based, so subtract 1 to get 0-based index
    insert_index = line_num - 1

    # Adjust index based on before/after
    if before_or_after == "after":
        insert_index += 1

    # Handle edge cases for insertion index
    # Clamp to valid range [0, len(lines)]
    insert_index = max(0, min(insert_index, len(lines)))

    # Insert the data
    lines.insert(insert_index, data)

    # Write back to file
    new_content = "".join(lines)
    with open(file_path, 'w') as f:
        f.writelines(lines)
        f.flush()

    return new_content


def list_dir(folder_path:str) -> list[str]:
    """list folder

    Args:
        folder_path (str):

    Returns:
        list[str]:
    """
    return os.listdir(folder_path)

def read_files(files:list[str]) -> dict:
    """
    Read multiple files.

    Args:
        files (list[str]): some files

    Returns:
        dict: key is file_path, value is file_content
    """
    result = {}
    for file_path in format_tool.to_list(files):
        result[file_path] = read_file(file_path)
    return result

def list_dirs(dirs:list[str]) -> dict:
    """
    List multiple folders.

    Args:
        dirs (list[str]): some folders

    Returns:
        dict: key is folder_path, value is files
    """
    result = {}
    for dir_path in format_tool.to_list(dirs):
        result[dir_path] = list_dir(dir_path)
    return result


TOOLS = dict(
    write_file=write_file,
    read_file=read_file,
    append_file=append_file,
    check_files_existing=check_files_existing,
    mkdirs=mkdirs,
    overwrite_lines_in_file=replace_lines_in_file,
    insert_data_to_file=insert_data_to_file,
    list_dirs=list_dirs,
    read_files=read_files,
)
TOOLS.update(file_read_line.TOOLS)

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

FILE_RO_TOOLS = dict(
    read_file=read_file,
    check_files_existing=check_files_existing,
    list_dirs=list_dirs,
    read_files=read_files,
)

FILE_RO_TOOLS.update(file_read_line.TOOLS)
