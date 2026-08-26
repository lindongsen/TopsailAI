"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-19
Purpose: Unit tests for ai_base/llm_control/base_class.py
"""

import pytest
import os
from unittest.mock import patch, MagicMock

from topsailai.ai_base.llm_control.base_class import (
    parse_model_settings,
    LLMModelBase,
)
from topsailai.ai_base.llm_control.exception import (
    LLMServiceSpecialResponseError,
)


@pytest.fixture(autouse=True)
def clean_llm_parameter_environment(monkeypatch):
    """Remove all current and legacy LLM parameter variables per test."""
    for name in (
        "TOPSAILAI_MAX_COMPLETION_TOKENS", "MAX_TOKENS",
        "TOPSAILAI_TEMPERATURE", "TEMPERATURE",
        "TOPSAILAI_TOP_P", "TOP_P",
        "TOPSAILAI_FREQUENCY_PENALTY", "FREQUENCY_PENALTY",
    ):
        monkeypatch.delenv(name, raising=False)


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


    @staticmethod
    def _make_environment_model():
        """Create a minimal model for environment-resolution tests."""
        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        return TestModel()

    def test_init_falls_back_to_legacy_llm_parameter_variables(self, monkeypatch):
        """Legacy variables remain effective when preferred variables are unset."""
        monkeypatch.setenv("MAX_TOKENS", "4100")
        monkeypatch.setenv("TEMPERATURE", "0.4")
        monkeypatch.setenv("TOP_P", "0.8")
        monkeypatch.setenv("FREQUENCY_PENALTY", "0.2")

        model = self._make_environment_model()

        assert model.max_tokens == 4100
        assert model.temperature == 0.4
        assert model.top_p == 0.8
        assert model.frequency_penalty == 0.2

    def test_init_prefers_prefixed_llm_parameter_variables(self, monkeypatch):
        """Preferred variables override legacy variables when both have values."""
        legacy_values = {
            "MAX_TOKENS": "4100",
            "TEMPERATURE": "0.4",
            "TOP_P": "0.8",
            "FREQUENCY_PENALTY": "0.2",
        }
        preferred_values = {
            "TOPSAILAI_MAX_COMPLETION_TOKENS": "5100",
            "TOPSAILAI_TEMPERATURE": "0.5",
            "TOPSAILAI_TOP_P": "0.9",
            "TOPSAILAI_FREQUENCY_PENALTY": "0.3",
        }
        for name, value in {**legacy_values, **preferred_values}.items():
            monkeypatch.setenv(name, value)

        model = self._make_environment_model()

        assert model.max_tokens == 5100
        assert model.temperature == 0.5
        assert model.top_p == 0.9
        assert model.frequency_penalty == 0.3

    def test_init_empty_preferred_variable_falls_back_to_legacy(self, monkeypatch):
        """An empty preferred variable is treated as having no value."""
        monkeypatch.setenv("TOPSAILAI_MAX_COMPLETION_TOKENS", "")
        monkeypatch.setenv("MAX_TOKENS", "6100")

        model = self._make_environment_model()

        assert model.max_tokens == 6100

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

    @pytest.fixture
    def request_model(self, monkeypatch):
        """Return a model for request-parameter tests."""
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        monkeypatch.delenv("TOPSAILAI_LLM_EXTRA_BODY", raising=False)
        monkeypatch.delenv("TOPSAILAI_LLM_EXTRA_BODY_MAP", raising=False)

        class TestModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                return MagicMock()
            def chat(self, *args, **kwargs):
                pass

        return TestModel()

    def test_extra_body_unset_or_empty_leaves_params_unchanged(
            self, monkeypatch, request_model):
        """Unset or empty extra-body configuration should not alter parameters."""
        messages = [{"role": "user", "content": "Hello"}]
        assert "extra_body" not in request_model.build_parameters_for_chat(messages)

        monkeypatch.setenv("TOPSAILAI_LLM_EXTRA_BODY", "")
        monkeypatch.setenv("TOPSAILAI_LLM_EXTRA_BODY_MAP", "")
        assert "extra_body" not in request_model.build_parameters_for_chat(messages)

    def test_extra_body_injects_chat_template_kwargs(
            self, monkeypatch, request_model):
        """Configured provider fields should be injected through extra_body."""
        monkeypatch.setenv(
            "TOPSAILAI_LLM_EXTRA_BODY",
            '{"chat_template_kwargs":{"thinking":false}}',
        )
        params = request_model.build_parameters_for_chat(
            [{"role": "user", "content": "Hello"}]
        )
        assert params["extra_body"] == {
            "chat_template_kwargs": {"thinking": False}
        }

    def test_extra_body_recursively_merges_with_environment_precedence(
            self, monkeypatch, request_model):
        """Environment values should override matching keys without dropping peers."""
        monkeypatch.setenv(
            "TOPSAILAI_LLM_EXTRA_BODY",
            '{"chat_template_kwargs":{"thinking":false}}',
        )
        params = request_model.build_parameters_for_chat(
            [{"role": "user", "content": "Hello"}],
            extra_body={
                "chat_template_kwargs": {"thinking": True, "custom": "kept"},
                "provider_option": 1,
            },
        )
        assert params["extra_body"] == {
            "chat_template_kwargs": {"thinking": False, "custom": "kept"},
            "provider_option": 1,
        }

    @pytest.mark.parametrize("raw", ["not-json", "[]"])
    def test_invalid_extra_body_is_ignored(
            self, monkeypatch, request_model, caplog, raw):
        """Invalid extra-body configuration should warn and leave parameters unchanged."""
        monkeypatch.setenv("TOPSAILAI_LLM_EXTRA_BODY", raw)
        with caplog.at_level("WARNING"):
            params = request_model.build_parameters_for_chat(
                [{"role": "user", "content": "Hello"}]
            )
        assert "extra_body" not in params
        assert "TOPSAILAI_LLM_EXTRA_BODY" in caplog.text

    def test_extra_body_map_exact_match_injects_model_configuration(
            self, monkeypatch, request_model):
        """An exact model-name match should inject its model-specific fields."""
        monkeypatch.setenv(
            "TOPSAILAI_LLM_EXTRA_BODY_MAP",
            '{"test-model":{"chat_template_kwargs":{"thinking":false}},'
            '"test":{"ignored":true}}',
        )
        params = request_model.build_parameters_for_chat(
            [{"role": "user", "content": "Hello"}]
        )
        assert params["extra_body"] == {
            "chat_template_kwargs": {"thinking": False}
        }

    def test_extra_body_map_miss_uses_only_global_configuration(
            self, monkeypatch, request_model):
        """A map miss should leave the global extra-body configuration in effect."""
        monkeypatch.setenv("TOPSAILAI_LLM_EXTRA_BODY", '{"global":true}')
        monkeypatch.setenv(
            "TOPSAILAI_LLM_EXTRA_BODY_MAP", '{"other-model":{"model":true}}'
        )
        params = request_model.build_parameters_for_chat(
            [{"role": "user", "content": "Hello"}]
        )
        assert params["extra_body"] == {"global": True}

    def test_extra_body_map_recursively_overrides_global_and_caller(
            self, monkeypatch, request_model):
        """Model-specific fields should have the highest recursive merge priority."""
        monkeypatch.setenv(
            "TOPSAILAI_LLM_EXTRA_BODY",
            '{"chat_template_kwargs":{"thinking":true,"global":"kept"}}',
        )
        monkeypatch.setenv(
            "TOPSAILAI_LLM_EXTRA_BODY_MAP",
            '{"test-model":{"chat_template_kwargs":{"thinking":false},'
            '"model_option":1}}',
        )
        params = request_model.build_parameters_for_chat(
            [{"role": "user", "content": "Hello"}],
            extra_body={"chat_template_kwargs": {"caller": "kept"}},
        )
        assert params["extra_body"] == {
            "chat_template_kwargs": {
                "caller": "kept", "global": "kept", "thinking": False,
            },
            "model_option": 1,
        }

    @pytest.mark.parametrize("raw", ["not-json", "[]"])
    def test_invalid_extra_body_map_is_ignored(
            self, monkeypatch, request_model, caplog, raw):
        """Invalid map configuration should warn and leave parameters unchanged."""
        monkeypatch.setenv("TOPSAILAI_LLM_EXTRA_BODY_MAP", raw)
        with caplog.at_level("WARNING"):
            params = request_model.build_parameters_for_chat(
                [{"role": "user", "content": "Hello"}]
            )
        assert "extra_body" not in params
        assert "TOPSAILAI_LLM_EXTRA_BODY_MAP" in caplog.text

    def test_non_object_matching_extra_body_map_value_is_ignored(
            self, monkeypatch, request_model, caplog):
        """A matching model value must itself be an extra-body JSON object."""
        monkeypatch.setenv(
            "TOPSAILAI_LLM_EXTRA_BODY_MAP", '{"test-model":false}'
        )
        with caplog.at_level("WARNING"):
            params = request_model.build_parameters_for_chat(
                [{"role": "user", "content": "Hello"}]
            )
        assert "extra_body" not in params
        assert "value for model test-model must be a JSON object" in caplog.text

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


class TestLLMModelBaseSpecialResponses:
    """Tests for special-response retry detection."""

    @pytest.fixture
    def test_model(self, monkeypatch):
        """Return a minimal LLMModelBase subclass instance."""
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

        return TestModel()

    @patch.dict(os.environ, {"TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY": '["服务器繁忙，请稍后再试。", "服务繁忙"]'}, clear=False)
    def test_check_response_content_exact_match_raises(self, test_model):
        """Exact match should raise LLMServiceSpecialResponseError."""
        with pytest.raises(LLMServiceSpecialResponseError) as exc_info:
            test_model.check_response_content(MagicMock(), "服务器繁忙，请稍后再试。")
        assert "服务器繁忙，请稍后再试。" in str(exc_info.value)

    @patch.dict(os.environ, {"TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY": '["服务器繁忙，请稍后再试。"]'}, clear=False)
    def test_check_response_content_non_match_passes(self, test_model):
        """Non-matching content should not raise."""
        # A normal structured response should pass through unchanged.
        test_model.check_response_content(MagicMock(), '{"action": "think", "content": "ok"}')

    @patch.dict(os.environ, {"TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY": '["服务器繁忙"]'}, clear=False)
    def test_check_response_content_whitespace_stripped(self, test_model):
        """Whitespace around the response should be stripped before matching."""
        with pytest.raises(LLMServiceSpecialResponseError):
            test_model.check_response_content(MagicMock(), "  服务器繁忙  \n")

    @patch.dict(os.environ, {"TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY": '["服务器繁忙"]'}, clear=False)
    def test_check_response_content_partial_match_passes(self, test_model):
        """Partial match should not raise; only exact full match counts."""
        test_model.check_response_content(MagicMock(), "服务器繁忙，请稍后再试。")

    @patch.dict(os.environ, {"TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY": "not-json"}, clear=False)
    def test_get_special_responses_invalid_json_returns_empty(self, test_model, caplog):
        """Invalid JSON config should log a warning and disable matching."""
        with caplog.at_level("WARNING"):
            result = test_model._get_special_responses_for_retry()
        assert result == []
        assert "invalid JSON" in caplog.text

    def test_get_special_responses_empty_unset(self, test_model, monkeypatch):
        """Empty or unset env var should return an empty list."""
        monkeypatch.delenv("TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY", raising=False)
        assert test_model._get_special_responses_for_retry() == []

        monkeypatch.setenv("TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY", "")
        assert test_model._get_special_responses_for_retry() == []

    @patch.dict(os.environ, {"TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY": '{"not": "a list"}'}, clear=False)
    def test_get_special_responses_non_list_returns_empty(self, test_model):
        """Non-list JSON should return an empty list."""
        assert test_model._get_special_responses_for_retry() == []

    @patch.dict(os.environ, {"TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY": '[" a ", null, "b"]'}, clear=False)
    def test_get_special_responses_filters_and_strips(self, test_model):
        """Items should be stringified, stripped, and nulls filtered out."""
        result = test_model._get_special_responses_for_retry()
        assert result == ["a", "b"]
class TestFormatNullResponseContent:
    """Tests for LLMModelBase.format_null_response_content native tool_call handling."""

    def _make_model(self):
        from topsailai.ai_base.llm_control.base_class import LLMModelBase

        class NativeToolModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                msg = MagicMock()
                msg.tool_calls = [MagicMock()]
                return msg
            def chat(self, *args, **kwargs):
                pass
        return NativeToolModel()

    def test_native_tool_call_returns_action_without_warning(self, monkeypatch, caplog):
        """Native tool_call on rsp_obj yields STEP_ACTION and logs no 'missing action'."""
        from topsailai.utils.format_tool import TOPSAILAI_STEP_ACTION

        monkeypatch.delenv("MAX_TOKENS", raising=False)
        model = self._make_model()
        with caplog.at_level("WARNING"):
            result = model.format_null_response_content(MagicMock(), "")
        assert result == TOPSAILAI_STEP_ACTION
        assert "missing action" not in caplog.text

    def test_empty_content_no_tool_call_returns_empty(self, monkeypatch):
        """Without native tool_calls, empty content stays unchanged (no crash)."""
        from topsailai.ai_base.llm_control.base_class import LLMModelBase

        monkeypatch.delenv("MAX_TOKENS", raising=False)

        class NoToolModel(LLMModelBase):
            def get_model_name(self, default=""):
                return "test-model"
            def get_llm_model(self, api_key=None, api_base=None):
                return MagicMock()
            def get_response_message(self, response):
                msg = MagicMock()
                msg.tool_calls = []
                return msg
            def chat(self, *args, **kwargs):
                pass

        model = NoToolModel()
        assert model.format_null_response_content(MagicMock(), "") == ""