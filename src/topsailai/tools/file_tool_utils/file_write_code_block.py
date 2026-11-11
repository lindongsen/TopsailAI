'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-05-19
Purpose:
'''

import os

from topsailai.tools.tool_utils.parameter import invalid_request, resolve_end_num, resolve_finite_int
from topsailai.utils import (
    file_tool as _file_tool,
    json_tool,
)
from . import file_diff


def overwrite_code_block(file_path: str, start_num: int, end_num: int = 0, content: str = None, **_) -> str:
    """
    Replace lines from start_num to end_num (1-based, inclusive) with the provided content.
    The content can be a single line or multi-line block.

    IMPORTANT LOGIC:
    To ensure code integrity and indentation, do not replace lines individually
    if they are part of a logical block (e.g., a function, a loop, or a class).
    Instead, replace the entire block containing the change in a single operation.
    > You MUST confirm the line numbers before each call.
    > You CANNOT call continuously due to the line number will change after each call.

    Args:
        file_path (str): Path to the file to modify
        start_num (int): The 1-based starting line number to begin replacement -> **include this line to replace**
        end_num (int): The 1-based ending line number (inclusive) to end replacement.
                       Omitted, ``0``, ``None``, or blank text means no end line,
                       so ONLY ``start_num`` is replaced.
                       ``-1`` replaces from ``start_num`` through the end of the file.
                       Any other negative value is rejected.
                       This differs from ``read_file_lines``, where omitting
                       ``end_num`` reads to the end of the file; a write is
                       destructive, so the ambiguous value must never delete
                       the rest of the file.
        content (str): The new content to insert in place of the replaced lines.
                       Can be a single line or multi-line string.
                       MUST be a string; a non-string value is rejected with
                       ``invalid_request`` and the file is left untouched.
                       Pass an empty string to delete lines.

    Returns:
        str: diff content on success, error message on failure

    Example:
        Replace lines 5-10 with new code block
        ```
        args=("example.py", 5, 10, "def new_function():\\n    pass\\n")
        ```

        Replace only line 5
        ```
        args=("example.py", 5, 0, "def new_function():\\n    pass\\n")
        ```

        Replace line 5 through the end of the file
        ```
        args=("example.py", 5, -1, "def new_function():\\n    pass\\n")
        ```
    """
    start_num, error = resolve_finite_int(start_num, "start_num")
    if error:
        return error
    end_num, error = resolve_end_num(end_num, "end_num")
    if error:
        return error
    # ``content`` is required and must be a string. A falsy non-string such as
    # ``0``, ``[]`` or ``{}`` would otherwise fall through to the empty-content
    # branch and silently delete the replaced lines, while ``42`` would raise
    # ``AttributeError``. Only an explicit empty string may delete lines.
    if not isinstance(content, str):
        return invalid_request("content", content, "must be a string")

    with _file_tool.ctxm_temp_file("") as (tmp_file, fp):
        # Check if file exists
        if not os.path.exists(file_path):
            raise Exception(f"File not found: {file_path}")

        # Parse content if it comes as a JSON string
        if isinstance(content, str):
            try:
                parsed = json_tool.json_load(content)
                if parsed is not None and isinstance(parsed, str):
                    content = parsed
            except Exception:
                pass

        # Read the entire file content to preserve line endings
        with open(file_path, 'r', encoding='utf-8') as file:
            original_content = file.read()

        if original_content:
            fp.write(original_content)
            fp.flush()

        # Split content into lines while preserving line endings
        lines_content = original_content.splitlines(keepends=True)

        # Handle the new content: split into lines
        if not content:
            new_lines = []
        else:
            # Split content into lines, preserving line endings
            new_lines = content.splitlines(keepends=True)

        # Convert to 0-based indices
        start_idx = start_num - 1

        # ``0`` means no end line, so only ``start_num`` is replaced.
        # ``-1`` means through the end of the file.
        if end_num == 0:
            end_idx = start_num
        elif end_num == -1:
            end_idx = len(lines_content)
        else:
            # end_num is 1-based inclusive, so end_num as slice end gives exclusive end
            end_idx = end_num

        # Validate start_num is within bounds
        if start_idx < 0:
            raise Exception(f"Invalid start_num: {start_num}. Must be >= 1.")

        if start_idx >= len(lines_content):
            raise Exception(
                f"start_num ({start_num}) exceeds file length ({len(lines_content)} lines)"
            )

        # Constrain end_idx within bounds
        if end_idx > len(lines_content):
            end_idx = len(lines_content)

        # Validate range: the replaced block must contain at least one line
        if start_idx >= end_idx:
            raise Exception(
                f"Invalid range: start_num ({start_num}) > end_num ({end_num})"
            )

        # Ensure new_lines elements that don't end with a line ending get proper
        # separation when there are subsequent original lines
        if new_lines and not new_lines[-1].endswith(('\n', '\r\n', '\r')):
            # Last new line has no line ending
            if lines_content[end_idx:]:
                # There are subsequent original lines after the replaced block
                next_line = lines_content[end_idx]
                # Extract the line ending from the first subsequent original line
                original_line_ending = next_line[len(next_line.rstrip()):]
                if original_line_ending:
                    new_lines[-1] = new_lines[-1] + original_line_ending
                else:
                    # Next line has no line ending (e.g., last line without \n),
                    # but we still need separation between blocks
                    new_lines[-1] = new_lines[-1] + '\n'
            else:
                # No subsequent lines - preserve the original line ending from
                # the last replaced line
                last_replaced_line = lines_content[end_idx - 1]
                original_line_ending = last_replaced_line[len(last_replaced_line.rstrip()):]
                if original_line_ending:
                    new_lines[-1] = new_lines[-1] + original_line_ending

        # Replace the block: keep lines before start_idx, insert new content,
        # keep lines after end_idx
        result_lines = lines_content[:start_idx] + new_lines + lines_content[end_idx:]

        # Write the modified content back to the file
        new_content_str = ''.join(result_lines)
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(new_content_str)
            file.flush()

        diff_content = file_diff.compare_files_strived(tmp_file, file_path)
        return (
            "> You CANNOT call continuously due to the line number will change after each call.\n"
            "> Invoke the tool that provides line numbers to check content Now!\n"
            + diff_content
        )
