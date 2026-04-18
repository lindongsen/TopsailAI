import pytest
from src.topsailai.utils.hash_tool import md5sum


def test_md5sum_string():
    """Test md5sum with string input"""
    result = md5sum("hello")
    expected = "5d41402abc4b2a76b9719d911017c592"
    assert result == expected


def test_md5sum_bytes():
    """Test md5sum with bytes input"""
    result = md5sum(b"hello")
    expected = "5d41402abc4b2a76b9719d911017c592"
    assert result == expected


def test_md5sum_empty_string():
    """Test md5sum with empty string"""
    result = md5sum("")
    expected = "d41d8cd98f00b204e9800998ecf8427e"
    assert result == expected


def test_md5sum_empty_bytes():
    """Test md5sum with empty bytes"""
    result = md5sum(b"")
    expected = "d41d8cd98f00b204e9800998ecf8427e"
    assert result == expected


def test_md5sum_unicode():
    """Test md5sum with unicode characters"""
    result = md5sum("你好世界")
    expected = "65396ee4aad0b4f17aacd1c6112ee364"
    assert result == expected


def test_md5sum_special_characters():
    """Test md5sum with special characters"""
    result = md5sum("!@#$%^&*()")
    expected = "05b28d17a7b6e7024b6e5d8cc43a8bf7"
    assert result == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])