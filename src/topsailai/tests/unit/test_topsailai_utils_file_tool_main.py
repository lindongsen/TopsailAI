"""
Test suite for topsailai.utils.file_tool module.
Comprehensive tests covering all file utility functions.
"""
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
    # Basic cases
    assert get_filename("/tmp/123.txt") == "123"
    assert get_filename("/path/to/file.py") == "file"
    assert get_filename("document.pdf") == "document"
    assert get_filename("archive.tar.gz") == "archive.tar"
    assert get_filename("") == ""
    assert get_filename(".hidden") == ".hidden"
    assert get_filename("no_extension") == "no_extension"
    # Edge cases
    assert get_filename("/tmp/dir/") == ""
    assert get_filename("///") == ""
    assert get_filename("file.name.test.txt") == "file.name.test"
    assert get_filename(".gitignore") == ".gitignore"
    assert get_filename(".env") == ".env"
    assert get_filename("/home/user/document.txt") == "document"
    assert get_filename("   ") == "   "
    assert get_filename("\t\n") == "\t\n"


def test_match_file():
    """Test match_file function with various filtering criteria."""
    # Basic cases
    assert not match_file("/tmp/.hidden/file.txt", True, ())
    assert not match_file(".hidden_file", True, ())
    assert match_file("/tmp/normal.txt", True, ())
    assert not match_file("/tmp/exclude_me/file.txt", False, ("exclude_me",))
    assert not match_file("exclude_this.txt", False, ("exclude_this",))
    assert match_file("/tmp/included/file.txt", False, ("exclude",))
    assert match_file("/tmp/important_doc.txt", False, (), ["important"])
    assert not match_file("/tmp/regular.txt", False, (), ["important"])
    assert not match_file("/tmp/im.txt", False, (), ["important"])
    # Edge cases
    assert match_file("/tmp/im.txt", False, (), ["im"], keyword_min_len=2)
    assert not match_file("/tmp/im.txt", False, (), ["im"], keyword_min_len=3)
    assert match_file("/tmp/any_file.txt", False, (), [])
    assert match_file("/tmp/.hidden.txt", False, ())
    assert match_file("/tmp/important.txt", False, (), ["imp", "important"])
    assert not match_file("/tmp/pycache/file.py", False, ("pycache", "__pycache__"))
    assert not match_file("/tmp/__pycache__/file.py", False, ("pycache", "__pycache__"))
    assert match_file("/tmp/normal/file.py", False, ("pycache", "__pycache__"))
    assert match_file("/tmp/ab.txt", False, (), ["ab"], keyword_min_len=2)
    assert match_file("/tmp/file-with-dash.txt", False, (), ["dash"])
    assert match_file("/tmp/file_with_underscore.txt", False, (), ["underscore"])


def test_find_files_by_name():
    """Test find_files_by_name function."""
    with tempfile.TemporaryDirectory() as tmp_dir:
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
        
        results = find_files_by_name(tmp_dir, "target.txt")
        assert len(results) == 2
        assert target_file in results
        assert sub_target in results
        assert find_files_by_name(tmp_dir, "nonexistent.txt") == []
    
    # Test case-sensitive matching
    with tempfile.TemporaryDirectory() as tmp_dir:
        file1 = os.path.join(tmp_dir, "Test.txt")
        file2 = os.path.join(tmp_dir, "test.txt")
        
        with open(file1, 'w') as f:
            f.write("content1")
        with open(file2, 'w') as f:
            f.write("content2")
        
        results = find_files_by_name(tmp_dir, "Test.txt")
        assert len(results) == 1
        assert file1 in results
        assert file2 not in results


def test_list_files():
    """Test list_files function with various filters."""
    with tempfile.TemporaryDirectory() as tmp_dir:
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
        
        results = list_files(tmp_dir, to_exclude_dot_start=False)
        assert len(results) == 3
        
        results = list_files(tmp_dir, to_exclude_dot_start=True)
        assert len(results) == 2
        assert normal_file in results
        assert sub_normal in results
        assert hidden_file not in results
        
        results = list_files(tmp_dir, included_filename_keywords=["normal"])
        assert len(results) == 2
    
    # Edge cases: excluded directories
    with tempfile.TemporaryDirectory() as tmp_dir:
        excluded_dir = os.path.join(tmp_dir, "exclude_me")
        os.makedirs(excluded_dir)
        normal_file = os.path.join(tmp_dir, "normal.txt")
        excluded_file = os.path.join(excluded_dir, "file.txt")
        
        with open(normal_file, 'w') as f:
            f.write("content")
        with open(excluded_file, 'w') as f:
            f.write("content")
        
        results = list_files(tmp_dir, excluded_starts=["exclude_me"])
        assert len(results) == 1
        assert normal_file in results
        assert excluded_file not in results
    
    # Edge cases: recursive directory listing
    with tempfile.TemporaryDirectory() as tmp_dir:
        deep_dir = os.path.join(tmp_dir, "a", "b", "c")
        os.makedirs(deep_dir)
        deep_file = os.path.join(deep_dir, "deep.txt")
        
        with open(deep_file, 'w') as f:
            f.write("deep content")
        
        results = list_files(tmp_dir, to_exclude_dot_start=False)
        assert len(results) == 1
        assert deep_file in results


def test_delete_file():
    """Test delete_file function."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write(b"content")
    
    try:
        assert os.path.exists(tmp_path)
        delete_file(tmp_path)
        assert not os.path.exists(tmp_path)
        delete_file("/tmp/this_path_does_not_exist_12345.txt")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Edge cases: empty string and None
    result = delete_file("")
    assert result is None
    result = delete_file(None)
    assert result is None

    # Edge case: read-only file
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write(b"content")
    
    try:
        os.chmod(tmp_path, 0o444)
        delete_file(tmp_path)
        assert not os.path.exists(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.chmod(tmp_path, 0o644)
            os.unlink(tmp_path)


def test_get_file_content_fuzzy():
    """Test get_file_content_fuzzy function."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write("file content")
    
    try:
        file_path, content = get_file_content_fuzzy(tmp_path)
        assert file_path == tmp_path
        assert content == "file content"
        
        file_path, content = get_file_content_fuzzy("direct content")
        assert file_path == ""
        assert content == "direct content"
        
        file_path, content = get_file_content_fuzzy("/tmp/this_file_does_not_exist_12345.txt")
        assert file_path == ""
        assert content == "/tmp/this_file_does_not_exist_12345.txt"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Edge cases: empty input and Unicode
    file_path, content = get_file_content_fuzzy("")
    assert file_path == ""
    assert content == ""
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write("Hello ‰∏ñÁïå üåç")
    
    try:
        file_path, content = get_file_content_fuzzy(tmp_path)
        assert file_path == tmp_path
        assert content == "Hello ‰∏ñÁïå üåç"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Edge case: large file content
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:
        tmp_path = tmp_file.name
        large_content = "x" * 100000
        tmp_file.write(large_content)
    
    try:
        file_path, content = get_file_content_fuzzy(tmp_path)
        assert file_path == tmp_path
        assert content == large_content
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_ctxm_file_lock():
    """Test file locking context manager."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    try:
        with ctxm_file_lock(tmp_path) as f:
            f.write("locked content")
        
        with open(tmp_path, 'r') as f:
            assert f.read() == "locked content"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Edge case: append mode
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    try:
        with ctxm_file_lock(tmp_path, mode='a') as f:
            assert f is not None
            f.write("content")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_ctxm_temp_file():
    """Test temporary file context manager."""
    test_content = "temporary content"
    
    with ctxm_temp_file(test_content) as (file_path, fd):
        assert os.path.exists(file_path)
        with open(file_path, 'r') as f:
            assert f.read() == test_content
    
    assert not os.path.exists(file_path)


class TestWriteText:
    """Test suite for write_text function."""
    
    def test_create_and_write_file(self):
        """Test creating files in various scenarios."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # New file in existing folder
            file_path = os.path.join(tmp_dir, "new_file.txt")
            write_text(file_path, "hello world")
            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == "hello world"
            
            # New file in non-existent subfolder
            subdir = os.path.join(tmp_dir, "sub", "nested")
            file_path = os.path.join(subdir, "nested_file.txt")
            write_text(file_path, "nested content")
            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == "nested content"
            
            # Empty content
            file_path = os.path.join(tmp_dir, "empty.txt")
            write_text(file_path, "")
            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == ""
    
    def test_overwrite_file(self, caplog):
        """Test overwriting existing file (warning logged)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "existing.txt")
            with open(file_path, 'w') as f:
                f.write("original content")
            
            with caplog.at_level(logging.WARNING):
                write_text(file_path, "new content")
            
            with open(file_path, 'r') as f:
                assert f.read() == "new content"
    
    def test_write_special_content(self):
        """Test writing Unicode and special characters."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Unicode content
            file_path = os.path.join(tmp_dir, "unicode.txt")
            unicode_content = "Hello ‰∏ñÁïå üåç –ü—Ä–∏–≤–µ—Ç"
            write_text(file_path, unicode_content)
            with open(file_path, 'r', encoding='utf-8') as f:
                assert f.read() == unicode_content
            
            # Special characters
            file_path = os.path.join(tmp_dir, "special.txt")
            special_content = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
            write_text(file_path, special_content)
            with open(file_path, 'r') as f:
                assert f.read() == special_content


class TestAppendData:
    """Test suite for append_data function."""
    
    def test_append_to_existing_file(self):
        """Test appending to existing file with various data types."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # String append
            file_path = os.path.join(tmp_dir, "append_test.txt")
            with open(file_path, 'w') as f:
                f.write("initial")
            
            result = append_data(file_path, " appended")
            assert result is True
            with open(file_path, 'r') as f:
                assert f.read() == "initial appended"
            
            # Bytes append
            file_path = os.path.join(tmp_dir, "bytes_test.txt")
            with open(file_path, 'wb') as f:
                f.write(b"initial")
            
            result = append_data(file_path, b" bytes")
            assert result is True
            with open(file_path, 'rb') as f:
                assert f.read() == b"initial bytes"
            
            # Non-string/non-bytes type (converted to bytes)
            file_path = os.path.join(tmp_dir, "convert_test.txt")
            with open(file_path, 'w') as f:
                f.write("initial")
            
            result = append_data(file_path, 123)
            assert result is True
            with open(file_path, 'rb') as f:
                assert f.read() == b"initial123"
            
            # Empty string
            file_path = os.path.join(tmp_dir, "empty_append.txt")
            with open(file_path, 'w') as f:
                f.write("content")
            
            result = append_data(file_path, "")
            assert result is True
            with open(file_path, 'r') as f:
                assert f.read() == "content"
    
    def test_append_to_new_file(self):
        """Test appending to non-existent file (auto-creates)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Non-existent file
            file_path = os.path.join(tmp_dir, "new_append.txt")
            result = append_data(file_path, "new content")
            assert result is True
            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == "new content"
            
            # Non-existent directory
            subdir = os.path.join(tmp_dir, "sub", "nested")
            file_path = os.path.join(subdir, "nested_append.txt")
            result = append_data(file_path, "nested content")
            assert result is True
            assert os.path.exists(file_path)
    
    def test_append_multiple_times(self):
        """Test appending multiple times to same file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "multi_append.txt")
            with open(file_path, 'w') as f:
                f.write("start")
            
            for i in range(5):
                append_data(file_path, f"_{i}")
            
            with open(file_path, 'r') as f:
                assert f.read() == "start_0_1_2_3_4"


class TestGetAllFiles:
    """Test suite for get_all_files function."""
    
    def test_valid_absolute_paths(self):
        """Test with valid absolute file paths."""
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
    
    def test_invalid_path_handling(self):
        """Test handling of invalid paths."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.txt")
            with open(file1, 'w') as f:
                f.write("content")
            
            # Not absolute path
            flag, files = get_all_files([file1, "relative/path.txt"])
            assert flag is False
            assert file1 in files
            
            # Non-existent path
            non_existent = os.path.join(tmp_dir, "non_existent.txt")
            flag, files = get_all_files([file1, non_existent])
            assert flag is False
            assert file1 in files
            assert non_existent not in files
    
    def test_empty_and_whitespace_args(self):
        """Test with empty or whitespace args."""
        # Empty list
        flag, files = get_all_files([])
        assert flag is False
        assert files == []
        
        # Empty strings (skipped)
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "file1.txt")
            with open(file1, 'w') as f:
                f.write("content")
            
            flag, files = get_all_files([file1, ""])
            assert flag is True
            assert file1 in files
        
        # All empty strings
        flag, files = get_all_files(["", "", ""])
        assert flag is False
        assert files == []
        
        # All whitespace
        flag, files = get_all_files(["   ", "\t", "\n"])
        assert flag is False
        assert files == []
    
    def test_single_file(self):
        """Test with single file (valid and invalid)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file1 = os.path.join(tmp_dir, "single.txt")
            with open(file1, 'w') as f:
                f.write("content")
            
            flag, files = get_all_files([file1])
            assert flag is True
            assert len(files) == 1
            assert file1 in files
        
        # Single invalid file
        flag, files = get_all_files(["/non/existent/path.txt"])
        assert flag is False
        assert files == []


class TestCtxmTryFileLock:
    """Test suite for ctxm_try_file_lock context manager."""
    
    def test_acquire_and_use_lock(self):
        """Test acquiring and using lock."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            # Successfully acquire and write
            with ctxm_try_file_lock(lock_file) as f:
                assert f is not None
                assert hasattr(f, 'write')
                f.write("locked content")
            
            with open(lock_file, 'r') as f:
                assert f.read() == "locked content"
            
            # Lock already held
            with ctxm_try_file_lock(lock_file) as f1:
                assert f1 is not None
                f1.write("first lock")
                
                with ctxm_try_file_lock(lock_file) as f2:
                    assert f2 is None
    
    def test_write_and_modes(self):
        """Test writing content with different modes."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            # Write mode
            with ctxm_try_file_lock(lock_file, mode='w') as f:
                assert f is not None
                f.write("test content\n")
                f.write("more content\n")
            
            with open(lock_file, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 2
            
            # Append mode
            with ctxm_try_file_lock(lock_file, mode='a') as f:
                assert f is not None
                f.write("first")
            
            with ctxm_try_file_lock(lock_file, mode='a') as f:
                assert f is not None
                f.write("second")
            
            with open(lock_file, 'r') as f:
                assert f.read() == "test content\nmore content\nfirstsecond"
    
    def test_read_and_binary_modes(self):
        """Test with read and binary modes."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "read.lock")
            
            # Read mode
            with open(lock_file, 'w') as f:
                f.write("content")
            
            with ctxm_try_file_lock(lock_file, mode='r') as f:
                assert f is not None
                content = f.read()
                assert content == "content"
            
            # Binary mode
            lock_file = os.path.join(tmp_dir, "binary.lock")
            with ctxm_try_file_lock(lock_file, mode='wb') as f:
                assert f is not None
                f.write(b"\x00\x01\x02")
            
            with open(lock_file, 'rb') as f:
                assert f.read() == b"\x00\x01\x02"


class TestCtxmWaitFlock:
    """Test suite for ctxm_wait_flock context manager."""
    
    def test_acquire_lock(self):
        """Test acquiring lock."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            with ctxm_wait_flock(lock_file, timeout=5, to_delete_lock_file=False) as f:
                assert f is not None
                f.write("immediate lock")
            
            with open(lock_file, 'r') as f:
                assert f.read() == "immediate lock"
    
    def test_timeout_and_delete(self):
        """Test timeout and delete options."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            # Timeout expires
            with ctxm_try_file_lock(lock_file) as f:
                assert f is not None
                f.write("holding lock")
                
                with ctxm_wait_flock(lock_file, timeout=0.1) as f2:
                    assert f2 is None
            
            # Delete lock file
            lock_file = os.path.join(tmp_dir, "delete.lock")
            with ctxm_wait_flock(lock_file, to_delete_lock_file=True) as f:
                assert f is not None
                f.write("content")
            
            assert not os.path.exists(lock_file)
            
            # Preserve lock file
            lock_file = os.path.join(tmp_dir, "preserve.lock")
            with ctxm_wait_flock(lock_file, to_delete_lock_file=False) as f:
                assert f is not None
                f.write("content")
            
            assert os.path.exists(lock_file)
            with open(lock_file, 'r') as f:
                assert f.read() == "content"
    
    def test_edge_cases(self):
        """Test edge cases."""
        # Empty file path
        with ctxm_wait_flock("", timeout=5) as f:
            assert f is None
        
        # Zero or negative timeout
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "test.lock")
            
            with ctxm_wait_flock(lock_file, timeout=0) as f:
                assert f is not None
                f.write("zero timeout")
            
            with ctxm_wait_flock(lock_file, timeout=-5) as f:
                assert f is not None
                f.write("negative timeout")
    
    def test_lock_file_creation_and_defaults(self):
        """Test lock file creation and default parameters."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_file = os.path.join(tmp_dir, "create.lock")
            
            assert not os.path.exists(lock_file)
            
            with ctxm_wait_flock(lock_file, to_delete_lock_file=False) as f:
                assert f is not None
                assert os.path.exists(lock_file)
            
            # Default parameters
            lock_file = os.path.join(tmp_dir, "default.lock")
            with ctxm_wait_flock(lock_file) as f:
                assert f is not None
                f.write("default test")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
