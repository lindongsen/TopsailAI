#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Unit tests for file_tool write operations
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
        assert result in ("", True)
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
        # Use /proc/ path that will genuinely fail on any Linux system
        result = write_file("/proc/1/cmdline_fake/test.txt", "content")
        assert result != ""
        assert "Permission denied" in result or "No such file" in result

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
        assert content == "ShortLonger content"

    def test_write_file_integration_with_read_file(self, test_file):
        """Test integration between write_file and read_file"""
        result = write_file(test_file, "Test content")
        assert result == ""
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
        content = "Hello\nWorld!\tTabbed\nNewline"
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
        large_content = "A" * 10000
        result = write_file(test_file, large_content)
        assert result == ""
        with open(test_file, 'r') as f:
            read_content = f.read()
        assert len(read_content) == 10000
        assert read_content == large_content

    def test_write_file_complex_seek_patterns(self, test_file):
        """Test complex seek patterns with multiple operations"""
        result = write_file(test_file, "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        assert result == ""
        result = write_file(test_file, "INSERT", seek=10, to_insert=True)
        assert result == ""
        with open(test_file, 'r') as f:
            assert f.read() == "ABCDEFGHIJINSERTKLMNOPQRSTUVWXYZ"
        result = write_file(test_file, "OVERWRITE", seek=5, to_insert=False)
        assert result == ""
        # append_file returns True, not ""
        result = write_file(test_file, "APPEND", seek=-1, to_insert=True)
        assert result in ("", True)
        with open(test_file, 'r') as f:
            final_content = f.read()
        expected = "ABCDEOVERWRITERTKLMNOPQRSTUVWXYZAPPEND"
        assert final_content == expected

    def test_write_file_edge_case_seek_values(self, test_file):
        """Test edge case seek values"""
        result = write_file(test_file, "Content", seek=-1000, to_insert=True)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Content"
        result = write_file(test_file, "Content", seek=1000, to_insert=False)
        assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "ContentContent"

    def test_write_file_multibyte_characters_seek(self, test_file):
        """Test seek operations with multibyte characters"""
        content = "你好世界Hello世界你好"
        result = write_file(test_file, content)
        assert result == ""
        result = write_file(test_file, "INSERT", seek=6, to_insert=True)
        assert result == ""
        with open(test_file, 'r', encoding='utf-8') as f:
            final_content = f.read()
        assert "INSERT" in final_content

    def test_write_file_performance_large_operations(self, test_file):
        """Test performance with multiple large operations"""
        large_content = "X" * 5000
        result = write_file(test_file, large_content)
        assert result == ""
        for i in range(10):
            result = write_file(test_file, f"INSERT{i}", seek=100 * i, to_insert=True)
            assert result == ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert len(content) > 5000
        assert "INSERT9" in content

    def test_write_file_error_recovery(self, test_file):
        """Test error recovery scenarios"""
        result = write_file(test_file, "Valid content")
        assert result == ""
        # Use /proc/ path that will genuinely fail
        invalid_result = write_file("/proc/1/cmdline_fake/test.txt", "content")
        assert invalid_result != ""
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Valid content"
