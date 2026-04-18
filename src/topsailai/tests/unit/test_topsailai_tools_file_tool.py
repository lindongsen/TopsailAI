#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Unit tests for file_tool module
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
from topsailai.tools.file_tool import write_file, read_file, replace_lines_in_file, insert_data_to_file

class TestFileToolWriteFile:
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

    def test_write_file_create_new(self, test_file):
        """Test creating a new file with content"""
        result = write_file(test_file, "Hello World!")
        assert result == ""
        assert os.path.exists(test_file)
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Hello World!"

    def test_write_file_overwrite_existing(self, test_file):
        """Test overwriting an existing file"""
        # Create initial file
        with open(test_file, 'w') as f:
            f.write("Initial content")

        result = write_file(test_file, "New content")
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "New content"

    def test_write_file_insert_mode_append_end(self, test_file):
        """Test insert mode with negative seek (append to end)"""
        with open(test_file, 'w') as f:
            f.write("Hello")

        result = write_file(test_file, " World!", seek=-1, to_insert=True)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Hello World!"

    def test_write_file_insert_mode_middle(self, test_file):
        """Test insert mode in the middle of content"""
        with open(test_file, 'w') as f:
            f.write("Hello World!")

        result = write_file(test_file, "Beautiful ", seek=6, to_insert=True)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Hello Beautiful World!"

    def test_write_file_insert_mode_beginning(self, test_file):
        """Test insert mode at the beginning"""
        with open(test_file, 'w') as f:
            f.write("World!")

        result = write_file(test_file, "Hello ", seek=0, to_insert=True)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Hello World!"

    def test_write_file_overwrite_mode_seek_positive(self, test_file):
        """Test overwrite mode with positive seek"""
        with open(test_file, 'w') as f:
            f.write("Hello World!")

        result = write_file(test_file, "Universe", seek=6, to_insert=False)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Hello Universe"

    def test_write_file_overwrite_mode_seek_negative(self, test_file):
        """Test overwrite mode with negative seek"""
        with open(test_file, 'w') as f:
            f.write("Hello World!")

        result = write_file(test_file, "Universe", seek=-6, to_insert=False)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Hello Universe"

    def test_write_file_overwrite_mode_seek_zero(self, test_file):
        """Test overwrite mode with seek=0"""
        with open(test_file, 'w') as f:
            f.write("Hello World!")

        result = write_file(test_file, "New", seek=0, to_insert=False)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "New"

    def test_write_file_insert_mode_nonexistent_file(self, test_file):
        """Test insert mode on non-existent file (should create file)"""
        result = write_file(test_file, "Content", seek=5, to_insert=True)
        assert result == ""
        assert os.path.exists(test_file)
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Content"

    def test_write_file_error_handling(self):
        """Test error handling with invalid file path"""
        result = write_file("/invalid/path/test.txt", "content")
        assert result != ""  # Should return error message
        assert "Permission denied" in result or "No such file or directory" in result

    def test_write_file_large_seek_insert(self, test_file):
        """Test insert mode with seek beyond file length"""
        with open(test_file, 'w') as f:
            f.write("Short")

        result = write_file(test_file, " text", seek=100, to_insert=True)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Short text"

    def test_write_file_large_seek_overwrite(self, test_file):
        """Test overwrite mode with seek beyond file length"""
        with open(test_file, 'w') as f:
            f.write("Short")

        result = write_file(test_file, "Longer content", seek=100, to_insert=False)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        # Should append content after existing content when seek is beyond file length
        assert content == "ShortLonger content"

    def test_write_file_integration_with_read_file(self, test_file):
        """Test integration between write_file and read_file"""
        # Write content
        result = write_file(test_file, "Test content")
        assert result == ""

        # Read it back
        content = read_file(test_file)
        assert content == "Test content"

    def test_write_file_empty_content(self, test_file):
        """Test writing empty content"""
        result = write_file(test_file, "")
        assert result == ""
        assert os.path.exists(test_file)
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == ""

    def test_write_file_special_characters(self, test_file):
        """Test writing content with special characters"""
        content = "Hello\nWorld!\tTabbed\nNewline"  # Use consistent \n line endings
        result = write_file(test_file, content)
        assert result == ""
        with open(test_file, 'r') as f:
            read_content = f.read()
        assert read_content == content

    def test_write_file_unicode_characters(self, test_file):
        """Test writing content with Unicode characters"""
        content = "你好世界！🌍✨\nUnicode test: ñáéíóú\nEmoji: 😊🚀🎉"
        result = write_file(test_file, content)
        assert result == ""
        with open(test_file, 'r', encoding='utf-8') as f:
            read_content = f.read()
        assert read_content == content

    def test_write_file_large_content(self, test_file):
        """Test writing large content"""
        large_content = "A" * 10000  # 10KB of data
        result = write_file(test_file, large_content)
        assert result == ""
        with open(test_file, 'r') as f:
            read_content = f.read()
        assert len(read_content) == 10000
        assert read_content == large_content

    def test_write_file_complex_seek_patterns(self, test_file):
        """Test complex seek patterns with multiple operations"""
        # Initial content
        result = write_file(test_file, "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        assert result == ""

        # Insert at position 10 (after 'J')
        result = write_file(test_file, "INSERT", seek=10, to_insert=True)
        assert result == ""

        with open(test_file, 'r') as f:
            assert f.read() == "ABCDEFGHIJINSERTKLMNOPQRSTUVWXYZ"

        # Overwrite from position 5 (after 'E') - replaces 9 characters (length of "OVERWRITE")
        result = write_file(test_file, "OVERWRITE", seek=5, to_insert=False)
        assert result == ""

        # Append to end
        result = write_file(test_file, "APPEND", seek=-1, to_insert=True)
        assert result == ""

        with open(test_file, 'r') as f:
            final_content = f.read()

        # Expected behavior:
        # 1. Initial: "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        # 2. Insert "INSERT" at position 10: "ABCDEFGHIJINSERTKLMNOPQRSTUVWXYZ"
        # 3. Overwrite 9 chars from position 5: "ABCDE" + "OVERWRITE" + "RTKLMNOPQRSTUVWXYZ" = "ABCDEOVERWRITERTKLMNOPQRSTUVWXYZ"
        # 4. Append "APPEND": "ABCDEOVERWRITERTKLMNOPQRSTUVWXYZAPPEND"

        # Verify the expected content
        expected = "ABCDEOVERWRITERTKLMNOPQRSTUVWXYZAPPEND"
        assert final_content == expected
        assert len(final_content) == len(expected)

    def test_write_file_edge_case_seek_values(self, test_file):
        """Test edge case seek values"""
        # Test very large negative seek
        result = write_file(test_file, "Content", seek=-1000, to_insert=True)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Content"

        # Test very large positive seek on empty file - current implementation doesn't pad
        # so it just writes the content at position 0
        result = write_file(test_file, "Content", seek=1000, to_insert=False)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "ContentContent"  # No padding in current implementation

    def test_write_file_multibyte_characters_seek(self, test_file):
        """Test seek operations with multibyte characters"""
        # Create file with multibyte characters
        content = "你好世界Hello世界你好"
        result = write_file(test_file, content)
        assert result == ""

        # Insert in the middle of multibyte sequence
        result = write_file(test_file, "INSERT", seek=6, to_insert=True)
        assert result == ""

        with open(test_file, 'r', encoding='utf-8') as f:
            final_content = f.read()

        # Should handle multibyte characters correctly
        assert "INSERT" in final_content

    def test_write_file_performance_large_operations(self, test_file):
        """Test performance with multiple large operations"""
        # Create initial large file
        large_content = "X" * 5000
        result = write_file(test_file, large_content)
        assert result == ""

        # Perform multiple insert operations
        for i in range(10):
            result = write_file(test_file, f"INSERT{i}", seek=100 * i, to_insert=True)
            assert result == ""

        # Verify final content
        with open(test_file, 'r') as f:
            content = f.read()
        assert len(content) > 5000
        assert "INSERT9" in content

    def test_write_file_error_recovery(self, test_file):
        """Test error recovery scenarios"""
        # First create a valid file
        result = write_file(test_file, "Valid content")
        assert result == ""

        # Try to write to invalid path (should not affect original file)
        invalid_result = write_file("/invalid/path/file.txt", "content")
        assert invalid_result != ""

        # Original file should still be intact
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Valid content"


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
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace line 3
        result = replace_lines_in_file(test_file, [(3, "New Line 3")])
        assert result == "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"

        # Verify the replacement
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"
        assert content == expected_content

    def test_replace_lines_in_file_multiple_lines(self, test_file):
        """Test replacing multiple lines in a file"""
        # Create initial file content
        initial_content = "First line\nSecond line\nThird line\nFourth line\nFifth line"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace lines 2 and 4
        result = replace_lines_in_file(test_file, [
            (2, "New Second line"),
            (4, "New Fourth line")
        ])
        assert result == "First line\nNew Second line\nThird line\nNew Fourth line\nFifth line"

        # Verify the replacements
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "First line\nNew Second line\nThird line\nNew Fourth line\nFifth line"
        assert content == expected_content

    def test_replace_lines_in_file_preserve_line_endings(self, test_file):
        """Test that line endings are preserved when replacing lines"""
        # Create initial file with mixed line endings
        initial_content = "Line 1\nLine 2\r\nLine 3\nLine 4\r\nLine 5"
        with open(test_file, 'w', newline='') as f:
            f.write(initial_content)

        # Replace line 3
        result = replace_lines_in_file(test_file, [(3, "New Line 3")])
        assert result == "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"

        # Verify the replacement - the function normalizes line endings to \n
        with open(test_file, 'r', newline='') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"
        assert content == expected_content

    def test_replace_lines_in_file_out_of_bounds_line(self, test_file):
        """Test replacing a line that doesn't exist (should not modify file)"""
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Try to replace line 10 (which doesn't exist)
        result = replace_lines_in_file(test_file, [(10, "Non-existent line")])
        assert result == initial_content

        # Verify the file content remains unchanged
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == initial_content

    def test_replace_lines_in_file_negative_line_number(self, test_file):
        """Test replacing with negative line number (should not modify file)"""
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Try to replace line -1 (invalid)
        result = replace_lines_in_file(test_file, [(-1, "Invalid line")])
        assert result == initial_content

        # Verify the file content remains unchanged
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == initial_content

    def test_replace_lines_in_file_empty_file(self, test_file):
        """Test replacing lines in an empty file (should not modify file)"""
        # Create empty file
        with open(test_file, 'w') as f:
            f.write("")

        # Try to replace line 1
        result = replace_lines_in_file(test_file, [(1, "New line")])
        assert result == ""

        # Verify the file remains empty
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == ""

    def test_replace_lines_in_file_single_line_no_newline(self, test_file):
        """Test replacing a line in a file with no trailing newline"""
        # Create file without trailing newline
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace line 2
        result = replace_lines_in_file(test_file, [(2, "New Line 2")])
        assert result == "Line 1\nNew Line 2\nLine 3"

        # Verify the replacement
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nNew Line 2\nLine 3"
        assert content == expected_content

    def test_replace_lines_in_file_with_empty_lines(self, test_file):
        """Test replacing lines including empty lines"""
        # Create file with empty lines
        initial_content = "Line 1\n\nLine 3\n\nLine 5"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace lines 2 and 4 (empty lines)
        result = replace_lines_in_file(test_file, [
            (2, "Filled Line 2"),
            (4, "Filled Line 4")
        ])
        assert result == "Line 1\nFilled Line 2\nLine 3\nFilled Line 4\nLine 5"

        # Verify the replacements
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nFilled Line 2\nLine 3\nFilled Line 4\nLine 5"
        assert content == expected_content

    def test_replace_lines_in_file_same_line_multiple_times(self, test_file):
        """Test replacing the same line multiple times in one call"""
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace line 2 multiple times (last replacement should win)
        result = replace_lines_in_file(test_file, [
            (2, "First replacement"),
            (2, "Second replacement"),
            (2, "Final replacement")
        ])
        assert result == "Line 1\nFinal replacement\nLine 3"

        # Verify only the last replacement is applied
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nFinal replacement\nLine 3"
        assert content == expected_content

    def test_replace_lines_in_file_error_handling(self):
        """Test error handling with non-existent file"""
        # Try to replace lines in a non-existent file
        result = replace_lines_in_file("/non/existent/file.txt", [(1, "Content")])
        # The function should return an error message, not "OK"
        assert result != "OK"
        assert "File not found" in result or "No such file" in result

    def test_replace_lines_in_file_unicode_content(self, test_file):
        """Test replacing lines with Unicode content"""
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(initial_content)

        # Replace with Unicode content
        unicode_content = "你好世界 🌍\nUnicode line with emoji 😊"
        result = replace_lines_in_file(test_file, [(2, unicode_content)])
        expected_content = f"Line 1\n{unicode_content}\nLine 3"
        assert result == expected_content

        # Verify the Unicode content is preserved
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        expected_content = f"Line 1\n{unicode_content}\nLine 3"
        assert content == expected_content

    def test_replace_lines_in_file_large_file(self, test_file):
        """Test replacing lines in a large file"""
        # Create a large file with many lines
        lines = [f"Line {i}" for i in range(1000)]
        initial_content = "\n".join(lines)
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace multiple lines throughout the file
        result = replace_lines_in_file(test_file, [
            (1, "New First Line"),
            (500, "Middle Line Replacement"),
            (1000, "New Last Line")
        ])
        # Verify the result is the new content
        lines_result = result.splitlines()
        assert lines_result[0] == "New First Line"
        assert lines_result[499] == "Middle Line Replacement"
        assert lines_result[999] == "New Last Line"
        assert len(lines_result) == 1000

        # Verify the replacements
        with open(test_file, 'r') as f:
            content = f.read()

        lines = content.splitlines()
        assert lines[0] == "New First Line"
        assert lines[499] == "Middle Line Replacement"  # 0-based index
        assert lines[999] == "New Last Line"
        assert len(lines) == 1000

    def test_replace_lines_in_file_zero_line_number(self, test_file):
        """Test replacing line 0 (invalid line number)"""
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Try to replace line 0 (invalid)
        result = replace_lines_in_file(test_file, [(0, "Invalid line")])
        assert result == initial_content

        # Verify the file content remains unchanged
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == initial_content

    def test_replace_lines_in_file_mixed_line_endings_preserved(self, test_file):
        """Test that mixed line endings are preserved when replacing lines"""
        # Create initial file with mixed line endings
        initial_content = "Line 1\nLine 2\r\nLine 3\nLine 4\rLine 5"
        with open(test_file, 'w', newline='') as f:
            f.write(initial_content)

        # Replace line 3
        result = replace_lines_in_file(test_file, [(3, "New Line 3")])
        assert result == "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"

        # Verify the replacement - the function normalizes line endings to \n
        with open(test_file, 'r', newline='') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nNew Line 3\nLine 4\nLine 5"
        assert content == expected_content

    def test_replace_lines_in_file_empty_content_replacement(self, test_file):
        """Test replacing lines with empty content"""
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace line 2 with empty content
        result = replace_lines_in_file(test_file, [(2, "")])
        assert result == "Line 1\n\nLine 3"

        # Verify the replacement
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\n\nLine 3"
        assert content == expected_content

    def test_replace_lines_in_file_null_content_replacement(self, test_file):
        """Test replacing lines with None content (should be treated as empty string)"""
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace line 2 with None content
        result = replace_lines_in_file(test_file, [(2, None)])
        assert result == "Line 1\n\nLine 3"

        # Verify the replacement (None should be treated as empty string)
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\n\nLine 3"
        assert content == expected_content

    def test_replace_lines_in_file_permission_error(self, test_file):
        """Test error handling with permission denied"""
        # Create a file and make it read-only to test permission errors
        with open(test_file, 'w') as f:
            f.write("Line 1\nLine 2\nLine 3")

        # Make file read-only
        os.chmod(test_file, 0o444)

        try:
            # Try to replace a line (should fail with permission error)
            result = replace_lines_in_file(test_file, [(2, "New Line 2")])
            # The function may return file content if the permission error doesn't occur in this environment
            # or it may return an error message
            # Check if it's either the modified content or an error
            if result != "Line 1\nNew Line 2\nLine 3":
                assert "Permission denied" in result or "permission" in result.lower()
            else:
                # If the modification succeeded, that's acceptable too - it means the environment
                # doesn't enforce read-only permissions in the expected way
                pass
        finally:
            # Restore permissions for cleanup
            os.chmod(test_file, 0o644)

    def test_replace_lines_in_file_last_line(self, test_file):
        """Test replacing the last line in a file"""
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace the last line (line 3)
        result = replace_lines_in_file(test_file, [(3, "New Last Line")])
        assert result == "Line 1\nLine 2\nNew Last Line"

        # Verify the replacement
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nNew Last Line"
        assert content == expected_content

    def test_replace_lines_in_file_last_line_no_newline(self, test_file):
        """Test replacing the last line in a file with no trailing newline"""
        # Create file without trailing newline
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace the last line (line 3)
        result = replace_lines_in_file(test_file, [(3, "New Last Line")])
        assert result == "Line 1\nLine 2\nNew Last Line"

        # Verify the replacement
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nNew Last Line"
        assert content == expected_content

    def test_replace_lines_in_file_first_line(self, test_file):
        """Test replacing the first line in a file"""
        # Create initial file content
        initial_content = "Line 1\nLine 2\nLine 3"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Replace the first line (line 1)
        result = replace_lines_in_file(test_file, [(1, "New First Line")])
        assert result == "New First Line\nLine 2\nLine 3"

        # Verify the replacement
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "New First Line\nLine 2\nLine 3"
        assert content == expected_content


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
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert after line 2
        result = insert_data_to_file(test_file, "Inserted Line", line_num=2, before_or_after="after")
        assert result == "Line 1\nLine 2\nInserted Line\nLine 3\n"

        # Verify the insertion
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nInserted Line\nLine 3\n"
        assert content == expected_content

    def test_insert_data_to_file_before_line(self, test_file):
        """Test inserting data before a specific line"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert before line 3
        result = insert_data_to_file(test_file, "Inserted Line", line_num=3, before_or_after="before")
        assert result == "Line 1\nLine 2\nInserted Line\nLine 3\n"

        # Verify the insertion
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nInserted Line\nLine 3\n"
        assert content == expected_content

    def test_insert_data_to_file_first_line_after(self, test_file):
        """Test inserting data after the first line"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert after line 1
        result = insert_data_to_file(test_file, "New Line", line_num=1, before_or_after="after")
        assert result == "Line 1\nNew Line\nLine 2\nLine 3\n"

        # Verify the insertion
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nNew Line\nLine 2\nLine 3\n"
        assert content == expected_content

    def test_insert_data_to_file_last_line_after(self, test_file):
        """Test inserting data after the last line"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert after last line (line 3)
        result = insert_data_to_file(test_file, "New Line", line_num=3, before_or_after="after")
        assert result == "Line 1\nLine 2\nLine 3\nNew Line\n"

        # Verify the insertion
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nLine 3\nNew Line\n"
        assert content == expected_content

    def test_insert_data_to_file_empty_file(self, test_file):
        """Test inserting data into an empty file"""
        # Create empty file
        with open(test_file, 'w') as f:
            f.write("")

        # Try to insert after line 0 (clamped to 0)
        result = insert_data_to_file(test_file, "New Line", line_num=0, before_or_after="after")
        assert result == "New Line\n"

        # Verify the insertion - function adds newline to data
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "New Line\n"
        assert content == expected_content

    def test_insert_data_to_file_data_without_newline(self, test_file):
        """Test inserting data without trailing newline (should add one)"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert without newline
        result = insert_data_to_file(test_file, "Inserted", line_num=1, before_or_after="after")
        assert result == "Line 1\nInserted\nLine 2\n"

        # Verify the insertion - newline should be added automatically
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nInserted\nLine 2\n"
        assert content == expected_content

    def test_insert_data_to_file_data_with_newline(self, test_file):
        """Test inserting data that already ends with newline"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert with trailing newline
        result = insert_data_to_file(test_file, "Inserted Line\n", line_num=1, before_or_after="after")
        assert result == "Line 1\nInserted Line\nLine 2\n"

        # Verify the insertion
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nInserted Line\nLine 2\n"
        assert content == expected_content

    def test_insert_data_to_file_invalid_before_or_after(self, test_file):
        """Test error handling with invalid before_or_after value"""
        # Create initial file
        with open(test_file, 'w') as f:
            f.write("Line 1\n")

        # Try to insert with invalid before_or_after
        with pytest.raises(ValueError) as exc_info:
            insert_data_to_file(test_file, "New Line", line_num=1, before_or_after="invalid")

        assert "before_or_after must be 'before' or 'after'" in str(exc_info.value)

    def test_insert_data_to_file_out_of_bounds_line(self, test_file):
        """Test inserting after a line number beyond file length"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert after line 100 (beyond file length)
        result = insert_data_to_file(test_file, "New Line", line_num=100, before_or_after="after")
        assert result == "Line 1\nLine 2\nNew Line\n"

        # Verify the insertion - should append at end
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nNew Line\n"
        assert content == expected_content

    def test_insert_data_to_file_zero_line_number(self, test_file):
        """Test inserting at line 0"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert after line 0 (clamped to beginning)
        result = insert_data_to_file(test_file, "New Line", line_num=0, before_or_after="after")
        assert result == "New Line\nLine 1\nLine 2\n"

        # Verify the insertion
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "New Line\nLine 1\nLine 2\n"
        assert content == expected_content

    def test_insert_data_to_file_unicode_content(self, test_file):
        """Test inserting Unicode content"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(initial_content)

        # Insert Unicode content
        unicode_content = "你好世界 🌍"
        result = insert_data_to_file(test_file, unicode_content, line_num=1, before_or_after="after")
        expected_content = f"Line 1\n{unicode_content}\nLine 2\n"
        assert result == expected_content

        # Verify the insertion
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        expected_content = f"Line 1\n{unicode_content}\nLine 2\n"
        assert content == expected_content

    def test_insert_data_to_file_empty_data(self, test_file):
        """Test inserting empty data - empty data is not inserted"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert empty data - empty string is falsy so it won't be inserted
        result = insert_data_to_file(test_file, "", line_num=1, before_or_after="after")
        assert result == initial_content

        # Verify - empty data is not inserted (function does nothing for empty data)
        with open(test_file, 'r') as f:
            content = f.read()
        # Empty data is not inserted - function skips insertion for empty/falsy data
        assert content == initial_content

    def test_insert_data_to_file_large_line_number_before(self, test_file):
        """Test inserting before a line number larger than file"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert before line 100 (beyond file length)
        # Both "before" and "after" clamp to end when line number > file length
        result = insert_data_to_file(test_file, "New Line", line_num=100, before_or_after="before")
        assert result == "Line 1\nLine 2\nLine 3\nNew Line\n"

        # Verify the insertion - function clamps to end, same as "after"
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Line 1\nLine 2\nLine 3\nNew Line\n"
        assert content == expected_content

    def test_insert_data_to_file_single_line_file(self, test_file):
        """Test inserting into a file with a single line"""
        # Create file with single line (with trailing newline)
        initial_content = "Only Line\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert after line 1
        result = insert_data_to_file(test_file, "New Line", line_num=1, before_or_after="after")
        assert result == "Only Line\nNew Line\n"

        # Verify the insertion
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = "Only Line\nNew Line\n"
        assert content == expected_content

    def test_insert_data_to_file_special_characters(self, test_file):
        """Test inserting content with special characters"""
        # Create initial file content with trailing newline
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)

        # Insert with special characters
        special_content = "Tab:\tNewline:\nBackslash:\\"
        result = insert_data_to_file(test_file, special_content, line_num=1, before_or_after="after")
        expected_content = f"Line 1\n{special_content}\nLine 2\n"
        assert result == expected_content

        # Verify the insertion
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = f"Line 1\n{special_content}\nLine 2\n"
        assert content == expected_content