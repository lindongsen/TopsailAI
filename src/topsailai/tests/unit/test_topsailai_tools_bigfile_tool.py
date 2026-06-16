"""
Unit tests for topsailai.tools.bigfile_tool module.

Test coverage:
- TOOLS dictionary contains read_file
- read_file is delegated from file_tool
- Normal file reading
- Edge cases (empty file, nonexistent file, seek/size parameters)
- Error handling

Author: km3-programmer
"""

import os
import tempfile
import pytest

from topsailai.tools import bigfile_tool
from topsailai.tools.bigfile_tool import TOOLS


class TestBigfileToolModule:
    """Test module-level attributes."""

    def test_module_has_tools_dict(self):
        """Verify bigfile_tool has TOOLS dictionary."""
        assert hasattr(bigfile_tool, "TOOLS")
        assert isinstance(bigfile_tool.TOOLS, dict)

    def test_tools_contains_read_file(self):
        """Verify TOOLS contains read_file key."""
        assert "read_file" in TOOLS

    def test_tools_only_contains_read_file(self):
        """Verify TOOLS only exposes read_file."""
        assert set(TOOLS.keys()) == {"read_file"}

    def test_read_file_is_callable(self):
        """Verify read_file tool is callable."""
        assert callable(TOOLS["read_file"])

    def test_read_file_is_file_tool_read_file(self, tmp_path):
        """Verify bigfile_tool.read_file delegates to file_tool.read_file."""
        from topsailai.tools.file_tool import read_file as file_tool_read_file

        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        bigfile_result = TOOLS["read_file"](str(test_file))
        file_tool_result = file_tool_read_file(str(test_file))
        assert bigfile_result == file_tool_result
        assert bigfile_result == "Hello, World!"


class TestBigfileToolReadFile:
    """Test read_file via bigfile_tool."""

    def test_read_file_basic(self):
        """Verify read_file reads entire file content."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Hello, World!")
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path)
            assert result == "Hello, World!"
        finally:
            os.unlink(temp_path)

    def test_read_file_with_seek(self):
        """Verify read_file reads from specified seek position."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Hello, World!")
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path, seek=7)
            assert result == "World!"
        finally:
            os.unlink(temp_path)

    def test_read_file_with_size(self):
        """Verify read_file reads specified number of bytes."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Hello, World!")
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path, size=5)
            assert result == "Hello"
        finally:
            os.unlink(temp_path)

    def test_read_file_with_seek_and_size(self):
        """Verify read_file reads from seek with size limit."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Hello, World!")
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path, seek=7, size=5)
            assert result == "World"
        finally:
            os.unlink(temp_path)

    def test_read_file_nonexistent(self):
        """Verify read_file raises FileNotFoundError for nonexistent file."""
        with pytest.raises(FileNotFoundError):
            TOOLS["read_file"]("/nonexistent/path/to/file.txt")

    def test_read_file_empty(self):
        """Verify read_file returns empty string for empty file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path)
            assert result == ""
        finally:
            os.unlink(temp_path)

    def test_read_file_whitelist_extension(self):
        """Verify read_file does not truncate whitelist extensions."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
            f.write("def test(): pass")
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path)
            assert result == "def test(): pass"
        finally:
            os.unlink(temp_path)

    def test_read_file_negative_seek(self):
        """Verify read_file reads from end with negative seek."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Hello, World!")
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path, seek=-3)
            assert result == "ld!"
        finally:
            os.unlink(temp_path)

    def test_read_file_unicode_content(self):
        """Verify read_file handles unicode content."""
        content = "你好世界 🌍"
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path)
            assert result == content
        finally:
            os.unlink(temp_path)

    def test_read_file_binary_content(self):
        """Verify read_file handles binary content safely."""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.bin') as f:
            f.write(b'\x00\x01\x02\x03\x04\x05')
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path)
            assert result is not None
            assert isinstance(result, str)
        finally:
            os.unlink(temp_path)

    def test_read_file_missing_file_path(self):
        """Verify read_file asserts on empty file_path."""
        with pytest.raises(AssertionError):
            TOOLS["read_file"]("")

    def test_read_file_compatibility_files_argument(self):
        """Verify read_file delegates to read_files when only files arg is provided."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f1:
            f1.write("File one content")
            temp_path1 = f1.name
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f2:
            f2.write("File two content")
            temp_path2 = f2.name

        try:
            result = TOOLS["read_file"](files=[temp_path1, temp_path2])
            assert isinstance(result, dict)
            assert result[temp_path1] == "File one content"
            assert result[temp_path2] == "File two content"
        finally:
            os.unlink(temp_path1)
            os.unlink(temp_path2)

    def test_read_file_compatibility_files_argument_with_nonexistent(self):
        """Verify read_file compatibility raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            TOOLS["read_file"](files=["/nonexistent/path/file1.txt"])

    def test_read_file_directory_raises(self):
        """Verify read_file raises when path is a directory."""
        temp_dir = tempfile.mkdtemp()
        try:
            with pytest.raises((IsADirectoryError, PermissionError, OSError)):
                TOOLS["read_file"](temp_dir)
        finally:
            os.rmdir(temp_dir)

    def test_read_file_large_file_truncation(self):
        """Verify read_file truncates large non-whitelist files."""
        # Default MAX_MSG_SIZE is 30KB, so use content larger than that.
        large_content = "A" * 35000
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write(large_content)
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path)
            assert isinstance(result, str)
            assert len(result) < len(large_content)
            assert "(force to truncate)" in result
        finally:
            os.unlink(temp_path)

    def test_read_file_large_whitelist_no_truncation(self):
        """Verify read_file does not truncate whitelisted files."""
        content = "B" * 3000
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
            f.write(content)
            temp_path = f.name

        try:
            result = TOOLS["read_file"](temp_path)
            assert result == content
        finally:
            os.unlink(temp_path)

    def test_tools_is_independent_from_file_tool_tools(self):
        """Verify bigfile_tool.TOOLS is not the same object as file_tool.TOOLS."""
        from topsailai.tools import file_tool
        assert bigfile_tool.TOOLS is not file_tool.TOOLS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
