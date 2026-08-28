'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose:
'''

import io
import re
from collections import deque
from contextlib import contextmanager

import chardet

from topsailai.tools.tool_utils.parameter import resolve_finite_int


_ENCODING_SAMPLE_SIZE = 32768


@contextmanager
def _open_text_stream(file_path: str):
    """Open a file and yield a line iterator with sampled encoding detection.

    Reads a small byte sample from the start of the file to detect the
    encoding, then rewinds and yields an ``io.TextIOWrapper`` that decodes
    incrementally. This avoids loading or decoding the entire file when the
    caller only needs a small window of lines.
    """
    fd = open(file_path, 'rb')
    try:
        sample = fd.read(_ENCODING_SAMPLE_SIZE)
        encoding = _detect_encoding(sample)
        fd.seek(0)
        wrapper = io.TextIOWrapper(fd, encoding=encoding, errors='replace')
        try:
            yield wrapper
        finally:
            wrapper.close()
    finally:
        fd.close()


def _detect_encoding(sample_bytes: bytes) -> str:
    """Detect text encoding from a byte sample.

    Falls back to utf-8 when detection fails or returns nothing.
    """
    if not sample_bytes:
        return 'utf-8'
    detected = chardet.detect(sample_bytes)
    encoding = detected.get('encoding')
    if not encoding:
        return 'utf-8'
    return encoding


def _strip_line_ending(line: str) -> str:
    """Remove trailing line ending characters from a line.

    ``io.TextIOWrapper`` with universal newlines keeps the line ending
    character(s) in the yielded string. This helper strips them so the
    output matches the previous ``splitlines()`` behavior.
    """
    if line.endswith('\r\n'):
        return line[:-2]
    if line.endswith('\n') or line.endswith('\r'):
        return line[:-1]
    return line


_DEFAULT_CASE_SENSITIVE = False
_INVALID_CASE_SENSITIVE_REASON = "invalid_case_sensitive"


def _resolve_case_sensitive(value) -> tuple[bool, str | None]:
    """Resolve a case-sensitive flag accepting integer 1/0 and their string forms.

    Args:
        value: Raw argument value.

    Returns:
        tuple[bool, str | None]: Resolved flag with ``None`` when valid, or
            ``False`` with a machine-readable reason when invalid.
    """
    if value is None:
        return _DEFAULT_CASE_SENSITIVE, None
    if isinstance(value, bool):
        return value, None
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value), None
        return False, _INVALID_CASE_SENSITIVE_REASON
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return _DEFAULT_CASE_SENSITIVE, None
        if text in ("0", "1"):
            return text == "1", None
        return False, _INVALID_CASE_SENSITIVE_REASON
    return False, _INVALID_CASE_SENSITIVE_REASON


def read_file_with_context(
    file_path: str,
    pattern: str,
    context_num: int = 10,
    case_sensitive: int = 0
) -> str:
    """Read a file and return lines matching a pattern with context.

    Provide line numbers and context lines around matches.

    Output format:
        Each output line is formatted as ``{line_number}{marker}{content}``.
        ``line_number`` is the 1-based line number. ``marker`` is ``:`` for
        matching lines and ``-`` for context lines. The marker is the first
        character after the number and is NOT part of the file content.
        For example, ``109----`` means line 109 contains ``---`` (three
        dashes), not four.

    Args:
        file_path (str): Path to the file to read
        pattern (str): Regular expression pattern to search for
        context_num (int, optional): Number of context lines to show before and after each match. Defaults to 10.
        case_sensitive (int, optional): 1 for case-sensitive matching, 0 for case-insensitive. Defaults to 0.

    Returns:
        str: Formatted output with line numbers.
             Returns empty string if file doesn't exist or no matches found.

    Example:
        >>> content = read_file_with_context("example.py", "def function", context_num=3)
        >>> print(content)
        15-    some_code_here
        16-    more_code
        17:    def function():
        18-        function_body
        19-        return value
        20-    end_function
        21-    next_code

    Note:
        - Line numbers are 1-based (start from 1)
        - Matches are marked with ':' while context lines use '-'
        - The first '-' or ':' after the line number is the separator, not part of the content
        - Context lines are deduplicated when matches are close together
        - Uses streaming decoding to avoid loading the entire file into memory
    """
    context_num, error = resolve_finite_int(context_num, "context_num")
    if error:
        return f"Error: invalid_request reason={error['reason']}"
    case_sensitive, invalid_reason = _resolve_case_sensitive(case_sensitive)
    if invalid_reason is not None:
        return f"Error: invalid_request reason={invalid_reason}, case_sensitive must be integer 1 or 0"

    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern '{pattern}': {e}"

        result = {}
        with _open_text_stream(file_path) as wrapper:
            if context_num <= 0:
                for line_num, line in enumerate(wrapper, start=1):
                    line = _strip_line_ending(line)
                    if regex.search(line):
                        result[line_num] = f"{line_num}:{line}"
            else:
                pre_window = deque(maxlen=context_num)
                post_remaining = 0
                for line_num, line in enumerate(wrapper, start=1):
                    line = _strip_line_ending(line)
                    is_match = regex.search(line)
                    if is_match:
                        for ln, l in pre_window:
                            result[ln] = f"{ln}-{l}"
                        result[line_num] = f"{line_num}:{line}"
                        post_remaining = context_num
                        pre_window.clear()
                    elif post_remaining > 0:
                        result[line_num] = f"{line_num}-{line}"
                        post_remaining -= 1

                    if not is_match:
                        pre_window.append((line_num, line))

        if not result:
            return ""

        return "\n".join(
            result[line_num] for line_num in sorted(result)
        )

    except FileNotFoundError:
        return f"Error: File not found: {file_path}"
    except PermissionError:
        return f"Error: Permission denied reading file: {file_path}"
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


def read_file_around_line(
    file_path: str,
    line_number: int,
    context_num: int = 10
) -> str:
    """Read a file and return lines around a specific line number.

    This function provides context around a specific line, similar to viewing
    a section of a file with line numbers.

    Output format:
        Each output line is formatted as ``{line_number}{marker}{content}``.
        ``line_number`` is the 1-based line number. ``marker`` is ``:`` for
        the target line and ``-`` for surrounding context lines. The marker
        is the first character after the number and is NOT part of the file
        content. For example, ``109----`` means line 109 contains ``---``
        (three dashes), not four.

    Args:
        file_path (str): Path to the file to read
        line_number (int): The 1-based line number to center the view around
        context_num (int, optional): Number of lines to show before and after the target line. Defaults to 10.

    Returns:
        str: Formatted output with line numbers.
             Returns empty string if file doesn't exist or line number is invalid.

    Example:
        >>> content = read_file_around_line("example.py", 15, context_num=3)
        >>> print(content)
        12-some_code_here
        13-more_code
        14-previous_line
        15:target_line
        16-next_line
        17-more_code
        18-end_code

    Note:
        - Line numbers are 1-based (start from 1)
        - The target line is marked with ':' while other lines use '-'
        - The first '-' or ':' after the line number is the separator, not part of the content
        - Automatically handles edge cases (beginning/end of file)
        - Uses streaming decoding to avoid loading the entire file into memory
    """
    line_number, error = resolve_finite_int(line_number, "line_number")
    if error:
        return error
    context_num, error = resolve_finite_int(context_num, "context_num")
    if error:
        return error
    target_idx = line_number - 1

    try:
        output_lines = []
        total_lines = 0

        with _open_text_stream(file_path) as wrapper:
            if context_num <= 0:
                for line_num, line in enumerate(wrapper, start=1):
                    total_lines = line_num
                    line = _strip_line_ending(line)
                    if line_num == line_number:
                        output_lines.append(f"{line_num}:{line}")
                        break
            else:
                start_idx = max(0, target_idx - context_num)
                end_idx = target_idx + context_num + 1
                for line_num, line in enumerate(wrapper, start=1):
                    total_lines = line_num
                    line = _strip_line_ending(line)
                    idx = line_num - 1
                    if idx >= end_idx:
                        break
                    if idx >= start_idx:
                        marker = ":" if idx == target_idx else "-"
                        output_lines.append(f"{line_num}{marker}{line}")

        if total_lines == 0:
            return ""

        if target_idx < 0 or target_idx >= total_lines:
            return f"Error: Line number {line_number} is out of range (file has {total_lines} lines)"

        return "\n".join(output_lines)

    except FileNotFoundError:
        return f"Error: File not found: {file_path}"
    except PermissionError:
        return f"Error: Permission denied reading file: {file_path}"
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


def read_file_lines(file_path: str, start_num: int=1, end_num: int=0, **_) -> str:
    """Read specific lines from a file and return them as a string.

    This function reads a range of lines from a file using 1-based line numbering.

    Output format:
        Each output line is formatted as ``{line_number}-{content}``.
        ``line_number`` is the 1-based line number. The first ``-`` after the
        number is the separator and is NOT part of the file content. For
        example, ``109----`` means line 109 contains ``---`` (three dashes),
        not four.

    Args:
        file_path (str): The path to the file to read from
        start_num (int): The starting line number (1-based). Lines before this number
                        will be excluded. Must be >= 1.
        end_num (int): The ending line number (1-based, inclusive). 0 for no end limit.

    Returns:
        str: The concatenated content of the specified lines as a single string.
             Returns empty string if the file is empty or line range is invalid.

    Raises:
        This function catches all exceptions and returns them as strings rather than raising

    Examples:
        # Read lines 1-10 from a file
        content = read_file_lines("example.txt", 1, 10)

        # Read all of content from a file
        content = read_file_lines("example.txt", 1, 0)
    """
    start_num, error = resolve_finite_int(start_num, "start_num")
    if error:
        return error
    end_num, error = resolve_finite_int(end_num, "end_num")
    if error:
        return error
    try:
        if not start_num:
            start_num = 1

        if end_num != 0 and start_num > end_num:
            return f"Error: Invalid range: start_num ({start_num}) > end_num ({end_num})"

        start_idx = start_num - 1
        output_lines = []
        total_lines = 0

        with _open_text_stream(file_path) as wrapper:
            for line_num, line in enumerate(wrapper, start=1):
                total_lines = line_num
                line = _strip_line_ending(line)
                idx = line_num - 1
                if end_num and idx >= end_num:
                    break
                if idx >= start_idx:
                    output_lines.append(f"{line_num}-{line}")

        if total_lines == 0:
            return ""

        if start_idx >= total_lines:
            return ""

        return "\n".join(output_lines)
    except FileNotFoundError:
        return f"Error: File not found: {file_path}"
    except PermissionError:
        return f"Error: Permission denied reading file: {file_path}"
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


TOOLS = dict(
  read_file_around_line=read_file_around_line,
  read_file_lines=read_file_lines,
  read_file_with_context=read_file_with_context,
)
