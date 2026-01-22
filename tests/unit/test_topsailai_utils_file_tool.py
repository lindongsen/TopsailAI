import os
import tempfile
import pytest
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
    ctxm_temp_file
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


def test_delete_file():
    """Test delete_file function."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write(b"content")
    
    # File should exist
    assert os.path.exists(tmp_path)
    
    # Delete the file
    delete_file(tmp_path)
    
    # File should no longer exist
    assert not os.path.exists(tmp_path)
    
    # Test deleting non-existent file (should not raise error)
    delete_file("/nonexistent/path")
def test_get_file_content_fuzzy():
    """Test get_file_content_fuzzy function."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write("file content")
    
    try:
        # Test with file path    
        # Test with file path
        file_path, content = get_file_content_fuzzy(tmp_path)
        assert file_path == tmp_path
        assert content == "file content"        

        # Test with direct content        
        file_path, content = get_file_content_fuzzy("direct content")
        assert file_path == ""
        assert content == "direct content"        

        # Test with non-existent file path        
        file_path, content = get_file_content_fuzzy("/nonexistent/path")
        assert file_path == ""
        assert content == "/nonexistent/path"        
    finally:
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])