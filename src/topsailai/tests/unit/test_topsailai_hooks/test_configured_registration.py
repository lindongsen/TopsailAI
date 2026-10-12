"""Registration-state tests for configured Hook bootstrap wrappers."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding, ConfiguredHookBootstrap
from topsailai.hooks.configured_contracts import ConfiguredRegistrationResult
from topsailai.hooks.configured_registration import (
    ConfiguredHookRegistrar,
    RegistrationFailureKind,
    RegistrationState,
)
from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration


class _Scope:
    """Provide one controllable application-scope identity."""

    scope_id = "application-scope"

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Runtime:
    """Record low-level configured API calls without filesystem work."""

    def __init__(self, results: list[ConfiguredRegistrationResult] | None = None) -> None:
        self.calls = 0
        self.active: set[str] = set()
        self.removed: list[str] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.results = results or [ConfiguredRegistrationResult(True, True, 1)]

    def register_configured(self, hook_name, scope, *, scripts=None, folder=None):
        self.calls += 1
        self.started.set()
        self.release.wait(2)
        result = self.results[min(self.calls - 1, len(self.results) - 1)]
        if result.accepted:
            self.active.add(hook_name)
        return result

    def retire_configured(self, hook_name, scope):
        self.active.discard(hook_name)
        self.removed.append(hook_name)
        return True

    def dispatch_configured(self, hook_name):
        """Reject admission when Runtime custody is absent."""
        if hook_name not in self.active:
            raise RuntimeError("configured plan is absent")
        return "dispatched"


def _catalog(*names: str) -> HookPointCatalog:
    return HookPointCatalog(tuple(
        HookPointDeclaration(
            name,
            EventDefinition(f"test.event_{index}", 1, {"type": "object"}),
            "before",
            "sync",
            "tests",
        )
        for index, name in enumerate(names)
    ))


def _bootstrap(*names: str, mode: str = "lazy", generation: int = 1) -> ConfiguredHookBootstrap:
    bindings = tuple(
        ConfiguredHookBinding(name, scripts=(Path(f"/trusted/{name}.py"),))
        for name in names
    )
    return ConfiguredHookBootstrap(
        True,
        registration_mode=mode,
        configuration_generation=generation,
        hooks=bindings,
        trust=_trust(),
        trust_identity="a" * 64,
    )


def _trust():
    from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy

    return ConfiguredTrustPolicy((Path("/trusted"),))


def test_startup_registers_all_known_points_before_ready() -> None:
    runtime = _Runtime()
    runtime.release.set()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap("hook_a", "hook_b", mode="startup"), _catalog("hook_a", "hook_b"))

    result = registrar.start()

    assert result.ready
    assert runtime.calls == 2
    assert registrar.state("hook_a") is RegistrationState.READY
    assert registrar.state("hook_b") is RegistrationState.READY


def test_lazy_sync_and_async_callers_share_one_registration() -> None:
    runtime = _Runtime()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a"))
    sync_result = []

    thread = threading.Thread(target=lambda: sync_result.append(registrar.ensure_registered("hook_a")))
    thread.start()
    assert runtime.started.wait(1)

    async def wait_async():
        task = asyncio.create_task(registrar.aensure_registered("hook_a"))
        await asyncio.sleep(0.02)
        runtime.release.set()
        return await task

    async_result = asyncio.run(wait_async())
    thread.join(1)

    assert runtime.calls == 1
    assert sync_result[0].ready and async_result.ready
    assert registrar.ensure_registered("hook_a").ready
    assert runtime.calls == 1


def test_deterministic_failure_is_cached_until_reload() -> None:
    runtime = _Runtime([ConfiguredRegistrationResult(False, errors=("artifact_rejected",))])
    runtime.release.set()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a"))

    first = registrar.ensure_registered("hook_a")
    second = registrar.ensure_registered("hook_a")

    assert first.failure_kind is RegistrationFailureKind.DETERMINISTIC
    assert second == first
    assert runtime.calls == 1


def test_close_wakes_waiters_and_prevents_ready_publication() -> None:
    runtime = _Runtime()
    scope = _Scope()
    registrar = ConfiguredHookRegistrar(runtime, scope, _bootstrap("hook_a"), _catalog("hook_a"))
    results = []
    winner = threading.Thread(target=lambda: results.append(registrar.ensure_registered("hook_a")))
    waiter = threading.Thread(target=lambda: results.append(registrar.ensure_registered("hook_a")))
    winner.start()
    assert runtime.started.wait(1)
    waiter.start()
    time.sleep(0.02)

    registrar.close()
    runtime.release.set()
    winner.join(1)
    waiter.join(1)

    assert scope.closed
    assert all(result.state is RegistrationState.CLOSED for result in results)
    assert registrar.state("hook_a") is RegistrationState.CLOSED


def test_reload_retires_changed_and_removed_lazy_points() -> None:
    runtime = _Runtime()
    runtime.release.set()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap("hook_a", "hook_b"), _catalog("hook_a", "hook_b"))
    assert registrar.ensure_registered("hook_a").ready

    changed = ConfiguredHookBootstrap(
        True,
        registration_mode="lazy",
        configuration_generation=2,
        hooks=(ConfiguredHookBinding("hook_a", scripts=(Path("/trusted/new.py"),)),),
        trust=_trust(),
        trust_identity="a" * 64,
    )
    registrar.reload(changed)

    assert runtime.removed == ["hook_b"]
    assert registrar.state("hook_a") is RegistrationState.UNINITIALIZED
    assert registrar.state("hook_b") is RegistrationState.UNCONFIGURED


def test_changed_reload_keeps_old_plan_until_atomic_runtime_replacement() -> None:
    """Changed bindings must not retire the last successful plan before replacement."""
    runtime = _Runtime()
    runtime.release.set()
    registrar = ConfiguredHookRegistrar(
        runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a")
    )
    assert registrar.ensure_registered("hook_a").ready
    changed = ConfiguredHookBootstrap(
        True,
        registration_mode="lazy",
        configuration_generation=2,
        hooks=(ConfiguredHookBinding("hook_a", scripts=(Path("/trusted/new.py"),)),),
        trust=_trust(),
        trust_identity="a" * 64,
    )

    registrar.reload(changed)

    assert runtime.removed == []
    assert registrar.state("hook_a") is RegistrationState.UNINITIALIZED


def test_reload_waits_for_changed_inflight_registration_before_invalidation() -> None:
    """A stale winner must settle before a new generation can register the same name."""
    runtime = _Runtime()
    registrar = ConfiguredHookRegistrar(
        runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a")
    )
    winner = threading.Thread(target=lambda: registrar.ensure_registered("hook_a"))
    winner.start()
    assert runtime.started.wait(1)
    changed = ConfiguredHookBootstrap(
        True,
        registration_mode="lazy",
        configuration_generation=2,
        hooks=(ConfiguredHookBinding("hook_a", scripts=(Path("/trusted/new.py"),)),),
        trust=_trust(),
        trust_identity="a" * 64,
    )
    reloaded = threading.Event()
    thread = threading.Thread(target=lambda: (registrar.reload(changed), reloaded.set()))
    thread.start()
    time.sleep(0.02)
    assert not reloaded.is_set()

    runtime.release.set()
    winner.join(1)
    thread.join(1)

    assert reloaded.is_set()
    assert registrar.state("hook_a") is RegistrationState.UNINITIALIZED
    assert runtime.removed == []


def test_startup_fail_invalidates_rolled_back_readiness_and_can_republish() -> None:
    """A failed startup must reconcile Registrar state with Runtime custody."""
    runtime = _Runtime([
        ConfiguredRegistrationResult(True, True, 1),
        ConfiguredRegistrationResult(False, errors=("artifact_rejected",)),
        ConfiguredRegistrationResult(True, True, 1),
    ])
    runtime.release.set()
    registrar = ConfiguredHookRegistrar(
        runtime,
        _Scope(),
        _bootstrap("hook_a", "hook_b", mode="startup"),
        _catalog("hook_a", "hook_b"),
    )

    result = registrar.start()

    assert result.failure_kind is RegistrationFailureKind.DETERMINISTIC
    assert runtime.removed == ["hook_a"]
    assert runtime.active == set()
    assert registrar.state("hook_a") is RegistrationState.INVALIDATED
    with pytest.raises(RuntimeError, match="configured plan is absent"):
        runtime.dispatch_configured("hook_a")

    restored = registrar.ensure_registered("hook_a")

    assert restored.ready
    assert registrar.state("hook_a") is RegistrationState.READY
    assert runtime.active == {"hook_a"}
    assert runtime.dispatch_configured("hook_a") == "dispatched"
    assert runtime.calls == 3


def test_startup_disable_retires_the_complete_configured_layer() -> None:
    """Explicit disable must not expose a successful subset after one rejection."""
    runtime = _Runtime([
        ConfiguredRegistrationResult(True, True, 1),
        ConfiguredRegistrationResult(False, errors=("artifact_rejected",)),
    ])
    runtime.release.set()
    bootstrap = ConfiguredHookBootstrap(
        True,
        registration_mode="startup",
        startup_policy="disable",
        hooks=_bootstrap("hook_a", "hook_b").hooks,
        trust=_trust(),
        trust_identity="a" * 64,
    )
    registrar = ConfiguredHookRegistrar(
        runtime, _Scope(), bootstrap, _catalog("hook_a", "hook_b")
    )

    result = registrar.start()

    assert result.state is RegistrationState.UNCONFIGURED
    assert runtime.removed == ["hook_a", "hook_b"]
    assert registrar.state("hook_a") is RegistrationState.UNCONFIGURED


def test_transient_failure_obeys_backoff_and_attempt_limit(monkeypatch) -> None:
    """Transient registration retries must be typed, delayed, and bounded."""
    runtime = _Runtime([
        ConfiguredRegistrationResult(False, errors=("capacity_exceeded",)),
        ConfiguredRegistrationResult(False, errors=("cleanup_pending",)),
        ConfiguredRegistrationResult(True, True, 1),
    ])
    runtime.release.set()
    now = [10.0]
    monkeypatch.setattr(
        "topsailai.hooks.configured_registration.time.monotonic", lambda: now[0]
    )
    registrar = ConfiguredHookRegistrar(
        runtime,
        _Scope(),
        _bootstrap("hook_a"),
        _catalog("hook_a"),
        max_transient_attempts=2,
        transient_backoff_seconds=1,
    )

    first = registrar.ensure_registered("hook_a")
    immediate = registrar.ensure_registered("hook_a")
    now[0] = 11.0
    second = registrar.ensure_registered("hook_a")
    now[0] = 12.0
    exhausted = registrar.ensure_registered("hook_a")

    assert first.failure_kind is RegistrationFailureKind.TRANSIENT
    assert immediate == first
    assert second.attempt == 2
    assert exhausted == second
    assert runtime.calls == 2


def test_folder_registration_unknown_state_and_close_are_stable(tmp_path: Path) -> None:
    """Folder mode delegates exactly once and closed admission remains terminal."""
    runtime = _Runtime()
    runtime.release.set()
    binding = ConfiguredHookBinding("hook_a", folder=tmp_path)
    bootstrap = ConfiguredHookBootstrap(
        True,
        registration_mode="lazy",
        hooks=(binding,),
        trust=_trust(),
        trust_identity="a" * 64,
    )
    scope = _Scope()
    registrar = ConfiguredHookRegistrar(
        runtime, scope, bootstrap, _catalog("hook_a")
    )

    assert registrar.state("missing") is RegistrationState.UNCONFIGURED
    assert registrar.ensure_registered("missing").state is RegistrationState.UNCONFIGURED
    assert registrar.ensure_registered("hook_a").ready
    assert registrar.ensure_registered("hook_a").ready
    assert runtime.calls == 1
    registrar.close()
    registrar.close()
    assert registrar.ensure_registered("hook_a").failure_kind is RegistrationFailureKind.CLOSED


def test_reload_rejects_trust_change_and_closed_registrar() -> None:
    """Trust epochs require Runtime replacement and closed state cannot reload."""
    runtime = _Runtime()
    runtime.release.set()
    registrar = ConfiguredHookRegistrar(
        runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a")
    )
    changed_trust = ConfiguredHookBootstrap(
        True,
        hooks=_bootstrap("hook_a").hooks,
        trust=_trust(),
        trust_identity="b" * 64,
    )
    with pytest.raises(ValueError, match="Runtime replacement"):
        registrar.reload(changed_trust)

    registrar.close()
    with pytest.raises(RuntimeError, match="closed"):
        registrar.reload(_bootstrap("hook_a", generation=2))


def test_registrar_rejects_invalid_retry_configuration() -> None:
    """Retry policy must remain finite and bounded."""
    runtime = _Runtime()
    with pytest.raises(ValueError, match="invalid configured Hook Registrar"):
        ConfiguredHookRegistrar(
            runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a"),
            max_transient_attempts=0,
        )
    with pytest.raises(ValueError, match="invalid configured Hook Registrar"):
        ConfiguredHookRegistrar(
            runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a"),
            transient_backoff_seconds=-1,
        )


def test_disabled_and_lazy_start_modes_do_not_register() -> None:
    """Start must preserve disabled and lazy snapshots without registration work."""
    runtime = _Runtime()
    runtime.release.set()
    disabled = ConfiguredHookRegistrar(
        runtime,
        _Scope(),
        ConfiguredHookBootstrap.disabled(),
        _catalog(),
    )
    assert disabled.start().state is RegistrationState.UNCONFIGURED

    lazy = ConfiguredHookRegistrar(
        runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a")
    )
    assert lazy.start().state is RegistrationState.UNINITIALIZED
    assert runtime.calls == 0


def test_registrar_rejects_invalid_foundations_and_startup_reload_failure() -> None:
    """Registrar inputs stay typed and eager reload reports a failed replacement."""
    runtime = _Runtime([
        ConfiguredRegistrationResult(False, errors=("artifact_rejected",))
    ])
    runtime.release.set()
    with pytest.raises(ValueError, match="invalid configured Hook Registrar"):
        ConfiguredHookRegistrar(runtime, _Scope(), object(), _catalog())

    registrar = ConfiguredHookRegistrar(
        runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a")
    )
    startup = ConfiguredHookBootstrap(
        True,
        registration_mode="startup",
        startup_policy="fail",
        configuration_generation=2,
        hooks=_bootstrap("hook_a").hooks,
        trust=_trust(),
        trust_identity="a" * 64,
    )
    with pytest.raises(RuntimeError, match="artifact_rejected"):
        registrar.reload(startup)


@pytest.mark.parametrize("category", ["artifact_rejected", "cleanup_pending"])
@pytest.mark.parametrize("mode", ["lazy", "startup"])
def test_failed_replacement_keeps_exact_active_admission(category, mode):
    """A rejected desired revision must retain usable exact publication evidence."""
    from dataclasses import replace

    runtime = _Runtime([
        ConfiguredRegistrationResult(True, True, 1, active_revision=7),
        ConfiguredRegistrationResult(False, errors=(category,)),
        ConfiguredRegistrationResult(True, True, 1, active_revision=8),
    ])
    runtime.release.set()
    bootstrap = _bootstrap("hook_a", mode=mode)
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), bootstrap, _catalog("hook_a"),
        transient_backoff_seconds=0)
    assert registrar.ensure_registered("hook_a").active_revision == 7
    changed = replace(bootstrap, configuration_generation=2,
        hooks=(ConfiguredHookBinding("hook_a", scripts=(Path("/trusted/new.py"),)),))
    registrar.reload(changed)
    failed = registrar.ensure_registered("hook_a")
    assert failed.ready
    assert failed.desired_revision == 2
    assert failed.active_revision == 7
    assert failed.update_failed_using_last_known_good
    assert failed.error_category == category
    assert runtime.dispatch_configured("hook_a") == "dispatched"
    assert registrar.ensure_registered("hook_a") == failed
    assert runtime.calls == 2
    assert runtime.removed == []
    registrar.reload(changed)
    restored = registrar.ensure_registered("hook_a")
    assert restored.ready and restored.active_revision == 8
    assert not restored.update_failed_using_last_known_good
    assert runtime.calls == 3


def test_unchanged_reload_preserves_inflight_cell_publication():
    """A global configuration advance must not invalidate an unchanged winner."""
    runtime = _Runtime([ConfiguredRegistrationResult(True, True, 1, active_revision=9)])
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a"))
    results = []
    worker = threading.Thread(target=lambda: results.append(registrar.ensure_registered("hook_a")))
    worker.start()
    try:
        assert runtime.started.wait(1)
        registrar.reload(_bootstrap("hook_a", generation=2))
        runtime.release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert results[0].ready and results[0].active_revision == 9
        assert runtime.removed == []
        assert registrar.ensure_registered("hook_a").ready
        assert runtime.calls == 1
    finally:
        runtime.release.set()
        worker.join(2)


def test_first_failure_has_no_active_revision_or_admission():
    """A failed first candidate cannot invent an active plan or blocking policy."""
    runtime = _Runtime([ConfiguredRegistrationResult(False, errors=("artifact_rejected",))])
    runtime.release.set()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap("hook_a"), _catalog("hook_a"))
    result = registrar.ensure_registered("hook_a")
    assert not result.ready
    assert result.desired_revision == 1 and result.active_revision is None
    assert not result.update_failed_using_last_known_good
    assert runtime.active == set()


@pytest.mark.parametrize("revision", [True, 0, -1, "1"])
def test_registration_rejects_invalid_publication_revision(revision):
    """Publication evidence must be a positive integer, never a malformed alias."""
    with pytest.raises(ValueError, match="invalid configured registration result"):
        ConfiguredRegistrationResult(True, active_revision=revision)
    with pytest.raises(ValueError, match="invalid configured registration result"):
        ConfiguredRegistrationResult(False, active_revision=1)


@pytest.mark.parametrize("policy", ["fail", "disable"])
def test_startup_failure_preserves_prior_active_plan(policy):
    """Rollback of new startup points must never retire prior valid custody."""
    from dataclasses import replace

    runtime = _Runtime([
        ConfiguredRegistrationResult(True, True, 1, active_revision=7),
        ConfiguredRegistrationResult(False, errors=("artifact_rejected",)),
        ConfiguredRegistrationResult(False, errors=("artifact_rejected",)),
    ])
    runtime.release.set()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap("hook_a"),
        _catalog("hook_a", "hook_b"))
    assert registrar.ensure_registered("hook_a").active_revision == 7
    startup = replace(_bootstrap("hook_a", "hook_b", mode="startup", generation=2),
        startup_policy=policy,
        hooks=(ConfiguredHookBinding("hook_a", scripts=(Path("/trusted/new.py"),)),
            ConfiguredHookBinding("hook_b", scripts=(Path("/trusted/b.py"),))))
    if policy == "fail":
        with pytest.raises(RuntimeError, match="artifact_rejected"):
            registrar.reload(startup)
    else:
        registrar.reload(startup)
    retained = registrar.ensure_registered("hook_a")
    assert retained.ready and retained.active_revision == 7
    assert retained.desired_revision == 2 and retained.update_failed_using_last_known_good
    assert runtime.dispatch_configured("hook_a") == "dispatched"
    assert "hook_a" not in runtime.removed
    assert runtime.active == {"hook_a"}
    assert not registrar.ensure_registered("hook_b").ready
    assert runtime.calls == 3


def test_stop_admission_does_not_close_scope_and_legacy_close_still_does():
    """Application stop wakes admission without taking the Scope close stage."""
    runtime = _Runtime()
    scope = _Scope()
    registrar = ConfiguredHookRegistrar(runtime, scope, _bootstrap("hook_a"), _catalog("hook_a"))
    registrar.stop_admission()
    registrar.stop_admission()
    assert not scope.closed
    assert registrar.ensure_registered("hook_a").state is RegistrationState.CLOSED
    assert runtime.calls == 0
    registrar.close()
    assert scope.closed
    registrar.close()


def test_stop_admission_wakes_waiter_and_retires_late_winner():
    """No in-flight winner can advertise readiness after application admission stop."""
    runtime = _Runtime()
    scope = _Scope()
    registrar = ConfiguredHookRegistrar(runtime, scope, _bootstrap("hook_a"), _catalog("hook_a"))
    results = []
    winner = threading.Thread(target=lambda: results.append(registrar.ensure_registered("hook_a")))
    waiter = threading.Thread(target=lambda: results.append(registrar.ensure_registered("hook_a")))
    winner.start()
    assert runtime.started.wait(1)
    waiter.start()
    registrar.stop_admission()
    waiter.join(1)
    assert not waiter.is_alive() and not scope.closed
    runtime.release.set()
    winner.join(1)
    assert not winner.is_alive()
    assert all(item.state is RegistrationState.CLOSED for item in results)
    assert not runtime.active and runtime.removed == ["hook_a"]
