"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-16
Purpose: Unit tests for the per-request LLM wall-clock budget.
"""

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.configuration import (
    LLM_REQUEST_WALL_CLOCK_BUDGET_DEFAULT_SEC,
    get_llm_request_wall_clock_budget,
)
from topsailai.ai_base.llm_control.exception import (
    LLMRequestTimeoutError,
    LLMSevereRepetitionError,
    ModelServiceError,
)


def _make_model():
    """Return a bare object carrying the retry-loop budget helpers.

    The helpers live on ``LLMModel`` because they are used by its retry loop.
    Binding them to a plain object avoids constructing a provider backend,
    which the budget logic does not depend on.
    """
    return MagicMock()


class TestErrorClassification:
    """The budget error is a specialized model-service error."""

    def test_error_is_a_model_service_error(self):
        """Callers that handle model-service failures keep working."""
        assert issubclass(LLMRequestTimeoutError, ModelServiceError)

    def test_error_is_not_a_severe_repetition_error(self):
        """A stalled request is not a content verdict."""
        assert not issubclass(LLMRequestTimeoutError, LLMSevereRepetitionError)


class TestBudgetConfiguration:
    """The budget is configurable and clamped."""

    def test_default_budget_is_thirty_minutes(self):
        """The default bounds a request at 1800 seconds."""
        assert LLM_REQUEST_WALL_CLOCK_BUDGET_DEFAULT_SEC == 1800

    def test_budget_is_read_from_the_environment(self, monkeypatch):
        """An operator can shorten or lengthen the budget."""
        monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_WALL_CLOCK_BUDGET_SEC", "60")
        assert get_llm_request_wall_clock_budget() == 60.0

    def test_zero_disables_the_budget(self, monkeypatch):
        """Zero must disable the check instead of raising immediately."""
        monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_WALL_CLOCK_BUDGET_SEC", "0")
        assert get_llm_request_wall_clock_budget() == 0.0

    def test_negative_budget_falls_back_to_the_default(self, monkeypatch):
        """A negative budget would raise on the first attempt."""
        monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_WALL_CLOCK_BUDGET_SEC", "-5")
        assert get_llm_request_wall_clock_budget() == 1800.0

    def test_invalid_budget_falls_back_to_the_default(self, monkeypatch):
        """A non-numeric value must not disable the budget."""
        monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_WALL_CLOCK_BUDGET_SEC", "soon")
        assert get_llm_request_wall_clock_budget() == 1800.0

    def test_boolean_value_falls_back_to_the_default(self):
        """A boolean reader value must not be treated as a number."""
        reader = MagicMock()
        reader.get.return_value = True
        assert get_llm_request_wall_clock_budget(reader) == 1800.0

    def test_fractional_budget_is_accepted(self, monkeypatch):
        """A sub-second budget is legal for tests and short probes."""
        monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_WALL_CLOCK_BUDGET_SEC", "0.5")
        assert get_llm_request_wall_clock_budget() == 0.5


class TestBudgetCheck:
    """The check raises only after the budget is actually spent."""

    def test_check_returns_while_the_budget_remains(self, monkeypatch):
        """A request inside its budget keeps running."""
        model = _make_model()
        monkeypatch.setattr(
            "topsailai.ai_base.llm_base.time.monotonic", lambda: 1000.0
        )
        LLMModel._check_request_wall_clock_budget(model, 1000.0, 1800.0, 3)

    def test_check_raises_after_the_budget_is_spent(self, monkeypatch):
        """A request past its budget stops instead of resending."""
        model = _make_model()
        monkeypatch.setattr(
            "topsailai.ai_base.llm_base.time.monotonic", lambda: 3000.0
        )
        with pytest.raises(LLMRequestTimeoutError) as exc_info:
            LLMModel._check_request_wall_clock_budget(model, 1000.0, 1800.0, 12)

        message = str(exc_info.value)
        assert "wall-clock budget" in message
        assert "2000.0s" in message
        assert "11 attempts" in message

    def test_zero_budget_disables_the_check(self, monkeypatch):
        """A disabled budget must never raise, however long the request ran."""
        model = _make_model()
        monkeypatch.setattr(
            "topsailai.ai_base.llm_base.time.monotonic", lambda: 999999.0
        )
        LLMModel._check_request_wall_clock_budget(model, 0.0, 0.0, 50)

    def test_none_budget_disables_the_check(self):
        """A missing budget must not raise."""
        model = _make_model()
        LLMModel._check_request_wall_clock_budget(model, 0.0, None, 50)


class TestRetryLoopWiring:
    """The retry loop must stop on the budget error, not retry it."""

    @staticmethod
    def _llm_base_source():
        """Return the source text of ai_base/llm_base.py."""
        import topsailai.ai_base.llm_base as llm_base_module

        return Path(llm_base_module.__file__).read_text(encoding="utf-8")

    def test_specialized_handler_precedes_the_generic_handler(self):
        """A subclass caught by the parent branch would retry forever."""
        source = self._llm_base_source()
        specialized = source.index("except LLMRequestTimeoutError")
        generic = source.index("except ModelServiceError as e:")
        assert specialized < generic

    def test_specialized_handler_reraises(self):
        """The handler must propagate instead of sleeping and continuing."""
        source = self._llm_base_source()
        start = source.index("except LLMRequestTimeoutError")
        end = source.index("except ModelServiceError as e:", start)
        handler_body = source[start:end]
        assert "raise" in handler_body
        assert "continue" not in handler_body

    def test_budget_is_read_once_per_request(self):
        """Every attempt of one request must share one budget value."""
        source = self._llm_base_source()
        assert source.count("self._get_request_wall_clock_budget()") == 1

    def test_budget_is_read_before_the_attempt_loop(self):
        """The budget must exist before the first attempt starts."""
        source = self._llm_base_source()
        budget_read = source.index("self._get_request_wall_clock_budget()")
        attempt_loop = source.index("for total_attempt in range(")
        assert budget_read < attempt_loop

    def test_check_runs_inside_the_attempt_loop(self):
        """The check must be reached by every attempt, not once per request."""
        source = self._llm_base_source()
        attempt_loop = source.index("for total_attempt in range(")
        check_call = source.index("self._check_request_wall_clock_budget(")
        assert check_call > attempt_loop

    def test_check_runs_before_the_backoff_sleep(self):
        """A stalled request must not pay another sleep before stopping."""
        source = self._llm_base_source()
        check_call = source.index("self._check_request_wall_clock_budget(")
        backoff_sleep = source.index("time.sleep(sec)")
        assert check_call < backoff_sleep

    def test_specialized_error_is_imported_by_the_retry_module(self):
        """The handler cannot reference a name the module never imported."""
        source = self._llm_base_source()
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported.add(alias.asname or alias.name)
        assert "LLMRequestTimeoutError" in imported

    def test_budget_helper_is_imported_by_the_retry_module(self):
        """The wrapper cannot call a helper the module never imported."""
        source = self._llm_base_source()
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported.add(alias.asname or alias.name)
        assert "_get_llm_request_wall_clock_budget" in imported
