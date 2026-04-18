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

    def test_replace_lines_in_file_empty_content_replacement(self, test_file):
        """Test replacing lines with empty content"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, "")])
        assert result == "Line 1\n\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\n\nLine 3"

    def test_replace_lines_in_file_null_content_replacement(self, test_file):
        """Test replacing lines with None content"""
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = replace_lines_in_file(test_file, [(2, None)])
        assert result == "Line 1\n\nLine 3"
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\n\nLine 3"

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
