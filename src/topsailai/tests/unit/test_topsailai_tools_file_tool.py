"""
Unit tests for topsailai.tools.file_tool module.

Test coverage:
- read_file: File reading with seek/size parameters
- read_files: Multiple file reading
- write_file: File writing with positioning
- append_file: File appending
- check_files_existing: File existence checking
- exists_file: Single file existence checking
- mkdirs: Directory creation
- replace_lines_in_file: Line replacement
- insert_data_to_file: Data insertion
- list_dir: Directory listing
- list_dirs: Multiple directory listing
- is_need_truncate: Truncation check
- TOOLS dictionary

Author: mm-m25
"""

import os
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock

from topsailai.tools.file_tool import (
    read_file,
    read_files,
    write_file,
    append_file,
    check_files_existing,
    exists_file,
    mkdirs,
    replace_lines_in_file,
    insert_data_to_file,
    list_dir,
    list_dirs,
    is_need_truncate,
    TOOLS,
)


class TestReadFile:
    """Test read_file function."""

    def test_read_file_basic(self):
        """Verify read_file reads entire file content."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Hello, World!")
            temp_path = f.name
        
        try:
            result = read_file(temp_path)
            assert result == "Hello, World!"
        finally:
            os.unlink(temp_path)

    def test_read_file_with_seek(self):
        """Verify read_file reads from specified seek position."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Hello, World!")
            temp_path = f.name
        
        try:
            result = read_file(temp_path, seek=7)
            assert result == "World!"
        finally:
            os.unlink(temp_path)

    def test_read_file_with_size(self):
        """Verify read_file reads specified number of bytes."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Hello, World!")
            temp_path = f.name
        
        try:
            result = read_file(temp_path, size=5)
            assert result == "Hello"
        finally:
            os.unlink(temp_path)

    def test_read_file_with_seek_and_size(self):
        """Verify read_file reads from seek with size limit."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Hello, World!")
            temp_path = f.name
        
        try:
            result = read_file(temp_path, seek=7, size=5)
            assert result == "World"
        finally:
            os.unlink(temp_path)

    def test_read_file_nonexistent(self):
        """Verify read_file returns None for nonexistent file."""
        result = read_file("/nonexistent/path/to/file.txt")
        assert result is None

    def test_read_file_whitelist_extension(self):
        """Verify read_file does not truncate whitelist extensions."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
            f.write("def test(): pass")
            temp_path = f.name
        
        try:
            result = read_file(temp_path)
            assert result == "def test(): pass"
        finally:
            os.unlink(temp_path)

    def test_read_file_binary_content(self):
        """Verify read_file handles binary content."""
        binary_content = b'\x00\x01\x02\x03\x04\x05'
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.bin') as f:
            f.write(binary_content)
            temp_path = f.name
        
        try:
            result = read_file(temp_path)
            assert result is not None
        finally:
            os.unlink(temp_path)


class TestReadFiles:
    """Test read_files function."""

    def test_read_files_multiple(self):
        """Verify read_files reads multiple files."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f1:
            f1.write("File 1 content")
            temp_path1 = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f2:
            f2.write("File 2 content")
            temp_path2 = f2.name
        
        try:
            result = read_files([temp_path1, temp_path2])
            assert temp_path1 in result
            assert temp_path2 in result
            assert result[temp_path1] == "File 1 content"
            assert result[temp_path2] == "File 2 content"
        finally:
            os.unlink(temp_path1)
            os.unlink(temp_path2)

    def test_read_files_single(self):
        """Verify read_files works with single file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Single file content")
            temp_path = f.name
        
        try:
            result = read_files([temp_path])
            assert temp_path in result
            assert result[temp_path] == "Single file content"
        finally:
            os.unlink(temp_path)

    def test_read_files_nonexistent(self):
        """Verify read_files handles nonexistent files."""
        result = read_files(["/nonexistent/file1.txt", "/nonexistent/file2.txt"])
        assert "/nonexistent/file1.txt" in result
        assert "/nonexistent/file2.txt" in result
        assert result["/nonexistent/file1.txt"] is None
        assert result["/nonexistent/file2.txt"] is None


class TestWriteFile:
    """Test write_file function."""

    def test_write_file_basic(self):
        """Verify write_file creates new file."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_write.txt")
        
        try:
            result = write_file(temp_path, "New content")
            assert result == ""
            with open(temp_path, 'r') as f:
                assert f.read() == "New content"
        finally:
            shutil.rmtree(temp_dir)

    def test_write_file_overwrite(self):
        """Verify write_file overwrites existing file."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_overwrite.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("Initial content")
            
            result = write_file(temp_path, "New content")
            assert result == ""
            with open(temp_path, 'r') as f:
                assert f.read() == "New content"
        finally:
            shutil.rmtree(temp_dir)

    def test_write_file_insert_mode(self):
        """Verify write_file inserts content at position."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_insert.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("Hello World")
            
            result = write_file(temp_path, " Beautiful", seek=5, to_insert=True)
            assert result == ""
            with open(temp_path, 'r') as f:
                assert f.read() == "Hello Beautiful World"
        finally:
            shutil.rmtree(temp_dir)

    def test_write_file_append_mode(self):
        """Verify write_file appends content at end."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_append.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("Hello")
            
            result = write_file(temp_path, " World", seek=-1, to_insert=True)
            assert result is True
            with open(temp_path, 'r') as f:
                assert f.read() == "Hello World"
        finally:
            shutil.rmtree(temp_dir)

    def test_write_file_overwrite_from_position(self):
        """Verify write_file overwrites from specific position."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_overwrite_pos.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("Hello World")
            
            result = write_file(temp_path, "Python", seek=6, to_insert=False)
            assert result == ""
            with open(temp_path, 'r') as f:
                assert f.read() == "Hello Python"
        finally:
            shutil.rmtree(temp_dir)


class TestAppendFile:
    """Test append_file function."""

    def test_append_file_basic(self):
        """Verify append_file appends content to file."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_append.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("Line 1\n")
            
            result = append_file(temp_path, "Line 2\n")
            assert result is True
            with open(temp_path, 'r') as f:
                content = f.read()
                assert content == "Line 1\nLine 2\n"
        finally:
            shutil.rmtree(temp_dir)

    def test_append_file_creates_new(self):
        """Verify append_file creates file if not exists."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "new_file.txt")
        
        try:
            result = append_file(temp_path, "New content")
            assert result is True
            with open(temp_path, 'r') as f:
                assert f.read() == "New content"
        finally:
            shutil.rmtree(temp_dir)


class TestExistsFile:
    """Test exists_file function."""

    def test_exists_file_returns_true(self):
        """Verify exists_file returns True for existing file."""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            temp_path = f.name
        
        try:
            result = exists_file(temp_path)
            assert result is True
        finally:
            os.unlink(temp_path)

    def test_exists_file_returns_false(self):
        """Verify exists_file returns False for nonexistent file."""
        result = exists_file("/nonexistent/path/to/file.txt")
        assert result is False

    def test_exists_file_directory(self):
        """Verify exists_file returns True for existing directory."""
        temp_dir = tempfile.mkdtemp()
        try:
            result = exists_file(temp_dir)
            assert result is True
        finally:
            shutil.rmtree(temp_dir)


class TestCheckFilesExisting:
    """Test check_files_existing function."""

    def test_check_files_existing_all_exist(self):
        """Verify check_files_existing returns True for all existing files."""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f1:
            temp_path1 = f1.name
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f2:
            temp_path2 = f2.name
        
        try:
            result = check_files_existing(file1=temp_path1, file2=temp_path2)
            assert result["file1"] is True
            assert result["file2"] is True
        finally:
            os.unlink(temp_path1)
            os.unlink(temp_path2)

    def test_check_files_existing_none_exist(self):
        """Verify check_files_existing returns False for nonexistent files."""
        result = check_files_existing(
            file1="/nonexistent/path1.txt",
            file2="/nonexistent/path2.txt"
        )
        assert result["file1"] is False
        assert result["file2"] is False

    def test_check_files_existing_mixed(self):
        """Verify check_files_existing handles mixed existence."""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            temp_path = f.name
        
        try:
            result = check_files_existing(
                existing=temp_path,
                nonexistent="/nonexistent/path.txt"
            )
            assert result["existing"] is True
            assert result["nonexistent"] is False
        finally:
            os.unlink(temp_path)


class TestMkdirs:
    """Test mkdirs function."""

    def test_mkdirs_creates_single_directory(self):
        """Verify mkdirs creates a single directory."""
        temp_dir = tempfile.mkdtemp()
        new_dir = os.path.join(temp_dir, "new_subdir")
        
        try:
            result = mkdirs([new_dir])
            assert result is True
            assert os.path.isdir(new_dir)
        finally:
            shutil.rmtree(temp_dir)

    def test_mkdirs_creates_multiple_directories(self):
        """Verify mkdirs creates multiple directories."""
        temp_dir = tempfile.mkdtemp()
        dir1 = os.path.join(temp_dir, "dir1")
        dir2 = os.path.join(temp_dir, "dir2")
        
        try:
            result = mkdirs([dir1, dir2])
            assert result is True
            assert os.path.isdir(dir1)
            assert os.path.isdir(dir2)
        finally:
            shutil.rmtree(temp_dir)

    def test_mkdirs_existing_directory(self):
        """Verify mkdirs handles existing directories."""
        temp_dir = tempfile.mkdtemp()
        
        try:
            result = mkdirs([temp_dir])
            assert result is True
        finally:
            shutil.rmtree(temp_dir)

    def test_mkdirs_nested_directories(self):
        """Verify mkdirs creates nested directories."""
        temp_dir = tempfile.mkdtemp()
        nested_dir = os.path.join(temp_dir, "level1", "level2", "level3")
        
        try:
            result = mkdirs([nested_dir])
            assert result is True
            assert os.path.isdir(nested_dir)
        finally:
            shutil.rmtree(temp_dir)

    def test_mkdirs_requires_absolute_path(self):
        """Verify mkdirs requires absolute paths."""
        with pytest.raises(AssertionError):
            mkdirs(["relative/path"])


class TestReplaceLinesInFile:
    """Test replace_lines_in_file function."""

    def test_replace_lines_in_file_single_line(self):
        """Verify replace_lines_in_file replaces a single line."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_replace.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("AAA\nBBB\nCCC\n")
            
            result = replace_lines_in_file(temp_path, [(2, "XXX")])
            assert "XXX" in result
            with open(temp_path, 'r') as f:
                content = f.read()
                assert "XXX" in content
                lines = content.split('\n')
                assert lines[1] == "XXX"
        finally:
            shutil.rmtree(temp_dir)

    def test_replace_lines_in_file_multiple_lines(self):
        """Verify replace_lines_in_file replaces multiple lines."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_replace_multi.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("AAA\nBBB\nCCC\nDDD\n")
            
            result = replace_lines_in_file(temp_path, [(1, "XXX"), (3, "YYY")])
            assert "XXX" in result
            assert "YYY" in result
        finally:
            shutil.rmtree(temp_dir)

    def test_replace_lines_in_file_delete_line(self):
        """Verify replace_lines_in_file can delete a line."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_delete.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("AAA\nBBB\nCCC\n")
            
            result = replace_lines_in_file(temp_path, [(2, "")])
            lines = result.split('\n')
            assert "BBB" not in result
        finally:
            shutil.rmtree(temp_dir)

    def test_replace_lines_in_file_nonexistent(self):
        """Verify replace_lines_in_file returns error for nonexistent file."""
        result = replace_lines_in_file("/nonexistent/file.txt", [(1, "content")])
        assert isinstance(result, str)
        assert len(result) > 0


class TestInsertDataToFile:
    """Test insert_data_to_file function."""

    def test_insert_data_after_line(self):
        """Verify insert_data_to_file inserts after specified line."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_insert.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("AAA\nBBB\nCCC\n")
            
            result = insert_data_to_file(temp_path, "XXX", 1, "after")
            assert "XXX" in result
            lines = result.split('\n')
            assert lines[1] == "XXX"
        finally:
            shutil.rmtree(temp_dir)

    def test_insert_data_before_line(self):
        """Verify insert_data_to_file inserts before specified line."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_insert_before.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("AAA\nBBB\nCCC\n")
            
            result = insert_data_to_file(temp_path, "XXX", 2, "before")
            assert "XXX" in result
            lines = result.split('\n')
            assert lines[1] == "XXX"
        finally:
            shutil.rmtree(temp_dir)

    def test_insert_data_at_beginning(self):
        """Verify insert_data_to_file inserts at beginning."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_insert_begin.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("AAA\nBBB\n")
            
            result = insert_data_to_file(temp_path, "XXX", 1, "before")
            assert "XXX" in result
            lines = result.split('\n')
            assert lines[0] == "XXX"
        finally:
            shutil.rmtree(temp_dir)

    def test_insert_data_invalid_position(self):
        """Verify insert_data_to_file handles invalid position."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_insert_invalid.txt")
        
        try:
            with open(temp_path, 'w') as f:
                f.write("AAA\n")
            
            result = insert_data_to_file(temp_path, "XXX", 100, "after")
            assert "XXX" in result
        finally:
            shutil.rmtree(temp_dir)


class TestListDir:
    """Test list_dir function."""

    def test_list_dir_empty_directory(self):
        """Verify list_dir returns empty list for empty directory."""
        temp_dir = tempfile.mkdtemp()
        
        try:
            result = list_dir(temp_dir)
            assert result == []
        finally:
            shutil.rmtree(temp_dir)

    def test_list_dir_with_files(self):
        """Verify list_dir returns list of files."""
        temp_dir = tempfile.mkdtemp()
        
        try:
            open(os.path.join(temp_dir, "file1.txt"), 'w').close()
            open(os.path.join(temp_dir, "file2.txt"), 'w').close()
            
            result = list_dir(temp_dir)
            assert "file1.txt" in result
            assert "file2.txt" in result
            assert len(result) == 2
        finally:
            shutil.rmtree(temp_dir)


class TestListDirs:
    """Test list_dirs function."""

    def test_list_dirs_multiple_directories(self):
        """Verify list_dirs lists multiple directories."""
        temp_dir1 = tempfile.mkdtemp()
        temp_dir2 = tempfile.mkdtemp()
        
        try:
            open(os.path.join(temp_dir1, "file1.txt"), 'w').close()
            open(os.path.join(temp_dir2, "file2.txt"), 'w').close()
            
            result = list_dirs([temp_dir1, temp_dir2])
            assert temp_dir1 in result
            assert temp_dir2 in result
            assert "file1.txt" in result[temp_dir1]
            assert "file2.txt" in result[temp_dir2]
        finally:
            shutil.rmtree(temp_dir1)
            shutil.rmtree(temp_dir2)


class TestIsNeedTruncate:
    """Test is_need_truncate function."""

    def test_is_need_truncate_whitelisted_extension(self):
        """Verify is_need_truncate returns False for whitelisted extensions."""
        assert is_need_truncate("py") is False
        assert is_need_truncate("md") is False
        assert is_need_truncate("json") is False

    def test_is_need_truncate_non_whitelisted_extension(self):
        """Verify is_need_truncate returns True for non-whitelisted extensions."""
        assert is_need_truncate("txt") is True
        assert is_need_truncate("log") is True
        assert is_need_truncate("csv") is True

    def test_is_need_truncate_case_insensitive(self):
        """Verify is_need_truncate is case insensitive."""
        assert is_need_truncate("PY") is False
        assert is_need_truncate("MD") is False
        assert is_need_truncate("TXT") is True


class TestToolsDictionary:
    """Test TOOLS dictionary structure."""

    def test_tools_is_dict(self):
        """Verify TOOLS is a dictionary."""
        assert isinstance(TOOLS, dict)

    def test_tools_contains_expected_keys(self):
        """Verify TOOLS contains expected function keys."""
        expected_keys = {
            "write_file", "read_file", "append_file", "check_files_existing",
            "mkdirs", "replace_lines_in_file", "insert_data_to_file",
            "list_dirs", "read_files"
        }
        for key in expected_keys:
            assert key in TOOLS, f"Missing key: {key}"

    def test_tools_all_callable(self):
        """Verify all TOOLS values are callable."""
        for key, value in TOOLS.items():
            assert callable(value), f"Non-callable value for key: {key}"

    def test_tools_write_file_is_same_function(self):
        """Verify TOOLS write_file is the actual function."""
        assert TOOLS["write_file"] is write_file

    def test_tools_read_file_is_same_function(self):
        """Verify TOOLS read_file is the actual function."""
        assert TOOLS["read_file"] is read_file


class TestIntegration:
    """Integration tests for file_tool module."""

    def test_write_then_read_file(self):
        """Verify write and read workflow."""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "integration_test.txt")
        
        try:
            write_result = write_file(temp_path, "Integration test content")
            assert write_result == ""
            
            read_result = read_file(temp_path)
            assert read_result == "Integration test content"
        finally:
            shutil.rmtree(temp_dir)

    def test_create_directory_and_list(self):
        """Verify directory creation and listing workflow."""
        temp_dir = tempfile.mkdtemp()
        new_dir = os.path.join(temp_dir, "new_dir")
        
        try:
            mkdirs([new_dir])
            
            result = list_dir(temp_dir)
            assert "new_dir" in result
        finally:
            shutil.rmtree(temp_dir)

    def test_module_import(self):
        """Verify module can be imported successfully."""
        from topsailai.tools import file_tool
        assert file_tool is not None

    def test_functions_exported(self):
        """Verify key functions are exported from module."""
        from topsailai.tools import file_tool
        assert hasattr(file_tool, 'read_file')
        assert hasattr(file_tool, 'write_file')
        assert hasattr(file_tool, 'TOOLS')
