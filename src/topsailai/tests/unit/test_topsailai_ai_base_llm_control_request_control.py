"""Current-target admission and replay contracts. Author: DawsonLin."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from topsailai.ai_base.llm_control.attempt_control import AttemptTarget
from topsailai.ai_base.llm_control.request_control import RequestControl


def target(attempt="a"):
    """Build one exact route-owned target."""
    return AttemptTarget("binding", 1, "invocation", attempt)


def submit(service, current, command="command", operation="force_retry", **kwargs):
    """Submit through the route-scoped convenience boundary."""
    return service.submit_current("binding", 1, current, command, operation, **kwargs)


@pytest.mark.parametrize("state", ["queued", "accepted", "recovery", "applied", "rejected"])
def test_replay_original_target_across_states(state):
    """Retained history wins over new target, idle and capacity fallback."""
    service = RequestControl()
    a = target()
    service.bind(a)
    receipt = submit(service, a)
    proposal = receipt.proposal
    if state in ("accepted", "recovery", "applied"):
        service.select(a, proposal)
    if state in ("recovery", "applied"):
        service.applied(proposal)
    if state == "applied":
        service.settle(proposal)
    if state != "queued":
        service.retire(a)
    if state == "queued":
        current = a
    else:
        current = target("b")
        service.bind(current)
    original = service.status("command")
    assert original.state == state
    for current_target in (None, current):
        assert submit(service, current_target, capacity_unavailable=True) is original
    conflict = submit(service, current, operation="hard_interrupt")
    assert conflict.reason == "conflict"
    assert conflict.proposal.target == a
    assert service.status("command") is original
    if current != a:
        assert service.probe(current, "creating") is None


def test_cross_mode_and_no_retarget():
    """Both entry modes share one ledger and preserve exact-target equality."""
    service = RequestControl()
    a, b = target(), target("b")
    service.bind(a)
    original = service.submit(a, "command", "force_retry")
    assert submit(service, a) is original
    service.retire(a)
    service.bind(b)
    retained = submit(service, b)
    assert retained.proposal.target == a
    assert service.submit(a, "command", "force_retry") is retained
    assert service.submit(b, "command", "force_retry").reason == "conflict"
    fresh = submit(service, b, "new")
    assert service.submit(b, "new", "force_retry") is fresh


@pytest.mark.parametrize("binding,generation", [("other", 1), ("binding", 2)])
def test_cross_owner_does_not_disclose(binding, generation):
    """Route and generation scope reject before projecting old proposals."""
    service = RequestControl()
    a = target()
    service.bind(a)
    submit(service, a)
    with pytest.raises(ValueError, match="^conflict$"):
        service.submit_current(binding, generation, None, "command", "force_retry")


@pytest.mark.parametrize("kwargs,error", [({}, "no_active_target"),
    ({"capacity_unavailable": True}, "unavailable/control_capacity")])
def test_no_target_never_queues(kwargs, error):
    """Idle and fallback reject new intent without future targeting."""
    service = RequestControl()
    with pytest.raises(ValueError, match=error):
        submit(service, None, **kwargs)
    assert service.status("command") is None


def test_validation_stale_decided_and_full():
    """Input checks and original authority/capacity outcomes remain intact."""
    service = RequestControl(capacity=1)
    a = target()
    for args in [(None, 1, a, "c", "force_retry"), ("binding", True, a, "c", "force_retry"),
                 ("binding", 1, a, None, "force_retry"), ("binding", 1, a, "c", "bad")]:
        with pytest.raises(ValueError):
            service.submit_current(*args)
    for invalid in (replace(a, generation=2), object()):
        with pytest.raises(ValueError, match="stale_target"):
            submit(service, invalid)
    assert submit(service, a).reason == "stale_target"
    authority = service.bind(a)
    submit(service, a)
    assert submit(service, a, "overflow").reason == "capacity"
    authority.publish("value")
    assert submit(service, a, "late").reason == "already_decided"


def test_retention_expiry_and_concurrent_single_issue():
    """Finite retention is explicit; concurrent retries issue only one record."""
    now = [0]
    service = RequestControl(retention=1, clock=lambda: now[0])
    a, b = target(), target("b")
    service.bind(a)
    gate = Barrier(8)
    def run(_):
        """Synchronize simultaneous submission without scheduling sleeps."""
        gate.wait()
        return submit(service, a)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(8)))
    assert all(value is results[0] for value in results)
    service.retire(a)
    service.bind(b)
    now[0] = 2
    assert submit(service, b).proposal.target == b
