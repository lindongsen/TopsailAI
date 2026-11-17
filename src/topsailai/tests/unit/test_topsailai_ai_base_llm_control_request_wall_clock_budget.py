"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-16
Purpose: Unit tests for the per-request LLM wall-clock budget.
"""

import ast
from collections import deque
from pathlib import Path
from types import SimpleNamespace
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
from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy


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


class _FakeClock:
    """Advance monotonic time only when the test decides to."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        """Return the current fake monotonic time."""
        return self.now

    def sleep(self, sec):
        """Record a backoff sleep without advancing the clock."""
        self.sleeps.append(sec)


def _make_retry_model(monkeypatch, clock, budget):
    """Build a bare model that drives the real retry loop under a fake clock."""
    model = object.__new__(LLMModel)
    model.tokenStat = SimpleNamespace(current_tokens=0, current_cached_tokens=0)
    model.model_config = {"api_key": "private"}
    model._get_pending_native_tool_call_responses = lambda: deque()
    model._split_native_tool_call_response = lambda obj, content: (obj, content, 1, 1)
    model._return_chat_response = MagicMock(return_value="parsed")
    model._is_special_response_for_retry = lambda error: False
    model.call_llm_model = MagicMock(return_value=(object(), "ok"))
    model.call_llm_model_by_stream = model.call_llm_model
    model._get_request_wall_clock_budget = lambda: budget

    monkeypatch.setattr(
        "topsailai.ai_base.llm_base.time",
        SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep),
    )
    monkeypatch.setattr("topsailai.ai_base.llm_base.get_agent_object", lambda: None)
    monkeypatch.setattr("topsailai.ai_base.llm_base.print_error", lambda *a, **k: None)
    monkeypatch.setattr("topsailai.ai_base.llm_base.print_warning", lambda *a, **k: None)
    monkeypatch.setattr(
        "topsailai.ai_base.llm_base._record_llm_request_event", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "topsailai.ai_base.llm_base._observe_llm_request_attempt", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "topsailai.ai_base.llm_base._record_llm_request_failure", lambda *a, **k: None,
    )
    for phase in ("before", "after", "error"):
        monkeypatch.setattr(
            f"topsailai.ai_base.llm_base.hook__aibase__{phase}__llm_chat_attempt",
            lambda *a, **k: None,
        )
    return model


class TestHumanDecisionIsNotChargedToTheBudget:
    """A human decision restarts the budget instead of consuming it."""

    def test_human_decision_time_does_not_exhaust_the_budget(self, monkeypatch):
        """A retry the human just authorized must not be rejected by their own wait.

        The operator can leave the retry-exhaustion prompt unanswered for hours.
        Charging that wait to the request rejects the very retry they approved,
        so the baseline must restart when the decision arrives. The attempt that
        follows the decision must therefore still be allowed to run.
        """
        clock = _FakeClock()
        model = _make_retry_model(monkeypatch, clock, budget=100.0)
        # Attempt 19 is the first attempt after the decision, so it must fail to
        # reach attempt 20, which is the first attempt measured from the new
        # baseline. Without the reset, attempt 20 is rejected by the human's wait.
        model.call_llm_model.side_effect = [TypeError("cycle one")] * 19 + [
            (object(), "ok")
        ]

        def decide(_policy, *, allow_retry, warning_func):
            """Simulate a human who answers after nearly three hours."""
            clock.now += 10000.0
            return "retry"

        monkeypatch.setattr(
            "topsailai.ai_base.llm_base._read_retry_exhaustion_action", decide,
        )
        policy = LLMRetryInteractionPolicy(
            interactive_enabled=True,
            input_func=lambda _: "yes",
            max_manual_retry_cycles=1,
        )

        result = model.chat([], for_raw=True, retry_interaction_policy=policy)

        assert result == "ok"
        assert model.call_llm_model.call_count == 20

    def test_budget_baseline_restarts_at_the_decision(self, monkeypatch):
        """The post-decision attempt must be measured from the decision instant."""
        clock = _FakeClock()
        model = _make_retry_model(monkeypatch, clock, budget=100.0)
        model.call_llm_model.side_effect = [TypeError("cycle one")] * 19 + [
            (object(), "ok")
        ]
        baselines = []
        real_check = LLMModel._check_request_wall_clock_budget

        def spy(instance, started_at, budget, attempt_number):
            """Record the baseline each attempt is measured from."""
            baselines.append((attempt_number, started_at))
            return real_check(instance, started_at, budget, attempt_number)

        monkeypatch.setattr(LLMModel, "_check_request_wall_clock_budget", spy)

        def decide(_policy, *, allow_retry, warning_func):
            """Simulate a human who answers after nearly three hours."""
            clock.now += 10000.0
            return "retry"

        monkeypatch.setattr(
            "topsailai.ai_base.llm_base._read_retry_exhaustion_action", decide,
        )
        policy = LLMRetryInteractionPolicy(
            interactive_enabled=True,
            input_func=lambda _: "yes",
            max_manual_retry_cycles=1,
        )

        model.chat([], for_raw=True, retry_interaction_policy=policy)

        # Attempt 20 is the first attempt after the decision, so it must be
        # measured from the decision instant rather than from request start.
        assert (20, 10000.0) in baselines
        assert (20, 0.0) not in baselines

    def test_budget_still_bounds_provider_work(self, monkeypatch):
        """Without a human decision the budget must still stop a stalled request."""
        clock = _FakeClock()
        model = _make_retry_model(monkeypatch, clock, budget=100.0)

        def slow_failure(*_args, **_kwargs):
            """Fail slowly so the accumulated provider work exceeds the budget."""
            clock.now += 60.0
            raise TypeError("slow failure")

        model.call_llm_model.side_effect = slow_failure

        with pytest.raises(LLMRequestTimeoutError):
            model.chat([], for_raw=True)

        # Attempt 1 starts at 0s, attempt 2 at 60s, attempt 3 at 120s > 100s.
        assert model.call_llm_model.call_count == 2


class TestBudgetBaselineWiring:
    """The retry loop must measure the budget from its own resettable baseline."""

    @staticmethod
    def _llm_base_source():
        """Return the source text of ai_base/llm_base.py."""
        import topsailai.ai_base.llm_base as llm_base_module

        return Path(llm_base_module.__file__).read_text(encoding="utf-8")

    def test_check_uses_the_resettable_baseline(self):
        """The check must not read the telemetry timestamp directly."""
        source = self._llm_base_source()
        check = source.index("self._check_request_wall_clock_budget(")
        call = source[check:check + 200]
        assert "budget_started_at, request_wall_clock_budget" in call
        assert "request_started_at, request_wall_clock_budget" not in call

    def test_baseline_restarts_between_the_decision_and_the_retry_branch(self):
        """The reset must land after the prompt and before the retry branch."""
        source = self._llm_base_source()
        prompt = source.index("action = _read_retry_exhaustion_action(")
        reset = source.index("budget_started_at = time.monotonic()", prompt)
        retry_branch = source.index('if action == "retry":', prompt)
        assert prompt < reset < retry_branch
