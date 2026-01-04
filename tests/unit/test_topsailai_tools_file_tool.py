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
from topsailai.tools.file_tool import write_file, read_file

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
