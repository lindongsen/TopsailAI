import os
import tempfile
import pytest
import logging
from pathlib import Path
from unittest.mock import patch, mock_open

from topsailai.utils.file_tool import (
    get_filename,
    match_file,
    find_files_by_name,
    list_files,
    delete_file,
    get_file_content_fuzzy,
    ctxm_file_lock,
    ctxm_temp_file,
    write_text,
    append_data,
    get_all_files,
    ctxm_try_file_lock,
    ctxm_wait_flock
)


def test_get_filename():
    """Test get_filename function with various inputs."""
    # Test with full path
    assert get_filename("/tmp/123.txt") == "123"
    assert get_filename("/path/to/file.py") == "file"
    
    # Test with filename only
    assert get_filename("document.pdf") == "document"
    
    # Test with multiple extensions
    assert get_filename("archive.tar.gz") == "archive.tar"
    
    # Test edge cases
    assert get_filename("") == ""
    assert get_filename(".hidden") == ".hidden"
    assert get_filename("no_extension") == "no_extension"


def test_get_filename_edge_cases():
    """Test get_filename function with additional edge cases."""
    # Test path with trailing slash
    assert get_filename("/tmp/dir/") == ""
    
    # Test path with only slashes
    assert get_filename("///") == ""


def test_match_file():
    """Test match_file function with various filtering criteria."""
    # Test dot-start exclusion
    assert not match_file("/tmp/.hidden/file.txt", True, ())
    assert not match_file(".hidden_file", True, ())
    assert match_file("/tmp/normal.txt", True, ())
    
    # Test excluded_starts
    assert not match_file("/tmp/exclude_me/file.txt", False, ("exclude_me",))
    assert not match_file("exclude_this.txt", False, ("exclude_this",))
    assert match_file("/tmp/included/file.txt", False, ("exclude",))
    
    # Test keyword inclusion
    assert match_file("/tmp/important_doc.txt", False, (), ["important"])
    assert not match_file("/tmp/regular.txt", False, (), ["important"])
    assert not match_file("/tmp/im.txt", False, (), ["important"])  # Too short


def test_match_file_edge_cases():
    """Test match_file function with additional edge cases."""
    # Test with custom keyword_min_len
    assert match_file("/tmp/im.txt", False, (), ["im"], keyword_min_len=2)
    assert not match_file("/tmp/im.txt", False, (), ["im"], keyword_min_len=3)
    
    # Test empty included_filename_keywords list (should behave as None)
    assert match_file("/tmp/any_file.txt", False, (), [])
    
    # Test file starting with "." but to_exclude_dot_start=False
    assert match_file("/tmp/.hidden.txt", False, ())
    
    # Test multiple keywords where first is too short but second matches
    assert match_file("/tmp/important.txt", False, (), ["imp", "important"])


def test_find_files_by_name():
    """Test find_files_by_name function."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create test structure
        sub_dir = os.path.join(tmp_dir, "subdir")
        os.makedirs(sub_dir)
        
        target_file = os.path.join(tmp_dir, "target.txt")
        sub_target = os.path.join(sub_dir, "target.txt")
        other_file = os.path.join(tmp_dir, "other.txt")
        
        with open(target_file, 'w') as f:
            f.write("content")
        with open(sub_target, 'w') as f:
            f.write("content")
        with open(other_file, 'w') as f:
            f.write("content")
        
        # Test finding files
        results = find_files_by_name(tmp_dir, "target.txt")
        assert len(results) == 2
        assert target_file in results
        assert sub_target in results
        
        # Test non-existent file
        assert find_files_by_name(tmp_dir, "nonexistent.txt") == []


def test_list_files():
    """Test list_files function with various filters."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create test structure
        sub_dir = os.path.join(tmp_dir, "subdir")
        os.makedirs(sub_dir)
        
        normal_file = os.path.join(tmp_dir, "normal.txt")
        hidden_file = os.path.join(tmp_dir, ".hidden.txt")
        sub_normal = os.path.join(sub_dir, "normal.txt")
        
        with open(normal_file, 'w') as f:
            f.write("content")
        with open(hidden_file, 'w') as f:
            f.write("content")
        with open(sub_normal, 'w') as f:
            f.write("content")
        
        # Test without filters
        results = list_files(tmp_dir, to_exclude_dot_start=False)
        assert len(results) == 3
        
        # Test with dot-start exclusion
        results = list_files(tmp_dir, to_exclude_dot_start=True)
        assert len(results) == 2
        assert normal_file in results
        assert sub_normal in results
        assert hidden_file not in results
        
        # Test with keyword filter
        results = list_files(tmp_dir, included_filename_keywords=["normal"])
        assert len(results) == 2
        assert normal_file in results
        assert sub_normal in results


def test_list_files_edge_cases():
    """Test list_files function with additional edge cases."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create test structure with excluded_starts
        excluded_dir = os.path.join(tmp_dir, "exclude_me")
        os.makedirs(excluded_dir)
        
        normal_file = os.path.join(tmp_dir, "normal.txt")
        excluded_file = os.path.join(excluded_dir, "file.txt")
        
        with open(normal_file, 'w') as f:
            f.write("content")
        with open(excluded_file, 'w') as f:
            f.write("content")
        
        # Test with excluded_starts filter
        results = list_files(tmp_dir, excluded_starts=["exclude_me"])
        assert len(results) == 1
        assert normal_file in results
        assert excluded_file not in results
        
        # Test with combined excluded_starts + included_filename_keywords
        results = list_files(
            tmp_dir,
            excluded_starts=["exclude"],
            included_filename_keywords=["normal"]
        )
        assert len(results) == 1
        assert normal_file in results


def test_delete_file():
    """Test delete_file function."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write(b"content")
    
    try:
        # File should exist
        assert os.path.exists(tmp_path)
        
        # Delete the file
        delete_file(tmp_path)
        
        # File should no longer exist
        assert not os.path.exists(tmp_path)
        
        # Test deleting non-existent file (should not raise error)
        delete_file("/tmp/this_path_does_not_exist_12345.txt")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_delete_file_edge_cases():
    """Test delete_file function with additional edge cases."""
    # Test empty string input (should return None without error)
    result = delete_file("")
    assert result is None
    
    # Test None input (should not raise AttributeError)
    result = delete_file(None)
    assert result is None


def test_get_file_content_fuzzy():
    """Test get_file_content_fuzzy function."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write("file content")
    
    try:
        # Test with file path
        file_path, content = get_file_content_fuzzy(tmp_path)
        assert file_path == tmp_path
        assert content == "file content"
        
        # Test with direct content
        file_path, content = get_file_content_fuzzy("direct content")
        assert file_path == ""
        assert content == "direct content"
        
        # Test with non-existent file path
        file_path, content = get_file_content_fuzzy("/tmp/this_file_does_not_exist_12345.txt")
        assert file_path == ""
        assert content == "/tmp/this_file_does_not_exist_12345.txt"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_get_file_content_fuzzy_edge_cases():
    """Test get_file_content_fuzzy function with additional edge cases."""
    # Test empty string input
    file_path, content = get_file_content_fuzzy("")
    assert file_path == ""
    assert content == ""
    
    # Test file with Unicode content
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write("Hello 世界 🌍")
    
    try:
        file_path, content = get_file_content_fuzzy(tmp_path)
        assert file_path == tmp_path
        assert content == "Hello 世界 🌍"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_ctxm_file_lock():
    """Test file locking context manager."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    try:
        # Test that we can write with lock
        with ctxm_file_lock(tmp_path) as f:
            f.write("locked content")
        
        # Verify content was written
        with open(tmp_path, 'r') as f:
            assert f.read() == "locked content"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_ctxm_temp_file():
    """Test temporary file context manager."""
    test_content = "temporary content"
    
    with ctxm_temp_file(test_content) as (file_path, fd):
        # File should exist and contain content
        assert os.path.exists(file_path)
        with open(file_path, 'r') as f:
            assert f.read() == test_content
    
    # File should be deleted after context
    assert not os.path.exists(file_path)


# =============================================================================
# New Tests for Previously Untested Functions
# =============================================================================

class TestWriteText:
    """Test suite for write_text function."""
    
    def test_create_new_file_in_existing_folder(self):
        """Test creating a new file in an existing folder."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "new_file.txt")
            
            write_text(file_path, "hello world")
            
            # write_text doesn't return a value, just writes to file
            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == "hello world"
    
    def test_create_file_in_non_existent_subfolder(self):
        """Test creating a file in a non-existent subfolder (auto-makedirs)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            subdir = os.path.join(tmp_dir, "sub", "nested")
            file_path = os.path.join(subdir, "nested_file.txt")
            
            write_text(file_path, "nested content")
            
            # write_text doesn't return a value, just writes to file
            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == "nested content"
    
    def test_overwrite_existing_file(self, caplog):
        """Test overwriting an existing file (warning logged)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "existing.txt")
            
            # Create existing file
            with open(file_path, 'w') as f:
                f.write("original content")
            
            # Overwrite with warning
            with caplog.at_level(logging.WARNING):
                write_text(file_path, "new content")
            
            # write_text doesn't return a value, just writes to file
            with open(file_path, 'r') as f:
                assert f.read() == "new content"
            # Check that warning was logged
            assert any("overwrite" in record.message.lower() for record in caplog.records)
    
    def test_write_empty_content(self):
        """Test writing empty content to a file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "empty.txt")
            
            write_text(file_path, "")
            
            # write_text doesn't return a value, just writes to file
            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == ""
    
    def test_write_unicode_content(self):
        """Test writing Unicode content to a file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "unicode.txt")
            unicode_content = "Hello 世界 🌍 Привет"
            
            write_text(file_path, unicode_content)
            
            # write_text doesn't return a value, just writes to file
            with open(file_path, 'r', encoding='utf-8') as f:
                assert f.read() == unicode_content
    
    def test_write_to_path_where_parent_is_file(self):
        """Test writing to a path where parent is a file (error scenario)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a file that will be treated as a directory
            file_as_dir = os.path.join(tmp_dir, "file_as_dir")
            with open(file_as_dir, 'w') as f:
                f.write("content")
            
            # Try to write to a file inside the "file_as_dir"
            file_path = os.path.join(file_as_dir, "nested.txt")
            
            # This should raise an exception
            with pytest.raises(OSError):
                write_text(file_path, "should fail")
            
            assert not os.path.exists(file_path)


class TestAppendData:
    """Test suite for append_data function."""
    
    def test_append_string_to_existing_file(self):
        """Test appending string to an existing file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "append_test.txt")
            
            # Create initial file
            with open(file_path, 'w') as f:
                f.write("initial")
            
            result = append_data(file_path, " appended")
            
            assert result is True
            with open(file_path, 'r') as f:
                assert f.read() == "initial appended"
    
    def test_append_bytes_to_existing_file(self):
        """Test appending bytes to an existing file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "bytes_test.txt")
            
            # Create initial file
            with open(file_path, 'wb') as f:
                f.write(b"initial")
            
            result = append_data(file_path, b" bytes")
            
            assert result is True
            with open(file_path, 'rb') as f:
                assert f.read() == b"initial bytes"
    
    def test_append_to_non_existent_file(self):
        """Test appending to a non-existent file (auto-creates)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "new_append.txt")
            
            result = append_data(file_path, "new content")
            
            assert result is True
            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == "new content"
    
    def test_append_to_file_in_non_existent_directory(self):
        """Test appending to a file in a non-existent directory (auto-makedirs)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            subdir = os.path.join(tmp_dir, "sub", "nested")
            file_path = os.path.join(subdir, "nested_append.txt")
            
            result = append_data(file_path, "nested content")
            
            assert result is True
            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == "nested content"
    
    def test_append_non_string_non_bytes_type(self):
        """Test appending non-string/non-bytes type (converted to bytes)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "convert_test.txt")
            
            # Create initial file
            with open(file_path, 'w') as f:
                f.write("initial")
            
            # Append an integer (should be converted to bytes)
            result = append_data(file_path, 123)
            
            assert result is True
            with open(file_path, 'rb') as f:
                assert f.read() == b"initial123"
    
    def test_append_empty_string(self):
        """Test appending empty string to a file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "empty_append.txt")
            
            # Create initial file
            with open(file_path, 'w') as f:
                f.write("content")
            
            result = append_data(file_path, "")
            
            assert result is True
            with open(file_path, 'r') as f:
                assert f.read() == "content"
    
    def test_append_empty_bytes(self):
        """Test appending empty bytes to a file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "empty_bytes_append.txt")
            
            # Create initial file
            with open(file_path, 'wb') as f:
                f.write(b"content")
            
            result = append_data(file_path, b"")
            
            assert result is True
            with open(file_path, 'rb') as f:
                assert f.read() == b"content"


class TestGetAllFiles:
    """Test suite for get_all_files function."""
    
    def test_all_valid_absolute_paths(self):
        """Test when all args are valid absolute file paths."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.txt")
            file2 = os.path.join(tmp_dir, "file2.txt")
            
            with open(file1, 'w') as f:
                f.write("content1")
            with open(file2, 'w') as f:
                f.write("content2")
            
            flag, files = get_all_files([file1, file2])
            
            assert flag is True
            assert len(files) == 2
            assert file1 in files
            assert file2 in files
    
    def test_some_args_not_absolute_paths(self):
        """Test when some args are not absolute paths."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.txt")
            
            with open(file1, 'w') as f:
                f.write("content")
            
            flag, files = get_all_files([file1, "relative/path.txt"])
            
            assert flag is False
            assert file1 in files
            assert "relative/path.txt" not in files
    
    def test_some_args_point_to_non_existent_paths(self):
        """Test when some args point to non-existent paths."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.txt")
            non_existent = os.path.join(tmp_dir, "non_existent.txt")
            
            with open(file1, 'w') as f:
                f.write("content")
            
            flag, files = get_all_files([file1, non_existent])
            
            assert flag is False
            assert file1 in files
            assert non_existent not in files
    
    def test_empty_args_list(self):
        """Test with empty args list."""
        flag, files = get_all_files([])
        
        assert flag is False
        assert files == []
    
    def test_args_with_empty_strings(self):
        """Test args with empty strings (skipped)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.txt")
            
            with open(file1, 'w') as f:
                f.write("content")
            
            # Empty strings are skipped, so only file1 remains
            # Since all remaining args are valid files, flag is True
            flag, files = get_all_files([file1, ""])
            
            assert flag is True
            assert file1 in files
            assert "" not in files
    
    def test_args_with_whitespace_only_strings(self):
        """Test args with whitespace-only strings (trimmed, then skipped if empty)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.txt")
            
            with open(file1, 'w') as f:
                f.write("content")
            
            # Whitespace-only strings are trimmed and skipped
            # Since all remaining args are valid files, flag is True
            flag, files = get_all_files([file1, "   ", "\t"])
            
            assert flag is True
            assert file1 in files
            assert "   " not in files
            assert "\t" not in files
    
    def test_mix_of_valid_and_invalid_paths(self):
        """Test mix of valid and invalid paths."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.txt")
            file2 = os.path.join(tmp_dir, "file2.txt")
            
            with open(file1, 'w') as f:
                f.write("content1")
            with open(file2, 'w') as f:
                f.write("content2")
            
            flag, files = get_all_files([
                file1,
                "relative/path.txt",
                file2,
                "/non/existent/path.txt",
                ""
            ])
            
            assert flag is False
            assert file1 in files
            assert file2 in files
            assert "relative/path.txt" not in files
            assert "/non/existent/path.txt" not in files
            assert "" not in files


class TestCtxmTryFileLock:
    """Test suite for ctxm_try_file_lock context manager."""
    
    def test_successfully_acquire_lock(self):
        """Test successfully acquiring lock (yields file object)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            with ctxm_try_file_lock(lock_file) as f:
                assert f is not None
                assert hasattr(f, 'write')
                f.write("locked content")
            
            # Verify content was written
            with open(lock_file, 'r') as f:
                assert f.read() == "locked content"
    
    def test_lock_already_held_by_another_process(self):
        """Test lock already held by another process (yields None)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            # Acquire lock in first context
            with ctxm_try_file_lock(lock_file) as f1:
                assert f1 is not None
                f1.write("first lock")
                
                # Try to acquire same lock in nested context
                with ctxm_try_file_lock(lock_file) as f2:
                    # Should yield None because lock is already held
                    assert f2 is None
    
    def test_write_content_through_locked_file(self):
        """Test writing content through locked file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            with ctxm_try_file_lock(lock_file, mode='w') as f:
                assert f is not None
                f.write("test content\n")
                f.write("more content\n")
            
            # Verify all content was written
            with open(lock_file, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 2
                assert lines[0] == "test content\n"
                assert lines[1] == "more content\n"
    
    def test_different_open_modes(self):
        """Test with different open modes."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            # Test with 'a' mode (append)
            with ctxm_try_file_lock(lock_file, mode='a') as f:
                assert f is not None
                f.write("first")
            
            with ctxm_try_file_lock(lock_file, mode='a') as f:
                assert f is not None
                f.write("second")
            
            with open(lock_file, 'r') as f:
                assert f.read() == "firstsecond"


class TestCtxmWaitFlock:
    """Test suite for ctxm_wait_flock context manager."""
    
    def test_acquire_lock_immediately(self):
        """Test acquiring lock immediately (yields file)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            with ctxm_wait_flock(lock_file, timeout=5, to_delete_lock_file=False) as f:
                assert f is not None
                f.write("immediate lock")
            
            with open(lock_file, 'r') as f:
                assert f.read() == "immediate lock"
    
    def test_timeout_expires(self):
        """Test timeout expires (yields None)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            # Acquire lock and hold it
            with ctxm_try_file_lock(lock_file) as f:
                assert f is not None
                f.write("holding lock")
                
                # Try to acquire with very short timeout
                with ctxm_wait_flock(lock_file, timeout=0.1) as f2:
                    # Should yield None after timeout
                    assert f2 is None
    
    def test_to_delete_lock_file_true(self):
        """Test to_delete_lock_file=True (file deleted after release)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            with ctxm_wait_flock(lock_file, to_delete_lock_file=True) as f:
                assert f is not None
                f.write("content")
            
            # File should be deleted after context
            assert not os.path.exists(lock_file)
    
    def test_to_delete_lock_file_false(self):
        """Test to_delete_lock_file=False (file preserved after release)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            with ctxm_wait_flock(lock_file, to_delete_lock_file=False) as f:
                assert f is not None
                f.write("content")
            
            # File should still exist after context
            assert os.path.exists(lock_file)
            with open(lock_file, 'r') as f:
                assert f.read() == "content"
    
    def test_empty_file_path(self):
        """Test empty file_path (yields None immediately)."""
        with ctxm_wait_flock("", timeout=5) as f:
            assert f is None
    
    def test_timeout_zero_or_negative(self):
        """Test timeout=0 or negative (clamped to 1)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            # Test with timeout=0 (should be clamped to 1)
            with ctxm_wait_flock(lock_file, timeout=0) as f:
                assert f is not None
                f.write("zero timeout")
            
            # Test with negative timeout (should be clamped to 1)
            with ctxm_wait_flock(lock_file, timeout=-5) as f:
                assert f is not None
                f.write("negative timeout")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
