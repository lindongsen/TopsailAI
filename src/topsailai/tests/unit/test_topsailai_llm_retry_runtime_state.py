"""Tests for request-scoped LLM retry Runtime Data publication."""

import threading
from types import SimpleNamespace

import pytest

from topsailai.ai_base.llm_control.configuration import (
    get_llm_request_retry_state_threshold,
)
from topsailai.ai_base.llm_control.retry_runtime_state import (
    RUNTIME_STATE_KEY,
    bind_retry_runtime_operation,
    current_retry_runtime_state,
    observe_retry_attempt_error,
    track_retry_runtime_state,
)
from topsailai.ai_base.exception import (
    HardInterruptError,
    LLMBackToChatError,
    LLMRetryExhaustedError,
)
from topsailai.ai_base.runtime_data import RuntimeDataStore
from topsailai.hooks.points.aibase.error_llm_chat_attempt.modules import (
    publish_retry_runtime_state,
)
from topsailai.utils.thread_local_tool import ctxm_set_agent


class _Subject:
    """Expose decorated request bodies for focused lifecycle tests."""

    @track_retry_runtime_state
    def chat(self, behavior):
        """Bind the default operation and execute the request behavior."""
        bind_retry_runtime_operation("operation-1")
        return behavior()

    @track_retry_runtime_state
    def chat_operation(self, operation_id, behavior):
        """Bind a caller-selected operation and execute its request behavior."""
        bind_retry_runtime_operation(operation_id)
        return behavior()


def _agent(store=None):
    """Build the minimal current-Agent shape consumed by the decorator."""
    return SimpleNamespace(
        runtime=SimpleNamespace(runtime_data=store or RuntimeDataStore())
    )


def _publish(category="LLMProviderTimeoutError"):
    """Publish one failed attempt for the bound test operation."""
    return observe_retry_attempt_error("operation-1", category)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 3),
        ("", 3),
        ("3", 3),
        ("1", 1),
        ("0", 0),
        ("-1", 3),
        ("invalid", 3),
    ],
)
def test_retry_state_threshold_configuration(monkeypatch, value, expected):
    """Threshold parsing follows the documented request configuration contract."""
    key = "TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD"
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)

    assert get_llm_request_retry_state_threshold() == expected


def test_third_failure_activates_and_later_failure_updates_one_state(monkeypatch):
    """The approved threshold activates at three and reuses one generation."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "3")
    agent = _agent()
    observed = {}

    def behavior():
        assert _publish() is False
        assert _publish() is False
        assert agent.runtime.runtime_data.snapshot() == ()
        assert _publish() is True
        activated = agent.runtime.runtime_data.get(RUNTIME_STATE_KEY)
        assert activated is not None
        assert _publish("LLMProviderReadError") is True
        assert _publish("LLMProviderReadError") is True
        updated = agent.runtime.runtime_data.get(RUNTIME_STATE_KEY)
        observed.update(activated=activated, updated=updated)
        return "success"

    with ctxm_set_agent(agent):
        assert _Subject().chat(behavior) == "success"

    assert observed["activated"].value["failed_attempts"] == 3
    assert observed["updated"].value == {
        "phase": "fault_retrying",
        "failed_attempts": 5,
        "next_retry_number": 6,
        "threshold": 3,
        "last_error_category": "LLMProviderReadError",
    }
    assert observed["updated"].revision == 3
    assert agent.runtime.runtime_data.snapshot() == ()
    history = agent.runtime.runtime_data.history(RUNTIME_STATE_KEY)
    assert len(history) == 1
    assert history[0].outcome == "recovered"
    assert history[0].value["failed_attempts"] == 5


def test_request_below_threshold_has_no_history(monkeypatch):
    """A request that settles before activation leaves no state record."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "3")
    agent = _agent()

    with ctxm_set_agent(agent):
        assert _Subject().chat(lambda: (_publish(), _publish())) == (False, False)

    assert agent.runtime.runtime_data.snapshot() == ()
    assert agent.runtime.runtime_data.history() == ()


def test_zero_threshold_disables_publication(monkeypatch):
    """Threshold zero disables both active state and settled history."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "0")
    agent = _agent()

    with ctxm_set_agent(agent):
        assert _Subject().chat(lambda: _publish()) is False

    assert agent.runtime.runtime_data.snapshot() == ()
    assert agent.runtime.runtime_data.history() == ()


def test_threshold_is_frozen_for_one_request(monkeypatch):
    """An environment change affects only the next complete request."""
    key = "TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD"
    monkeypatch.setenv(key, "3")
    agent = _agent()

    def first_request():
        monkeypatch.setenv(key, "1")
        assert _publish() is False
        assert _publish() is False
        assert _publish() is True

    with ctxm_set_agent(agent):
        _Subject().chat(first_request)
        assert _Subject().chat(lambda: _publish()) is True

    history = agent.runtime.runtime_data.history(RUNTIME_STATE_KEY)
    assert [item.value["threshold"] for item in history] == [3, 1]


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (RuntimeError("failed"), "failed"),
        (KeyboardInterrupt(), "interrupted"),
    ],
)
def test_exception_settles_state_without_replacing_error(monkeypatch, error, outcome):
    """Failure and interruption preserve the original exception and settle state."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")
    agent = _agent()

    def behavior():
        assert _publish() is True
        raise error

    with ctxm_set_agent(agent):
        with pytest.raises(type(error)) as caught:
            _Subject().chat(behavior)

    assert caught.value is error
    assert agent.runtime.runtime_data.snapshot() == ()
    assert agent.runtime.runtime_data.history()[0].outcome == outcome


def test_missing_agent_runtime_keeps_request_result(monkeypatch):
    """Direct LLM use has no process-global Store and retains its result."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")

    def behavior():
        assert _publish() is False
        return "direct-result"

    assert _Subject().chat(behavior) == "direct-result"
    assert current_retry_runtime_state() is None


def test_different_operation_cannot_publish(monkeypatch):
    """A stale Hook event cannot mutate another request's Store."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")
    agent = _agent()

    def behavior():
        return observe_retry_attempt_error("operation-2", "Error")

    with ctxm_set_agent(agent):
        assert _Subject().chat(behavior) is False

    assert agent.runtime.runtime_data.snapshot() == ()
    assert agent.runtime.runtime_data.history() == ()


def test_hook_module_forwards_validated_attempt_metadata(monkeypatch):
    """The bundled error Hook module publishes the attempt count and category."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")
    agent = _agent()
    seen = {}

    def behavior():
        assert publish_retry_runtime_state.main(
            operation_id="operation-1",
            attempt_number=1,
            error_category="LLMNullResponseError",
        ) is True
        seen["state"] = agent.runtime.runtime_data.get(RUNTIME_STATE_KEY)

    with ctxm_set_agent(agent):
        _Subject().chat(behavior)

    assert seen["state"].value["last_error_category"] == "LLMNullResponseError"


def test_history_capacity_bounds_completed_retry_requests(monkeypatch):
    """Repeated requests cannot grow retry-state history without a limit."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")
    store = RuntimeDataStore(history_capacity=2)
    agent = _agent(store)

    with ctxm_set_agent(agent):
        for _ in range(4):
            _Subject().chat(lambda: _publish())

    assert len(store.history(RUNTIME_STATE_KEY)) == 2


def test_activation_failure_does_not_change_request_result(monkeypatch, caplog):
    """Observability failure is bounded and cannot fail the LLM request."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")

    class FailingStore(RuntimeDataStore):
        """Fail the producer's first publication without exposing request data."""

        def activate(self, *args, **kwargs):
            raise RuntimeError("secret exception detail")

    agent = _agent(FailingStore())

    with ctxm_set_agent(agent):
        assert _Subject().chat(lambda: _publish()) is False

    text = caplog.text
    assert "RuntimeError" in text
    assert "secret exception detail" not in text
    assert agent.runtime.runtime_data.snapshot() == ()


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (
            LLMBackToChatError(
                attempts=3,
                last_error=RuntimeError("provider failed"),
            ),
            "abandoned",
        ),
        (HardInterruptError("stop"), "interrupted"),
        (
            LLMRetryExhaustedError(
                attempts=18,
                last_error=RuntimeError("provider failed"),
                explicit_exit=True,
            ),
            "failed",
        ),
    ],
)
def test_control_flow_exit_settles_with_bounded_outcome(monkeypatch, error, outcome):
    """Back, interruption, and explicit exit keep their original contracts."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")
    agent = _agent()

    def behavior():
        assert _publish() is True
        raise error

    with ctxm_set_agent(agent):
        with pytest.raises(type(error)) as caught:
            _Subject().chat(behavior)

    assert caught.value is error
    if isinstance(error, LLMRetryExhaustedError):
        assert caught.value.explicit_exit is True
    assert agent.runtime.runtime_data.snapshot() == ()
    assert agent.runtime.runtime_data.history()[0].outcome == outcome


def test_update_failure_disables_further_publication_without_failing_request(
    monkeypatch,
    caplog,
):
    """An update failure stops observability work but preserves the LLM result."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")

    class FailingUpdateStore(RuntimeDataStore):
        """Fail only the first update after successful activation."""

        def __init__(self):
            super().__init__()
            self.update_calls = 0

        def update(self, *args, **kwargs):
            self.update_calls += 1
            raise RuntimeError("secret update detail")

    store = FailingUpdateStore()
    agent = _agent(store)

    def behavior():
        assert _publish() is True
        assert _publish() is False
        assert _publish() is False
        return "success"

    with ctxm_set_agent(agent):
        assert _Subject().chat(behavior) == "success"

    assert store.update_calls == 1
    assert store.snapshot() == ()
    history = store.history(RUNTIME_STATE_KEY)
    assert len(history) == 1
    assert history[0].outcome == "recovered"
    assert history[0].value["failed_attempts"] == 1
    assert "RuntimeError" in caplog.text
    assert "secret update detail" not in caplog.text


def test_settlement_failure_does_not_replace_success_or_original_error(
    monkeypatch,
    caplog,
):
    """Settlement failure remains secondary to both result and request error."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")

    class FailingSettlementStore(RuntimeDataStore):
        """Retain active state while simulating settlement storage failure."""

        def deactivate(self, *args, **kwargs):
            raise RuntimeError("secret settlement detail")

    success_store = FailingSettlementStore()
    with ctxm_set_agent(_agent(success_store)):
        assert _Subject().chat(lambda: (_publish(), "success")[1]) == "success"

    original = RuntimeError("request failed")
    failure_store = FailingSettlementStore()

    def fail_request():
        assert _publish() is True
        raise original

    with ctxm_set_agent(_agent(failure_store)):
        with pytest.raises(RuntimeError) as caught:
            _Subject().chat(fail_request)

    assert caught.value is original
    assert len(success_store.snapshot()) == 1
    assert len(failure_store.snapshot()) == 1
    assert "RuntimeError" in caplog.text
    assert "secret settlement detail" not in caplog.text


def test_store_deactivation_is_idempotent_after_request_settlement(monkeypatch):
    """A repeated cleanup attempt cannot duplicate history or change settlement."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")
    store = RuntimeDataStore()
    agent = _agent(store)
    captured = {}

    def behavior():
        assert _publish() is True
        captured["lease"] = current_retry_runtime_state().lease
        return "success"

    with ctxm_set_agent(agent):
        assert _Subject().chat(behavior) == "success"

    assert store.deactivate(captured["lease"], outcome="failed") is False
    assert len(store.history(RUNTIME_STATE_KEY)) == 1
    assert store.history(RUNTIME_STATE_KEY)[0].outcome == "recovered"


def test_independent_agents_keep_retry_state_isolated(monkeypatch):
    """One Agent's retry state and history never appear in another Agent."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")
    first = _agent()
    second = _agent()
    observed = {}

    def first_behavior():
        assert _publish() is True
        observed["first"] = first.runtime.runtime_data.get(RUNTIME_STATE_KEY)
        observed["second"] = second.runtime.runtime_data.get(RUNTIME_STATE_KEY)

    with ctxm_set_agent(first):
        _Subject().chat(first_behavior)

    assert observed["first"] is not None
    assert observed["second"] is None
    assert len(first.runtime.runtime_data.history(RUNTIME_STATE_KEY)) == 1
    assert second.runtime.runtime_data.history(RUNTIME_STATE_KEY) == ()


def test_same_agent_overlapping_retry_owner_is_rejected_without_corruption(
    monkeypatch,
):
    """A second concurrent owner cannot overwrite or clean the first state."""
    monkeypatch.setenv("TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD", "1")
    agent = _agent()
    subject = _Subject()
    first_active = threading.Event()
    release_first = threading.Event()
    first_result = {}
    second_result = {}

    def first_behavior():
        assert observe_retry_attempt_error("operation-a", "FirstError") is True
        first_result["active"] = agent.runtime.runtime_data.get(RUNTIME_STATE_KEY)
        first_active.set()
        assert release_first.wait(timeout=5)
        return "first"

    def run_first():
        with ctxm_set_agent(agent):
            first_result["result"] = subject.chat_operation(
                "operation-a",
                first_behavior,
            )

    first_thread = threading.Thread(target=run_first, name="runtime-owner-a")
    first_thread.start()
    assert first_active.wait(timeout=5)

    def second_behavior():
        second_result["published"] = observe_retry_attempt_error(
            "operation-b",
            "SecondError",
        )
        second_result["active"] = agent.runtime.runtime_data.get(RUNTIME_STATE_KEY)
        return "second"

    with ctxm_set_agent(agent):
        second_result["result"] = subject.chat_operation(
            "operation-b",
            second_behavior,
        )

    still_active = agent.runtime.runtime_data.get(RUNTIME_STATE_KEY)
    release_first.set()
    first_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert first_result["result"] == "first"
    assert second_result["result"] == "second"
    assert second_result["published"] is False
    assert first_result["active"].owner_id == "operation-a"
    assert second_result["active"].owner_id == "operation-a"
    assert still_active.owner_id == "operation-a"
    assert agent.runtime.runtime_data.snapshot() == ()
    history = agent.runtime.runtime_data.history(RUNTIME_STATE_KEY)
    assert len(history) == 1
    assert history[0].owner_id == "operation-a"
    assert history[0].outcome == "recovered"
