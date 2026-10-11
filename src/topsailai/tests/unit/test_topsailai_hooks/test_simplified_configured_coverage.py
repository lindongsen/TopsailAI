"""Focused branch coverage for the simplified configured Hook API."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from topsailai.hooks import ConfiguredRegistrationResult
from topsailai.hooks.configured_runtime import (
    _ConfiguredAdmission,
    _capture_plan,
    _platform_policy,
    _terminal_configured,
    detach_configured_trust,
    register_configured,
    retire_configured_scope,
)
from topsailai.hooks.configured_trust import ConfiguredTrustPolicy
from topsailai.hooks.hook_script_discovery import (
    ExecutablePlatformPolicy,
    HookScriptDiscoveryResult,
    HookScriptEntry,
    discover_configured_hook_scripts,
)
from topsailai.hooks.artifact_contracts import ArtifactDisposeResult
from topsailai.hooks.hook_point_plan_ownership import CandidateBuildError, HookPointOwner
from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions
from topsailai.hooks.registry import HookRegistry
from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_plan_publication import empty_candidate
from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import (
    _event,
    _runtime,
    _script,
)


class _Owner:
    """Record exact close calls for configured-plan ownership tests."""

    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> ArtifactDisposeResult:
        """Record one close operation."""
        self.close_count += 1
        return ArtifactDisposeResult(True)


def _publish(registry, tmp_path, *, scope_id="scope-a", candidate=None):
    """Publish a real complete candidate and return its exact custody owner."""
    if candidate is None:
        candidate = empty_candidate(tmp_path, "hook_test")
    changed, generation, previous = registry.publish_configured(
        scope_id, "hook_test", candidate.plan.fingerprint, candidate
    )
    owner = registry.configured_plan(scope_id, "hook_test")[1]
    return owner, (changed, generation, previous)


@pytest.mark.parametrize(
    "arguments",
    (
        {"accepted": 1},
        {"accepted": True, "changed": 1},
        {"accepted": True, "script_count": True},
        {"accepted": True, "script_count": -1},
        {"accepted": True, "errors": ["bad"]},
        {"accepted": True, "errors": ("",)},
        {"accepted": False, "changed": True},
        {"accepted": False, "script_count": 1},
        {"accepted": True, "errors": ("bad",)},
    ),
)
def test_registration_result_rejects_inconsistent_boundary_values(arguments: dict) -> None:
    """The public result cannot represent contradictory registration state."""
    with pytest.raises(ValueError, match="invalid configured registration result"):
        ConfiguredRegistrationResult(**arguments)


def test_configured_plan_retires_after_last_reader_and_release_is_idempotent(tmp_path) -> None:
    """Retirement closes ownership only after the final admission releases once."""
    registry = HookRegistry()
    owner = _Owner()
    candidate = empty_candidate(tmp_path, "hook_test")
    candidate._capture_owner = owner
    plan, _ = _publish(registry, tmp_path, candidate=candidate)
    reader = registry.acquire_hook_point("scope-a", "hook_test")
    assert reader is not None
    plan.retire()
    assert plan.acquire() is None
    assert owner.close_count == 0

    admission = _ConfiguredAdmission(
        SimpleNamespace(event_id="event"), plan, 3, 100, 0.0,
        reader=reader, registry=registry,
    )
    admission.release()
    admission.release()

    assert owner.close_count == 1
    assert plan.owner is None


def test_detach_trust_validates_type_and_copies_mutable_boundary(tmp_path: Path) -> None:
    """Configured trust is detached and malformed authority fails before allocation."""
    assert detach_configured_trust(None) is None
    with pytest.raises(ValueError, match="invalid configured trust policy"):
        detach_configured_trust(object())

    policy = ConfiguredTrustPolicy(source_roots=(tmp_path.resolve(),))
    detached = detach_configured_trust(policy)
    assert detached == policy
    assert detached is not policy


def test_registry_configured_publication_lookup_replacement_and_scope_removal(tmp_path) -> None:
    """Configured state publishes atomically and is removed by exact owning scope."""
    from dataclasses import replace

    registry = HookRegistry()
    first, result = _publish(registry, tmp_path)
    assert result == (True, 1, None)
    assert registry.configured_plan("scope-a", "hook_test") == (1, first)
    assert registry.configured_plan("scope-b", "hook_test") == (1, None)

    _, repeated = _publish(registry, tmp_path)
    assert repeated == (False, 1, None)
    candidate = empty_candidate(tmp_path, "hook_test")
    candidate._plan = replace(candidate.plan, options=HookScriptExecutionOptions(argv=("two",)))
    replacement, replaced = _publish(registry, tmp_path, candidate=candidate)
    assert replaced == (True, 2, first)
    assert first.retire().accepted
    assert registry.remove_configured_scope("missing") == ()
    assert registry.remove_configured_scope("scope-a") == (replacement,)
    assert replacement.retire().accepted
    assert registry.configured_plan("scope-a", "hook_test") == (3, None)


def test_unregister_scope_handles_configured_only_and_empty_state(tmp_path) -> None:
    """Generic scope cleanup observes configured plans without requiring bindings."""
    registry = HookRegistry()
    unchanged = registry.unregister_scope("scope-a")
    assert unchanged.accepted and unchanged.generation == 0
    owner, _ = _publish(registry, tmp_path)
    removed = registry.unregister_scope("scope-a")
    assert removed.accepted and removed.generation == 2
    assert registry.configured_plan("scope-a", "hook_test") == (2, None)
    assert owner.retire().accepted


def test_recursive_discovery_validates_source_shape_and_target_kind(tmp_path: Path) -> None:
    """Configured discovery rejects ambiguous, malformed, and non-directory sources."""
    policy = ExecutablePlatformPolicy("posix", allowed_interpreters=("/bin/sh",))
    assert not discover_configured_hook_scripts(
        scripts=None, folder=None, platform_policy=policy
    ).accepted
    assert not discover_configured_hook_scripts(
        scripts=(), folder=tmp_path, platform_policy=policy
    ).accepted
    assert not discover_configured_hook_scripts(
        scripts=[], folder=None, platform_policy=policy  # type: ignore[arg-type]
    ).accepted
    assert not discover_configured_hook_scripts(
        scripts=None, folder=object(), platform_policy=policy
    ).accepted

    file_target = tmp_path / "file"
    file_target.write_text("x", encoding="utf-8")
    assert not discover_configured_hook_scripts(
        scripts=None, folder=file_target, platform_policy=policy
    ).accepted


def test_recursive_discovery_rejects_bad_candidate_and_duplicate_name(tmp_path: Path) -> None:
    """Recursive snapshots fail atomically for inadmissible or conflicting scripts."""
    policy = ExecutablePlatformPolicy("posix", allowed_interpreters=("/bin/sh",))
    root = tmp_path / "root"
    root.mkdir()
    bad = root / "bad"
    bad.write_text("not a script", encoding="utf-8")
    bad.chmod(0o700)
    result = discover_configured_hook_scripts(
        scripts=None, folder=root, platform_policy=policy
    )
    assert not result.accepted
    assert result.errors == ("configured hook_script file is not executable",)

    bad.unlink()
    for folder in (root / "a", root / "b"):
        folder.mkdir()
        script = folder / "same"
        script.write_text("#!/bin/sh\n", encoding="utf-8")
        script.chmod(0o700)
    duplicate = discover_configured_hook_scripts(
        scripts=None, folder=root, platform_policy=policy
    )
    assert not duplicate.accepted
    assert duplicate.errors == ("duplicate hook_script name",)


def test_recursive_discovery_ignores_symlink_directory_and_non_executable(
    tmp_path: Path,
) -> None:
    """Recursive discovery does not traverse symlink directories or plain files."""
    policy = ExecutablePlatformPolicy("posix", allowed_interpreters=("/bin/sh",))
    root = tmp_path / "root"
    root.mkdir()
    real = root / "real"
    real.mkdir()
    script = real / "ok"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o700)
    (root / "linked").symlink_to(real, target_is_directory=True)
    (root / "plain").write_text("ignored", encoding="utf-8")

    result = discover_configured_hook_scripts(
        scripts=None, folder=root, platform_policy=policy
    )
    assert result.accepted
    assert [entry.basename for entry in result.entries] == ["ok"]


def test_register_rejection_paths_preserve_runtime_state(tmp_path: Path, monkeypatch) -> None:
    """Closed, untrusted, malformed, and discovery-rejected registration fail closed."""
    runtime, scope = _runtime(tmp_path)
    try:
        assert not register_configured(
            runtime, "hook_test", scope, scripts=1  # type: ignore[arg-type]
        ).accepted
        missing = register_configured(
            runtime, "hook_test", scope, scripts=(tmp_path / "missing",)
        )
        assert missing.errors == ("discovery_rejected",)
        monkeypatch.setattr(runtime, "_configured_trust", None)
        assert register_configured(
            runtime, "hook_test", scope, scripts=()
        ).errors == ("trust_policy_missing",)
    finally:
        runtime.close()
    assert register_configured(
        runtime, "hook_test", scope, scripts=()
    ).errors == ("runtime_closed",)


def test_capture_plan_empty_rejection_and_exception_cleanup(tmp_path: Path, monkeypatch) -> None:
    """Capture handles no-op plans and closes ownership on rejection or expected failure."""
    from topsailai.hooks import hook_point_plan_capture as module

    runtime, _ = _runtime(tmp_path)
    trust = runtime.configured_trust
    platform = _platform_policy(trust)
    empty, error = _capture_plan(
        runtime, "hook_test", HookScriptDiscoveryResult(True), platform, trust
    )
    assert error is None and empty.plan.default_script_hook.scripts == ()
    assert empty._capture_owner is None
    assert empty.close().accepted

    script = _script(tmp_path / "script.py")
    discovery = HookScriptDiscoveryResult(
        True, (HookScriptEntry(script.resolve(), script.name),)
    )
    owners: list[object] = []

    class RejectingOwner(_Owner):
        """Return an explicit capture rejection."""

        def __init__(self, **kwargs) -> None:
            super().__init__()
            owners.append(self)

        def capture(self, *args, **kwargs):
            """Reject the capture."""
            return SimpleNamespace(accepted=False, artifact=None, errors=("artifact_rejected",))

    monkeypatch.setattr(module, "ArtifactCaptureOwner", RejectingOwner)
    with pytest.raises(CandidateBuildError) as raised:
        _capture_plan(runtime, "hook_test", discovery, platform, trust)
    assert raised.value.category == "artifact_rejected"
    assert raised.value.recovery_owner._capture_owner is owners[-1]
    assert owners[-1].close_count == 1

    class RaisingOwner(RejectingOwner):
        """Raise one expected capture error."""

        def capture(self, *args, **kwargs):
            """Raise during capture."""
            raise RuntimeError("capture failed")

    monkeypatch.setattr(module, "ArtifactCaptureOwner", RaisingOwner)
    with pytest.raises(CandidateBuildError) as raised:
        _capture_plan(runtime, "hook_test", discovery, platform, trust)
    assert raised.value.category == "capture failed"
    assert raised.value.recovery_owner._capture_owner is owners[-1]
    assert owners[-1].close_count == 1
    runtime.close()


def test_registration_scope_close_during_capture_retires_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    """A scope closed after capture cannot publish and candidate ownership is retired."""
    from topsailai.hooks import configured_runtime as module

    runtime, scope = _runtime(tmp_path)
    owner = _Owner()
    plan = empty_candidate(tmp_path, "hook_test")
    plan._capture_owner = owner

    def capture(*args, **kwargs):
        scope.close()
        return plan, None

    monkeypatch.setattr(module, "_capture_plan", capture)
    result = runtime.register_configured("hook_test", scope, scripts=())
    assert result.errors == ("scope_closed",)
    assert owner.close_count == 1
    with pytest.raises(RuntimeError, match="candidate is not live"):
        _ = plan.plan
    runtime.close()


def test_platform_policy_and_terminal_report_cover_host_policy(
    tmp_path: Path, monkeypatch
) -> None:
    """Platform selection and queued terminal reports retain exact public facts."""
    from topsailai.hooks import configured_runtime as module

    policy = ConfiguredTrustPolicy(source_roots=(tmp_path.resolve(),))
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    assert _platform_policy(policy) == ExecutablePlatformPolicy(
        "windows", native_suffixes=(".exe",)
    )

    owner = _Owner()
    registry = HookRegistry()
    candidate = empty_candidate(tmp_path, "hook_test")
    candidate._capture_owner = owner
    plan, _ = _publish(registry, tmp_path, candidate=candidate)
    reader = registry.acquire_hook_point("scope-a", "hook_test")
    assert reader is not None
    admission = _ConfiguredAdmission(
        SimpleNamespace(event_id="event"), plan, 7, 100, 0.0,
        reader=reader, registry=registry
    )
    report = _terminal_configured(admission, "deadline")
    assert report.rejection_reason == "deadline"
    assert report.deadline_exhausted
    plan.retire()
    assert owner.close_count == 1


def test_retire_configured_scope_ignores_foreign_plan_and_retires_owned_plan(tmp_path) -> None:
    """Scope retirement closes owned plans without retiring another scope's plan."""
    runtime, scope = _runtime(tmp_path)
    owned, _ = _publish(runtime._registry, tmp_path, scope_id=scope.scope_id)
    foreign, _ = _publish(runtime._registry, tmp_path, scope_id="foreign")
    try:
        assert retire_configured_scope(runtime, scope.scope_id)
        assert owned.settled and owned.owner is None
        assert not foreign.settled
        assert runtime._registry.configured_plan("foreign", "hook_test")[1] is foreign
        assert runtime.cleanup_debts() == ()
    finally:
        assert runtime._registry.remove_configured_scope("foreign") == (foreign,)
        assert foreign.retire().accepted
        runtime.close()


@pytest.mark.asyncio
async def test_async_configured_dispatch_preserves_admission_rejection(
    tmp_path: Path,
) -> None:
    """Async configured dispatch returns the exact invalid-name rejection."""
    runtime, scope = _runtime(tmp_path)
    try:
        event = _event(runtime, scope)
        report = await runtime.adispatch_configured("before_chat", event)

        assert report.event_id == event.event_id
        assert report.rejection_reason == "invalid_hook_name"
        assert report.outcomes == ()
    finally:
        runtime.close()


def test_waiting_configured_dispatch_reports_scheduler_capacity_and_releases_plan(
    tmp_path: Path, monkeypatch
) -> None:
    """Scheduler refusal rejects waiting work without retaining a plan reader."""
    runtime, scope = _runtime(tmp_path)
    try:
        registered = runtime.register_configured("hook_after_chat", scope, scripts=[])
        assert registered.accepted
        _, plan = runtime._registry.configured_plan(
            scope.scope_id, "hook_after_chat"
        )
        assert isinstance(plan, HookPointOwner)
        monkeypatch.setattr(runtime._scheduler, "submit", lambda *args, **kwargs: None)

        report = runtime.dispatch_configured(
            "hook_after_chat", _event(runtime, scope)
        )

        assert report.outcomes == ()
        assert report.rejection_reason == "rejected_capacity"
        assert plan._readers == {}
    finally:
        runtime.close()


def test_recursive_discovery_rejects_walk_failure(tmp_path: Path, monkeypatch) -> None:
    """A recursive enumeration failure rejects the entire configured snapshot."""
    from topsailai.hooks import hook_script_discovery as module

    root = tmp_path / "root"
    root.mkdir()
    policy = ExecutablePlatformPolicy("posix", allowed_interpreters=("/bin/sh",))

    def fail_walk(*args, **kwargs):
        raise OSError("walk failed")

    monkeypatch.setattr(module.os, "walk", fail_walk)
    result = discover_configured_hook_scripts(
        scripts=None, folder=root, platform_policy=policy
    )

    assert not result.accepted
    assert result.entries == ()
    assert result.errors == ("hook_script target is invalid",)


def test_recursive_discovery_rejects_candidate_metadata_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """A disappearing recursive candidate rejects rather than publishing partial state."""
    root = tmp_path / "root"
    root.mkdir()
    candidate = root / "vanished"
    candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    candidate.chmod(0o700)
    policy = ExecutablePlatformPolicy("posix", allowed_interpreters=("/bin/sh",))
    original_lstat = Path.lstat

    def selective_lstat(path: Path):
        if path == candidate:
            raise OSError("candidate vanished")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", selective_lstat)
    result = discover_configured_hook_scripts(
        scripts=None, folder=root, platform_policy=policy
    )

    assert not result.accepted
    assert result.entries == ()
    assert result.errors == ("hook_script target is invalid",)
