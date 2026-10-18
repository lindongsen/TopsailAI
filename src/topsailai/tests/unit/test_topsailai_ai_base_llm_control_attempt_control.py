"""Pure attempt arbitration tests. Author: DawsonLin."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier

import pytest

from topsailai.ai_base.llm_control.attempt_control import (
    AttemptControl, AttemptTarget, ControlProposal,
)


def target():
    """Build a detached test target."""
    return AttemptTarget("route", 1, "invocation", "attempt")


@pytest.mark.parametrize("field,value", [("binding_id", ""), ("attempt_id", []),
                                        ("invocation_id", "x" * 129), ("generation", True),
                                        ("generation", 0)])
def test_target_validation(field, value):
    """Malformed target components fail before registry access."""
    values = dict(binding_id="b", generation=1, invocation_id="i", attempt_id="a")
    values[field] = value
    with pytest.raises(ValueError):
        AttemptTarget(**values)


def test_immutable_and_proposal_validation():
    """References are typed and immutable; actions are a closed vocabulary."""
    with pytest.raises(FrozenInstanceError):
        target().generation = 2
    for args in ((None, "c", "force_retry"), (target(), "", "force_retry"),
                 (target(), "c", "restart"), (target(), "c", [])):
        with pytest.raises(ValueError):
            ControlProposal(*args)


@pytest.mark.parametrize("kwargs", [{"deadline": float("inf")}, {"deadline": True},
                                     {"retry_available": 1}, {"raise_timeout": None}])
def test_policy_validation(kwargs):
    """Malformed policy never becomes control authority."""
    with pytest.raises(ValueError):
        AttemptControl(target(), **kwargs)
    with pytest.raises(ValueError):
        AttemptControl(None)


@pytest.mark.parametrize("outcome", ["value", "eof", "error"])
def test_stream_creation_is_not_terminal(outcome):
    """Metadata-only records use the same value boundary as visible content."""
    authority = AttemptControl(target())
    assert authority.created()
    assert authority.snapshot().phase == "first_record"
    assert authority.publish(outcome)
    assert not authority.publish("value")
    assert not authority.created()
    assert authority.select("hard_interrupt") == "already_decided"
    assert authority.snapshot().outcome == outcome


def test_nonstream_and_deadline_precedence():
    """Publication at deadline equality loses; nonstream creation commits value."""
    authority = AttemptControl(target(), deadline=10, clock=lambda: 10)
    assert authority.select("hard_interrupt") == "already_decided"
    assert authority.snapshot().outcome == "timeout"
    assert not authority.publish("value")
    assert not authority.created()
    authority = AttemptControl(target())
    assert authority.created(streaming=False)
    assert authority.snapshot().outcome == "value"


@pytest.mark.parametrize("kwargs,operation,reason", [
    ({"interrupt_supported": False}, "hard_interrupt", "unsupported_exit_scope"),
    ({"retry_available": False}, "force_retry", "retry_budget_exhausted"),
    ({}, "force_retry", "cleanup_pending"),
])
def test_rejection_does_not_close_window(kwargs, operation, reason):
    """Policy rejection cannot consume a provider result."""
    authority = AttemptControl(target(), **kwargs)
    assert authority.select(operation, cleanup_pending=True) == reason
    assert authority.publish("value")


def test_warning_deadline_stays_open_and_bad_calls_reject():
    """Warning-only expiry does not prevent later controls."""
    authority = AttemptControl(target(), deadline=1, raise_timeout=False, clock=lambda: 2)
    assert authority.created()
    assert authority.select("hard_interrupt", cleanup_pending=True) == "accepted"
    for call in (lambda: authority.created(streaming=1), lambda: authority.publish("bad"),
                 lambda: authority.select("bad"), lambda: authority.select("force_retry", cleanup_pending=1)):
        with pytest.raises(ValueError):
            call()


@pytest.mark.parametrize("other", ["value", "eof", "error", "force_retry"])
def test_terminal_race_has_one_winner(other):
    """A deterministic barrier starts competing selectors with one outcome."""
    barrier = Barrier(2)
    authority = AttemptControl(target())

    def select(operation):
        """Race two domain terminal operations, not scheduling sleeps."""
        barrier.wait()
        return authority.select(operation) == "accepted" if operation in ("hard_interrupt", "force_retry") else authority.publish(operation)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(select, action) for action in ("hard_interrupt", other)]
        assert sum(future.result() for future in futures) == 1
