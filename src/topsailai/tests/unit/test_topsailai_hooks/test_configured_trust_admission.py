"""Public Runtime admission tests for configured trust wiring."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from topsailai.hooks import (
    ArtifactClosureAssertion,
    ArtifactPythonRuntimeAuthority,
    Binding,
    ConfiguredHooks,
    ConfiguredTrustPolicy,
    EventDefinition,
    HookRuntime,
    HookSettings,
)


class AllocationSentinel:
    """Fail if malformed trust reaches backend allocation."""

    def __init__(self, **kwargs: object) -> None:
        """Reject every attempted allocation."""
        del kwargs
        raise AssertionError("backend allocated")


class LockEntryBarrier:
    """Pause one selected thread before it enters the wrapped Runtime lock."""

    def __init__(self, lock: object) -> None:
        """Retain the exact Runtime lock and initialize deterministic events."""
        self._lock = lock
        self.target_thread_id: int | None = None
        self.entered = threading.Event()
        self.release_target = threading.Event()
        self._armed = True

    def __enter__(self) -> "LockEntryBarrier":
        """Pause the selected thread once, then acquire the original lock."""
        if self._armed and threading.get_ident() == self.target_thread_id:
            self._armed = False
            self.entered.set()
            if not self.release_target.wait(5):
                raise AssertionError("timed out waiting to enter Runtime lock")
        self._lock.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Release the original Runtime lock."""
        self._lock.release()


def _start_blocked_prepare(
    runtime: HookRuntime,
    configuration: ConfiguredHooks,
    scope: object,
) -> tuple[LockEntryBarrier, threading.Thread, list[object]]:
    """Start preparation and pause it immediately before Runtime lock entry."""
    barrier = LockEntryBarrier(runtime._lock)
    runtime._lock = barrier
    results: list[object] = []

    def prepare() -> None:
        """Select this thread for the one-shot barrier and retain its result."""
        barrier.target_thread_id = threading.get_ident()
        results.append(runtime.prepare_configured(configuration, scope))

    thread = threading.Thread(target=prepare)
    thread.start()
    assert barrier.entered.wait(5)
    return barrier, thread, results


def test_scope_closed_rejection_uses_current_generation(tmp_path: Path) -> None:
    """Scope rejection and generation must come from one Runtime snapshot."""
    runtime = HookRuntime(HookSettings(), temp_root=str(tmp_path))
    target_scope = runtime.open_scope()
    mutation_scope = runtime.open_scope()
    configuration = ConfiguredHooks((), HookSettings())
    barrier, thread, results = _start_blocked_prepare(runtime, configuration, target_scope)
    try:
        first = runtime.register(
            EventDefinition("test.first", 1),
            Binding("first", "test.first", 1, "builtins:len"),
            mutation_scope,
        )
        target_scope.close()
        second = runtime.register(
            EventDefinition("test.second", 1),
            Binding("second", "test.second", 1, "builtins:len"),
            mutation_scope,
        )
        assert first.accepted and second.accepted
        barrier.release_target.set()
        thread.join(5)
        assert not thread.is_alive()
        assert len(results) == 1
        result = results[0]
        assert result.errors == ("scope_closed",)
        assert result.generation == second.generation
    finally:
        barrier.release_target.set()
        thread.join(5)
        runtime.close()


def test_runtime_closed_rejection_uses_current_generation(tmp_path: Path) -> None:
    """Runtime rejection and generation must come from one Runtime snapshot."""
    runtime = HookRuntime(HookSettings(), temp_root=str(tmp_path))
    scope = runtime.open_scope()
    configuration = ConfiguredHooks((), HookSettings())
    barrier, thread, results = _start_blocked_prepare(runtime, configuration, scope)
    try:
        registered = runtime.register(
            EventDefinition("test.explicit", 1),
            Binding("explicit", "test.explicit", 1, "builtins:len"),
            scope,
        )
        assert registered.accepted
        runtime.close()
        closed_generation = runtime.reload(HookSettings()).generation
        barrier.release_target.set()
        thread.join(5)
        assert not thread.is_alive()
        assert len(results) == 1
        result = results[0]
        assert result.errors == ("runtime_closed",)
        assert result.generation == closed_generation
    finally:
        barrier.release_target.set()
        thread.join(5)
        runtime.close()


def test_valid_configured_boundary_uses_current_generation(tmp_path: Path) -> None:
    """A valid U09-A boundary result must report the current generation."""
    policy = ConfiguredTrustPolicy((tmp_path,))
    runtime = HookRuntime(
        HookSettings(), temp_root=str(tmp_path), configured_trust=policy
    )
    scope = runtime.open_scope()
    try:
        registered = runtime.register(
            EventDefinition("test.explicit", 1),
            Binding("explicit", "test.explicit", 1, "builtins:len"),
            scope,
        )
        assert registered.accepted
        result = runtime.prepare_configured(ConfiguredHooks((), HookSettings()), scope)
        assert result.errors == ("internal_error",)
        assert result.generation == registered.generation
    finally:
        runtime.close()


def test_missing_trust_rejects_empty_prepare_without_mutation(tmp_path: Path) -> None:
    """Default construction must preserve legacy state and deny configured admission."""
    runtime = HookRuntime(HookSettings(), temp_root=str(tmp_path))
    scope = runtime.open_scope()
    definition = EventDefinition("test.explicit", 1)
    binding = Binding("explicit", "test.explicit", 1, "builtins:len")
    try:
        registered = runtime.register(definition, binding, scope)
        result = runtime.prepare_configured(ConfiguredHooks((), HookSettings()), scope)
        assert registered.accepted
        assert result.accepted is False
        assert result.candidate is None
        assert result.errors == ("trust_policy_missing",)
        assert result.generation == registered.generation
        assert runtime.unregister(registered.handle).accepted
    finally:
        runtime.close()


def test_malformed_runtime_policy_fails_before_backend_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The constructor must reject a non-policy with one fixed safe error."""
    monkeypatch.setattr("topsailai.hooks.runtime.IsolatedProcessBackend", AllocationSentinel)
    with pytest.raises(ValueError, match="^invalid configured trust policy$"):
        HookRuntime(HookSettings(), temp_root=str(tmp_path), configured_trust={})


def test_valid_policy_is_detached_without_filesystem_probe(tmp_path: Path) -> None:
    """Construction must retain structural authority without requiring roots to exist."""
    root = tmp_path / "not-created"
    policy = ConfiguredTrustPolicy((root,))
    runtime = HookRuntime(
        HookSettings(),
        temp_root=str(tmp_path),
        configured_trust=policy,
    )
    try:
        assert runtime.configured_trust == policy
        assert runtime.configured_trust is not policy
    finally:
        runtime.close()


def test_runtime_rejects_malformed_nested_policy_before_backend_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed nested authority must fail before backend allocation."""
    monkeypatch.setattr("topsailai.hooks.runtime.IsolatedProcessBackend", AllocationSentinel)
    policy = object.__new__(ConfiguredTrustPolicy)
    object.__setattr__(policy, "source_roots", (tmp_path,))
    object.__setattr__(policy, "allowed_interpreters", ())
    object.__setattr__(policy, "allow_native_scripts", False)
    object.__setattr__(policy, "closure_assertions", ())
    object.__setattr__(
        policy,
        "python_runtime",
        ArtifactPythonRuntimeAuthority(Path("python"), ["a" * 64]),
    )
    with pytest.raises(ValueError, match="^invalid configured trust policy$"):
        HookRuntime(HookSettings(), temp_root=str(tmp_path), configured_trust=policy)


def test_runtime_owns_nested_trust_snapshots(tmp_path: Path) -> None:
    """Runtime trust must not retain caller-owned nested authority records."""
    digest = "c" * 64
    assertion = ArtifactClosureAssertion(
        tmp_path / "plugin.py", "python_source", "plugin", digest, digest, digest
    )
    python_runtime = ArtifactPythonRuntimeAuthority(tmp_path / "python", digest)
    policy = ConfiguredTrustPolicy(
        (tmp_path,), closure_assertions=(assertion,), python_runtime=python_runtime
    )
    runtime = HookRuntime(HookSettings(), temp_root=str(tmp_path), configured_trust=policy)
    try:
        assert runtime.configured_trust is not policy
        assert runtime.configured_trust.closure_assertions[0] is not policy.closure_assertions[0]
        assert runtime.configured_trust.python_runtime is not policy.python_runtime
    finally:
        runtime.close()
