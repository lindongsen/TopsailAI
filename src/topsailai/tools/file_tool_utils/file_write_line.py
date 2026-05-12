'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-05-12
Purpose:
'''

import os

from topsailai.utils import (
    file_tool as _file_tool,
    json_tool,
)
from . import file_diff


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
        str: diff content on success, error message on failure
    """
    with _file_tool.ctxm_temp_file("") as (tmp_file, fp):
        # Check if file exists
        if not os.path.exists(file_path):
            raise Exception(f"File not found: {file_path}")

        # json str
        if isinstance(lines, str):
            lines = json_tool.json_load(lines)

        # Read the entire file content to preserve line endings
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        if content:
            fp.write(content)
            fp.flush()

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

        diff_content = file_diff.compare_files_strived(tmp_file, file_path)
        return diff_content
