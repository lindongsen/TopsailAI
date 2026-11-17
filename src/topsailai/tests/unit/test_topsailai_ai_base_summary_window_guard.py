"""
Unit tests for the sliding-window summary guard.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-16
Purpose: Verify the bottom-line guard that terminates a turn when recent LLM
         traffic is dominated by summary requests, including the exact
         threshold boundary, window eviction, runtime configuration, the
         disabled state, and the re-raise chain that lets the exception reach
         the agent chat loop instead of being retried or swallowed
"""
import logging

import pytest

from topsailai.ai_base.exception import SummaryWindowLimitError
from topsailai.ai_base.llm_control.summary_window_guard import (
    SUMMARY_WINDOW_MAX_SUMMARIES_DEFAULT,
    SUMMARY_WINDOW_SIZE_DEFAULT,
    SummaryWindowGuard,
    get_agent_summary_window_guard,
    get_summary_window_max_summaries,
    get_summary_window_size,
)


class _EnvReader(object):
    """Minimal environment reader exposing the ``get`` contract."""

    def __init__(self, values=None):
        """Store the values this reader returns.

        Args:
            values (dict, optional): Mapping of name to raw value.
        """
        self._values = dict(values or {})

    def get(self, name, default=None):
        """Return the configured value or the supplied default."""
        return self._values.get(name, default)


def _guard(window_size=10, max_summaries=3):
    """Build a guard with explicit settings so tests never read the process env."""
    return SummaryWindowGuard(window_size=window_size, max_summaries=max_summaries)


def test_three_summaries_in_ten_requests_does_not_fire():
    """Exactly three summary requests inside the window must stay below the limit."""
    guard = _guard()
    sequence = [True, False, True, False, True] + [False] * 5

    results = [guard.record(is_summary) for is_summary in sequence]

    exceeded, summary_count, window_size, max_summaries = results[-1]
    assert exceeded is False
    assert summary_count == 3
    assert window_size == 10
    assert max_summaries == 3


def test_fourth_summary_in_ten_requests_fires():
    """The fourth summary request inside the window must trip the guard."""
    guard = _guard()

    results = [guard.record(True) for _ in range(4)]

    assert [item[0] for item in results] == [False, False, False, True]
    exceeded, summary_count, _, _ = results[-1]
    assert exceeded is True
    assert summary_count == 4


def test_alternating_summary_and_agent_requests_fires():
    """A summary on every other request reaches five per window and must fire."""
    guard = _guard()

    results = [
        guard.record(index % 2 == 0)
        for index in range(10)
    ]

    exceeded, summary_count, _, _ = results[-1]
    assert exceeded is True
    assert summary_count == 5


def test_window_evicts_oldest_request():
    """Ordinary traffic must push old summaries out of the window."""
    guard = _guard()
    for _ in range(3):
        guard.record(True)

    for _ in range(10):
        guard.record(False)

    assert guard.snapshot() == [False] * 10
    assert guard.record(False)[1] == 0


def test_window_keeps_only_the_configured_size():
    """The window must never retain more entries than its configured size."""
    guard = _guard(window_size=4)

    for _ in range(9):
        guard.record(False)

    assert len(guard.snapshot()) == 4


def test_zero_max_summaries_disables_the_guard():
    """A zero limit disables the guard, matching the project threshold convention."""
    guard = _guard(max_summaries=0)

    results = [guard.record(True) for _ in range(6)]

    assert all(item[0] is False for item in results)


def test_reset_clears_the_window():
    """Reset must drop every recorded request."""
    guard = _guard()
    for _ in range(4):
        guard.record(True)

    guard.reset()

    assert guard.snapshot() == []
    assert guard.record(True) == (False, 1, 10, 3)


def test_configuration_is_read_at_call_time():
    """Window settings must be re-read on every record call."""
    reader = _EnvReader({
        "TOPSAILAI_SUMMARY_WINDOW_SIZE": "4",
        "TOPSAILAI_SUMMARY_WINDOW_MAX_SUMMARIES": "1",
    })
    guard = SummaryWindowGuard(env_reader=reader)

    assert guard.record(True)[0] is False
    assert guard.record(True)[0] is True

    reader._values["TOPSAILAI_SUMMARY_WINDOW_MAX_SUMMARIES"] = "5"
    assert guard.record(True)[0] is False


def test_invalid_configuration_falls_back_to_defaults():
    """Invalid settings must fall back to the documented defaults."""
    reader = _EnvReader({
        "TOPSAILAI_SUMMARY_WINDOW_SIZE": "not-a-number",
        "TOPSAILAI_SUMMARY_WINDOW_MAX_SUMMARIES": "-2",
    })

    assert get_summary_window_size(reader) == SUMMARY_WINDOW_SIZE_DEFAULT
    assert (
        get_summary_window_max_summaries(reader)
        == SUMMARY_WINDOW_MAX_SUMMARIES_DEFAULT
    )


def test_non_positive_window_size_falls_back_to_default():
    """A zero or negative window size cannot describe a window."""
    reader = _EnvReader({"TOPSAILAI_SUMMARY_WINDOW_SIZE": "0"})

    assert get_summary_window_size(reader) == SUMMARY_WINDOW_SIZE_DEFAULT


def test_guard_is_created_once_per_agent():
    """The same agent must reuse one guard so the window survives across models."""
    class _Agent(object):
        """Stand-in agent that owns the guard attribute."""

    agent = _Agent()

    first = get_agent_summary_window_guard(agent)
    second = get_agent_summary_window_guard(agent)

    assert first is second
    assert first is not None


def test_guard_is_absent_without_an_agent():
    """No agent means no window, so the guard must be skipped rather than crash."""
    assert get_agent_summary_window_guard(None) is None


def test_exception_is_a_control_flow_signal():
    """The exception must be a plain Exception subclass for the re-raise chain."""
    assert issubclass(SummaryWindowLimitError, Exception)
    assert not issubclass(SummaryWindowLimitError, (SystemExit, KeyboardInterrupt))


def test_summary_control_exceptions_include_the_new_signal():
    """Summary handlers must treat the new exception as a control signal."""
    from topsailai.hooks.points.context.summary_adapter import (
        SUMMARY_CONTROL_EXCEPTIONS,
    )

    assert SummaryWindowLimitError in SUMMARY_CONTROL_EXCEPTIONS


def test_prompt_base_reraises_the_new_signal():
    """A hook raising the new exception must not be swallowed as a hook failure."""
    from topsailai.ai_base.prompt_base import PromptBase

    class _Prompt(PromptBase):
        """Prompt stand-in whose only hook raises the control signal."""

        def __init__(self):
            """Register one failing hook without running the real constructor."""
            self.hooks_pre_chat = [self._raise]

        def _raise(self, _prompt):
            """Raise the control signal the way a summary hook would."""
            raise SummaryWindowLimitError("window exceeded")

    with pytest.raises(SummaryWindowLimitError):
        _Prompt().call_hooks_pre_chat()


def _fast_llm_stack():
    """Replace the provider seam so chat() never performs a network request.

    ``_chat_once`` does not exist on ``LLMModel``, so patching it with
    ``create=True`` only added an unused attribute while the real provider call
    still ran, which made the test depend on network access and retry sleeps.
    The production seam is ``call_llm_model`` / ``call_llm_model_by_stream``,
    plus the two response-shaping helpers used by the non-raw path.
    """
    from contextlib import ExitStack
    from unittest.mock import patch

    from topsailai.ai_base.llm_base import LLMModel

    stack = ExitStack()
    stack.enter_context(
        patch.object(LLMModel, "call_llm_model", return_value=(None, "ok"))
    )
    stack.enter_context(
        patch.object(
            LLMModel, "call_llm_model_by_stream", return_value=(None, "ok")
        )
    )
    stack.enter_context(
        patch.object(
            LLMModel,
            "_split_native_tool_call_response",
            return_value=(None, "ok", 1, 1),
        )
    )
    stack.enter_context(
        patch.object(LLMModel, "_return_chat_response", return_value="ok")
    )
    return stack


def test_guard_fires_through_a_real_chat_call():
    """A real chat() call must raise once the window is exceeded.

    This drives the production request boundary instead of inspecting source,
    so it proves the guard is wired in and that the retry loop re-raises the
    control signal instead of treating it as a retryable provider failure.
    """
    from unittest.mock import patch

    from topsailai.ai_base.llm_base import LLMModel

    class _Agent(object):
        """Minimal agent that owns the guard."""

    agent = _Agent()
    agent._summary_window_guard = SummaryWindowGuard(
        window_size=10, max_summaries=3
    )
    model = LLMModel()

    fired_at = None
    with _fast_llm_stack(), patch(
        "topsailai.ai_base.llm_base.get_agent_object", return_value=agent
    ):
        for index in range(6):
            try:
                model.chat([{"role": "user", "content": "hi"}], is_summary_request=True)
            except SummaryWindowLimitError as error:
                fired_at = (index, str(error))
                break

    assert fired_at is not None, "the guard never fired through chat()"
    index, message = fired_at
    assert index == 3, f"expected the 4th summary to fire, got index {index}"
    assert "4 summary requests" in message
    assert "last 10 LLM requests" in message
    assert agent._summary_window_guard.snapshot() == [True] * 4


def test_ordinary_requests_never_fire_through_chat():
    """Ordinary agent traffic must never trip the guard."""
    from unittest.mock import patch

    from topsailai.ai_base.llm_base import LLMModel

    class _Agent(object):
        """Minimal agent that owns the guard."""

    agent = _Agent()
    agent._summary_window_guard = SummaryWindowGuard(
        window_size=10, max_summaries=3
    )
    model = LLMModel()

    with _fast_llm_stack(), patch(
        "topsailai.ai_base.llm_base.get_agent_object", return_value=agent
    ):
        for _ in range(20):
            try:
                model.chat([{"role": "user", "content": "hi"}], for_response=True)
            except SummaryWindowLimitError:
                pytest.fail("ordinary traffic must never trip the guard")

    assert agent._summary_window_guard.snapshot() == [False] * 10


def test_guard_is_skipped_without_an_agent():
    """Without an agent there is no window, so chat() must not raise."""
    from unittest.mock import patch

    from topsailai.ai_base.llm_base import LLMModel

    model = LLMModel()

    with _fast_llm_stack(), patch(
        "topsailai.ai_base.llm_base.get_agent_object", return_value=None
    ):
        for _ in range(6):
            try:
                model.chat([{"role": "user", "content": "hi"}], is_summary_request=True)
            except SummaryWindowLimitError:
                pytest.fail("no agent means no window and no termination")


def _retrying_llm_stack(failures):
    """Make the provider seam fail a fixed number of times, then succeed.

    The retry loop treats an ordinary exception as a retryable provider
    failure, so this reproduces a real retry storm without any network access.

    Args:
        failures (int): Number of leading attempts that must fail.

    Returns:
        ExitStack: Active patches; use as a context manager.
    """
    from contextlib import ExitStack
    from unittest.mock import patch

    from topsailai.ai_base.llm_base import LLMModel

    state = {"remaining": failures}

    def _flaky(*_args, **_kwargs):
        """Fail while the budget lasts, then return a normal result."""
        if state["remaining"] > 0:
            state["remaining"] -= 1
            raise RuntimeError("transient provider failure")
        return (None, "ok")

    stack = ExitStack()
    stack.enter_context(patch.object(LLMModel, "call_llm_model", side_effect=_flaky))
    stack.enter_context(
        patch.object(LLMModel, "call_llm_model_by_stream", side_effect=_flaky)
    )
    stack.enter_context(
        patch.object(
            LLMModel,
            "_split_native_tool_call_response",
            return_value=(None, "ok", 1, 1),
        )
    )
    stack.enter_context(
        patch.object(LLMModel, "_return_chat_response", return_value="ok")
    )
    # Backoff sleeps would make the test slow and prove nothing about counting.
    stack.enter_context(patch("topsailai.ai_base.llm_base.time.sleep"))
    return stack


def test_one_logical_request_retried_twelve_times_fires_the_guard():
    """A single summary request retried twelve times must trip the guard.

    This is the exact shape of the incident that motivated attempt-level
    counting: one logical summary request retried twelve times and stalled for
    over an hour. Counting only the logical request recorded it once, so the
    window never exceeded the limit and the turn never ended.
    """
    from unittest.mock import patch

    from topsailai.ai_base.llm_base import LLMModel

    class _Agent(object):
        """Minimal agent that owns the guard."""

    agent = _Agent()
    agent._summary_window_guard = SummaryWindowGuard(
        window_size=10, max_summaries=3
    )
    model = LLMModel()

    with _retrying_llm_stack(failures=12), patch(
        "topsailai.ai_base.llm_base.get_agent_object", return_value=agent
    ):
        with pytest.raises(SummaryWindowLimitError) as excinfo:
            model.chat([{"role": "user", "content": "hi"}], is_summary_request=True)

    message = str(excinfo.value)
    assert "4 summary requests" in message
    assert "last 10 LLM requests" in message
    # Four attempts were recorded before the guard stopped the request, so the
    # window proves the retries were counted individually.
    assert agent._summary_window_guard.snapshot() == [True] * 4


def test_retries_of_ordinary_requests_never_fire_the_guard():
    """Retrying ordinary traffic must not be mistaken for summary traffic."""
    from unittest.mock import patch

    from topsailai.ai_base.llm_base import LLMModel

    class _Agent(object):
        """Minimal agent that owns the guard."""

    agent = _Agent()
    agent._summary_window_guard = SummaryWindowGuard(
        window_size=10, max_summaries=3
    )
    model = LLMModel()

    with _retrying_llm_stack(failures=12), patch(
        "topsailai.ai_base.llm_base.get_agent_object", return_value=agent
    ):
        try:
            model.chat([{"role": "user", "content": "hi"}], for_response=True)
        except SummaryWindowLimitError:
            pytest.fail("ordinary retries must never trip the guard")

    snapshot = agent._summary_window_guard.snapshot()
    assert snapshot == [False] * 10, snapshot


def test_attempt_level_window_evicts_older_attempts():
    """The window must slide over attempts, not over logical requests."""
    guard = _guard(window_size=4, max_summaries=1)

    # One summary attempt is tolerated; the second one exceeds the limit.
    assert guard.record(True)[0] is False
    assert guard.record(True)[0] is True
    # Ordinary attempts do not clear the limit until they evict both summary
    # attempts, which proves the window slides one attempt at a time.
    assert guard.record(False)[0] is True
    assert guard.record(False)[0] is True
    assert guard.snapshot() == [True, True, False, False]
    # The fifth attempt evicts the oldest summary attempt.
    assert guard.record(False)[0] is False
    assert guard.snapshot() == [True, False, False, False]
    # The sixth attempt evicts the last summary attempt.
    assert guard.record(False)[0] is False
    assert guard.snapshot() == [False, False, False, False]


def test_replacing_a_foreign_guard_attribute_is_logged(caplog):
    """A discarded non-guard attribute must leave a trace instead of vanishing."""
    class _Agent(object):
        """Stand-in agent holding a foreign object under the guard attribute."""

    agent = _Agent()
    agent._summary_window_guard = "not-a-guard"

    with caplog.at_level(logging.WARNING):
        guard = get_agent_summary_window_guard(agent)

    assert isinstance(guard, SummaryWindowGuard)
    assert agent._summary_window_guard is guard
    assert "replaced a non-guard attribute" in caplog.text
    assert "existing_type=str" in caplog.text
    assert "agent_type=_Agent" in caplog.text


def test_creating_a_missing_guard_attribute_is_not_logged(caplog):
    """First use on a clean agent is normal, so it must not warn."""
    class _Agent(object):
        """Stand-in agent without the guard attribute."""

    agent = _Agent()

    with caplog.at_level(logging.WARNING):
        guard = get_agent_summary_window_guard(agent)

    assert isinstance(guard, SummaryWindowGuard)
    assert "replaced a non-guard attribute" not in caplog.text


def test_an_existing_real_guard_is_reused_without_logging(caplog):
    """A real guard must be reused silently, otherwise every call would warn."""
    class _Agent(object):
        """Stand-in agent owning a real guard."""

    agent = _Agent()
    installed = SummaryWindowGuard(window_size=4, max_summaries=1)
    agent._summary_window_guard = installed

    with caplog.at_level(logging.WARNING):
        guard = get_agent_summary_window_guard(agent)

    assert guard is installed
    assert "replaced a non-guard attribute" not in caplog.text
