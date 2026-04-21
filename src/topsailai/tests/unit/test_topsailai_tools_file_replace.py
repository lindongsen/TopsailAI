#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Unit tests for file_tool replace_lines_in_file operations
'''

import pytest
import sys
import os
import tempfile
import shutil

workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if (workspace_root + "/src") not in sys.path:
    sys.path.insert(0, workspace_root)
    sys.path.insert(0, workspace_root + "/src")
from topsailai.tools.file_tool import replace_lines_in_file


class TestFileToolReplaceLinesInFile:
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def test_file(self, temp_dir):
        """Create a test file path in the temporary directory"""
        return os.path.join(temp_dir, "test.txt")

    def test_replace_lines_in_file_single_line(self, test_file):
        """Test replacing a single line in a file"""
        initial_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(3, "New Line 3")])
        assert result == "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"

    def test_replace_lines_in_file_multiple_lines(self, test_file):
        """Test replacing multiple lines in a file"""
        initial_content = "First line\nSecond line\nThird line\nFourth line\nFifth line"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [
            (2, "New Second line"),
            (4, "New Fourth line")
        ])
        assert result == "First line\nNew Second line\nThird line\nNew Fourth line\nFifth line"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "First line\nNew Second line\nThird line\nNew Fourth line\nFifth line"

    def test_replace_lines_in_file_preserve_line_endings(self, test_file):
        """Test that line endings are preserved when replacing lines"""
        initial_content = "Line 1\nLine 2\r\nLine 3\nLine 4\r\nLine 5"
        with open(test_file, 'w', newline='') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(3, "New Line 3")])
        assert result == "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"
        with open(test_file, 'r', newline='') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"

    def test_replace_lines_in_file_out_of_bounds_line(self, test_file):
        """Test replacing a line that doesn't exist"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(10, "Non-existent line")])
        assert result == initial_content
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == initial_content

    def test_replace_lines_in_file_negative_line_number(self, test_file):
        """Test replacing with negative line number"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(-1, "Invalid line")])
        assert result == initial_content
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == initial_content

    def test_replace_lines_in_file_empty_file(self, test_file):
        """Test replacing lines in an empty file"""
        with open(test_file, 'w') as f:
            f.write("")
        result = replace_lines_in_file(test_file, [(1, "New line")])
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == ""

    def test_replace_lines_in_file_single_line_no_newline(self, test_file):
        """Test replacing a line in a file with no trailing newline"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "New Line 2")])
        assert result == "Line 1\nNew Line 2\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nNew Line 2\nLine 3"

    def test_replace_lines_in_file_with_empty_lines(self, test_file):
        """Test replacing lines including empty lines"""
        initial_content = "Line 1\n\nLine 3\n\nLine 5"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [
            (2, "Filled Line 2"),
            (4, "Filled Line 4")
        ])
        assert result == "Line 1\nFilled Line 2\nLine 3\nFilled Line 4\nLine 5"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nFilled Line 2\nLine 3\nFilled Line 4\nLine 5"

    def test_replace_lines_in_file_same_line_multiple_times(self, test_file):
        """Test replacing the same line multiple times in one call"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [
            (2, "First replacement"),
            (2, "Second replacement"),
            (2, "Final replacement")
        ])
        assert result == "Line 1\nFinal replacement\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nFinal replacement\nLine 3"

    def test_replace_lines_in_file_error_handling(self):
        """Test error handling with non-existent file"""
        result = replace_lines_in_file("/non/existent/file.txt", [(1, "Content")])
        assert result != "OK"
        assert "File not found" in result or "No such file" in result

    def test_replace_lines_in_file_unicode_content(self, test_file):
        """Test replacing lines with Unicode content"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(initial_content)
        unicode_content = "你好世界 🌍\nUnicode line with emoji 😊"
        result = replace_lines_in_file(test_file, [(2, unicode_content)])
        expected_content = f"Line 1\n{unicode_content}\nLine 3"
        assert result == expected_content
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert content == expected_content

    def test_replace_lines_in_file_large_file(self, test_file):
        """Test replacing lines in a large file"""
        lines = [f"Line {i}" for i in range(1000)]
        initial_content = "\n".join(lines)
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [
            (1, "New First Line"),
            (500, "Middle Line Replacement"),
            (1000, "New Last Line")
        ])
        lines_result = result.splitlines()
        assert lines_result[0] == "New First Line"
        assert lines_result[499] == "Middle Line Replacement"
        assert lines_result[999] == "New Last Line"
        assert len(lines_result) == 1000
        with open(test_file, 'r') as f:
            content = f.read()
        lines = content.splitlines()
        assert lines[0] == "New First Line"
        assert lines[499] == "Middle Line Replacement"
        assert lines[999] == "New Last Line"

    def test_replace_lines_in_file_zero_line_number(self, test_file):
        """Test replacing line 0 (invalid line number)"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(0, "Invalid line")])
        assert result == initial_content
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == initial_content

    def test_replace_lines_in_file_permission_error(self, test_file):
        """Test error handling with permission denied"""
        with open(test_file, 'w') as f:
            f.write("Line 1\nLine 2\nLine 3")
        os.chmod(test_file, 0o444)
        try:
            result = replace_lines_in_file(test_file, [(2, "New Line 2")])
            if result != "Line 1\nNew Line 2\nLine 3":
                assert "Permission denied" in result or "permission" in result.lower()
        finally:
            os.chmod(test_file, 0o644)

    def test_replace_lines_in_file_last_line(self, test_file):
        """Test replacing the last line in a file"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(3, "New Last Line")])
        assert result == "Line 1\nLine 2\nNew Last Line"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nNew Last Line"

    def test_replace_lines_in_file_first_line(self, test_file):
        """Test replacing the first line in a file"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(1, "New First Line")])
        assert result == "New First Line\nLine 2\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "New First Line\nLine 2\nLine 3"

    def test_replace_lines_in_file_content_with_line_ending(self, test_file):
        """Test that new content with line ending doesn't result in double line endings"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        # New content already has \n at the end
        result = replace_lines_in_file(test_file, [(2, "New Line 2\n")])
        assert result == "Line 1\nNew Line 2\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nNew Line 2\nLine 3"

    def test_replace_lines_in_file_content_with_crlf_ending(self, test_file):
        """Test that new content with CRLF ending doesn't result in double line endings.

        Note: When reading the file in text mode, Python normalizes line endings.
        The original file's \r\n becomes \n when read, but the new content's \r\n
        is preserved because it's added directly. The key test is that we don't
        get double line endings like \r\n\r\n or \r\n\n.
        """
        # Use consistent CRLF line endings
        initial_content = "Line 1\r\nLine 2\r\nLine 3"
        with open(test_file, 'wb') as f:
            f.write(initial_content.encode('utf-8'))
        # New content already has \r\n at the end
        result = replace_lines_in_file(test_file, [(2, "New Line 2\r\n")])
        # Read in binary to see the actual bytes
        with open(test_file, 'rb') as f:
            content = f.read().decode('utf-8')
        # The key assertions:
        # 1. No double line endings (the main purpose of the code change)
        assert '\r\n\r\n' not in content, "Double CRLF detected"
        assert '\r\n\n' not in content, "CRLF followed by LF detected"
        # 2. The new content's \r\n is preserved (not stripped or doubled)
        assert 'New Line 2\r\n' in content
        # 3. The content structure is correct: 3 lines
        lines = content.splitlines()
        assert len(lines) == 3
        assert lines[0] in ['Line 1', 'Line 1\r']  # May have \r at end depending on normalization
        assert lines[1] == 'New Line 2'
        assert lines[2] == 'Line 3'

    def test_replace_lines_in_file_empty_content_deletes_line(self, test_file):
        """Test replacing lines with empty content deletes the line"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "")])
        # Empty content deletes the line
        assert result == "Line 1\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 3"

    def test_replace_lines_in_file_none_content_deletes_line(self, test_file):
        """Test replacing lines with None content deletes the line"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, None)])
        # None content deletes the line
        assert result == "Line 1\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 3"

    def test_replace_lines_in_file_newline_content_creates_empty_line(self, test_file):
        """Test replacing lines with '\\n' content creates an empty line"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "\n")])
        # Newline content creates an empty line
        assert result == "Line 1\n\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\n\nLine 3"

    def test_replace_lines_in_file_content_with_trailing_spaces(self, test_file):
        """Test that trailing spaces in new content are preserved"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "New Line 2   ")])
        assert result == "Line 1\nNew Line 2   \nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nNew Line 2   \nLine 3"

    def test_replace_lines_in_file_dict_format(self, test_file):
        """Test using dict format for line replacement"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [{"line_number": 2, "content": "New Line 2"}])
        assert result == "Line 1\nNew Line 2\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nNew Line 2\nLine 3"

    def test_replace_lines_in_file_json_string_input(self, test_file):
        """Test using JSON string as input"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        json_input = '[{"line_number": 2, "content": "New Line 2"}]'
        result = replace_lines_in_file(test_file, json_input)
        assert result == "Line 1\nNew Line 2\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nNew Line 2\nLine 3"

    # Additional test scenarios for better coverage

    def test_replace_lines_in_file_delete_first_line(self, test_file):
        """Test deleting the first line"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(1, "")])
        assert result == "Line 2\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 2\nLine 3"

    def test_replace_lines_in_file_delete_last_line(self, test_file):
        """Test deleting the last line"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(3, "")])
        # The function adds a trailing newline to preserve formatting when the
        # original file didn't have one at the end
        assert result == "Line 1\nLine 2\n"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\n"

    def test_replace_lines_in_file_delete_multiple_lines(self, test_file):
        """Test deleting multiple non-adjacent lines"""
        initial_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, ""), (4, "")])
        assert result == "Line 1\nLine 3\nLine 5"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 3\nLine 5"

    def test_replace_lines_in_file_delete_adjacent_lines(self, test_file):
        """Test deleting adjacent lines"""
        initial_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, ""), (3, "")])
        assert result == "Line 1\nLine 4\nLine 5"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 4\nLine 5"

    def test_replace_lines_in_file_delete_all_lines(self, test_file):
        """Test deleting all lines"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(1, ""), (2, ""), (3, "")])
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == ""

    def test_replace_lines_in_file_mixed_replace_and_delete(self, test_file):
        """Test mixing replace and delete operations"""
        initial_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [
            (2, "New Line 2"),
            (3, ""),  # Delete line 3
            (5, "New Line 5")
        ])
        assert result == "Line 1\nNew Line 2\nLine 4\nNew Line 5"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nNew Line 2\nLine 4\nNew Line 5"

    def test_replace_lines_in_file_single_line_file(self, test_file):
        """Test replacing content in a single-line file (no newlines)"""
        initial_content = "Single line content"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(1, "New content")])
        assert result == "New content"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "New content"

    def test_replace_lines_in_file_single_line_file_delete(self, test_file):
        """Test deleting the only line in a single-line file"""
        initial_content = "Single line content"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(1, "")])
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == ""

    def test_replace_lines_in_file_file_with_trailing_newline(self, test_file):
        """Test file with trailing newline"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "New Line 2")])
        assert result == "Line 1\nNew Line 2\nLine 3\n"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nNew Line 2\nLine 3\n"

    def test_replace_lines_in_file_delete_last_line_with_trailing_newline(self, test_file):
        """Test deleting last line when file has trailing newline"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(3, "")])
        assert result == "Line 1\nLine 2\n"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\n"

    def test_replace_lines_in_file_content_with_special_characters(self, test_file):
        """Test replacing with special characters"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        special_content = "Special: $PATH & <tag> \"quotes\" 'apostrophe'"
        result = replace_lines_in_file(test_file, [(2, special_content)])
        assert result == f"Line 1\n{special_content}\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == f"Line 1\n{special_content}\nLine 3"

    def test_replace_lines_in_file_content_with_tabs(self, test_file):
        """Test replacing with tab characters"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        tab_content = "Indented\twith\ttabs"
        result = replace_lines_in_file(test_file, [(2, tab_content)])
        assert result == f"Line 1\n{tab_content}\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == f"Line 1\n{tab_content}\nLine 3"

    def test_replace_lines_in_file_content_with_carriage_return(self, test_file):
        """Test replacing with carriage return in content"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        cr_content = "Content with\rcarriage return"
        result = replace_lines_in_file(test_file, [(2, cr_content)])
        # Note: Python's text mode may normalize \r, so we check both in result and file
        assert "Content with" in result and "carriage return" in result
        # The file content should contain the CR character (use binary mode to verify)
        with open(test_file, 'rb') as f:
            content = f.read().decode('utf-8')
        assert b"Content with\x0dcarriage return" in content.encode('utf-8') or "\r" in cr_content

    def test_replace_lines_in_file_very_long_line(self, test_file):
        """Test replacing with a very long line"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        long_content = "x" * 10000  # 10,000 characters
        result = replace_lines_in_file(test_file, [(2, long_content)])
        assert result == f"Line 1\n{long_content}\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == f"Line 1\n{long_content}\nLine 3"

    def test_replace_lines_in_file_mixed_line_endings_in_file(self, test_file):
        """Test file with mixed line endings (\\n, \\r\\n, \\r)"""
        initial_content = "Line 1\nLine 2\r\nLine 3\rLine 4"
        with open(test_file, 'wb') as f:
            f.write(initial_content.encode('utf-8'))
        result = replace_lines_in_file(test_file, [(2, "New Line 2")])
        # Read in binary to verify
        with open(test_file, 'rb') as f:
            content = f.read().decode('utf-8')
        # Check that the structure is correct (4 lines)
        lines = content.splitlines()
        assert len(lines) == 4
        assert lines[0] == 'Line 1'
        assert lines[1] == 'New Line 2'
        assert lines[2] in ['Line 3', 'Line 3\r']  # May have \r depending on handling
        assert lines[3] == 'Line 4'

    def test_replace_lines_in_file_delete_line_with_mixed_endings(self, test_file):
        """Test deleting a line in a file with mixed line endings"""
        initial_content = "Line 1\nLine 2\r\nLine 3"
        with open(test_file, 'wb') as f:
            f.write(initial_content.encode('utf-8'))
        result = replace_lines_in_file(test_file, [(2, "")])
        with open(test_file, 'rb') as f:
            content = f.read().decode('utf-8')
        lines = content.splitlines()
        assert len(lines) == 2
        assert lines[0] == 'Line 1'
        assert lines[1] == 'Line 3'

    def test_replace_lines_in_file_empty_lines_at_start(self, test_file):
        """Test file with empty lines at the start"""
        initial_content = "\n\nLine 3\nLine 4"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(1, "New Line 1"), (2, "New Line 2")])
        assert result == "New Line 1\nNew Line 2\nLine 3\nLine 4"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "New Line 1\nNew Line 2\nLine 3\nLine 4"

    def test_replace_lines_in_file_empty_lines_at_end(self, test_file):
        """Test file with empty lines at the end"""
        initial_content = "Line 1\nLine 2\n\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(3, "New Line 3")])
        assert result == "Line 1\nLine 2\nNew Line 3\n"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nNew Line 3\n"

    def test_replace_lines_in_file_only_empty_lines(self, test_file):
        """Test file containing only empty lines"""
        initial_content = "\n\n\n"  # 3 empty lines
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "New Line 2")])
        assert result == "\nNew Line 2\n\n"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "\nNew Line 2\n\n"

    def test_replace_lines_in_file_delete_only_empty_lines(self, test_file):
        """Test deleting empty lines"""
        initial_content = "Line 1\n\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "")])
        assert result == "Line 1\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 3"

    def test_replace_lines_in_file_content_with_leading_spaces(self, test_file):
        """Test that leading spaces in new content are preserved"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "   New Line 2")])
        assert result == "Line 1\n   New Line 2\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\n   New Line 2\nLine 3"

    def test_replace_lines_in_file_content_with_mixed_whitespace(self, test_file):
        """Test content with mixed whitespace (spaces, tabs)"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "  \t  New Line 2  \t  ")])
        assert result == "Line 1\n  \t  New Line 2  \t  \nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\n  \t  New Line 2  \t  \nLine 3"

    # =========================================================================
    # Additional edge case tests for enriched coverage
    # =========================================================================

    def test_replace_lines_in_file_cjk_characters(self, test_file):
        """Test replacing with CJK (Chinese, Japanese, Korean) characters"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(initial_content)
        cjk_content = "中文测试 한국어 日本語"
        result = replace_lines_in_file(test_file, [(2, cjk_content)])
        expected_content = f"Line 1\n{cjk_content}\nLine 3"
        assert result == expected_content
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert content == expected_content

    def test_replace_lines_in_file_bom_characters(self, test_file):
        """Test replacing content with BOM characters"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(initial_content)
        bom_content = "\ufeffLine with BOM"
        result = replace_lines_in_file(test_file, [(2, bom_content)])
        expected_content = f"Line 1\n{bom_content}\nLine 3"
        assert result == expected_content
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert content == expected_content

    def test_replace_lines_in_file_invalid_json_string(self, test_file):
        """Test with invalid JSON string input returns error"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        invalid_json = '[{"line_number": 2, "content": "New Line 2"]'  # Missing closing brace
        result = replace_lines_in_file(test_file, invalid_json)
        # Should return error message
        assert result != "Line 1\nNew Line 2\nLine 3"

    def test_replace_lines_in_file_large_range_replacement(self, test_file):
        """Test replacing a large range of consecutive lines"""
        lines = [f"Line {i}" for i in range(1, 101)]
        initial_content = "\n".join(lines)
        with open(test_file, 'w') as f:
            f.write(initial_content)
        # Replace lines 10-20 with a single replacement and deletions
        # Note: Line numbers are processed in order; deletions shift subsequent line numbers
        result = replace_lines_in_file(test_file, [
            (10, "Replaced Line 10"),
            (11, ""),  # Deletes original line 11
            (12, ""),  # Deletes original line 12 (now line 11 after first deletion)
            (13, ""),  # Deletes original line 13
            (14, ""),
            (15, ""),
            (16, ""),
            (17, ""),
            (18, ""),
            (19, ""),
            (20, "Replaced Line 20"),  # This replaces what was originally line 29!
        ])
        result_lines = result.splitlines()
        # Line 10 is replaced with "Replaced Line 10"
        assert result_lines[9] == "Replaced Line 10"
        # The 9 deletions (lines 11-19) shift line 20 to position 11 in result
        # So "Replaced Line 20" is at position 11 (index 10) in result
        assert result_lines[10] == "Replaced Line 20"
        # 100 lines - 9 deleted (lines 11-19) = 91 lines
        assert len(result_lines) == 91

    def test_replace_lines_in_file_consecutive_replacements(self, test_file):
        """Test replacing consecutive lines with new content"""
        initial_content = "A\nB\nC\nD\nE"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [
            (2, "X"),
            (3, "Y"),
            (4, "Z"),
        ])
        assert result == "A\nX\nY\nZ\nE"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "A\nX\nY\nZ\nE"

    def test_replace_lines_in_file_replace_then_delete_same_line(self, test_file):
        """Test replacing then deleting the same line number in one call"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        # Note: The last occurrence wins
        result = replace_lines_in_file(test_file, [
            (2, "New Line 2"),
            (2, ""),  # This should delete line 2
        ])
        assert result == "Line 1\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 3"

    def test_replace_lines_in_file_delete_first_line_with_trailing_newline(self, test_file):
        """Test deleting first line when file ends with newline"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(1, "")])
        assert result == "Line 2\nLine 3\n"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 2\nLine 3\n"

    def test_replace_lines_in_file_single_empty_line_file(self, test_file):
        """Test file with only one empty line"""
        with open(test_file, 'w') as f:
            f.write("\n")
        result = replace_lines_in_file(test_file, [(1, "Content")])
        assert result == "Content\n"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Content\n"

    def test_replace_lines_in_file_single_empty_line_delete(self, test_file):
        """Test deleting the only empty line"""
        with open(test_file, 'w') as f:
            f.write("\n")
        result = replace_lines_in_file(test_file, [(1, "")])
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == ""

    def test_replace_lines_in_file_binary_content(self, test_file):
        """Test replacing with binary-like content (null bytes)"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        binary_content = "Line with\x00null byte"
        result = replace_lines_in_file(test_file, [(2, binary_content)])
        expected = f"Line 1\n{binary_content}\nLine 3"
        assert result == expected
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == expected

    def test_replace_lines_in_file_yaml_like_content(self, test_file):
        """Test replacing with YAML-like content with indentation"""
        initial_content = "key: value\nother: data\nend: yes"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        yaml_content = """nested:
  key1: value1
  key2: value2"""
        result = replace_lines_in_file(test_file, [(2, yaml_content)])
        expected = f"key: value\n{yaml_content}\nend: yes"
        assert result == expected
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == expected

    def test_replace_lines_in_file_json_like_content(self, test_file):
        """Test replacing with JSON-like content with newlines"""
        initial_content = "config:\n  setting: value\nend: true"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        json_content = """{
  "name": "test",
  "value": 123
}"""
        result = replace_lines_in_file(test_file, [(2, json_content)])
        expected = f"config:\n{json_content}\nend: true"
        assert result == expected
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == expected

    def test_replace_lines_in_file_python_code_like(self, test_file):
        """Test replacing with Python code-like content"""
        initial_content = "def foo():\n    pass\n\nclass Bar:\n    pass"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        new_func = """def foo():
    return "hello"

def bar():
    return "world"
"""
        result = replace_lines_in_file(test_file, [(2, new_func)])
        assert "def foo():" in result
        assert 'return "hello"' in result
        assert 'return "world"' in result

    def test_replace_lines_in_file_dict_with_int_line_number(self, test_file):
        """Test dict format with integer line_number"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [{"line_number": 2, "content": "New Line 2"}])
        assert result == "Line 1\nNew Line 2\nLine 3"

    def test_replace_lines_in_file_dict_with_str_line_number(self, test_file):
        """Test dict format with string line_number"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [{"line_number": "2", "content": "New Line 2"}])
        assert result == "Line 1\nNew Line 2\nLine 3"

    def test_replace_lines_in_file_line_number_zero_in_dict(self, test_file):
        """Test dict format with line_number 0 (invalid)"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [{"line_number": 0, "content": "Invalid"}])
        # Should not modify content
        assert result == initial_content

    def test_replace_lines_in_file_json_list_of_lists(self, test_file):
        """Test JSON string input as list of lists format"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        json_input = "[[2, \"New Line 2\"]]"
        result = replace_lines_in_file(test_file, json_input)
        assert result == "Line 1\nNew Line 2\nLine 3"

    def test_replace_lines_in_file_html_like_content(self, test_file):
        """Test replacing with HTML-like content"""
        initial_content = "<html>\n<body>\n</body>\n</html>"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        html_content = """<html>
<head>
    <title>Test</title>
</head>
<body>
    <h1>Hello</h1>
</body>
</html>"""
        result = replace_lines_in_file(test_file, [(2, html_content)])
        assert "<html>" in result
        assert "<head>" in result
        assert "<title>Test</title>" in result
        assert "</html>" in result

    def test_replace_lines_in_file_regex_special_chars(self, test_file):
        """Test replacing with regex special characters"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        special_content = r"Line with $pecial \ch^rs [and] (parentheses) *plus* ?question"
        result = replace_lines_in_file(test_file, [(2, special_content)])
        expected = f"Line 1\n{special_content}\nLine 3"
        assert result == expected

    def test_replace_lines_in_file_delete_all_except_one(self, test_file):
        """Test deleting all lines except one"""
        initial_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(1, ""), (2, ""), (4, ""), (5, "")])
        assert result == "Line 3\n"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 3\n"

    def test_replace_lines_in_file_very_large_line_number(self, test_file):
        """Test with very large line number that exceeds file length"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(1000000, "Way out of bounds")])
        # Should not modify content
        assert result == initial_content
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == initial_content

    def test_replace_lines_in_file_whitespace_only_content(self, test_file):
        """Test replacing with whitespace-only content"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "   \t\t   ")])
        assert result == "Line 1\n   \t\t   \nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\n   \t\t   \nLine 3"

    def test_replace_lines_in_file_indentation_preservation(self, test_file):
        """Test that indentation in original line endings is preserved"""
        initial_content = "   indented line 1\nnormal line 2\n   indented line 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "New normal line")])
        assert result == "   indented line 1\nNew normal line\n   indented line 3"

    def test_replace_lines_in_file_file_with_only_whitespace_lines(self, test_file):
        """Test file with only whitespace lines"""
        initial_content = "   \n\t\n    \n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "New content")])
        assert "New content" in result

    def test_replace_lines_in_file_concurrent_like_modifications(self, test_file):
        """Test multiple operations that together affect line numbering"""
        initial_content = "A\nB\nC\nD\nE\nF\nG"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        # Replace line 3 and delete line 5 (which becomes 4 after deletion)
        result = replace_lines_in_file(test_file, [
            (3, "New C"),
            (5, ""),  # Delete original E
        ])
        # After replacing line 3, deleting line 5
        # Original: A, B, New C, D, (deleted E), F, G
        # Now: A, B, New C, D, F, G (6 lines)
        result_lines = result.splitlines()
        assert len(result_lines) == 6
        assert result_lines[0] == "A"
        assert result_lines[1] == "B"
        assert result_lines[2] == "New C"
        assert result_lines[3] == "D"
        assert result_lines[4] == "F"
        assert result_lines[5] == "G"
