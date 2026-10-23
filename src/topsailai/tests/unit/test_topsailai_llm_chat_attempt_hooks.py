"""Chat-attempt integration contracts. Author: DawsonLin."""

import asyncio
import re
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import topsailai.ai_base.llm_base as llm
import topsailai.hooks as hooks
from topsailai.ai_base.exception import HardInterruptError, LLMRetryExhaustedError
from topsailai.ai_base.llm_control.control_runtime import LLMRequestedRetryError
from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy


@pytest.fixture
def case(monkeypatch):
    """Keep execution local while retaining real chat retry/return orchestration."""
    model = object.__new__(llm.LLMModel)
    model.tokenStat = SimpleNamespace(current_tokens=0, current_cached_tokens=0)
    model.model_config = {"api_key": "private"}
    model._get_pending_native_tool_call_responses = lambda: deque()
    model._split_native_tool_call_response = lambda obj, content: (obj, content, 1, 1)
    model._return_chat_response = MagicMock(return_value=object())
    model._is_special_response_for_retry = lambda error: False
    model.call_llm_model = MagicMock(return_value=(object(), "ok"))
    model.call_llm_model_by_stream = model.call_llm_model
    events, sleeps = [], []
    monkeypatch.setattr(llm, "time", SimpleNamespace(monotonic=time.monotonic, sleep=sleeps.append))
    monkeypatch.setattr(llm, "get_agent_object", lambda: None)
    for phase in ("before", "after", "error"):
        def record(_phase=phase, **metadata):
            """Capture the exact direct-call kwargs in emission order."""
            events.append((_phase, metadata))
        monkeypatch.setattr(llm, f"hook__aibase__{phase}__llm_chat_attempt", record)
    return SimpleNamespace(model=model, events=events, sleeps=sleeps)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("raw,response,mode", [(True, True, "raw"), (False, False, "parsed"),
                                              (False, True, "response_and_parsed")])
def test_success_modes(case, stream, raw, response, mode):
    """After observes the fully selected result, once, with correct runtime flags."""
    result = case.model.chat([], for_raw=raw, for_response=response, for_stream=stream)
    assert result == "ok" if raw else result is case.model._return_chat_response.return_value
    assert [phase for phase, _ in case.events] == ["before", "after"]
    before, after = [payload for _, payload in case.events]
    assert before["operation_id"] == after["operation_id"]
    assert re.fullmatch("[0-9a-f]{32}", before["operation_id"])
    assert before["attempt_number"] == 1 and before["loop_attempts"] == 18
    assert before["stream"] is stream and before["return_mode"] == mode
    assert after["duration_sec"] >= 0


def test_retry_and_parse_failure(case):
    """Parsing failure is error, never after; ordinals and operation stay stable."""
    failure = TypeError("parse failure")
    case.model._return_chat_response.side_effect = [failure, "parsed"]
    assert case.model.chat([]) == "parsed"
    assert [p for p, _ in case.events] == ["before", "error", "before", "after"]
    assert [v["attempt_number"] for _, v in case.events] == [1, 1, 2, 2]
    assert len({v["operation_id"] for _, v in case.events}) == 1
    assert case.events[1][1]["error_category"] == "TypeError"
    assert case.sleeps == [5]


def test_exhaustion_identity_and_limit(case):
    """All 18 failures are terminal once and exhaustion retains the original cause."""
    error = TypeError("parameter build failure")
    case.model.call_llm_model.side_effect = error
    with pytest.raises(LLMRetryExhaustedError) as caught:
        case.model.chat([], for_raw=True)
    assert caught.value.__cause__ is error
    assert [p for p, _ in case.events] == ["before", "error"] * 18
    assert [v["attempt_number"] for p, v in case.events if p == "error"] == list(range(1, 19))
    assert case.sleeps == list(range(5, 90, 5))


def test_manual_cycle_ordinals(case, monkeypatch):
    """Manual cycles continue the same operation and ordinal, not a new chat."""
    case.model.call_llm_model.side_effect = [TypeError("retry")] * 18 + [(object(), "ok")]
    monkeypatch.setattr(llm, "_read_retry_exhaustion_action", lambda *a, **k: "retry")
    policy = LLMRetryInteractionPolicy(interactive_enabled=True, input_func=lambda _: "yes",
                                       max_manual_retry_cycles=1)
    assert case.model.chat([], for_raw=True, retry_interaction_policy=policy) == "ok"
    assert case.events[-1][1]["attempt_number"] == 19
    assert case.events[-1][1]["loop_attempts"] == 36
    assert len({v["operation_id"] for _, v in case.events}) == 1


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(), asyncio.CancelledError(),
                                  HardInterruptError("stop")])
def test_business_control_identity(case, error):
    """Host/domain interrupts bypass ordinary-error observation and keep identity."""
    case.model.call_llm_model.side_effect = error
    with pytest.raises(type(error)) as caught:
        case.model.chat([], for_raw=True)
    assert caught.value is error
    assert [p for p, _ in case.events] == ["before"]


def test_requested_retry_is_control(case):
    """A requested retry does not fabricate an ordinary error terminal."""
    case.model.call_llm_model.side_effect = [LLMRequestedRetryError(), (object(), "ok")]
    assert case.model.chat([], for_raw=True) == "ok"
    assert [p for p, _ in case.events] == ["before", "before", "after"]


def test_pending_and_unique_calls(case):
    """Pending native responses skip attempts; independent chats get unique IDs."""
    case.model.chat([], for_raw=True)
    first = case.events[0][1]["operation_id"]
    case.events.clear()
    case.model.chat([], for_raw=True)
    assert case.events[0][1]["operation_id"] != first
    case.events.clear()
    pending = deque([(object(), "queued", 2, 2)])
    case.model._get_pending_native_tool_call_responses = lambda: pending
    case.model.chat([], for_raw=True)
    assert not case.events


@pytest.mark.parametrize("phase", ["before", "after", "error"])
@pytest.mark.parametrize("control", [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
def test_real_plugin_control_identity(case, monkeypatch, tmp_path, phase, control):
    """Real point dispatch must propagate host controls from every checkpoint."""
    from importlib import import_module
    entry = import_module(f"topsailai.hooks.points.aibase.{phase}_llm_chat_attempt")
    monkeypatch.setattr(llm, entry.NAME, getattr(entry, entry.NAME))
    monkeypatch.setattr(hooks, "_point_configuration", ())
    plugin = tmp_path / "interrupt.py"
    plugin.write_text("def main(**kwargs):\n    import builtins\n    raise builtins._attempt_control\n")
    error = control()
    import builtins
    monkeypatch.setattr(builtins, "_attempt_control", error, raising=False)
    hooks.initialize_hook_points({entry.NAME: {"modules": str(plugin)}})
    if phase == "error":
        case.model.call_llm_model.side_effect = TypeError("failed")
    with pytest.raises(control) as caught:
        case.model.chat([], for_raw=True)
    assert caught.value is error
    assert case.model.call_llm_model.call_count == (0 if phase == "before" else 1)


def test_native_split_success(case):
    """A split native response completes its initial request attempt only once."""
    case.model._split_native_tool_call_response = lambda obj, content: (obj, content, 1, 2)
    result = case.model.chat([])
    assert result is case.model._return_chat_response.return_value
    assert [phase for phase, _ in case.events] == ["before", "after"]


@pytest.mark.parametrize("phase", ["after", "error"])
def test_interactive_hook_interrupt_never_prompts(case, monkeypatch, phase):
    """Hook interrupts bypass the existing business interactive retry handler."""
    error = KeyboardInterrupt()

    def interrupt(**metadata):
        """Raise the original host interruption at the terminal observation."""
        raise error

    monkeypatch.setattr(llm, f"hook__aibase__{phase}__llm_chat_attempt", interrupt)
    prompt = MagicMock(side_effect=AssertionError("must not prompt"))
    monkeypatch.setattr(llm, "input_yes_or_no", prompt)
    if phase == "error":
        case.model.call_llm_model.side_effect = TypeError("failed")
    policy = LLMRetryInteractionPolicy(interactive_enabled=True, input_func=lambda _: "yes")
    with pytest.raises(KeyboardInterrupt) as caught:
        case.model.chat([], for_raw=True, retry_interaction_policy=policy)
    assert caught.value is error
    assert case.model.call_llm_model.call_count == 1
    prompt.assert_not_called()


def test_interactive_business_interrupt_retains_retry(case, monkeypatch):
    """Business KeyboardInterrupt retains its existing explicit retry choice."""
    case.model.call_llm_model.side_effect = [KeyboardInterrupt(), (object(), "ok")]
    prompt = MagicMock(return_value=True)
    monkeypatch.setattr(llm, "input_yes_or_no", prompt)
    policy = LLMRetryInteractionPolicy(interactive_enabled=True, input_func=lambda _: "yes")
    assert case.model.chat([], for_raw=True, retry_interaction_policy=policy) == "ok"
    prompt.assert_called_once()
    assert case.model.call_llm_model.call_count == 2
    assert [phase for phase, _ in case.events] == ["before", "before", "after"]
