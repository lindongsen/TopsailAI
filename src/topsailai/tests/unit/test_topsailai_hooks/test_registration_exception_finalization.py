"""Singleflight exception finalization and exact waiter propagation tests."""

from __future__ import annotations

import threading

import pytest

from topsailai.hooks.configured_registration import ConfiguredHookRegistrar, RegistrationState
from topsailai.tests.unit.test_topsailai_hooks.test_configured_registration import (
    _Runtime, _Scope, _bootstrap, _catalog,
)


@pytest.mark.parametrize("failure", [RuntimeError("registration failed"), KeyboardInterrupt("host stop")])
def test_shared_registration_failure_finalizes_and_wakes_waiter(monkeypatch, failure):
    """Propagate one preparation failure without stranding its shared waiter."""
    runtime = _Runtime()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a"))
    started = threading.Event()
    release = threading.Event()
    waiting = threading.Event()
    errors = []
    original_wait = registrar._condition.wait

    def register(binding):
        """Block the owner until the second caller is waiting."""
        started.set()
        assert release.wait(2)
        raise failure

    def observe_wait(*args, **kwargs):
        """Record actual condition waiting rather than scheduling delay."""
        waiting.set()
        return original_wait(*args, **kwargs)

    def invoke():
        """Capture host interruptions as evidence without escaping the thread."""
        try:
            registrar.ensure_registered("hook_a")
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(registrar, "_register", register)
    monkeypatch.setattr(registrar._condition, "wait", observe_wait)
    winner = threading.Thread(target=invoke)
    waiter = threading.Thread(target=invoke)
    try:
        winner.start()
        assert started.wait(1)
        waiter.start()
        assert waiting.wait(1)
        release.set()
        winner.join(1)
        waiter.join(0.2)
        assert registrar.state("hook_a") is not RegistrationState.REGISTERING
        assert not waiter.is_alive()
        assert len(errors) == 2 and all(exc is failure for exc in errors)
        with pytest.raises(type(failure)) as raised:
            registrar.ensure_registered("hook_a")
        assert raised.value is failure
    finally:
        release.set()
        registrar.close()
        winner.join(2)
        if waiter.ident is not None:
            waiter.join(2)
        assert not winner.is_alive() and not waiter.is_alive()


@pytest.mark.parametrize("transition", ["close", "replace"])
def test_exception_finalization_does_not_overwrite_departed_cell(monkeypatch, transition):
    """Keep a closed or replacement cell outside the failed owner's authority."""
    registrar = ConfiguredHookRegistrar(_Runtime(), _Scope(), _bootstrap("hook_a"), _catalog("hook_a"))
    failure = RuntimeError("departed owner")
    original_cell = registrar._cells["hook_a"]

    def register(binding):
        """Move cell ownership before the original preparation raises."""
        if transition == "close":
            registrar.close()
        else:
            with registrar._condition:
                registrar._cells["hook_a"] = type(original_cell)(RegistrationState.UNINITIALIZED)
        raise failure

    monkeypatch.setattr(registrar, "_register", register)
    with pytest.raises(RuntimeError) as raised:
        registrar.ensure_registered("hook_a")
    assert raised.value is failure
    expected = RegistrationState.CLOSED if transition == "close" else RegistrationState.UNINITIALIZED
    assert registrar.state("hook_a") is expected
    assert registrar._cells["hook_a"].exception is None
    registrar.close()


def test_changed_generation_recovers_after_registration_exception(monkeypatch):
    """Clear cached failure only when reload establishes a new binding cell."""
    from pathlib import Path
    from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding, ConfiguredHookBootstrap
    from topsailai.tests.unit.test_topsailai_hooks.test_configured_registration import _trust

    runtime = _Runtime()
    runtime.release.set()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a"))
    original_register = registrar._register
    failure = KeyboardInterrupt("old generation")

    def register(binding):
        """Fail the first generation without replacing shared authority."""
        raise failure

    monkeypatch.setattr(registrar, "_register", register)
    with pytest.raises(KeyboardInterrupt) as raised:
        registrar.ensure_registered("hook_a")
    assert raised.value is failure
    registrar.reload(ConfiguredHookBootstrap(
        True, registration_mode="lazy", configuration_generation=2,
        hooks=(ConfiguredHookBinding("hook_a", scripts=(Path("/trusted/changed.py"),)),),
        trust=_trust(), trust_identity="a" * 64,
    ))
    monkeypatch.setattr(registrar, "_register", original_register)
    assert registrar.ensure_registered("hook_a").ready
    assert runtime.calls == 1
    registrar.close()
