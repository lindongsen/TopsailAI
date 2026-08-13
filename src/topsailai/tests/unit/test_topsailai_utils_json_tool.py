import pytest
import simplejson
from topsailai.utils.json_tool import (
    convert_code_block_to_json_str,
    fix_llm_mistakes_on_json,
    to_json_str,
    json_dump,
    json_load,
    safe_json_dump,
    safe_json_load
)


def test_convert_code_block_to_json_str():
    """Test convert_code_block_to_json_str function with various markdown code block formats."""
    # Test single JSON code block
    assert convert_code_block_to_json_str("```json\n{\"key\": \"value\"}\n```") == '[\n{\"key\": \"value\"}\n]'
    
    # Test multiple JSON code blocks
    assert convert_code_block_to_json_str("```json\n{\"a\": 1}\n```\n```json\n{\"b\": 2}\n```") == '[\n{\"a\": 1}\n,\n\n{\"b\": 2}\n]'
    
    # Test code block without json specifier
    assert convert_code_block_to_json_str("```\n{\"key\": \"value\"}\n```") == '\n{\"key\": \"value\"}\n'
    
    # Test non-code block content
    assert convert_code_block_to_json_str('{\"key\": \"value\"}') is None
    
    # Test empty string
    assert convert_code_block_to_json_str('') is None


def test_fix_llm_mistakes_on_json():
    """Test fix_llm_mistakes_on_json function with various LLM JSON formatting errors."""
    # Test valid JSON (should return unchanged)
    valid_json = '{\"key\": \"value\"}'
    assert fix_llm_mistakes_on_json(valid_json) == valid_json
    
    # Test missing closing bracket for array
    assert fix_llm_mistakes_on_json('[1, 2, 3') == '[1, 2, 3]'
    
    # Test extra newline before closing bracket
    assert fix_llm_mistakes_on_json('[1, 2, 3\n]') == '[1, 2, 3\n]'
    
    # Test JSON in markdown code blocks
    assert fix_llm_mistakes_on_json("```json\n{\"key\": \"value\"}\n```") == '[\n{\"key\": \"value\"}\n]'
    
    # Test non-string input
    assert fix_llm_mistakes_on_json(123) == 123


def test_to_json_str():
    """Test to_json_str function with various input types."""
    # Test dict input
    assert to_json_str({"key": "value"}) == '{\n  "key": "value"\n}'
    
    # Test list input
    assert to_json_str([1, 2, 3]) == '[\n  1,\n  2,\n  3\n]'
    
    # Test string input (should pass through fix_llm_mistakes_on_json)
    assert to_json_str('{"key": "value"}') == '{"key": "value"}'
    
    # Test string with code blocks
    assert to_json_str("```json\n{\"key\": \"value\"}\n```") == '[\n{\"key\": \"value\"}\n]'


def test_json_dump():
    """Test json_dump function with various Python objects."""
    # Test dict
    assert json_dump({"key": "value"}) == '{\n  "key": "value"\n}'
    
    # Test list
    assert json_dump([1, 2, 3]) == '[\n  1,\n  2,\n  3\n]'
    
    # Test set (should convert to list)
    assert json_dump({1, 2, 3}) == '[\n  1,\n  2,\n  3\n]'
    
    # Test tuple (should convert to list)
    assert json_dump((1, 2, 3)) == '[\n  1,\n  2,\n  3\n]'


def test_json_load():
    """Test json_load function with valid and invalid JSON."""
    # Test valid JSON object
    assert json_load('{"key": "value"}') == {"key": "value"}
    
    # Test valid JSON array
    assert json_load('[1, 2, 3]') == [1, 2, 3]
    
    # Test non-string input (should return unchanged)
    assert json_load(123) == 123
    
    # Test invalid JSON (should raise exception)
    with pytest.raises(Exception):
        json_load('invalid json')


def test_safe_json_dump():
    """Test safe_json_dump function with various inputs."""
    # Test string input
    assert safe_json_dump('{"key": "value"}') == '{"key": "value"}'
    
    # Test dict input
    assert safe_json_dump({"key": "value"}) == '{\n  "key": "value"\n}'
    
    # Test with non-serializable object (should fallback to str)
    class NonSerializable:
        def __str__(self):
            return "non-serializable"
    
    result = safe_json_dump(NonSerializable())
    assert "non-serializable" in result


def test_safe_json_load():
    """Test safe_json_load function with valid and invalid JSON."""
    # Test valid JSON
    assert safe_json_load('{"key": "value"}') == {"key": "value"}
    
    # Test invalid JSON (should return None)
    assert safe_json_load('invalid json') is None
    
    # Test empty string
    assert safe_json_load('') is None
    
# Test None input
    assert safe_json_load(None) is None


def test_fix_llm_mistakes_on_json_unclosed_object():
    """Test fix_llm_mistakes_on_json repairs truncated object missing closing brace."""
    # Truncated object (missing final '}') with nested object
    content = '{\n  "tool_args": {\n    "cmd": "echo yyy"\n  },\n  "tool_call": "cmd_tool-exec_cmd"\n'
    fixed = fix_llm_mistakes_on_json(content)
    parsed = simplejson.loads(fixed)
    assert parsed["tool_call"] == "cmd_tool-exec_cmd"
    assert parsed["tool_args"] == {"cmd": "echo yyy"}


def test_fix_llm_mistakes_on_json_unclosed_array():
    """Test fix_llm_mistakes_on_json repairs truncated array missing closing bracket."""
    content = '[1, 2, 3'
    fixed = fix_llm_mistakes_on_json(content)
    assert simplejson.loads(fixed) == [1, 2, 3]


def test_complete_unclosed_brackets_non_truncation_preserved():
    """Test that already-balanced JSON is returned unchanged by the repair helper."""
    from topsailai.utils.json_tool import _complete_unclosed_brackets
    balanced_obj = '{"a": {"b": 1}}'
    assert _complete_unclosed_brackets(balanced_obj) == balanced_obj
    balanced_arr = '[1, [2, 3]]'
    assert _complete_unclosed_brackets(balanced_arr) == balanced_arr


def test_complete_unclosed_brackets_nested_truncation():
    """Test nested unclosed brackets are completed in correct order."""
    from topsailai.utils.json_tool import _complete_unclosed_brackets
    # Missing two closing braces: outer object + inner object
    content = '{"a": {"b": 1}'
    repaired = _complete_unclosed_brackets(content)
    assert simplejson.loads(repaired) == {"a": {"b": 1}}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])