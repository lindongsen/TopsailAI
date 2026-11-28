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
from . import file_diff, file_line_model


def replace_lines_in_file(file_path: str, lines: list[tuple[int, str]], **_):
    """
    Replace specific lines in a file based on line numbers (start from 1).

    IMPORTANT LOGIC:
    To ensure code integrity and indentation, do not replace lines individually
    if they are part of a logical block (e.g., a function, a loop, or a class).
    Instead, replace the entire block containing the change in a single operation.
    You MUST confirm the line number before each call.
    You CANNOT call continuously due to the line number will change after each call.

    Args:
        file_path (str): Path to the file to modify
        lines (list[tuple[int, str]]): List of tuples where each tuple contains:
            - line_number (int): The 1-based line number to replace
            - content (str): The new content for that line, pass null str will delete this line

    Returns:
        str: diff content on success, error message on failure

    Example, Modify a function block (lines 1-3) and delete line 5
        ```
        lines = [
            (1, "def calculate_sum(a, b):"),
            (2, "    return a + b"),
            (3, "\\n"),
            (5, "")  # Passing an empty string deletes the line

        ]
        ```
    """
    with _file_tool.ctxm_temp_file("") as (tmp_file, fp):
        # Check if file exists
        if not os.path.exists(file_path):
            raise Exception(f"File not found: {file_path}")

        # json str
        if isinstance(lines, str):
            lines = json_tool.json_load(lines)

        # Read the entire file content without translating line endings, so an
        # edit to one line does not rewrite the endings of every other line.
        content = file_line_model.read_text(file_path)

        if content:
            fp.write(content)
            fp.flush()

        # Split with the same line model the read tool reports, so a line number
        # obtained from the read tool selects the line the model intended.
        lines_content = file_line_model.split_lines(content)

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
                    # Take only the ending of the original line, never its
                    # trailing spaces, or those spaces would be appended to the
                    # replacement.
                    original_line = lines_content[index]
                    original_line_ending = file_line_model.line_ending_of(original_line)

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
                # The last line was modified, check if it ends with a line ending
                # If it does, we need to remove it because the original had no ending.
                # Strip the whole ending, not just "\n", or a "\r\n" would leave a
                # stray "\r" behind.
                ending = file_line_model.line_ending_of(lines_content[-1])
                if ending:
                    lines_content[-1] = lines_content[-1][:-len(ending)]
            else:
                # The last line was not modified, remove the temporary newline we added
                if lines_content[-1].endswith('\n'):
                    lines_content[-1] = lines_content[-1][:-1]

        # Write the modified content back without translating line endings
        new_content = ''.join(lines_content)
        file_line_model.write_text(file_path, new_content)

        diff_content = file_diff.compare_files_strived(tmp_file, file_path)
        return diff_content
