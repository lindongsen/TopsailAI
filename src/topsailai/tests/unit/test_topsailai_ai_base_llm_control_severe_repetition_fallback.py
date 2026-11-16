"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-15
Purpose: Unit tests for the consecutive severe-repetition verdict fallback.
"""

import ast
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from topsailai.ai_base.llm_control.base_class import LLMModelBase
from topsailai.ai_base.llm_control.exception import (
    LLMSevereRepetitionError,
    LLMServiceSpecialResponseError,
    ModelServiceError,
)

REPETITION_VERDICT = {
    "total_lines": 100,
    "exact_duplicate_count": 20,
    "fuzzy_duplicate_count": 20,
    "total_duplicates": 40,
    "repetition_rate": 0.4,
    "has_severe_repetition": True,
    "structural_line_count": 0,
}

PASSING_VERDICT = {
    "total_lines": 100,
    "exact_duplicate_count": 1,
    "fuzzy_duplicate_count": 1,
    "total_duplicates": 2,
    "repetition_rate": 0.02,
    "has_severe_repetition": False,
    "structural_line_count": 0,
}

# A response that is not a configured special response and is long enough to
# reach the repetition gate once max_tokens is pinned to a small value.
ORDINARY_CONTENT = "alpha beta gamma delta epsilon zeta eta theta"


def _make_model():
    """Return a minimal LLMModelBase subclass instance."""

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


@pytest.fixture
def model(monkeypatch):
    """Return a model whose repetition gate is reachable for short content."""
    monkeypatch.setenv("TOPSAILAI_MAX_COMPLETION_TOKENS", "1")
    monkeypatch.setenv("TOPSAILAI_REFUSE_SEVERE_REPETITION", "1")
    monkeypatch.delenv("TOPSAILAI_SEVERE_REPETITION_MAX_CONSECUTIVE", raising=False)
    monkeypatch.delenv("TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY", raising=False)
    return _make_model()


class TestSevereRepetitionErrorClassification:
    """The fallback error is a specialized model-service error."""

    def test_error_is_a_model_service_error(self):
        """Callers that handle model-service failures keep working."""
        assert issubclass(LLMSevereRepetitionError, ModelServiceError)

    def test_error_is_not_a_special_response_error(self):
        """A content verdict must not be mistaken for a retryable special reply."""
        assert not issubclass(LLMSevereRepetitionError, LLMServiceSpecialResponseError)


class TestConsecutiveVerdictFallback:
    """A single verdict retries; a repeated verdict stops the request."""

    def test_first_verdict_raises_the_retryable_parent(self, model):
        """The first verdict stays retryable so a transient repetition recovers."""
        with patch(
            "topsailai.ai_base.llm_control.base_class.text_tool.check_repetition",
            return_value=REPETITION_VERDICT,
        ):
            with pytest.raises(ModelServiceError) as exc_info:
                model.check_response_content(MagicMock(), ORDINARY_CONTENT)

        assert not isinstance(exc_info.value, LLMSevereRepetitionError)
        assert model._consecutive_repetition_verdicts == 1

    def test_second_consecutive_verdict_raises_the_specialized_error(self, model):
        """Two consecutive verdicts exhaust the content-verdict budget."""
        with patch(
            "topsailai.ai_base.llm_control.base_class.text_tool.check_repetition",
            return_value=REPETITION_VERDICT,
        ):
            with pytest.raises(ModelServiceError):
                model.check_response_content(MagicMock(), ORDINARY_CONTENT)
            with pytest.raises(LLMSevereRepetitionError) as exc_info:
                model.check_response_content(MagicMock(), ORDINARY_CONTENT)

        assert "2 consecutive times" in str(exc_info.value)

    def test_passing_response_resets_the_streak(self, model):
        """A response that passes every check breaks the consecutive streak."""
        with patch(
            "topsailai.ai_base.llm_control.base_class.text_tool.check_repetition",
            return_value=REPETITION_VERDICT,
        ):
            with pytest.raises(ModelServiceError):
                model.check_response_content(MagicMock(), ORDINARY_CONTENT)
        assert model._consecutive_repetition_verdicts == 1

        with patch(
            "topsailai.ai_base.llm_control.base_class.text_tool.check_repetition",
            return_value=PASSING_VERDICT,
        ):
            model.check_response_content(MagicMock(), ORDINARY_CONTENT)
        assert model._consecutive_repetition_verdicts == 0

        # The next verdict is the first of a new streak, so it stays retryable.
        with patch(
            "topsailai.ai_base.llm_control.base_class.text_tool.check_repetition",
            return_value=REPETITION_VERDICT,
        ):
            with pytest.raises(ModelServiceError) as exc_info:
                model.check_response_content(MagicMock(), ORDINARY_CONTENT)
        assert not isinstance(exc_info.value, LLMSevereRepetitionError)

    def test_reset_clears_the_counter(self, model):
        """An explicit reset starts a new content-verdict budget."""
        model._consecutive_repetition_verdicts = 5
        model.reset_repetition_verdict_count()
        assert model._consecutive_repetition_verdicts == 0

    def test_verdict_is_not_counted_when_the_switch_is_off(self, model, monkeypatch):
        """Disabling the refusal switch keeps the legacy warn-only behavior."""
        monkeypatch.setenv("TOPSAILAI_REFUSE_SEVERE_REPETITION", "0")
        with patch(
            "topsailai.ai_base.llm_control.base_class.text_tool.check_repetition",
            return_value=REPETITION_VERDICT,
        ):
            model.check_response_content(MagicMock(), ORDINARY_CONTENT)

        assert model._consecutive_repetition_verdicts == 0


class TestVerdictLimitConfiguration:
    """The consecutive-verdict limit is configurable and clamped."""

    def test_default_limit_is_two(self, model):
        """The default tolerates one retry before raising."""
        assert model._get_repetition_verdict_limit() == 2

    def test_limit_is_read_from_the_environment(self, model, monkeypatch):
        """An operator can raise the tolerated consecutive verdict count."""
        monkeypatch.setenv("TOPSAILAI_SEVERE_REPETITION_MAX_CONSECUTIVE", "4")
        assert model._get_repetition_verdict_limit() == 4

    @pytest.mark.parametrize("value", ["0", "-3"])
    def test_limit_below_one_is_clamped(self, model, monkeypatch, value):
        """A non-positive limit would remove the recovering retry entirely."""
        monkeypatch.setenv("TOPSAILAI_SEVERE_REPETITION_MAX_CONSECUTIVE", value)
        assert model._get_repetition_verdict_limit() == 1

    def test_invalid_limit_falls_back_to_the_default(self, model, monkeypatch):
        """A non-numeric value must not disable the fallback."""
        monkeypatch.setenv("TOPSAILAI_SEVERE_REPETITION_MAX_CONSECUTIVE", "many")
        assert model._get_repetition_verdict_limit() == 2

    def test_configured_limit_controls_when_the_error_raises(self, model, monkeypatch):
        """A limit of three tolerates two retryable verdicts."""
        monkeypatch.setenv("TOPSAILAI_SEVERE_REPETITION_MAX_CONSECUTIVE", "3")
        with patch(
            "topsailai.ai_base.llm_control.base_class.text_tool.check_repetition",
            return_value=REPETITION_VERDICT,
        ):
            for _ in range(2):
                with pytest.raises(ModelServiceError) as exc_info:
                    model.check_response_content(MagicMock(), ORDINARY_CONTENT)
                assert not isinstance(exc_info.value, LLMSevereRepetitionError)
            with pytest.raises(LLMSevereRepetitionError):
                model.check_response_content(MagicMock(), ORDINARY_CONTENT)


class TestRetryLoopWiring:
    """The retry loop must stop on the specialized error, not retry it."""

    @staticmethod
    def _llm_base_source():
        """Return the source text of ai_base/llm_base.py."""
        import topsailai.ai_base.llm_base as llm_base_module

        return Path(llm_base_module.__file__).read_text(encoding="utf-8")

    def test_specialized_handler_precedes_the_generic_handler(self):
        """A subclass caught by the parent branch would retry forever."""
        source = self._llm_base_source()
        specialized = source.index("except LLMSevereRepetitionError")
        generic = source.index("except ModelServiceError as e:")
        assert specialized < generic

    def test_specialized_handler_reraises(self):
        """The handler must propagate instead of sleeping and continuing."""
        source = self._llm_base_source()
        start = source.index("except LLMSevereRepetitionError")
        handler_body = source[start:start + 600]
        assert "raise" in handler_body
        assert "continue" not in handler_body

    def test_new_request_resets_the_verdict_budget(self):
        """A verdict from a previous request must not count toward the next."""
        source = self._llm_base_source()
        reset_call = source.index("self.reset_repetition_verdict_count()")
        operation_id = source.index("operation_id = uuid4().hex")
        assert reset_call < operation_id

    def test_specialized_error_is_imported_by_the_retry_module(self):
        """The handler cannot reference a name the module never imported."""
        source = self._llm_base_source()
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported.add(alias.asname or alias.name)
        assert "LLMSevereRepetitionError" in imported
