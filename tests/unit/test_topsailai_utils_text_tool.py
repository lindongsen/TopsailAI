import pytest
import chardet
from src.topsailai.utils.text_tool import safe_decode


def test_safe_decode_string_input():
    """Test that string input is returned unchanged."""
    input_str = "hello world"
    result = safe_decode(input_str)
    assert result == input_str


def test_safe_decode_empty_string():
    """Test that empty string input is returned unchanged."""
    result = safe_decode("")
    assert result == ""


def test_safe_decode_none_input():
    """Test that None input returns empty string."""
    result = safe_decode(None)
    assert result == ""


def test_safe_decode_utf8_bytes():
    """Test decoding UTF-8 encoded bytes."""
    test_bytes = "hello world".encode('utf-8')
    result = safe_decode(test_bytes)
    assert result == "hello world"


def test_safe_decode_latin1_bytes():
    """Test decoding Latin-1 encoded bytes."""
    test_bytes = "café".encode('latin-1')
    result = safe_decode(test_bytes)
    assert result == "café"


def test_safe_decode_with_special_characters():
    """Test decoding bytes with special characters."""
    test_bytes = "hello café world".encode('utf-8')
    result = safe_decode(test_bytes)
    assert result == "hello café world"


def test_safe_decode_invalid_bytes_fallback():
    """Test that invalid bytes fall back to UTF-8 with replacement."""
    # Create some invalid UTF-8 bytes
    invalid_bytes = b'\xff\xfehello'
    result = safe_decode(invalid_bytes)
    # Should not raise an exception and should return a string
    assert isinstance(result, str)
    assert len(result) > 0


def test_safe_decode_empty_bytes():
    """Test decoding empty bytes."""
    result = safe_decode(b'')
    assert result == ""


def test_safe_decode_consistency():
    """Test that the function behaves consistently."""
    test_cases = [
        "hello",
        "",
        "café",
        "hello world with spaces",
        b'hello',
        b'',
    ]
    
    for case in test_cases:
        result1 = safe_decode(case)
        result2 = safe_decode(case)
        assert result1 == result2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])