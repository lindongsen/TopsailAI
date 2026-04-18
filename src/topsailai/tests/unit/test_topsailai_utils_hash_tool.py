import pytest
from topsailai.utils.hash_tool import md5sum


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


def test_md5sum_large_content():
    """Test md5sum with large content (1MB)"""
    large_content = "A" * (1024 * 1024)  # 1MB of 'A' characters
    result = md5sum(large_content)
    # MD5 hash of 1MB of 'A' is deterministic
    expected = "e6065c4aa2ab1603008fc18410f579d4"
    assert result == expected


def test_md5sum_consistency():
    """Test md5sum produces consistent results for same input"""
    test_input = "consistent_test_string_12345"
    result1 = md5sum(test_input)
    result2 = md5sum(test_input)
    result3 = md5sum(test_input)
    assert result1 == result2 == result3
    assert result1 == "42d3e9f2830f65c7928a9b6cb34bc497"


def test_md5sum_return_type():
    """Test md5sum returns a string type"""
    result = md5sum("test")
    assert isinstance(result, str)


def test_md5sum_invalid_type_int():
    """Test md5sum raises TypeError for integer input"""
    with pytest.raises(TypeError):
        md5sum(12345)


def test_md5sum_invalid_type_list():
    """Test md5sum raises TypeError for list input"""
    with pytest.raises(TypeError):
        md5sum([1, 2, 3])


def test_md5sum_invalid_type_dict():
    """Test md5sum raises TypeError for dictionary input"""
    with pytest.raises(TypeError):
        md5sum({"key": "value"})


def test_md5sum_invalid_type_none():
    """Test md5sum raises TypeError for None input"""
    with pytest.raises(TypeError):
        md5sum(None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
