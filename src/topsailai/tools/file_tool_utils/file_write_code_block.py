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
from . import file_diff, file_line_model


def _render_changed_range(start_idx: int, new_lines: list[str]) -> str:
    """Render the post-edit content of the replaced range with line numbers.

    The requested ``start_num``/``end_num`` describe the *old* range and cannot
    be reused for display: the replacement may add lines or remove them, so the
    range that now holds the new content has a different end. The new range is
    derived from the lines actually written.

    The lines are taken from the in-memory result instead of re-reading the
    file, because the write path already decoded the file as UTF-8 while the
    read path guesses the encoding from a byte sample. A mostly-ASCII file with
    one CJK line is detected as ISO-8859-1 and would be displayed as mojibake,
    so re-reading could show content that differs from what was written.

    Args:
        start_idx (int): 0-based index where the replacement started.
        new_lines (list[str]): The replacement lines, with their line endings.

    Returns:
        str: A titled section holding ``{line_number}-{content}`` lines, or an
            explicit note when the replacement deleted every line in the range.
    """
    if not new_lines:
        return (
            "## Changed Range (current content)\n"
            "The replaced range is now empty: every line in it was deleted.\n"
        )

    first_line = start_idx + 1
    last_line = start_idx + len(new_lines)
    body = "\n".join(
        f"{first_line + offset}-{line.rstrip('\r\n')}"
        for offset, line in enumerate(new_lines)
    )
    return (
        f"## Changed Range (current content, lines {first_line}-{last_line})\n"
        f"{body}\n"
    )


def overwrite_code_block(file_path: str, start_num: int, end_num: int = 0, content: str = None, **_) -> str:
    """
    Replace a contiguous line range with new content. This is the only tool that
    edits existing lines; use `insert_content_to_file` to add lines without
    replacing any.

    The replaced range is `start_num`..`end_num` inclusive, 1-based. Everything
    outside that range is preserved byte for byte, including line endings.

    IMPORTANT LOGIC:
    To ensure code integrity and indentation, do not replace lines individually
    if they are part of a logical block (e.g., a function, a loop, or a class).
    Instead, replace the entire block containing the change in a single operation.
    > You MUST confirm the line numbers before each call.
    > You CANNOT call continuously due to the line number will change after each call.

    Args:
        file_path (str): Path to the file to modify.
        start_num (int): The 1-based starting line number to begin replacement -> **include this line to replace**.
                         MUST be >= 1; a smaller value is rejected and the file is left untouched.
                         Numeric strings such as "12" and floats such as 12.9 are
                         coerced to an integer.
        end_num (int): The 1-based ending line number (inclusive) to end replacement.
                       Omitted, ``0``, ``None``, or blank text means no end line,
                       so ONLY ``start_num`` is replaced. ``0`` never means "to the
                       end of the file"; pass ``-1`` explicitly for that.
                       ``-1`` replaces from ``start_num`` through the end of the file.
                       A positive number replaces through that line, inclusive;
                       ``end_num == start_num`` replaces exactly one line.
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

    CRITICAL: content REPLACES the range, it does not append to it.
        The lines in the range are removed first, then ``content`` is inserted.
        Never repeat the anchor line inside ``content``. Copying the line you are
        replacing into the replacement duplicates it in the file.

        Wrong - line 2 is replaced by "b" then "B", so "b" appears twice:
            overwrite_lines_in_file(file_path="a.py", start_num=2, end_num=2,
                                    content="b\\nB\\n")
            before: a b c        after: a b B c

        Right - replace line 2 with only the new line:
            overwrite_lines_in_file(file_path="a.py", start_num=2, end_num=2,
                                    content="B\\n")
            before: a b c        after: a B c

    Line endings:
        A ``content`` that does not end with a newline still gets one when more
        lines follow, so the following line is never glued onto your last line.

    JSON string content:
        A ``content`` that parses as a JSON string is unwrapped before use, so a
        quoted "B\\n" writes B plus a newline. A JSON object or array is written
        literally as text.

    Returns:
        str: three sections on success, or an ``invalid_request`` dict when a
        parameter is rejected. Out-of-range line numbers raise an
        ``Exception`` instead of returning, so confirm the line numbers first.

        The three sections are:
        1. A reminder that the line numbers changed and must be re-read.
        2. ``## Diff`` — the unified diff of the edit.
        3. ``## Changed Range`` — the current content of the replaced range with
           line numbers. Its end line is recomputed from the lines actually
           written, because the replacement may add or remove lines, so it can
           differ from the requested ``end_num``. Use these numbers for the next
           call instead of the ones you passed in.

    Example:
        Replace lines 5-10 with a new function
        ```
        overwrite_lines_in_file(file_path="example.py", start_num=5, end_num=10,
                                content="def new_function():\\n    pass\\n")
        ```

        Replace only line 5
        ```
        overwrite_lines_in_file(file_path="example.py", start_num=5, end_num=0,
                                content="def new_function():\\n    pass\\n")
        ```

        Replace line 5 through the end of the file
        ```
        overwrite_lines_in_file(file_path="example.py", start_num=5, end_num=-1,
                                content="def new_function():\\n    pass\\n")
        ```

        Delete lines 5-10
        ```
        overwrite_lines_in_file(file_path="example.py", start_num=5, end_num=10,
                                content="")
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

        # Read the entire file content without translating line endings, so an
        # edit to one line does not rewrite the endings of every other line.
        original_content = file_line_model.read_text(file_path)

        if original_content:
            fp.write(original_content)
            fp.flush()

        # Split with the same line model the read tool reports, so a line number
        # obtained from the read tool selects the line the model intended.
        lines_content = file_line_model.split_lines(original_content)

        # Handle the new content: split into lines
        if not content:
            new_lines = []
        else:
            # Split content into lines, preserving line endings
            new_lines = file_line_model.split_lines(content)

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
                # Take only the ending, never the trailing spaces of that line
                original_line_ending = file_line_model.line_ending_of(next_line)
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
                original_line_ending = file_line_model.line_ending_of(last_replaced_line)
                if original_line_ending:
                    new_lines[-1] = new_lines[-1] + original_line_ending

        # Replace the block: keep lines before start_idx, insert new content,
        # keep lines after end_idx
        result_lines = lines_content[:start_idx] + new_lines + lines_content[end_idx:]

        # Write the modified content back without translating line endings
        new_content_str = ''.join(result_lines)
        file_line_model.write_text(file_path, new_content_str)

        diff_content = file_diff.compare_files_strived(tmp_file, file_path)
        # The replacement may add or remove lines, so the range that now holds
        # the new content is derived from the lines actually written instead of
        # the requested ``end_num``.
        changed_range = _render_changed_range(start_idx, new_lines)
        return (
            "> You CANNOT call continuously due to the line number will change after each call.\n"
            "> Invoke the tool that provides line numbers to check content Now!\n"
            "\n## Diff\n"
            f"{diff_content}\n"
            f"{changed_range}"
        )
