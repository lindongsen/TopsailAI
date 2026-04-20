"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-19
Purpose: Unit tests for ai_base/llm_control/base_class.py
"""

import pytest
import sys
import os
from io import StringIO
from unittest.mock import patch, MagicMock

from topsailai.ai_base.llm_control.base_class import (
    ContentSender,
    ContentStdout,
    parse_model_settings,
    LLMModelBase,
)


class TestContentSender:
    """Tests for ContentSender abstract base class."""

    def test_send_raises_not_implemented(self):
        """Test that send method raises NotImplementedError."""
        sender = ContentSender()
        with pytest.raises(NotImplementedError):
            sender.send("test content")


class TestContentStdout:
    """Tests for ContentStdout class."""

    def test_send_writes_to_stdout(self):
        """Test that send method writes content to stdout."""
        sender = ContentStdout()
        captured_output = StringIO()
        with patch.object(sys, 'stdout', captured_output):
            sender.send("Hello, World!")
        assert captured_output.getvalue() == "Hello, World!"

    def test_send_with_empty_string(self):
        """Test send with empty string."""
        sender = ContentStdout()
        captured_output = StringIO()
        with patch.object(sys, 'stdout', captured_output):
            sender.send("")
        assert captured_output.getvalue() == ""

    def test_send_with_multiline_content(self):
        """Test send with multiline content."""
        sender = ContentStdout()
        captured_output = StringIO()
        content = "Line 1\nLine 2\nLine 3"
        with patch.object(sys, 'stdout', captured_output):
            sender.send(content)
        assert captured_output.getvalue() == content

    def test_send_with_unicode_content(self):
        """Test send with unicode content."""
        sender = ContentStdout()
        captured_output = StringIO()
        content = "你好世界 🌍"
        with patch.object(sys, 'stdout', captured_output):
            sender.send(content)
        assert captured_output.getvalue() == content


class TestParseModelSettings:
    """Tests for parse_model_settings function."""

    @patch('topsailai.ai_base.llm_control.base_class.EnvReaderInstance')
    def test_parse_model_settings_with_topsailai_prefix(self, mock_env_reader):
        """Test parsing MODEL_SETTINGS with TOPSAILAI_ prefix."""
        mock_env_reader.get_list_str.return_value = ["api_key=key1,api_base=base1"]
        result = parse_model_settings()
        assert len(result) == 1
        assert result[0]["api_key"] == "key1"
        assert result[0]["api_base"] == "base1"

    @patch('topsailai.ai_base.llm_control.base_class.EnvReaderInstance')
    def test_parse_model_settings_with_model_prefix(self, mock_env_reader):
        """Test parsing MODEL_SETTINGS with MODEL_ prefix."""
        mock_env_reader.get_list_str.return_value = None
        mock_env_reader.get_list_str.return_value = ["key1=val1,key2=val2"]
        result = parse_model_settings()
        assert len(result) == 1
        assert result[0]["key1"] == "val1"
        assert result[0]["key2"] == "val2"

    @patch('topsailai.ai_base.llm_control.base_class.EnvReaderInstance')
    @patch('topsailai.utils.env_tool.EnvReaderInstance')
    def test_parse_model_settings_empty(self, mock_env_reader2, mock_env_reader):
        """Test parsing with no environment variable set."""
        mock_env_reader.get_list_str.return_value = None
        result = parse_model_settings()
        assert result == []

    @patch('topsailai.ai_base.llm_control.base_class.EnvReaderInstance')
    @patch('topsailai.utils.env_tool.EnvReaderInstance')
    def test_parse_model_settings_multiple_items(self, mock_env_reader2, mock_env_reader):
        """Test parsing multiple model settings."""
        mock_env_reader.get_list_str.return_value = [
            "api_key=k1,model=m1",
            "api_key=k2,model=m2"
        ]
        result = parse_model_settings()
        assert len(result) == 2
        assert result[0]["api_key"] == "k1"
        assert result[1]["api_key"] == "k2"

    @patch('topsailai.ai_base.llm_control.base_class.EnvReaderInstance')
    def test_parse_model_settings_with_spaces(self, mock_env_reader):
        """Test parsing with spaces around values."""
        mock_env_reader.get_list_str.return_value = ["api_key= key1 ,api_base= base1 "]
        result = parse_model_settings()
        assert len(result) == 1
        assert result[0]["api_key"] == "key1"
        assert result[0]["api_base"] == "base1"


class TestLLMModelBase:
    """Tests for LLMModelBase class."""

    def test_init_default_values(self, monkeypatch):
        """Test initialization with default values."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        assert model.max_tokens == 8000
        assert model.temperature == 0.3
        assert model.top_p == 0.97
        assert model.frequency_penalty == 0.0

    def test_init_with_model_name(self, monkeypatch):
        """Test initialization with custom model_name."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel(model_name="custom-model")
        assert model.model_name == "custom-model"

    def test_send_content(self, monkeypatch):
        """Test send_content method."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        mock_sender = MagicMock()
        model.content_senders = [mock_sender]
        model.send_content("test content")
        mock_sender.send.assert_called_once_with("test content")

    def test_send_content_multiple_senders(self, monkeypatch):
        """Test send_content with multiple senders."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        mock_sender1 = MagicMock()
        mock_sender2 = MagicMock()
        model.content_senders = [mock_sender1, mock_sender2]
        model.send_content("test content")
        mock_sender1.send.assert_called_once_with("test content")
        mock_sender2.send.assert_called_once_with("test content")

    def test_chat_model_property_single_model(self, monkeypatch):
        """Test chat_model property with single model."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        mock_model = MagicMock()
        model.model = mock_model
        model.models = []
        assert model.chat_model == mock_model

    def test_chat_model_property_multiple_models(self, monkeypatch):
        """Test chat_model property with multiple models."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        mock_model1 = MagicMock()
        mock_model2 = MagicMock()
        model.models = [
            {"_model": mock_model1},
            {"_model": mock_model2}
        ]
        model.model_config = {}
        result = model.chat_model
        assert result in [mock_model1, mock_model2]

    def test_build_parameters_for_chat(self, monkeypatch):
        """Test build_parameters_for_chat method."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        messages = [{"role": "user", "content": "Hello"}]
        params = model.build_parameters_for_chat(messages)
        
        assert params["model"] == "test-model"
        assert params["temperature"] == 0.3
        assert params["max_tokens"] == 8000
        assert params["stream"] == False

    def test_build_parameters_for_chat_with_tools(self, monkeypatch):
        """Test build_parameters_for_chat with tools parameter."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        messages = [{"role": "user", "content": "Hello"}]
        tools = [{"type": "function", "function": {"name": "test"}}]
        params = model.build_parameters_for_chat(messages, tools=tools)
        
        assert "tools" in params
        assert params["tool_choice"] == "auto"

    def test_check_response_content_none(self, monkeypatch):
        """Test check_response_content with None content."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        with pytest.raises(TypeError, match="no response"):
            model.check_response_content(MagicMock(), None)

    def test_check_response_content_empty(self, monkeypatch):
        """Test check_response_content with empty content."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        with pytest.raises(TypeError, match="null of response"):
            model.check_response_content(MagicMock(), "   ")

    def test_format_null_response_content_with_tool_calls(self, monkeypatch):
        """Test format_null_response_content when tool_calls exist."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                mock_response = MagicMock()
                mock_response.tool_calls = [MagicMock()]
                return mock_response
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        result = model.format_null_response_content(MagicMock(), None)
        assert result == "topsailai.action"

    def test_fix_response_content_with_content(self, monkeypatch):
        """Test fix_response_content when content exists."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        result = model.fix_response_content(MagicMock(), "existing content")
        assert result == "existing content"

    def test_get_llm_models_empty_settings(self, monkeypatch):
        """Test get_llm_models with no model settings."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        result = model.get_llm_models()
        assert result is None or result == []

    def test_rebuild_llm_models(self, monkeypatch):
        """Test rebuild_llm_models method."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        model = TestModel()
        mock_model = MagicMock()
        model.model = mock_model
        model.rebuild_llm_models()
        assert model.model is not None
