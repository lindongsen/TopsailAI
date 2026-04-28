#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Unit tests for file_tool insert_data_to_file operations
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
from topsailai.tools.file_tool import insert_data_to_file


class TestFileToolInsertDataToFile:
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

    def test_insert_data_to_file_after_line(self, test_file):
        """Test inserting data after a specific line"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "Inserted Line", line_num=2, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nInserted Line\nLine 3\n"

    def test_insert_data_to_file_before_line(self, test_file):
        """Test inserting data before a specific line"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "Inserted Line", line_num=3, before_or_after="before")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nInserted Line\nLine 3\n"

    def test_insert_data_to_file_first_line_after(self, test_file):
        """Test inserting data after the first line"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "New Line", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nNew Line\nLine 2\nLine 3\n"

    def test_insert_data_to_file_last_line_after(self, test_file):
        """Test inserting data after the last line"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "New Line", line_num=3, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nLine 3\nNew Line\n"

    def test_insert_data_to_file_empty_file(self, test_file):
        """Test inserting data into an empty file"""
        with open(test_file, 'w') as f:
            f.write("")
        result = insert_data_to_file(test_file, "New Line", line_num=0, before_or_after="after")
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "New Line\n"

    def test_insert_data_to_file_data_without_newline(self, test_file):
        """Test inserting data without trailing newline"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "Inserted", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nInserted\nLine 2\n"

    def test_insert_data_to_file_data_with_newline(self, test_file):
        """Test inserting data that already ends with newline"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "Inserted Line\n", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nInserted Line\nLine 2\n"

    def test_insert_data_to_file_invalid_before_or_after(self, test_file):
        """Test error handling with invalid before_or_after value"""
        with open(test_file, 'w') as f:
            f.write("Line 1\n")
        with pytest.raises(ValueError) as exc_info:
            insert_data_to_file(test_file, "New Line", line_num=1, before_or_after="invalid")
        assert "before_or_after must be 'before' or 'after'" in str(exc_info.value)

    def test_insert_data_to_file_out_of_bounds_line(self, test_file):
        """Test inserting after a line number beyond file length"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "New Line", line_num=100, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nNew Line\n"

    def test_insert_data_to_file_zero_line_number(self, test_file):
        """Test inserting at line 0"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "New Line", line_num=0, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "New Line\nLine 1\nLine 2\n"

    def test_insert_data_to_file_unicode_content(self, test_file):
        """Test inserting Unicode content"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(initial_content)
        unicode_content = "你好世界 🌍"
        result = insert_data_to_file(test_file, unicode_content, line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        expected_content = f"Line 1\n{unicode_content}\nLine 2\n"
        assert content == expected_content

    def test_insert_data_to_file_empty_data(self, test_file):
        """Test inserting empty data"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        # Empty data produces no diff changes, so no '+' markers
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == initial_content

    def test_insert_data_to_file_large_line_number_before(self, test_file):
        """Test inserting before a line number larger than file"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "New Line", line_num=100, before_or_after="before")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nLine 3\nNew Line\n"

    def test_insert_data_to_file_single_line_file(self, test_file):
        """Test inserting into a file with a single line"""
        initial_content = "Only Line\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_data_to_file(test_file, "New Line", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Only Line\nNew Line\n"

    def test_insert_data_to_file_special_characters(self, test_file):
        """Test inserting content with special characters"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        special_content = "Tab:\tNewline:\nBackslash:\\"
        result = insert_data_to_file(test_file, special_content, line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = f"Line 1\n{special_content}\nLine 2\n"
        assert content == expected_content
