'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-28
Purpose: One line model shared by the file read and write tools.
'''

import io


def split_lines(text: str) -> list[str]:
    """Split text into lines using the same boundaries the read tool reports.

    ``str.splitlines()`` treats eleven characters as line boundaries, while the
    read tool iterates an ``io.TextIOWrapper`` whose universal-newline mode
    recognises only ``\\n``, ``\\r`` and ``\\r\\n``. The line numbers shown to a
    model come from the read tool, so the read tool defines what a line is; a
    write that counts differently selects a different line than the model saw.

    ``io.StringIO(text, newline="")`` reproduces that model exactly and keeps
    every line ending byte for byte. ``newline=None`` must not be used here: it
    translates ``\\r\\n`` and ``\\r`` to ``\\n``, which would rewrite the line
    endings of the whole file on a single-line edit.

    Args:
        text (str): Text to split.

    Returns:
        list[str]: Lines with their original endings preserved. An empty string
            yields an empty list, and a trailing newline does not produce a
            final empty element.
    """
    if not text:
        return []
    return io.StringIO(text, newline="").readlines()


def read_text(file_path: str) -> str:
    """Read a file without translating its line endings.

    The default ``newline=None`` converts ``\\r\\n`` and ``\\r`` to ``\\n`` while
    reading, so a tool that reads and writes back would flatten every line
    ending in the file even when it edited one line.

    Args:
        file_path (str): Path to the file to read.

    Returns:
        str: The file content with its original line endings.
    """
    with open(file_path, 'r', encoding='utf-8', newline='') as handle:
        return handle.read()


def write_text(file_path: str, text: str) -> None:
    """Write text without translating its line endings.

    Args:
        file_path (str): Path to the file to write.
        text (str): Content to write, with the line endings to keep.
    """
    with open(file_path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(text)
        handle.flush()


def line_ending_of(line: str) -> str:
    """Return only the line ending of a line, never its trailing whitespace.

    ``line[len(line.rstrip()):]`` looks like it extracts the ending but also
    strips spaces and tabs, so the "ending" of ``"b  \\n"`` becomes ``"  \\n"``.
    Appending that to a replacement injects the next line's trailing spaces into
    the edited line.

    Args:
        line (str): A line that may or may not end with a line ending.

    Returns:
        str: ``"\\r\\n"``, ``"\\n"``, ``"\\r"``, or an empty string.
    """
    if line.endswith('\r\n'):
        return '\r\n'
    if line.endswith('\n'):
        return '\n'
    if line.endswith('\r'):
        return '\r'
    return ''


def dominant_line_ending(text: str) -> str:
    """Return the line ending a file uses, for text that must be added to it.

    A tool that appends a bare ``"\\n"`` to a CRLF file introduces one LF line
    among CRLF lines, so the file ends up with mixed endings and every later
    diff shows more changes than the edit made.

    The first line that has an ending defines the convention. Counting endings
    instead would need a tie-break rule for a mixed file, and the first line is
    both deterministic and the line a reader sees first.

    Args:
        text (str): Whole file content.

    Returns:
        str: ``"\\r\\n"``, ``"\\n"``, or ``"\\r"``; ``"\\n"`` when the text has
            no line ending at all, because a new line still needs one.
    """
    for line in split_lines(text):
        ending = line_ending_of(line)
        if ending:
            return ending
    return '\n'
