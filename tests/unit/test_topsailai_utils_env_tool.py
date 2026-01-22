import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.topsailai.utils.env_tool import (
    is_debug_mode,
    is_use_tool_calls,
    is_chat_multi_line,
    EnvironmentReader,
    EnvReaderInstance
)


class TestDebugMode:
    """Test is_debug_mode function"""
    
    def test_debug_mode_disabled_default(self):
        """Test debug mode is disabled by default"""
        with patch.dict(os.environ, {}, clear=True):
            assert is_debug_mode() is False
    
    def test_debug_mode_disabled_explicit_0(self):
        """Test debug mode is disabled when DEBUG="0"""
        with patch.dict(os.environ, {"DEBUG": "0"}):
            assert is_debug_mode() is False
    
    def test_debug_mode_enabled_1(self):
        """Test debug mode is enabled when DEBUG="1"""
        with patch.dict(os.environ, {"DEBUG": "1"}):
            assert is_debug_mode() is True
    
    def test_debug_mode_enabled_any_value(self):
        """Test debug mode is enabled for any non-zero value"""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            assert is_debug_mode() is True
        with patch.dict(os.environ, {"DEBUG": "yes"}):
            assert is_debug_mode() is True


class TestUseToolCalls:
    """Test is_use_tool_calls function"""
    
    def test_use_tool_calls_disabled_default(self):
        """Test tool calls are disabled by default"""
        with patch.dict(os.environ, {}, clear=True):
            assert is_use_tool_calls() is False
    
    def test_use_tool_calls_disabled_explicit_0(self):
        """Test tool calls are disabled when USE_TOOL_CALLS="0"""
        with patch.dict(os.environ, {"USE_TOOL_CALLS": "0"}):
            assert is_use_tool_calls() is False
    
    def test_use_tool_calls_enabled_1(self):
        """Test tool calls are enabled when USE_TOOL_CALLS="1"""
        with patch.dict(os.environ, {"USE_TOOL_CALLS": "1"}):
            assert is_use_tool_calls() is True
    
    def test_use_tool_calls_enabled_any_value(self):
        """Test tool calls are enabled for any non-zero value"""
        with patch.dict(os.environ, {"USE_TOOL_CALLS": "true"}):
            assert is_use_tool_calls() is True


class TestChatMultiLine:
    """Test is_chat_multi_line function"""
    
    def test_chat_multi_line_disabled_default(self):
        """Test multi-line chat is disabled by default"""
        with patch.dict(os.environ, {}, clear=True):
            assert is_chat_multi_line() is False
    
    def test_chat_multi_line_disabled_explicit_0(self):
        """Test multi-line chat is disabled when CHAT_MULTI_LINE="0"""
        with patch.dict(os.environ, {"CHAT_MULTI_LINE": "0"}):
            assert is_chat_multi_line() is False
    
    def test_chat_multi_line_enabled_1(self):
        """Test multi-line chat is enabled when CHAT_MULTI_LINE="1"""
        with patch.dict(os.environ, {"CHAT_MULTI_LINE": "1"}):
            assert is_chat_multi_line() is True
    
    def test_chat_multi_line_enabled_any_value(self):
        """Test multi-line chat is enabled for any non-zero value"""
        with patch.dict(os.environ, {"CHAT_MULTI_LINE": "true"}):
            assert is_chat_multi_line() is True


class TestEnvironmentReader:
    """Test EnvironmentReader class"""
    
    def setup_method(self):
        """Setup method to create a fresh instance for each test"""
        self.reader = EnvironmentReader()
    
    def test_try_read_file_none_path(self):
        """Test try_read_file with None path"""
        assert self.reader.try_read_file("") == ""
        assert self.reader.try_read_file(None) == ""
    
    def test_try_read_file_non_file_content(self):
        """Test try_read_file with content that's not a file path"""
        assert self.reader.try_read_file("some content") == ""
        assert self.reader.try_read_file("a" * 256) == ""
    
    def test_try_read_file_existing_file(self):
        """Test try_read_file with an existing file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            tmp.write("test content")
            tmp_path = tmp.name
        
        try:
            result = self.reader.try_read_file(tmp_path)
            assert result == "test content"
        finally:
            os.unlink(tmp_path)
    
    def test_try_read_file_nonexistent_file(self):
        """Test try_read_file with non-existent file"""
        assert self.reader.try_read_file("/nonexistent/file") == ""
    
    def test_story_prompt_content_no_env_var(self):
        """Test story_prompt_content when STORY_PROMPT is not set"""
        with patch.dict(os.environ, {}, clear=True):
            assert self.reader.story_prompt_content == ""
    
    def test_story_prompt_content_direct_content(self):
        """Test story_prompt_content with direct content"""
        with patch.dict(os.environ, {"STORY_PROMPT": "direct content"}):
            assert self.reader.story_prompt_content == "direct content"
    
    def test_story_prompt_content_file_path(self):
        """Test story_prompt_content with file path"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            tmp.write("file content")
            tmp_path = tmp.name
        
        try:
            with patch.dict(os.environ, {"STORY_PROMPT": tmp_path}):
                assert self.reader.story_prompt_content == "file content"
        finally:
            os.unlink(tmp_path)
    
    def test_check_bool(self):
        """Test check_bool method"""
        with patch.dict(os.environ, {"TEST_BOOL": "1"}):
            assert self.reader.check_bool("TEST_BOOL") is True
        
        with patch.dict(os.environ, {"TEST_BOOL": "true"}):
            assert self.reader.check_bool("TEST_BOOL") is True
        
        with patch.dict(os.environ, {"TEST_BOOL": "0"}):
            assert self.reader.check_bool("TEST_BOOL") is False
        
        with patch.dict(os.environ, {"TEST_BOOL": "false"}):
            assert self.reader.check_bool("TEST_BOOL") is False
        
        # Test default value
        assert self.reader.check_bool("NONEXISTENT", default="1") is True
        assert self.reader.check_bool("NONEXISTENT", default="0") is False
    
    def test_get_list_str(self):
        """Test get_list_str method"""
        # Test no config
        with patch.dict(os.environ, {}, clear=True):
            assert self.reader.get_list_str("TEST_LIST") is None
        
        # Test null config
        with patch.dict(os.environ, {"TEST_LIST": ""}):
            assert self.reader.get_list_str("TEST_LIST") == ""
        
        # Test with content
        with patch.dict(os.environ, {"TEST_LIST": "a;b;c"}):
            result = self.reader.get_list_str("TEST_LIST")
            assert isinstance(result, list)
            assert set(result) == {"a", "b", "c"}
        
        # Test with different separator
        with patch.dict(os.environ, {"TEST_LIST": "a,b,c"}):
            result = self.reader.get_list_str("TEST_LIST", separator=",")
            assert set(result) == {"a", "b", "c"}
        
        # Test with to_lower
        with patch.dict(os.environ, {"TEST_LIST": "A;B;C"}):
            result = self.reader.get_list_str("TEST_LIST", to_lower=True)
            assert set(result) == {"a", "b", "c"}
        
        # Test with duplicates and whitespace
        with patch.dict(os.environ, {"TEST_LIST": " a ; b ; a ; c "}):
            result = self.reader.get_list_str("TEST_LIST")
            assert set(result) == {"a", "b", "c"}
    
    def test_is_not_config(self):
        """Test is_not_config method"""
        with patch.dict(os.environ, {}, clear=True):
            assert self.reader.is_not_config("TEST_VAR") is True
        
        with patch.dict(os.environ, {"TEST_VAR": "value"}):
            assert self.reader.is_not_config("TEST_VAR") is False
    
    def test_is_null_config(self):
        """Test is_null_config method"""
        with patch.dict(os.environ, {"TEST_VAR": ""}):
            assert self.reader.is_null_config("TEST_VAR") is True
        
        with patch.dict(os.environ, {"TEST_VAR": "value"}):
            assert self.reader.is_null_config("TEST_VAR") is False
        
        with patch.dict(os.environ, {}, clear=True):
            assert self.reader.is_null_config("TEST_VAR") is False
    
    def test_get(self):
        """Test get method"""
        with patch.dict(os.environ, {}, clear=True):
            assert self.reader.get("TEST_VAR") is None
            assert self.reader.get("TEST_VAR", "default") == "default"
        
        with patch.dict(os.environ, {"TEST_VAR": "value"}):
            assert self.reader.get("TEST_VAR") == "value"
            assert self.reader.get("TEST_VAR", "default") == "value"


class TestEnvReaderInstance:
    """Test the global EnvReaderInstance"""
    
    def test_singleton_instance(self):
        """Test that EnvReaderInstance is a singleton"""
        from src.topsailai.utils.env_tool import EnvReaderInstance
        reader1 = EnvReaderInstance
        reader2 = EnvReaderInstance
        assert reader1 is reader2
        assert isinstance(reader1, EnvironmentReader)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])