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
        content = "‰Ω†Â•Ω‰∏ñÁïå üåç"
        with patch.object(sys, 'stdout', captured_output):
            sender.send(content)
        assert captured_output.getvalue() == content


class TestParseModelSettings:
    """Tests for parse_model_settings function."""

    @patch.dict(os.environ, {"TOPSAILAI_MODEL_SETTINGS": "api_key=key1,api_base=base1"}, clear=False)
    def test_parse_model_settings_with_topsailai_prefix(self):
        """Test parsing MODEL_SETTINGS with TOPSAILAI_ prefix."""
        result = parse_model_settings()
        assert len(result) == 1
        assert result[0]["api_key"] == "key1"
        assert result[0]["api_base"] == "base1"

    @patch.dict(os.environ, {"MODEL_SETTINGS": "key1=val1,key2=val2"}, clear=False)
    def test_parse_model_settings_with_model_prefix(self):
        """Test parsing MODEL_SETTINGS with MODEL_ prefix."""
        result = parse_model_settings()
        assert len(result) == 1
        assert result[0]["key1"] == "val1"
        assert result[0]["key2"] == "val2"

    def test_parse_model_settings_empty(self):
        """Test parsing with no environment variable set."""
        # Ensure no MODEL_SETTINGS env vars are set
        env_vars_to_clear = ["TOPSAILAI_MODEL_SETTINGS", "MODEL_SETTINGS"]
        with patch.dict(os.environ, {}, clear=False):
            for var in env_vars_to_clear:
                os.environ.pop(var, None)
            result = parse_model_settings()
            assert result == []

    @patch.dict(os.environ, {"TOPSAILAI_MODEL_SETTINGS": "api_key=k1,model=m1;api_key=k2,model=m2"}, clear=False)
    def test_parse_model_settings_multiple_items(self):
        """Test parsing multiple model settings."""
        result = parse_model_settings()
        assert len(result) == 2
        # Check both items exist without relying on order
        api_keys = [item["api_key"] for item in result]
        assert "k1" in api_keys
        assert "k2" in api_keys
        models = [item["model"] for item in result]
        assert "m1" in models
        assert "m2" in models

    @patch.dict(os.environ, {"TOPSAILAI_MODEL_SETTINGS": "api_key= key1 ,api_base= base1 "}, clear=False)
    def test_parse_model_settings_with_spaces(self):
        """Test parsing with spaces around values."""
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

    def test_init_with_max_tokens(self, monkeypatch):
        """Test initialization with custom max_tokens."""
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

        model = TestModel(max_tokens=4000)
        assert model.max_tokens == 4000

    def test_init_with_temperature(self, monkeypatch):
        """Test initialization with custom temperature."""
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

        model = TestModel(temperature=0.7)
        assert model.temperature == 0.7

    def test_init_with_top_p(self, monkeypatch):
        """Test initialization with custom top_p."""
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

        model = TestModel(top_p=0.95)
        assert model.top_p == 0.95

    def test_init_with_frequency_penalty(self, monkeypatch):
        """Test initialization with custom frequency_penalty."""
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

        model = TestModel(frequency_penalty=0.5)
        assert model.frequency_penalty == 0.5

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

        model = TestModel(
            model_name="gpt-4",
            max_tokens=2000,
            temperature=0.5,
            top_p=0.9,
            frequency_penalty=0.1
        )
        
        messages = [{"role": "user", "content": "Hello"}]
        params = model.build_parameters_for_chat(messages)
        assert params["model"] == "gpt-4"
        assert params["max_tokens"] == 2000
        assert params["temperature"] == 0.5
        assert params["top_p"] == 0.9
        assert params["frequency_penalty"] == 0.1

    def test_get_llm_models_empty_settings(self, monkeypatch):
        """Test get_llm_models with empty settings."""
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
        # get_llm_models returns None when no settings, but sets self.models
        result = model.get_llm_models()
        # The method returns None but populates self.models
        assert model.models is not None
        assert isinstance(model.models, list)


class TestLLMModelBaseEdgeCases:
    """Edge case tests for LLMModelBase."""

    def test_init_with_negative_max_tokens(self, monkeypatch):
        """Test initialization with negative max_tokens."""
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

        model = TestModel(max_tokens=-100)
        assert model.max_tokens == -100  # Should accept negative value

    def test_init_with_zero_temperature(self, monkeypatch):
        """Test initialization with zero temperature."""
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

        model = TestModel(temperature=0.0)
        assert model.temperature == 0.0

    def test_init_with_max_top_p(self, monkeypatch):
        """Test initialization with maximum top_p value."""
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

        model = TestModel(top_p=1.0)
        assert model.top_p == 1.0

    def test_build_parameters_preserves_stream(self, monkeypatch):
        """Test build_parameters_for_chat preserves stream parameter."""
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
        params = model.build_parameters_for_chat(messages, stream=True)
        assert params["stream"] is True

        params = model.build_parameters_for_chat(messages, stream=False)
        assert params["stream"] is False
