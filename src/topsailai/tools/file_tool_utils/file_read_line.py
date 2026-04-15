'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose:
'''

import re

from topsailai.utils import text_tool


def read_file_with_context(
    file_path: str,
    pattern: str,
    context_num: int = 10,
    case_sensitive: bool = False
) -> str:
    """Read a file and return lines matching a pattern with context.

    Provide line numbers and context lines around matches.

    Args:
        file_path (str): Path to the file to read
        pattern (str): Regular expression pattern to search for
        context_num (int, optional): Number of context lines to show before and after each match. Defaults to 10.
        case_sensitive (bool, optional): Whether the search should be case sensitive. Defaults to False.

    Returns:
        str: Formatted output with line numbers and context.
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
        - Context lines are deduplicated when matches are close together
        - Uses safe_decode for proper text handling
    """
    context_num = int(context_num)
    if isinstance(case_sensitive, str):
        if case_sensitive.lower() == "true":
            case_sensitive = True
        else:
            case_sensitive = False
    try:
        # Read file content
        with open(file_path, 'rb') as fd:
            raw_content = fd.read()

        # Decode content safely
        content = text_tool.safe_decode(raw_content)
        if not content:
            return ""

        # Split into lines
        lines = content.splitlines()
        if not lines:
            return ""

        # Compile regex pattern
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern '{pattern}': {e}"

        # Find all matching lines
        matches = []
        for i, line in enumerate(lines):
            if regex.search(line):
                matches.append(i)

        if not matches:
            return ""

        # Collect lines to display (with context)
        lines_to_show = set()

        for match_idx in matches:
            # Add context lines before match
            start = max(0, match_idx - context_num)
            # Add context lines after match
            end = min(len(lines), match_idx + context_num + 1)

            # Add all lines in this range
            for i in range(start, end):
                lines_to_show.add(i)

        # Sort line numbers
        sorted_lines = sorted(lines_to_show)

        # Build output
        output_lines = []
        for line_num in sorted_lines:
            line_content = lines[line_num]
            # Check if this line is a match
            is_match = line_num in matches
            # Format: line_number:content for matches, line_number-content for context
            marker = ":" if is_match else "-"
            output_lines.append(f"{line_num + 1}{marker}{line_content}")

        return "\n".join(output_lines)

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
        - Automatically handles edge cases (beginning/end of file)
        - Uses safe_decode for proper text handling
    """
    line_number = int(line_number)
    context_num = int(context_num)
    try:
        # Read file content
        with open(file_path, 'rb') as fd:
            raw_content = fd.read()

        # Decode content safely
        content = text_tool.safe_decode(raw_content)
        if not content:
            return ""

        # Split into lines
        lines = content.splitlines()
        if not lines:
            return ""

        # Convert to 0-based index
        target_idx = line_number - 1

        # Validate line number
        if target_idx < 0 or target_idx >= len(lines):
            return f"Error: Line number {line_number} is out of range (file has {len(lines)} lines)"

        # Calculate range with context
        start_idx = max(0, target_idx - context_num)
        end_idx = min(len(lines), target_idx + context_num + 1)

        # Build output
        output_lines = []
        for i in range(start_idx, end_idx):
            line_content = lines[i]
            # Mark the target line with ':', others with '-'
            marker = ":" if i == target_idx else "-"
            output_lines.append(f"{i + 1}{marker}{line_content}")

        return "\n".join(output_lines)

    except FileNotFoundError:
        return f"Error: File not found: {file_path}"
    except PermissionError:
        return f"Error: Permission denied reading file: {file_path}"
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


def read_file_lines(file_path: str, start_num: int, end_num: int) -> str:
    """Read specific lines from a file and return them as a string.
    This function reads a range of lines from a file using 1-based line numbering.
    Print line number with output lines, format is "{number}-{line_content}"

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
    try:
        start_num = int(start_num)
        end_num = int(end_num)
        if not start_num:
            start_num = 1

        # Validate range: start_num must be <= end_num when both are non-zero
        if end_num != 0 and start_num > end_num:
            return f"Error: Invalid range: start_num ({start_num}) > end_num ({end_num})"

        # Read file content
        with open(file_path, 'rb') as fd:
            raw_content = fd.read()

        # Decode content safely
        content = text_tool.safe_decode(raw_content)
        if not content:
            return ""

        # Split into lines
        lines = content.splitlines()
        if not lines:
            return ""

        # Convert 1-based line numbers to 0-based indices
        start_idx = start_num - 1
        if end_num:
            end_idx = end_num  # slice end is exclusive, so end_num gives us correct slice
        else:
            end_idx = len(lines)

        # Validate start_idx is within bounds
        if start_idx >= len(lines):
            return ""

        # Get the slice of lines
        result_lines = lines[start_idx:end_idx]
        if not result_lines:
            return ""

        # Build output with actual line numbers and '-' marker
        output_lines = []
        for i, line_content in enumerate(result_lines):
            actual_line_num = start_num + i
            output_lines.append(f"{actual_line_num}-{line_content}")

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
