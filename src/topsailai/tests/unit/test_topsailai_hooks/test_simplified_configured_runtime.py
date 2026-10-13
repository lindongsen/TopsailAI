"""Tests for the simple scope-local configured Hook Runtime API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from topsailai.tests.unit.test_topsailai_hooks.reload_helpers import (
    invoke_thread, join_owned, wait_for_queue,
)

from topsailai.hooks import (
    ConfiguredRegistrationResult,
    ConfiguredTrustPolicy,
    HookLimits,
    HookRuntime,
    HookSettings,
)
from topsailai.hooks.hook_script_discovery import (
    ExecutablePlatformPolicy,
    discover_configured_hook_scripts,
)


def test_candidate_lifecycle_records_are_not_package_root_exports() -> None:
    """The supported package API must not advertise the superseded candidate flow."""
    import topsailai.hooks as hooks

    for name in (
        "PreparedConfigured",
        "PrepareConfiguredResult",
        "PublishConfiguredResult",
        "DisposeConfiguredResult",
    ):
        assert name not in hooks.__all__
        assert not hasattr(hooks, name)


def _script(path: Path) -> Path:
    """Create one statically admissible executable script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{Path(sys.executable).resolve()}\n", encoding="utf-8")
    path.chmod(0o700)
    return path


def _platform_policy() -> ExecutablePlatformPolicy:
    """Return the host-injected interpreter policy used by discovery."""
    return ExecutablePlatformPolicy(
        "posix", allowed_interpreters=(str(Path(sys.executable).resolve()),)
    )


def _runtime(tmp_path: Path) -> tuple[HookRuntime, object]:
    """Build one trusted Runtime and one owned Scope."""
    trust = ConfiguredTrustPolicy(
        source_roots=(tmp_path,),
        allowed_interpreters=(Path(sys.executable).resolve(),),
    )
    limits = HookLimits(workers=1, queue_items=8, dispatch_timeout_ms=2_000)
    runtime = HookRuntime(
        HookSettings(limits=limits),
        temp_root=str(tmp_path / "runtime"),
        configured_trust=trust,
    )
    return runtime, runtime.open_scope(metadata={"owner_id": "configured-test"})


def _event(runtime: HookRuntime, scope: object):
    """Create an immutable execution context whose event name is not the Hook name."""
    return runtime.make_event(
        scope,
        "test.configured.event",
        1,
        {"value": 1},
        operation_id="configured-operation",
        layer="test",
        purpose="unit",
    )


def test_registration_contract_validates_name_source_and_scope(tmp_path: Path) -> None:
    """Registration must fail closed without publishing partial configured state."""
    runtime, scope = _runtime(tmp_path)
    other_runtime, other_scope = _runtime(tmp_path / "other")
    try:
        invalid_name = runtime.register_configured("before_chat", scope, scripts=[])
        assert invalid_name == ConfiguredRegistrationResult(
            False, errors=("invalid_hook_name",)
        )

        missing_source = runtime.register_configured("hook_before_chat", scope)
        assert missing_source == ConfiguredRegistrationResult(
            False, errors=("invalid_script_source",)
        )

        duplicate_source = runtime.register_configured(
            "hook_before_chat", scope, scripts=[], folder=tmp_path
        )
        assert duplicate_source == ConfiguredRegistrationResult(
            False, errors=("invalid_script_source",)
        )

        foreign_scope = runtime.register_configured(
            "hook_before_chat", other_scope, scripts=[]
        )
        assert foreign_scope == ConfiguredRegistrationResult(
            False, errors=("invalid_scope",)
        )
    finally:
        runtime.close()
        other_runtime.close()


def test_empty_plan_registers_noops_and_executes_by_exact_name(tmp_path: Path) -> None:
    """An empty configured plan is distinct from an unknown Hook name."""
    runtime, scope = _runtime(tmp_path)
    try:
        first = runtime.register_configured("hook_before_chat", scope, scripts=[])
        assert first == ConfiguredRegistrationResult(True, changed=True)

        repeated = runtime.register_configured("hook_before_chat", scope, scripts=[])
        assert repeated == ConfiguredRegistrationResult(True)

        event = _event(runtime, scope)
        report = runtime.dispatch_configured("hook_before_chat", event)
        assert report.rejection_reason is None
        assert report.outcomes == ()

        unknown = runtime.dispatch_configured("hook_unknown", event)
        assert unknown.rejection_reason == "unknown_configured_hook"
    finally:
        runtime.close()


def test_exact_configured_plan_can_be_retired_without_closing_scope(tmp_path: Path) -> None:
    """Registrar reload may retire one configured plan while retaining its Scope."""
    runtime, scope = _runtime(tmp_path)
    try:
        assert runtime.register_configured("hook_before_chat", scope, scripts=[]).accepted
        event = _event(runtime, scope)

        assert runtime.retire_configured("hook_before_chat", scope) is True
        assert runtime.retire_configured("hook_before_chat", scope) is False
        assert runtime.dispatch_configured("hook_before_chat", event).rejection_reason == "unknown_configured_hook"
        assert scope.closed is False
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_async_and_sync_execution_share_the_registered_plan(
    tmp_path: Path,
) -> None:
    """All execution modes must select the same scope-local configured plan."""
    runtime, scope = _runtime(tmp_path)
    try:
        assert runtime.register_configured(
            "hook_after_chat", scope, scripts=[]
        ).accepted
        event = _event(runtime, scope)

        report = await runtime.adispatch_configured("hook_after_chat", event)
        thread, reports, errors = invoke_thread(
            lambda: runtime.dispatch_configured("hook_after_chat", event)
        )
        try:
            join_owned(thread)
        finally:
            join_owned(thread)
        assert not errors and len(reports) == 1
        sync_report = reports[0]

        assert report.rejection_reason is None
        assert report.outcomes == ()
        assert sync_report.rejection_reason is None
        assert sync_report.outcomes == report.outcomes
        assert sync_report.event_id == event.event_id
    finally:
        runtime.close()


def test_failed_replacement_preserves_last_successful_plan(tmp_path: Path) -> None:
    """A replacement is all-or-nothing and cannot erase the active plan on failure."""
    runtime, scope = _runtime(tmp_path)
    try:
        assert runtime.register_configured(
            "hook_before_chat", scope, scripts=[]
        ).accepted

        failed = runtime.register_configured(
            "hook_before_chat",
            scope,
            scripts=[tmp_path / "missing-script"],
        )
        assert not failed.accepted
        assert not failed.changed

        report = runtime.dispatch_configured(
            "hook_before_chat", _event(runtime, scope)
        )
        assert report.rejection_reason is None
        assert report.outcomes == ()
    finally:
        runtime.close()


def test_scope_close_removes_configured_plan(tmp_path: Path) -> None:
    """Scope ownership must remove configured state without caller disposal."""
    runtime, scope = _runtime(tmp_path)
    try:
        assert runtime.register_configured(
            "hook_before_chat", scope, scripts=[]
        ).accepted
        event = _event(runtime, scope)
        scope.close()

        report = runtime.dispatch_configured("hook_before_chat", event)
        assert report.rejection_reason == "closed_scope"
    finally:
        runtime.close()


def test_explicit_scripts_preserve_caller_order(tmp_path: Path) -> None:
    """Explicit script registration must never sort caller-owned order."""
    second = _script(tmp_path / "02_second.py")
    first = _script(tmp_path / "01_first.py")

    result = discover_configured_hook_scripts(
        scripts=(second, first), folder=None, platform_policy=_platform_policy()
    )

    assert result.accepted
    assert tuple(entry.basename for entry in result.entries) == (
        "02_second.py",
        "01_first.py",
    )


def test_folder_discovery_is_recursive_and_relative_path_ordered(tmp_path: Path) -> None:
    """Folder mode must recursively sort by normalized relative path."""
    root = tmp_path / "hooks"
    _script(root / "z.py")
    _script(root / "nested" / "a.py")
    (root / "README.md").write_text("ignored", encoding="utf-8")

    result = discover_configured_hook_scripts(
        scripts=None, folder=root, platform_policy=_platform_policy()
    )

    assert result.accepted
    assert tuple(entry.basename for entry in result.entries) == ("a.py", "z.py")


def test_discovery_rejects_duplicate_identity_and_basename(tmp_path: Path) -> None:
    """Canonical aliases and conflicting script names must fail atomically."""
    script = _script(tmp_path / "one.py")
    duplicate = discover_configured_hook_scripts(
        scripts=(script, script), folder=None, platform_policy=_platform_policy()
    )
    assert not duplicate.accepted
    assert duplicate.entries == ()

    root = tmp_path / "folder"
    _script(root / "a" / "same.py")
    _script(root / "b" / "same.py")
    conflict = discover_configured_hook_scripts(
        scripts=None, folder=root, platform_policy=_platform_policy()
    )
    assert not conflict.accepted
    assert conflict.entries == ()


# Real-process fixtures below intentionally implement the protocol without importing
# project code so captured scripts remain single-file artifacts.
def _protocol_script(path: Path, marker: str, *, wait_for_gate: bool = False) -> Path:
    """Create one executable script that records execution and returns a valid frame."""
    gate = "\nwhile not pathlib.Path(payload['gate']).exists():\n    time.sleep(0.01)" if wait_for_gate else ""
    body = f'''#!{Path(sys.executable).resolve()}
import json
import os
import pathlib
import struct
import sys
import time
message = json.loads(sys.stdin.buffer.read().decode("utf-8"))
payload = message["context"]["event"]["payload"]
with pathlib.Path(payload["log"]).open("a", encoding="utf-8") as stream:
    stream.write({marker!r} + "\\n")
    stream.flush()
{gate}
result = {{
    "protocol_version": 1,
    "delivery_id": message["delivery_id"],
    "invocation_id": message["invocation_id"],
    "entry_index": message["entry_index"],
    "value": {{"marker": {marker!r}}},
}}
encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
result_fd = int(os.environ["TOPSAILAI_HOOK_RESULT_FD"])
os.write(result_fd, struct.pack("!I", len(encoded)) + encoded)
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)
    return path


def _assertion(path: Path):
    """Build the established closure assertion for one exact shebang script."""
    import hashlib

    from topsailai.hooks import ArtifactClosureAssertion
    from topsailai.hooks.artifact_identity import shebang_runtime_fingerprint

    interpreter = Path(sys.executable).resolve()
    status = interpreter.stat()
    interpreter_digest = hashlib.sha256(interpreter.read_bytes()).hexdigest()
    runtime_digest = shebang_runtime_fingerprint(
        interpreter,
        interpreter_digest,
        device=status.st_dev,
        inode=status.st_ino,
    )
    return ArtifactClosureAssertion(
        path.resolve(),
        "script",
        path.name,
        hashlib.sha256(path.read_bytes()).hexdigest(),
        runtime_digest,
        "a" * 64,
    )


def _real_runtime(tmp_path: Path, scripts: tuple[Path, ...]) -> tuple[HookRuntime, object]:
    """Build a Runtime authorized for exact real-process script fixtures."""
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    trust = ConfiguredTrustPolicy(
        source_roots=(source_root.resolve(),),
        allowed_interpreters=(Path(sys.executable).resolve(),),
        closure_assertions=tuple(_assertion(path) for path in scripts),
    )
    limits = HookLimits(
        workers=1,
        queue_items=8,
        dispatch_timeout_ms=3_000,
        shutdown_timeout_ms=3_000,
    )
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(mode=0o700)
    runtime = HookRuntime(
        HookSettings(limits=limits),
        temp_root=str(runtime_root),
        configured_trust=trust,
    )
    return runtime, runtime.open_scope(metadata={"owner_id": "configured-real-test"})


def _real_event(runtime: HookRuntime, scope: object, log: Path, gate: Path | None = None):
    """Create a real-execution event carrying only test-owned output paths."""
    payload = {"log": str(log)}
    if gate is not None:
        payload["gate"] = str(gate)
    return runtime.make_event(
        scope,
        "test.configured.real",
        1,
        payload,
        operation_id="configured-real-operation",
        layer="test",
        purpose="unit",
    )


def _wait_for(predicate, timeout: float = 3.0) -> None:
    """Wait for one asynchronous resource fact without fixed-delay assertions."""
    import time

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for configured Hook state")
        time.sleep(0.01)


def test_real_scripts_execute_in_final_name_order_with_legacy_fallback(tmp_path: Path) -> None:
    """Execute final legacy names in sorted order, independently of source selection."""
    first = _protocol_script(tmp_path / "sources" / "z.py", "z")
    second = _protocol_script(tmp_path / "sources" / "nested" / "a.py", "a")
    runtime, scope = _real_runtime(tmp_path, (first, second))
    explicit_log = tmp_path / "explicit.log"
    folder_log = tmp_path / "folder.log"
    try:
        explicit = runtime.register_configured(
            "hook_real_order", scope, scripts=(first, second)
        )
        assert explicit.accepted and explicit.script_count == 2
        report = runtime.dispatch_configured(
            "hook_real_order", _real_event(runtime, scope, explicit_log)
        )
        assert tuple(outcome.status.value for outcome in report.outcomes) == ("success",)
        assert explicit_log.read_text(encoding="utf-8").splitlines() == ["a", "z"]

        before = runtime._registry.configured_plan(scope.scope_id, "hook_real_order")
        folder = runtime.register_configured(
            "hook_real_order", scope, folder=tmp_path / "sources"
        )
        assert folder.accepted and not folder.changed
        assert runtime._registry.configured_plan(scope.scope_id, "hook_real_order") == before
        report = runtime.dispatch_configured(
            "hook_real_order", _real_event(runtime, scope, folder_log)
        )
        assert tuple(outcome.status.value for outcome in report.outcomes) == ("success",)
        assert folder_log.read_text(encoding="utf-8").splitlines() == ["a", "z"]
    finally:
        runtime.close()


def test_capture_is_immutable_and_replacement_is_atomic(tmp_path: Path) -> None:
    """Captured bytes survive source mutation and successful replacement affects future work."""
    old = _protocol_script(tmp_path / "sources" / "old" / "hook.py", "old")
    new = _protocol_script(tmp_path / "sources" / "new" / "hook.py", "new")
    runtime, scope = _real_runtime(tmp_path, (old, new))
    log = tmp_path / "capture.log"
    try:
        assert runtime.register_configured(
            "hook_capture", scope, scripts=(old,)
        ).accepted
        old.write_text("changed after capture\n", encoding="utf-8")
        first = runtime.dispatch_configured(
            "hook_capture", _real_event(runtime, scope, log)
        )
        assert first.outcomes[0].status.value == "success"

        replacement = runtime.register_configured(
            "hook_capture", scope, scripts=(new,)
        )
        assert replacement.accepted and replacement.changed
        second = runtime.dispatch_configured(
            "hook_capture", _real_event(runtime, scope, log)
        )
        assert second.outcomes[0].status.value == "success"
        assert log.read_text(encoding="utf-8").splitlines() == ["old", "new"]

        failed = runtime.register_configured(
            "hook_capture", scope, scripts=(tmp_path / "sources" / "missing.py",)
        )
        assert not failed.accepted
        third = runtime.dispatch_configured(
            "hook_capture", _real_event(runtime, scope, log)
        )
        assert third.outcomes[0].status.value == "success"
        assert log.read_text(encoding="utf-8").splitlines()[-1] == "new"
    finally:
        runtime.close()


def test_admitted_reader_delays_replacement_cleanup_and_releases_once(tmp_path: Path) -> None:
    """An admitted old plan retains its artifact until its real process settles."""
    blocking = _protocol_script(
        tmp_path / "sources" / "old" / "hook.py", "old", wait_for_gate=True
    )
    replacement = _protocol_script(tmp_path / "sources" / "new" / "hook.py", "new")
    runtime, scope = _real_runtime(tmp_path, (blocking, replacement))
    gate = tmp_path / "gate"
    log = tmp_path / "overlap.log"
    owned = []
    try:
        assert runtime.register_configured(
            "hook_overlap", scope, scripts=(blocking,)
        ).accepted
        _, old_plan = runtime._registry.configured_plan(scope.scope_id, "hook_overlap")
        old_artifact = old_plan.entries[0].source_path.parents[1]
        call = invoke_thread(lambda: runtime.dispatch_configured(
            "hook_overlap", _real_event(runtime, scope, log, gate)
        ))
        owned.append(call)
        _wait_for(lambda: log.exists())

        changed = runtime.register_configured(
            "hook_overlap", scope, scripts=(replacement,)
        )
        assert changed.accepted and changed.changed
        assert old_artifact.exists()
        assert len(old_plan._readers) == 1

        gate.touch()
        _wait_for(lambda: len(old_plan._readers) == 0)
        _wait_for(lambda: not old_artifact.exists())
        _wait_for(lambda: old_plan.settled)
        assert old_plan.owner is None
    finally:
        gate.touch()
        try:
            for thread, _, _ in owned:
                join_owned(thread)
        finally:
            runtime.close()
    assert all(not errors and len(reports) == 1 for _, reports, errors in owned)
    assert owned[0][1][0].outcomes[0].status.value == "success"
    assert runtime._scheduler._work == {}
    assert runtime.cleanup_debts() == ()


def test_scope_and_runtime_close_remove_captured_artifacts(tmp_path: Path) -> None:
    """Both ownership boundaries must remove plans and captured files automatically."""
    script = _protocol_script(tmp_path / "sources" / "hook.py", "close")
    runtime, scope = _real_runtime(tmp_path, (script,))
    assert runtime.register_configured("hook_close", scope, scripts=(script,)).accepted
    _, plan = runtime._registry.configured_plan(scope.scope_id, "hook_close")
    artifact = plan.entries[0].source_path.parents[1]
    assert artifact.exists()
    scope.close()
    assert runtime._registry.configured_plan(scope.scope_id, "hook_close")[1] is None
    assert not artifact.exists()
    runtime.close()

    runtime, scope = _real_runtime(tmp_path / "second", (
        _protocol_script(tmp_path / "second" / "sources" / "hook.py", "runtime-close"),
    ))
    script = tmp_path / "second" / "sources" / "hook.py"
    assert runtime.register_configured("hook_close", scope, scripts=(script,)).accepted
    _, plan = runtime._registry.configured_plan(scope.scope_id, "hook_close")
    artifact = plan.entries[0].source_path.parents[1]
    runtime.close()
    assert not artifact.exists()


def test_queued_deadline_releases_configured_plan_once(tmp_path: Path) -> None:
    """A queued deadline must release only its own configured-plan reader."""
    blocking = _protocol_script(
        tmp_path / "sources" / "hook.py", "deadline", wait_for_gate=True
    )
    runtime, scope = _real_runtime(tmp_path, (blocking,))
    gate = tmp_path / "gate"
    log = tmp_path / "deadline.log"
    owned = []
    try:
        assert runtime.register_configured(
            "hook_deadline", scope, scripts=(blocking,)
        ).accepted
        _, plan = runtime._registry.configured_plan(scope.scope_id, "hook_deadline")
        call = invoke_thread(lambda: runtime.dispatch_configured(
            "hook_deadline", _real_event(runtime, scope, log, gate)
        ))
        owned.append(call)
        _wait_for(lambda: log.exists())

        expired = runtime.dispatch_configured(
            "hook_deadline",
            _real_event(runtime, scope, log, gate),
            policy={"timeout_ms": 20},
        )
        assert expired.rejection_reason == "deadline"
        assert expired.deadline_exhausted
        assert len(plan._readers) == 1

        gate.touch()
        _wait_for(lambda: len(plan._readers) == 0)
    finally:
        gate.touch()
        try:
            for thread, _, _ in owned:
                join_owned(thread)
        finally:
            runtime.close()
    assert all(not errors and len(reports) == 1 for _, reports, errors in owned)
    assert owned[0][1][0].outcomes[0].status.value == "success"
    assert runtime._scheduler._work == {}
    assert runtime.cleanup_debts() == ()


def test_scope_cancellation_releases_queued_configured_plan_once(
    tmp_path: Path,
) -> None:
    """Scope closure must cancel one queued reader without double releasing it."""
    blocking = _protocol_script(
        tmp_path / "sources" / "hook.py", "cancel", wait_for_gate=True
    )
    runtime, scope = _real_runtime(tmp_path, (blocking,))
    gate = tmp_path / "gate"
    log = tmp_path / "cancel.log"
    owned = []
    try:
        assert runtime.register_configured(
            "hook_cancel", scope, scripts=(blocking,)
        ).accepted
        _, plan = runtime._registry.configured_plan(scope.scope_id, "hook_cancel")
        artifact = plan.entries[0].source_path.parents[1]
        call = invoke_thread(lambda: runtime.dispatch_configured(
            "hook_cancel", _real_event(runtime, scope, log, gate)
        ))
        owned.append(call)
        _wait_for(lambda: log.exists())
        call = invoke_thread(lambda: runtime.dispatch_configured(
            "hook_cancel", _real_event(runtime, scope, log, gate)
        ))
        owned.append(call)
        wait_for_queue(runtime, 1)
        assert len(plan._readers) == 2

        scope.close()
        assert len(plan._readers) == 1
        assert artifact.exists()
        gate.touch()
        _wait_for(lambda: len(plan._readers) == 0)
        _wait_for(lambda: not artifact.exists())
        _wait_for(lambda: plan.settled)
        assert plan.owner is None
    finally:
        gate.touch()
        try:
            for thread, _, _ in owned:
                join_owned(thread)
        finally:
            runtime.close()
    assert all(not errors and len(reports) == 1 for _, reports, errors in owned)
    assert runtime._scheduler._work == {}
    assert runtime.cleanup_debts() == ()


@pytest.mark.parametrize("count", (128, 129))
@pytest.mark.parametrize("source", ("scripts", "folder"))
def test_registration_capacity_before_capture(tmp_path, monkeypatch, count, source):
    """Apply the registration ceiling before capture or publication, not execution."""
    from topsailai.hooks import configured_runtime as module
    from topsailai.hooks.hook_script_discovery import HookScriptDiscoveryResult, HookScriptEntry
    runtime, scope = _runtime(tmp_path)
    entries = tuple(HookScriptEntry(tmp_path / f"s{i}", f"s{i}") for i in range(count))
    scripts = [entry.source_path for entry in entries]
    before = list(scripts)
    calls = []

    def discover(**kwargs):
        """Expose deterministic resource metadata without creating artifacts."""
        calls.append("discovery")
        return HookScriptDiscoveryResult(True, entries)

    def capture(*args):
        """Record the resource boundary without allocating a capture owner."""
        calls.append("capture")
        return None, "test_capture_boundary"

    monkeypatch.setattr(module, "discover_configured_hook_scripts", discover)
    monkeypatch.setattr(module, "_capture_plan", capture)
    generation = runtime._registry.generation
    try:
        kwargs = {"scripts": scripts} if source == "scripts" else {"folder": tmp_path}
        result = runtime.register_configured("hook_capacity", scope, **kwargs)
        assert not result.accepted
        assert result.errors == (("test_capture_boundary",) if count == 128
            else ("registration_capacity_exceeded",))
        assert calls == (["discovery", "capture"] if count == 128 else
            ([] if source == "scripts" else ["discovery"]))
        assert runtime._registry.generation == generation
        assert scripts == before
    finally:
        runtime.close()


def test_capture_capacity_before_filesystem(tmp_path, monkeypatch):
    """Defend the direct adapter before root, owner, or filesystem allocation."""
    from topsailai.hooks import configured_runtime as module
    from topsailai.hooks.hook_script_discovery import HookScriptDiscoveryResult, HookScriptEntry
    from types import SimpleNamespace
    entries = tuple(HookScriptEntry(tmp_path / f"s{i}", f"s{i}") for i in range(129))
    plan, error = module._capture_plan(SimpleNamespace(), "hook_capacity",
        HookScriptDiscoveryResult(True, entries), None, None)
    assert plan is None and error == "registration_capacity_exceeded"
    assert list(tmp_path.iterdir()) == []


def test_registration_capacity_bounds_iterable_consumption(tmp_path):
    """Read only limit plus one values and never exhaust an unsupported size."""
    runtime, scope = _runtime(tmp_path)
    observed = []

    def scripts():
        """Fail if capacity rejection consumes more than its bounded prefix."""
        for index in range(130):
            observed.append(index)
            assert index < 129
            yield tmp_path / f"s{index}"

    try:
        result = runtime.register_configured("hook_capacity", scope, scripts=scripts())
        assert result.errors == ("registration_capacity_exceeded",)
        assert observed == list(range(129))
    finally:
        runtime.close()


def test_real_registration_capacity_and_failed_replacement(tmp_path):
    """Capture 128 real scripts; oversized replacement preserves the active plan."""
    scripts = [_script(tmp_path / "sources" / f"s{i:03d}") for i in range(129)]
    runtime, scope = _real_runtime(tmp_path, tuple(scripts))
    before = list(scripts)
    try:
        accepted = runtime.register_configured("hook_capacity", scope, scripts=scripts[:128])
        assert accepted.accepted and accepted.script_count == 128
        generation, active = runtime._registry.configured_plan(scope.scope_id, "hook_capacity")
        assert len(active.entries) == 128
        assert active.policy.max_entries == 32
        rejected = runtime.register_configured("hook_capacity", scope, scripts=scripts)
        assert rejected.errors == ("registration_capacity_exceeded",)
        assert runtime._registry.configured_plan(scope.scope_id, "hook_capacity") == (generation, active)
        assert scripts == before
    finally:
        runtime.close()


@pytest.mark.parametrize("count", (128, 129, 130))
def test_bounded_real_folder_registration(tmp_path, monkeypatch, count):
    """Stop at capacity before later reads, capture, or active-plan replacement."""
    from topsailai.hooks import configured_runtime as registration
    from topsailai.hooks import hook_script_discovery as discovery

    folder = tmp_path / "sources"
    paths = [_script(folder / f"s{i:03d}") for i in range(count)]
    if count == 130:
        paths[-1].write_text("malformed late script", encoding="utf-8")
    original_bytes = tuple(path.read_bytes() for path in paths)
    runtime, scope = _real_runtime(tmp_path, tuple(paths))
    admitted = []
    captures = []
    original_admit = discovery._is_admitted
    original_walk = discovery.os.walk
    original_capture = registration._capture_plan

    def ordered_walk(*args, **kwargs):
        """Preserve real traversal while deterministically positioning late input."""
        for directory, names, files in original_walk(*args, **kwargs):
            yield directory, names, sorted(files)

    def admit(path, policy):
        """Record only real header admission, refusing any over-boundary read."""
        admitted.append(path.name)
        assert len(admitted) <= 128
        return original_admit(path, policy)

    def capture(*args):
        """Keep the real trusted capture for legal registrations only."""
        captures.append(True)
        return original_capture(*args)

    try:
        assert runtime.register_configured("hook_capacity", scope, scripts=[]).accepted
        before = runtime._registry.configured_plan(scope.scope_id, "hook_capacity")
        generation = runtime._registry.generation
        monkeypatch.setattr(discovery.os, "walk", ordered_walk)
        monkeypatch.setattr(discovery, "_is_admitted", admit)
        monkeypatch.setattr(registration, "_capture_plan", capture)
        result = runtime.register_configured("hook_capacity", scope, folder=folder)
        assert len(admitted) == 128
        if count == 128:
            assert result.accepted and result.script_count == 128
            assert captures == [True]
            _, active = runtime._registry.configured_plan(scope.scope_id, "hook_capacity")
            assert tuple(entry.basename for entry in active.entries) == tuple(p.name for p in paths)
            assert active.policy.max_entries == 32
        else:
            assert result.errors == ("registration_capacity_exceeded",)
            assert captures == []
            assert runtime._registry.configured_plan(scope.scope_id, "hook_capacity") == before
            assert runtime._registry.generation == generation
        assert tuple(path.read_bytes() for path in paths) == original_bytes
    finally:
        runtime.close()


def test_bounded_folder_walk_stops_before_next_row(tmp_path, monkeypatch):
    """Do not eagerly exhaust traversal or read the first excess candidate."""
    from topsailai.hooks import hook_script_discovery as discovery

    folder = tmp_path / "sources"
    paths = [_script(folder / f"s{i:03d}") for i in range(129)]
    rows = []

    def walk(*args, **kwargs):
        """Yield the boundary row then fail if discovery requests another row."""
        rows.append(1)
        def files():
            """Fail if candidates are sorted or consumed past the capacity boundary."""
            for path in paths:
                yield path.name
            raise AssertionError("files consumed after capacity")

        yield str(folder), [], files()
        raise AssertionError("walk consumed after capacity")

    monkeypatch.setattr(discovery.os, "walk", walk)
    runtime, scope = _runtime(tmp_path)
    try:
        result = runtime.register_configured("hook_capacity", scope, folder=folder)
        assert result.errors == ("registration_capacity_exceeded",)
        assert rows == [1]
        assert runtime._registry.generation == 0
    finally:
        runtime.close()


def test_independent_folder_discovery_retains_unbounded_default(tmp_path):
    """Standalone discovery does not silently inherit registration capacity."""
    paths = [_script(tmp_path / f"s{i:03d}") for i in range(130)]
    result = discover_configured_hook_scripts(
        scripts=None, folder=tmp_path, platform_policy=_platform_policy()
    )
    assert result.accepted and tuple(e.source_path for e in result.entries) == tuple(paths)


@pytest.mark.parametrize("limit", (0, -1, True, "128"))
def test_bounded_discovery_invalid_limit(tmp_path, limit):
    """Reject invalid explicit capacities without touching missing source files."""
    result = discover_configured_hook_scripts(
        scripts=(tmp_path / "missing",), folder=None,
        platform_policy=_platform_policy(), max_resources=limit,
    )
    assert not result.accepted and result.errors == ("hook_script target is invalid",)


def test_bounded_discovery_explicit_capacity(tmp_path):
    """The optional boundary rejects excess explicit entries before file reads."""
    result = discover_configured_hook_scripts(
        scripts=(tmp_path / "missing",) * 129, folder=None,
        platform_policy=_platform_policy(), max_resources=128,
    )
    assert result.errors == ("registration_capacity_exceeded",)


def test_bounded_discovery_walk_error(tmp_path, monkeypatch):
    """Traversal failure returns an atomic rejection without partial entries."""
    from topsailai.hooks import hook_script_discovery as discovery

    def walk(*args, **kwargs):
        """Raise only on iteration, as a streaming filesystem walker can."""
        yield str(tmp_path), [], []
        raise OSError("walk unavailable")

    monkeypatch.setattr(discovery.os, "walk", walk)
    result = discover_configured_hook_scripts(
        scripts=None, folder=tmp_path, platform_policy=_platform_policy(), max_resources=128,
    )
    assert not result.accepted and result.entries == ()


def test_runtime_closed_during_capture_cannot_publish(tmp_path, monkeypatch):
    """Real capture followed by Runtime close must reject before Registry mutation."""
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _runtime(tmp_path)
    original = configured._capture_plan
    calls = []

    def capture_then_close(*args, **kwargs):
        """Close the Runtime after real candidate construction, before revalidation."""
        plan, error = original(*args, **kwargs)
        calls.append(plan)
        runtime.close()
        return plan, error

    try:
        original_retire = configured._ConfiguredPlan.retire
        retire_calls = []

        def retire_outside_runtime_lock(plan):
            """Check the real retirement boundary, not merely final artifact absence."""
            assert not runtime._lock._is_owned()
            retire_calls.append(plan)
            return original_retire(plan)

        monkeypatch.setattr(configured, "_capture_plan", capture_then_close)
        monkeypatch.setattr(configured._ConfiguredPlan, "retire", retire_outside_runtime_lock)
        result = runtime.register_configured("hook_before_chat", scope, scripts=[])
        assert retire_calls == calls
        assert len(calls) == 1 and calls[0] is not None
        assert not result.accepted and not result.changed
        assert result.errors == ("runtime_closed",)
        assert runtime._registry.configured_plan(scope.scope_id, "hook_before_chat")[1] is None
    finally:
        runtime.close()


def test_empty_adapter_publishes_complete_typed_plan(tmp_path):
    """Legacy empty success still stores exactly one immutable default Hook."""
    from topsailai.hooks.hook_point_plan_ownership import PublishedHookPoint
    runtime, scope = _runtime(tmp_path)
    try:
        result = runtime.register_configured("hook_before_chat", scope, scripts=[])
        assert result.accepted and result.changed
        reader = runtime._registry.acquire_hook_point(scope.scope_id, "hook_before_chat")
        try:
            assert type(reader.snapshot) is PublishedHookPoint
            assert reader.snapshot.plan.modules == ()
            assert len(reader.snapshot.plan.handlers) == 1
            assert reader.snapshot.plan.default_script_hook.scripts == ()
            assert reader.snapshot.plan.default_script_hook.configured is True
        finally:
            assert runtime._registry.release_hook_point(reader)
        report = runtime.dispatch_configured("hook_before_chat", _event(runtime, scope))
        assert report.rejection_reason is None and report.outcomes == ()
    finally:
        runtime.close()


def test_mixed_plan_executes_complete_captured_snapshot(tmp_path, monkeypatch):
    """Execute sealed Modules and default Scripts with one deadline and local custody."""
    import threading
    import time
    from dataclasses import replace
    import topsailai.hooks.configured_runtime as configured
    from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_plan_capture import fixtures
    capture_root = tmp_path / "candidate"
    capture_root.mkdir()
    build, inputs, output, imported, called = fixtures(capture_root)
    scripts = tuple(_protocol_script(entry.source_path, entry.registered_name)
                    for entry in inputs["script_discovery"].entries)
    assertions = tuple(a for a in inputs["trust"].closure_assertions if a.kind == "python_source")
    inputs["trust"] = replace(inputs["trust"], allowed_interpreters=(Path(sys.executable).resolve(),),
        closure_assertions=assertions + tuple(_assertion(path) for path in scripts))
    inputs["platform_policy"] = _platform_policy()
    candidate = build("hook_before_chat", **inputs)
    plan = candidate.plan
    runtime, scope = _runtime(tmp_path)
    deadline, signal = time.monotonic() + 4.75, threading.Event()
    seen = []
    original = configured.execute_hook_point

    def execute(**kwargs):
        """Observe custody already bound before any real child invocation."""
        runners = kwargs["module_executor"].__closure__
        assert runners is not None
        assert kwargs["deadline"] == deadline and kwargs["cancellation"] is signal
        assert kwargs["script_runner"].cleanup_debts() == ()
        seen.append(kwargs["reader"].snapshot.active_version)
        return original(**kwargs)

    try:
        assert runtime._registry.publish_hook_point(scope.scope_id, "hook_before_chat", candidate).accepted
        for module in plan.modules:
            module.source_path.chmod(0o600)
            module.source_path.write_text("raise RuntimeError('live source reopened')\n")
        monkeypatch.setattr(configured, "execute_hook_point", execute)
        log = tmp_path / "calls"
        report = runtime.dispatch_configured("hook_before_chat", _real_event(runtime, scope, log),
            deadline=deadline, cancellation=signal)
        result = report.unified_result
        assert report.rejection_reason is None and result.status == "success"
        assert [h.handler.name for h in result.handlers[:-1]] == ["A", "Z"]
        assert all(h.returned.present and h.returned.value is None for h in result.handlers[:-1])
        assert result.handlers[-1].handler.kind == "default_script_hook"
        assert [c.handler.name for c in result.handlers[-1].children] == ["A", "Z"]
        assert log.read_text().splitlines() == ["A", "Z"]
        assert called.exists() and imported.exists()
        assert result.plan_version == seen[0] and result.cleanup.state == "safe"
        assert all(o.status.value == "success" for o in report.outcomes)
        assert runtime.cleanup_debts() == () and not runtime.retry_cleanup("foreign-execution")
    finally:
        runtime.close()
        candidate.close()
    assert list(output.iterdir()) == []


def test_runtime_retirement_pending_debt_is_exact_and_retryable(tmp_path, monkeypatch):
    """Real failed directory cleanup stays visible after active membership removal."""
    from types import SimpleNamespace
    import topsailai.hooks.artifact_cleanup as cleanup
    script = _protocol_script(tmp_path / "sources" / "hook.py", "debt")
    runtime, scope = _real_runtime(tmp_path, (script,))
    original_os = cleanup.os
    hits = []

    def blocked_rmdir(path, *args, **kwargs):
        """Fail only the owned sealed-entry removal and assert Runtime lock absence."""
        if path == "entry-000000":
            assert not runtime._lock._is_owned()
            hits.append(path)
            raise OSError("owned entry cleanup temporarily blocked")
        return original_os.rmdir(path, *args, **kwargs)

    try:
        assert runtime.register_configured("hook_debt", scope, scripts=(script,)).accepted
        _, plan = runtime._registry.configured_plan(scope.scope_id, "hook_debt")
        artifact = plan.entries[0].source_path.parents[1]
        capture_owner = plan.owner
        isolated_os = SimpleNamespace(**vars(original_os))
        isolated_os.rmdir = blocked_rmdir
        monkeypatch.setattr(cleanup, "os", isolated_os)
        assert runtime.retire_configured("hook_debt", scope)
        assert hits and artifact.exists()
        assert runtime._registry.configured_plan(scope.scope_id, "hook_debt")[1] is None
        debts = runtime.cleanup_debts()
        assert len(debts) == 1
        assert runtime.retry_cleanup("foreign-debt") is False
        assert runtime.cleanup_debts() == debts
        monkeypatch.setattr(cleanup, "os", original_os)
        assert runtime.retry_cleanup(debts[0].debt_id) is True
        assert runtime.cleanup_debts() == ()
        assert not artifact.exists() and script.exists()
        assert runtime.retry_cleanup(debts[0].debt_id) is False
    finally:
        monkeypatch.setattr(cleanup, "os", original_os)
        # Until Runtime recovery adoption exists, settle the exact fixture owner.
        if 'capture_owner' in locals() and capture_owner is not None:
            capture_owner.close()
        runtime.close()


def test_publication_recovery_reservation_is_bounded_before_capture(tmp_path, monkeypatch):
    """An exhausted exact recovery registry refuses before constructing an owner."""
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _runtime(tmp_path)
    tickets = []
    captured = []
    original = configured._capture_plan

    def observed_capture(*args, **kwargs):
        """Record the actual resource-producing boundary without replacing results."""
        captured.append(True)
        return original(*args, **kwargs)

    try:
        recovery = runtime._publication_recovery
        assert type(recovery.capacity) is int and 0 < recovery.capacity <= 128
        for _ in range(recovery.capacity):
            ticket = recovery.reserve()
            assert ticket is not None
            tickets.append(ticket)
        assert recovery.reserve() is None
        monkeypatch.setattr(configured, "_capture_plan", observed_capture)
        before = runtime._registry.generation
        rejected = runtime.register_configured("hook_before_chat", scope, scripts=[])
        assert not rejected.accepted
        assert rejected.errors == ("publication_capacity_exceeded",)
        assert captured == [] and runtime._registry.generation == before
        import copy
        assert not recovery.release(copy.copy(tickets[0]))
        for ticket in tickets:
            assert recovery.release(ticket)
            assert not recovery.release(ticket)
        tickets.clear()
        assert runtime.register_configured("hook_before_chat", scope, scripts=[]).accepted
        assert captured == [True]
    finally:
        for ticket in tickets:
            runtime._publication_recovery.release(ticket)
        runtime.close()


def test_publication_recovery_exact_interrupted_retirement(tmp_path):
    """Keep an interrupted owner reachable and retry cleanup outside Runtime locks."""
    runtime, scope = _runtime(tmp_path)
    hits = []
    interrupt = KeyboardInterrupt("close interrupted")

    class Owner:
        """Expose only the real disposal contract consumed by recovery custody."""
        def retire(self):
            """Interrupt once before confirming disposal and record exact lock facts."""
            from topsailai.hooks.artifact_contracts import ArtifactDisposeResult
            assert not runtime._lock._is_owned()
            hits.append(self)
            if len(hits) == 1:
                raise interrupt
            return ArtifactDisposeResult(True)

        def cleanup_debts(self):
            """Represent an interruption without an underlying artifact debt yet."""
            assert not runtime._lock._is_owned()
            return ()

    try:
        recovery = runtime._publication_recovery
        ticket = recovery.reserve()
        owner = Owner()
        assert recovery.bind(ticket, owner)
        assert not recovery.release(ticket)
        with pytest.raises(KeyboardInterrupt) as raised:
            recovery.settle(ticket)
        assert raised.value is interrupt
        debts = runtime.cleanup_debts()
        assert len(debts) == 1
        assert not runtime.retry_cleanup("foreign-publication")
        assert hits == [owner]
        assert runtime.retry_cleanup(debts[0].debt_id)
        assert hits == [owner, owner]
        assert runtime.cleanup_debts() == ()
        assert not runtime.retry_cleanup(debts[0].debt_id)
    finally:
        runtime.close()


def test_transfer_interruption_retains_exact_physical_owner(tmp_path, monkeypatch):
    """A real interruption after transfer cannot report success while bytes leak."""
    from topsailai.hooks.hook_point_plan_ownership import HookPointCandidate
    script = _protocol_script(tmp_path / "sources" / "hook.py", "transfer")
    runtime, scope = _real_runtime(tmp_path, (script,))
    original = HookPointCandidate.transfer
    owners = []
    primary = KeyboardInterrupt("after real transfer before swap")

    def transferred_then_interrupted(candidate, registry, version):
        """Interrupt a reachable class seam after the actual ownership mutation."""
        owner = original(candidate, registry, version)
        owners.append(owner)
        raise primary

    try:
        monkeypatch.setattr(HookPointCandidate, "transfer", transferred_then_interrupted)
        with pytest.raises(KeyboardInterrupt) as raised:
            runtime.register_configured("hook_transfer", scope, scripts=(script,))
        assert raised.value is primary and len(owners) == 1
        assert runtime._registry.configured_plan(scope.scope_id, "hook_transfer")[1] is None
        paths = tuple(item.captured_path for item in owners[0].snapshot.plan.default_script_hook.scripts)
        assert paths and all(path.exists() for path in paths)
        debts = runtime.cleanup_debts()
        assert len(debts) == 1
        assert runtime.retry_cleanup(debts[0].debt_id)
        assert all(not path.exists() for path in paths)
        assert runtime.cleanup_debts() == ()
    finally:
        monkeypatch.setattr(HookPointCandidate, "transfer", original)
        for owner in owners:
            owner.retire()
        runtime.close()


def test_build_interrupt_uses_preexisting_recovery_reservation(tmp_path, monkeypatch):
    """Capture interruption retains exact recovery despite all remaining slots filled."""
    import topsailai.hooks.configured_runtime as configured
    from topsailai.hooks.hook_point_plan_ownership import HookPointCandidate
    runtime, scope = _runtime(tmp_path)
    recovery = runtime._publication_recovery
    tickets = [recovery.reserve() for _ in range(recovery.capacity - 2)]
    primary = KeyboardInterrupt("capture interrupted")
    owner = HookPointCandidate(None)
    primary.recovery_owner = owner

    def interrupted_capture(*args):
        """Use the documented build exception contract with no forged canonical state."""
        assert recovery.reserve() is None
        raise primary

    try:
        monkeypatch.setattr(configured, "_capture_plan", interrupted_capture)
        with pytest.raises(KeyboardInterrupt) as caught:
            runtime.register_configured("hook_before_chat", scope, scripts=[])
        assert caught.value is primary
        debts = runtime.cleanup_debts()
        assert len(debts) == 1
        assert runtime.retry_cleanup(debts[0].debt_id)
        assert runtime.cleanup_debts() == ()
    finally:
        for ticket in tickets:
            recovery.release(ticket)
        runtime.close()


def test_execution_cleanup_pending_retains_old_bytes_until_exact_retry(tmp_path, monkeypatch):
    """A completed report is not evidence that the execution cleanup owner settled."""
    import topsailai.hooks.configured_runtime as configured
    from topsailai.hooks.hook_script_contracts import HookScriptSettlement
    from topsailai.hooks.process_state import CleanupDebt
    script = _protocol_script(tmp_path / "sources" / "hook.py", "pending")
    runtime, scope = _real_runtime(tmp_path, (script,))
    debt = CleanupDebt("execution-exact-debt", "process", None, "test pending")
    calls = []

    class Runner:
        """Model the documented runner cleanup boundary, not a fabricated plan owner."""
        def __init__(self, backend):
            """Retain one exact execution debt until selected retry."""
            self.pending = True

        def cleanup_debts(self):
            """Report the exact unresolved debt through the supported runner seam."""
            return (debt,) if self.pending else ()

        def retry_cleanup(self, debt_id):
            """Reject unrelated identifiers and record exact retry cardinality."""
            calls.append(debt_id)
            if debt_id != debt.debt_id or not self.pending:
                return False
            self.pending = False
            return True

    def execution(**kwargs):
        """Return a cleanup-pending settlement without claiming a real process launch."""
        assert kwargs["runner"].cleanup_debts() == (debt,)
        return HookScriptSettlement("error", error_category="hook_script_cleanup_pending")

    try:
        assert runtime.register_configured("hook_pending", scope, scripts=(script,)).accepted
        _, old = runtime._registry.configured_plan(scope.scope_id, "hook_pending")
        paths = tuple(entry.source_path for entry in old.entries)
        monkeypatch.setattr(configured, "OwnedHookScriptRunner", Runner)
        monkeypatch.setattr(configured, "execute_configured_hook_script", execution)
        report = runtime.dispatch_configured("hook_pending", _event(runtime, scope))
        assert report.outcomes[0].error_category == "hook_script_cleanup_pending"
        assert runtime.register_configured("hook_pending", scope, scripts=[]).accepted
        assert all(path.exists() for path in paths)
        debts = runtime.cleanup_debts()
        assert debt in debts
        assert not runtime.retry_cleanup("foreign-execution") and calls == []
        assert runtime.retry_cleanup(debt.debt_id)
        assert calls == [debt.debt_id]
        assert all(not path.exists() for path in paths)
        assert runtime.cleanup_debts() == ()
    finally:
        runtime.close()


def test_repeated_runtime_close_inspects_publication_outside_lock(tmp_path, monkeypatch):
    """Idempotent close must not observe cleanup owners under the Runtime lock."""
    runtime, scope = _real_runtime(tmp_path, ())
    runtime.close()
    original = runtime._publication_recovery.cleanup_debts
    observed = []

    def inspect():
        """Observe the real repeated-close boundary without mutating business state."""
        observed.append(runtime._lock._is_owned())
        return original()

    monkeypatch.setattr(runtime._publication_recovery, "cleanup_debts", inspect)
    assert runtime.close().already_closed
    assert observed == [False]


def test_scope_close_more_active_points_than_recovery_slots(tmp_path):
    """Valid active membership must remain closeable beyond the recovery slot bound."""
    runtime, scope = _real_runtime(tmp_path, ())
    try:
        for index in range(runtime._publication_recovery.capacity + 1):
            assert runtime.register_configured(f"hook_capacity_{index}", scope, scripts=[]).accepted
        report = scope.close()
        assert runtime._registry.deferred_scope_count(scope.scope_id) == 1
        report = scope.close()
        assert scope.scope_id in report.closed_scope_ids
        assert runtime._registry.configured_scope_owners(scope.scope_id) == ()
    finally:
        # Clean only the exact empty fixture owners after the failed close boundary.
        for owner in runtime._registry.remove_configured_scope(scope.scope_id):
            owner.retire()
        runtime._scheduler.close(1.0)
        runtime._diagnostics.close(1.0)
        runtime.close()


def test_deferred_scope_close_saturation_and_selected_retry(tmp_path):
    """A saturated journal defers close without losing explicit point custody."""
    runtime, scope = _real_runtime(tmp_path, ())
    recovery = runtime._publication_recovery
    tickets = []
    try:
        for index in range(129):
            assert runtime.register_configured(f"hook_deferred_{index}", scope, scripts=[]).accepted
        tickets = [recovery.reserve() for _ in range(recovery.capacity)]
        assert all(ticket is not None for ticket in tickets)
        report = scope.close()
        assert scope.closed and report.closed_scope_ids == ()
        assert runtime._registry.configured_scope_owners(scope.scope_id) == ()
        assert runtime._registry.deferred_scope_count(scope.scope_id) == 129
        pending = [debt for debt in report.cleanup_debts if debt.state == "scope_close_pending"]
        assert len(pending) == 1
        assert not runtime.retry_cleanup("foreign-close-debt")
        assert scope.close().already_closed
        assert runtime._registry.deferred_scope_count(scope.scope_id) == 129
        for ticket in tickets:
            assert recovery.release(ticket)
        tickets.clear()
        assert runtime.retry_cleanup(pending[0].debt_id)
        assert runtime._registry.deferred_scope_count(scope.scope_id) == 1
        assert runtime.retry_cleanup(pending[0].debt_id)
        assert runtime._registry.deferred_scope_count(scope.scope_id) == 0
        assert not runtime.retry_cleanup(pending[0].debt_id)
        assert runtime.cleanup_debts() == ()
    finally:
        for ticket in tickets:
            recovery.release(ticket)
        runtime.close()


def test_deferred_close_disposal_interruption_preserves_exact_owner(tmp_path, monkeypatch):
    """A finite physical retirement interruption retains exact recovery custody."""
    from topsailai.hooks.hook_point_plan_ownership import HookPointOwner
    runtime, scope = _real_runtime(tmp_path, ())
    assert runtime.register_configured("hook_interrupted_close", scope, scripts=[]).accepted
    _, owner = runtime._registry.configured_plan(scope.scope_id, "hook_interrupted_close")
    original = HookPointOwner.retire
    primary = KeyboardInterrupt("one retirement interruption")
    attempts = []

    def retire(current):
        """Interrupt an actual owner retirement once before allowing reconciliation."""
        assert not runtime._lock._is_owned()
        attempts.append(current)
        if len(attempts) == 1:
            raise primary
        return original(current)

    monkeypatch.setattr(HookPointOwner, "retire", retire)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            scope.close()
        assert caught.value is primary
        assert attempts == [owner]
        assert runtime._registry.configured_scope_owners(scope.scope_id) == ()
        debts = runtime.cleanup_debts()
        publication = [debt for debt in debts if debt.state == "publication_pending"]
        assert len(publication) == 1
        assert not runtime.retry_cleanup("foreign-retirement")
        assert runtime.retry_cleanup(publication[0].debt_id)
        assert attempts == [owner, owner]
        assert not runtime.retry_cleanup(publication[0].debt_id)
        scope.close()
        assert runtime.cleanup_debts() == ()
    finally:
        runtime.close()


def test_repeated_scope_close_inspection_outside_runtime_lock(tmp_path, monkeypatch):
    """Repeated scope reconciliation observes physical cleanup outside Runtime locks."""
    runtime, scope = _real_runtime(tmp_path, ())
    scope.close()
    original = runtime._publication_recovery.cleanup_debts
    observed = []

    def inspect():
        """Observe the supported debt inspection seam, not frame or cell state."""
        observed.append(runtime._lock._is_owned())
        return original()

    monkeypatch.setattr(runtime._publication_recovery, "cleanup_debts", inspect)
    try:
        assert scope.close().already_closed
        assert observed == [False]
    finally:
        runtime.close()


def test_deferred_migration_interruption_has_single_custody(tmp_path):
    """Interrupt the actual final state assignment without changing business locals."""
    import inspect
    from topsailai.hooks.registry import HookRegistry
    runtime, scope = _real_runtime(tmp_path, ())
    registry = runtime._registry
    for index in range(3):
        assert runtime.register_configured(f"hook_atomic_{index}", scope, scripts=[]).accepted
    owners = registry.configured_scope_owners(scope.scope_id)
    function = HookRegistry.defer_configured_scope
    lines, first = inspect.getsourcelines(function)
    boundary = first + next(index for index, line in enumerate(lines)
                            if "self._state =" in line)
    primary = KeyboardInterrupt("before migration publication")
    fired = False
    previous = sys.gettrace()

    def trace(frame, event, argument):
        """Inject once at a real source boundary and leave all frame data untouched."""
        nonlocal fired
        if frame.f_code is function.__code__ and event == "line" and frame.f_lineno == boundary:
            fired = True
            raise primary
        return trace

    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            scope.close()
        assert caught.value is primary and fired
    finally:
        sys.settrace(previous)
    try:
        active = registry.configured_scope_owners(scope.scope_id)
        deferred = registry.deferred_scope_count(scope.scope_id)
        assert len(active) + deferred == len(owners)
        assert active == owners or active == ()
        debt = next(debt for debt in runtime.cleanup_debts() if debt.state == "scope_close_pending")
        assert runtime.retry_cleanup(debt.debt_id)
        assert registry.deferred_scope_count(scope.scope_id) == 0
        assert runtime.cleanup_debts() == ()
    finally:
        runtime.close()


@pytest.mark.parametrize("operation", ("reservation_return", "withdrawal"))
def test_deferred_handoff_interruption_no_duplicate_or_empty_ticket(tmp_path, monkeypatch, operation):
    """Interrupt bound reservation or state withdrawal and reuse the same exact ticket."""
    import inspect
    from topsailai.hooks.registry import HookRegistry
    runtime, scope = _real_runtime(tmp_path, ())
    assert runtime.register_configured("hook_handoff", scope, scripts=[]).accepted
    registry = runtime._registry
    recovery = runtime._publication_recovery
    _, owner = registry.configured_plan(scope.scope_id, "hook_handoff")
    original = recovery.reserve_deferred
    primary = KeyboardInterrupt("after " + operation)
    fired = False
    tickets = []
    function = HookRegistry.handoff_deferred_scope
    lines, first = inspect.getsourcelines(function)
    boundary = first + next(index for index, line in enumerate(lines)
                            if "self._state =" in line)
    previous = sys.gettrace()

    def reserve(*args):
        """Record exact real tickets and interrupt the first return when selected."""
        nonlocal fired
        result = original(*args)
        tickets.append(result)
        if operation == "reservation_return" and not fired:
            fired = True
            raise primary
        return result

    def trace(frame, event, argument):
        """Interrupt before withdrawal publication without altering frame data."""
        nonlocal fired
        if (operation == "withdrawal" and not fired and frame.f_code is function.__code__
                and event == "line" and frame.f_lineno == boundary):
            fired = True
            raise primary
        return trace

    monkeypatch.setattr(recovery, "reserve_deferred", reserve)
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            scope.close()
        assert caught.value is primary and fired
    finally:
        sys.settrace(previous)
    try:
        assert registry.deferred_scope_count(scope.scope_id) == 1
        assert len(recovery._entries) == 1
        ticket = tickets[0]
        assert recovery._entries[id(ticket)] == (ticket, owner)
        assert not recovery.release(ticket)
        assert not recovery.settle(ticket)
        scope.close()
        assert tickets == [ticket, ticket]
        assert registry.deferred_scope_count(scope.scope_id) == 0
        assert recovery._entries == {}
        assert not recovery.release(ticket)
        assert owner.cleanup_debts() == ()
        assert runtime.cleanup_debts() == ()
        assert scope.close().already_closed
    finally:
        monkeypatch.setattr(recovery, "reserve_deferred", original)
        runtime.close()


def test_publication_return_interruption_retains_previous_owner(tmp_path, monkeypatch):
    """A committed replacement interrupted before return must not orphan old bytes."""
    first = _protocol_script(tmp_path / "sources" / "first.py", "first")
    second = _protocol_script(tmp_path / "sources" / "second.py", "second")
    runtime, scope = _real_runtime(tmp_path, (first, second))
    assert runtime.register_configured("hook_replace_gap", scope, scripts=(first,)).accepted
    registry = runtime._registry
    _, old = registry.configured_plan(scope.scope_id, "hook_replace_gap")
    old_paths = tuple(item.captured_path for item in old.snapshot.plan.default_script_hook.scripts)
    original = registry.publish_hook_point
    primary = KeyboardInterrupt("committed publication return gap")

    def publish(*args, **kwargs):
        """Run real publication then interrupt before Runtime receives its result."""
        result = original(*args, **kwargs)
        assert result.changed and result.previous is old
        raise primary

    monkeypatch.setattr(registry, "publish_hook_point", publish)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            runtime.register_configured("hook_replace_gap", scope, scripts=(second,))
        assert caught.value is primary
        _, new = registry.configured_plan(scope.scope_id, "hook_replace_gap")
        assert new is not old and new.snapshot.active_version == 2
        debts = runtime.cleanup_debts()
        assert debts
        for debt in debts:
            assert runtime.retry_cleanup(debt.debt_id)
        assert all(not path.exists() for path in old_paths)
        assert registry.configured_plan(scope.scope_id, "hook_replace_gap")[1] is new
    finally:
        monkeypatch.setattr(registry, "publish_hook_point", original)
        old.retire()
        runtime.close()


@pytest.mark.parametrize("method,marker", (
    ("defer_configured_scope", "state = self._state"),
    ("defer_configured_scope", "configured = {"),
    ("defer_configured_scope", "deferred = dict"),
    ("defer_configured_scope", "deferred.update"),
    ("defer_configured_scope", "self._state ="),
    ("handoff_deferred_scope", "state = self._state"),
    ("handoff_deferred_scope", "key = next"),
    ("handoff_deferred_scope", "owner = state.deferred"),
    ("handoff_deferred_scope", "ticket = recovery"),
    ("handoff_deferred_scope", "if ticket is None"),
    ("handoff_deferred_scope", "deferred = dict"),
    ("handoff_deferred_scope", "del deferred[key]"),
    ("handoff_deferred_scope", "self._state ="),
    ("handoff_deferred_scope", "return ticket"),
))
def test_deferred_close_boundary_matrix_converges(tmp_path, method, marker):
    """Interrupt real mutation/handoff lines once and prove bounded exact convergence."""
    import inspect
    from topsailai.hooks.registry import HookRegistry
    runtime, scope = _real_runtime(tmp_path, ())
    registry = runtime._registry
    recovery = runtime._publication_recovery
    assert runtime.register_configured("hook_boundary", scope, scripts=[]).accepted
    _, owner = registry.configured_plan(scope.scope_id, "hook_boundary")
    function = getattr(HookRegistry, method)
    lines, first = inspect.getsourcelines(function)
    boundary = first + next(index for index, line in enumerate(lines) if marker in line)
    primary = KeyboardInterrupt(method + marker)
    previous = sys.gettrace()
    fired = False

    def trace(frame, event, argument):
        """Use only frame identity and line position, never mutate locals or closures."""
        nonlocal fired
        if not fired and frame.f_code is function.__code__ and event == "line" and frame.f_lineno == boundary:
            fired = True
            raise primary
        return trace

    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            scope.close()
        assert caught.value is primary and fired
    finally:
        sys.settrace(previous)
    try:
        assert len(recovery._entries) <= recovery.capacity
        assert all(current is owner for ticket, current in recovery._entries.values())
        assert len({id(current) for ticket, current in recovery._entries.values()}) == len(recovery._entries)
        active = registry.configured_scope_owners(scope.scope_id)
        deferred = registry.deferred_scope_count(scope.scope_id)
        assert len(active) + deferred <= 1
        assert active == () or active == (owner,)
        for _ in range(3):
            scope.close()
            for debt in runtime.cleanup_debts():
                assert runtime.retry_cleanup(debt.debt_id)
        assert registry.configured_scope_owners(scope.scope_id) == ()
        assert registry.deferred_scope_count(scope.scope_id) == 0
        assert recovery._entries == {}
        assert owner.settled
        assert runtime.cleanup_debts() == ()
    finally:
        runtime.close()


def test_publication_recovery_guards_and_pending_retry(tmp_path):
    """Validate exact ticket guards and pending disposal without synthetic process claims."""
    import copy
    import threading
    from topsailai.hooks.artifact_contracts import ArtifactDisposeResult
    from topsailai.hooks.process_state import CleanupDebt
    from topsailai.hooks.hook_point_plan_publication import PublicationRecovery
    for capacity in (0, 129, True):
        with pytest.raises(ValueError):
            PublicationRecovery(threading.RLock(), capacity)
    runtime, scope = _real_runtime(tmp_path, ())
    recovery = runtime._publication_recovery
    ticket = recovery.reserve()
    clone = copy.copy(ticket)
    attempts = []

    class PendingOwner:
        """Expose a controlled cleanup contract, not a fake physical process."""
        settled = False
        pending = True

        def cleanup_debts(self):
            """Advertise one exact selected underlying debt while pending."""
            return (CleanupDebt("exact-pending", "artifact_pending", None, "pending"),) if self.pending else ()

        def retry_cleanup(self, debt_id):
            """Reject the first exact retry, then settle on the next one."""
            attempts.append(debt_id)
            if len(attempts) == 1:
                return False
            self.pending = False
            return True

        def close(self):
            """Assert duplicate disposal cannot enter while this owner is busy."""
            assert not runtime._lock._is_owned()
            assert not recovery.settle(ticket)
            assert not recovery.handoff(ticket)
            return ArtifactDisposeResult(not self.pending, cleanup_pending=self.pending)

    owner = PendingOwner()
    try:
        assert not runtime.retry_cleanup(None)
        assert not recovery.retry_cleanup(None)
        assert not recovery.bind(clone, owner)
        assert not recovery.bind(ticket, None)
        assert not recovery.handoff(clone)
        assert not recovery.settle(ticket)
        assert recovery.bind(ticket, owner)
        assert not recovery.bind(ticket, owner)
        assert not recovery.settle(ticket)
        assert not recovery.retry_cleanup("foreign")
        assert not recovery.retry_cleanup("exact-pending")
        assert recovery.retry_cleanup("exact-pending")
        assert attempts == ["exact-pending", "exact-pending"]
        assert not recovery.settle(ticket)
        assert recovery._entries == {}
    finally:
        runtime.close()


def test_point_retirement_return_gap_keeps_exact_owner(tmp_path, monkeypatch):
    """Committed removal interrupted before return must retain exact disposal custody."""
    runtime, scope = _real_runtime(tmp_path, ())
    assert runtime.register_configured("hook_retire_gap", scope, scripts=[]).accepted
    registry = runtime._registry
    _, owner = registry.configured_plan(scope.scope_id, "hook_retire_gap")
    original = registry.remove_configured
    primary = KeyboardInterrupt("retirement return boundary")

    def remove(*args, **kwargs):
        """Interrupt after actual removal, not a fabricated membership update."""
        removed = original(*args, **kwargs)
        assert removed is owner
        raise primary

    monkeypatch.setattr(registry, "remove_configured", remove)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            runtime.retire_configured("hook_retire_gap", scope)
        assert caught.value is primary
        assert registry.configured_plan(scope.scope_id, "hook_retire_gap")[1] is None
        debts = runtime.cleanup_debts()
        assert len(debts) == 1
        assert next(iter(runtime._publication_recovery._entries.values()))[1] is owner
        assert runtime.retry_cleanup(debts[0].debt_id)
        assert owner.settled
        assert runtime._publication_recovery._entries == {}
    finally:
        monkeypatch.setattr(registry, "remove_configured", original)
        owner.retire()
        runtime.close()


def test_execution_token_return_gap_releases_exact_retention(tmp_path, monkeypatch):
    """A committed cleanup token must remain reachable before its caller receives it."""
    import time
    import topsailai.hooks.configured_runtime as configured
    script = _protocol_script(tmp_path / "sources" / "hook.py", "return-gap")
    runtime, scope = _real_runtime(tmp_path, (script,))
    registry = runtime._registry
    assert runtime.register_configured("hook_token_gap", scope, scripts=(script,)).accepted
    reader = registry.acquire_hook_point(scope.scope_id, "hook_token_gap")
    owner = reader.owner
    paths = tuple(entry.source_path for entry in owner.entries)
    admission = configured._ConfiguredAdmission(_event(runtime, scope), owner,
        registry.generation, 1000, time.monotonic(), reader=reader, registry=registry)
    original = registry.retain_hook_point_cleanup
    primary = KeyboardInterrupt("after exact cleanup token registration")
    retained = []

    def retain(*args, **kwargs):
        """Commit through the real production seam, then interrupt its return."""
        token = original(*args, **kwargs)
        retained.append(token)
        raise primary

    try:
        monkeypatch.setattr(registry, "retain_hook_point_cleanup", retain)
        with pytest.raises(KeyboardInterrupt) as caught:
            configured._execute_configured(runtime, admission)
        assert caught.value is primary and len(retained) == 1
        assert retained[0] is not None
        assert runtime.retire_configured("hook_token_gap", scope)
        for debt in runtime.cleanup_debts():
            runtime.retry_cleanup(debt.debt_id)
        assert owner.settled
        assert all(not path.exists() for path in paths)
        assert runtime.cleanup_debts() == ()
        assert not registry.release_hook_point_cleanup(retained[0])
    finally:
        registry.release_hook_point_cleanup(retained[0]) if retained else None
        admission.release()
        runtime.close()


def test_admission_reader_return_gap_does_not_leak_owner(tmp_path, monkeypatch):
    """A reader committed before acquisition returns must remain in caller custody."""
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _real_runtime(tmp_path, ())
    registry = runtime._registry
    assert runtime.register_configured("hook_reader_gap", scope, scripts=[]).accepted
    _, owner = registry.configured_plan(scope.scope_id, "hook_reader_gap")
    original = registry.acquire_hook_point
    primary = KeyboardInterrupt("after exact reader registration")
    readers = []

    def acquire(*args, **kwargs):
        """Interrupt after the real same-lock acquisition has committed."""
        reader = original(*args, **kwargs)
        readers.append(reader)
        raise primary

    try:
        monkeypatch.setattr(registry, "acquire_hook_point", acquire)
        with pytest.raises(KeyboardInterrupt) as caught:
            configured._admit_configured(runtime, "hook_reader_gap", _event(runtime, scope), None, True)
        assert caught.value is primary and len(readers) == 1
        assert runtime.retire_configured("hook_reader_gap", scope)
        for debt in runtime.cleanup_debts():
            runtime.retry_cleanup(debt.debt_id)
        assert owner.settled
        assert runtime.cleanup_debts() == ()
        assert not registry.release_hook_point(readers[0])
    finally:
        for reader in readers:
            registry.release_hook_point(reader)
        runtime.close()


@pytest.mark.parametrize("primary_type,secondary_type", ((KeyboardInterrupt, OSError), (ValueError, OSError), (ValueError, SystemExit), (KeyboardInterrupt, SystemExit)))
def test_admission_secondary_release_failure_preserves_primary(tmp_path, monkeypatch, primary_type, secondary_type):
    """Real admission/release commits retain primary identity and native traceback."""
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _real_runtime(tmp_path, ())
    registry = runtime._registry
    assert runtime.register_configured("hook_primary", scope, scripts=[]).accepted
    _, owner = registry.configured_plan(scope.scope_id, "hook_primary")
    acquire_original = registry.acquire_hook_point
    release_original = registry.release_hook_point
    primary = primary_type("admission primary")
    secondary = secondary_type("release secondary")
    cleanup_wins = isinstance(primary, Exception) and not isinstance(secondary, Exception)
    expected = secondary if cleanup_wins else primary
    lock_observations = []

    def acquire(*args, **kwargs):
        """Commit a genuine armed reader before raising the primary interruption."""
        acquire_original(*args, **kwargs)
        raise primary

    def release(reader):
        """Commit real release, then fail at its public return boundary."""
        lock_observations.append(runtime._lock._is_owned())
        assert release_original(reader)
        raise secondary

    try:
        monkeypatch.setattr(registry, "acquire_hook_point", acquire)
        monkeypatch.setattr(registry, "release_hook_point", release)
        with pytest.raises(type(expected)) as caught:
            configured._admit_configured(runtime, "hook_primary", _event(runtime, scope), None, True)
        assert caught.value is expected
        frames = []
        traceback = caught.value.__traceback__
        while traceback is not None:
            frames.append(traceback.tb_frame.f_code)
            traceback = traceback.tb_next
        assert (release.__code__ if cleanup_wins else acquire.__code__) in frames
        assert lock_observations == [False]
        diagnostic = primary if cleanup_wins else secondary
        assert expected.__context__ is diagnostic
        assert diagnostic.__context__ is not expected
        assert runtime.retire_configured("hook_primary", scope)
        assert owner.settled and runtime.cleanup_debts() == ()
    finally:
        runtime.close()


def test_registration_one_remaining_slot_preserves_capacity_without_capture(tmp_path, monkeypatch):
    """Publication requires both candidate and previous-owner slots before capture."""
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _real_runtime(tmp_path, ())
    recovery = runtime._publication_recovery
    tickets = [recovery.reserve() for _ in range(recovery.capacity - 1)]
    calls = []

    def forbidden(*args, **kwargs):
        """Record unexpected capture; capacity rejection must precede this boundary."""
        calls.append(True)
        raise AssertionError("capture after capacity rejection")

    try:
        monkeypatch.setattr(configured, "_capture_plan", forbidden)
        result = runtime.register_configured("hook_slot", scope, scripts=[])
        assert result.errors == ("publication_capacity_exceeded",)
        assert calls == []
        assert len(recovery._entries) == recovery.capacity - 1
        assert registry_absent(runtime, scope, "hook_slot")
        last = recovery.reserve()
        assert last is not None
        assert not runtime.retire_configured("hook_slot", scope)
        assert recovery.release(last)
    finally:
        for ticket in tickets:
            assert recovery.release(ticket)
        runtime.close()


def registry_absent(runtime, scope, name):
    """Observe exact absent membership without introducing another authority."""
    return runtime._registry.configured_plan(scope.scope_id, name)[1] is None


def test_scope_closed_after_real_capture_rejects_and_disposes(tmp_path, monkeypatch):
    """Scope closure after real candidate build is revalidated before publication."""
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _real_runtime(tmp_path, ())
    original = configured._capture_plan
    owners = []

    def capture(*args, **kwargs):
        """Complete the real capture, then close its admission scope before returning."""
        result = original(*args, **kwargs)
        owners.append(result[0])
        scope.close()
        return result

    try:
        monkeypatch.setattr(configured, "_capture_plan", capture)
        result = runtime.register_configured("hook_closed", scope, scripts=[])
        assert result.errors == ("scope_closed",)
        assert registry_absent(runtime, scope, "hook_closed")
        assert len(owners) == 1
        with pytest.raises(RuntimeError):
            _ = owners[0].plan
        assert runtime.cleanup_debts() == ()
        assert runtime._publication_recovery._entries == {}
    finally:
        runtime.close()


def test_execution_custody_retry_requires_completed_exact_runner_debt(tmp_path):
    """Uncompleted execution and foreign runner debts cannot authorize cleanup retry."""
    from topsailai.hooks.hook_point_plan_publication import ExecutionCleanupCustody
    runtime, scope = _real_runtime(tmp_path, ())
    custody = ExecutionCleanupCustody(runtime._registry, None)
    try:
        assert not custody.retry_cleanup("foreign")
        assert custody.cleanup_debts() == ()
        assert custody.close().cleanup_pending
        custody.completed = True
        assert not custody.retry_cleanup("foreign")
        assert custody.cleanup_debts() == ()

        class Runner:
            """Expose an empty legitimate debt contract, not a fake process outcome."""
            def cleanup_debts(self):
                """Report no owned process debt."""
                return ()
            def retry_cleanup(self, debt_id):
                """Foreign retry must never reach the runner."""
                raise AssertionError("foreign runner retry")

        custody.runner = Runner()
        assert not custody.retry_cleanup("foreign")
        assert custody.close().accepted
        assert custody.close().accepted
    finally:
        runtime.close()


@pytest.mark.parametrize("failure", ("rejected", "exception"))
def test_publication_failure_retains_old_exact_plan(tmp_path, monkeypatch, failure):
    """Real built candidates rejected before swap cannot change old membership."""
    from topsailai.hooks.hook_point_plan_ownership import HookPointPublicationResult
    runtime, scope = _real_runtime(tmp_path, ())
    registry = runtime._registry
    assert runtime.register_configured("hook_failure", scope, scripts=[]).accepted
    generation, owner = registry.configured_plan(scope.scope_id, "hook_failure")

    def fail(*args, **kwargs):
        """Inject a publication decision failure before any actual Registry mutation."""
        if failure == "exception":
            raise ValueError("publication failure")
        return HookPointPublicationResult(False, False, generation, owner.snapshot)

    try:
        monkeypatch.setattr(registry, "publish_hook_point", fail)
        result = runtime.register_configured("hook_failure", scope, scripts=[])
        assert result.errors == ("artifact_rejected",)
        assert registry.configured_plan(scope.scope_id, "hook_failure") == (generation, owner)
        for debt in runtime.cleanup_debts():
            runtime.retry_cleanup(debt.debt_id)
        assert runtime.cleanup_debts() == ()
    finally:
        runtime.close()


def test_point_removal_precommit_interrupt_withdraws_recovery(tmp_path, monkeypatch):
    """An interruption before removal leaves active ownership and no duplicate ticket."""
    runtime, scope = _real_runtime(tmp_path, ())
    registry = runtime._registry
    assert runtime.register_configured("hook_precommit", scope, scripts=[]).accepted
    before = registry.configured_plan(scope.scope_id, "hook_precommit")
    primary = KeyboardInterrupt("before removal")
    original = registry.remove_configured

    def interrupt(*args, **kwargs):
        """Fail before the real removal; active membership remains authoritative."""
        raise primary

    try:
        monkeypatch.setattr(registry, "remove_configured", interrupt)
        with pytest.raises(KeyboardInterrupt) as caught:
            runtime.retire_configured("hook_precommit", scope)
        assert caught.value is primary
        assert registry.configured_plan(scope.scope_id, "hook_precommit") == before
        assert runtime._publication_recovery._entries == {}
        monkeypatch.setattr(registry, "remove_configured", original)
        assert runtime.retire_configured("hook_precommit", scope)
        assert before[1].settled
    finally:
        runtime.close()


def test_admission_release_precommit_interrupt_remains_retryable(tmp_path, monkeypatch):
    """A failed exact-reader release cannot consume admission's sole retry authority."""
    import threading
    import time
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _real_runtime(tmp_path, ())
    registry = runtime._registry
    assert runtime.register_configured("hook_release", scope, scripts=[]).accepted
    generation, owner = registry.configured_plan(scope.scope_id, "hook_release")
    reader = registry.acquire_hook_point(scope.scope_id, "hook_release")
    admission = configured._ConfiguredAdmission(_event(runtime, scope), owner,
        generation, 1000, time.monotonic(), reader=reader, registry=registry,
        release_lock=threading.Lock())
    original = registry.release_hook_point
    primary = KeyboardInterrupt("reader release before commit")
    attempts = []

    def release(token):
        """Interrupt one real release call before mutation, then allow reconciliation."""
        attempts.append(token)
        if len(attempts) == 1:
            raise primary
        return original(token)

    try:
        monkeypatch.setattr(registry, "release_hook_point", release)
        assert runtime.retire_configured("hook_release", scope)
        with pytest.raises(KeyboardInterrupt) as caught:
            admission.release()
        assert caught.value is primary
        admission.release()
        assert attempts == [reader, reader]
        for debt in runtime.cleanup_debts():
            runtime.retry_cleanup(debt.debt_id)
        assert owner.settled and runtime.cleanup_debts() == ()
        admission.release()
        assert len(attempts) == 2
    finally:
        original(reader)
        runtime.close()


@pytest.mark.parametrize("release_failure", (False, True))
@pytest.mark.parametrize("primary_type,cleanup_type", ((KeyboardInterrupt, OSError), (ValueError, OSError), (ValueError, SystemExit), (KeyboardInterrupt, SystemExit)))
def test_execution_finally_preserves_primary_and_attempts_both_cleanup(tmp_path, monkeypatch, primary_type, cleanup_type, release_failure):
    """Execution failures retain native evidence while both real cleanup seams run."""
    import time
    import topsailai.hooks.configured_runtime as configured
    script = _protocol_script(tmp_path / "sources" / "hook.py", "finally-priority")
    runtime, scope = _real_runtime(tmp_path, (script,))
    registry = runtime._registry
    assert runtime.register_configured("hook_finally", scope, scripts=(script,)).accepted
    reader = registry.acquire_hook_point(scope.scope_id, "hook_finally")
    admission = configured._ConfiguredAdmission(_event(runtime, scope), reader.owner,
        registry.generation, 1000, time.monotonic(), reader=reader, registry=registry)
    primary, cleanup = primary_type("execution primary"), cleanup_type("cleanup secondary")
    expected = cleanup if isinstance(primary, Exception) and not isinstance(cleanup, Exception) else primary
    settle_original = runtime._publication_recovery.settle
    release_original = registry.release_hook_point
    observations = []

    def execute(**kwargs):
        """Raise at the actual execution boundary without launching a subprocess."""
        raise primary

    def settle(ticket):
        """Commit exact cleanup before injecting its return-boundary failure."""
        observations.append(("settle", runtime._lock._is_owned()))
        monkeypatch.setattr(runtime._publication_recovery, "settle", settle_original)
        settle_original(ticket)
        raise cleanup

    def release(token):
        """Release the real reader even when the previous cleanup failed."""
        observations.append(("release", runtime._lock._is_owned()))
        result = release_original(token)
        if release_failure:
            monkeypatch.setattr(registry, "release_hook_point", release_original)
            raise OSError("reader return failure")
        return result

    try:
        monkeypatch.setattr(configured, "execute_configured_hook_script", execute)
        monkeypatch.setattr(runtime._publication_recovery, "settle", settle)
        monkeypatch.setattr(registry, "release_hook_point", release)
        with pytest.raises(type(expected)) as caught:
            configured._execute_configured(runtime, admission)
        assert caught.value is expected
        frames = []
        traceback = caught.value.__traceback__
        while traceback is not None:
            frames.append(traceback.tb_frame.f_code)
            traceback = traceback.tb_next
        assert (settle.__code__ if expected is cleanup else execute.__code__) in frames
        assert observations == [("settle", False), ("release", False)]
        assert admission.released is not release_failure
        admission.release()
        assert runtime.retire_configured("hook_finally", scope)
        assert reader.owner.settled
    finally:
        monkeypatch.setattr(runtime._publication_recovery, "settle", settle_original)
        admission.release()
        runtime.close()


@pytest.mark.parametrize("target_return", [1, 2])
def test_registration_reservation_return_restores_capacity(tmp_path, target_return):
    """Interrupt the real return after journal mutation without forging authority."""
    from topsailai.hooks.hook_point_plan_publication import PublicationRecovery

    runtime, scope = _runtime(tmp_path)
    recovery = runtime._publication_recovery
    primary = KeyboardInterrupt("real reservation return gap")
    previous_trace = sys.gettrace()
    observed = []
    armed = True

    def trace(frame, event, arg):
        """Deliver exactly once at the real reserve function return event."""
        nonlocal armed
        if armed and frame.f_code is PublicationRecovery.reserve.__code__ and event == "return":
            observed.append(event)
            if len(observed) == target_return:
                armed = False
                raise primary
        return trace

    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            runtime.register_configured("hook_reservation_gap", scope, scripts=[])
        sys.settrace(previous_trace)
        assert caught.value is primary
        assert len(observed) == target_return
        assert runtime._registry.generation == 0
        assert runtime._registry.configured_plan(scope.scope_id, "hook_reservation_gap")[1] is None
        entries = tuple(recovery._entries.values())
        debts = runtime.cleanup_debts()
        assert entries == (), f"lost {len(entries)} empty reservations; visible debts={debts!r}"
    finally:
        sys.settrace(previous_trace)
        for ticket, owner in tuple(recovery._entries.values()):
            if owner is None:
                recovery.release(ticket)
        runtime.close()


def test_retirement_reservation_return_restores_capacity(tmp_path):
    """An interrupted reserve return cannot strand capacity or retire the active plan."""
    from topsailai.hooks.hook_point_plan_publication import PublicationRecovery

    runtime, scope = _runtime(tmp_path)
    recovery = runtime._publication_recovery
    primary = KeyboardInterrupt("retirement reservation return")
    previous_trace = sys.gettrace()
    armed = True
    try:
        assert runtime.register_configured("hook_retirement_gap", scope, scripts=[]).accepted
        generation = runtime._registry.generation
        snapshot, owner = runtime._registry.configured_plan(scope.scope_id, "hook_retirement_gap")
        before = tuple(recovery._entries.values())

        def trace(frame, event, arg):
            """Inject once at the exact real reserve return without changing authority."""
            nonlocal armed
            if armed and frame.f_code is PublicationRecovery.reserve.__code__ and event == "return":
                armed = False
                raise primary
            return trace

        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            runtime.retire_configured("hook_retirement_gap", scope)
        sys.settrace(previous_trace)
        assert caught.value is primary
        assert not armed
        assert runtime._registry.generation == generation
        assert runtime._registry.configured_plan(scope.scope_id, "hook_retirement_gap") == (snapshot, owner)
        entries = tuple(recovery._entries.values())
        debts = runtime.cleanup_debts()
        assert entries == before, f"lost {len(entries) - len(before)} empty reservations; visible debts={debts!r}"
    finally:
        sys.settrace(previous_trace)
        for ticket, owner in tuple(recovery._entries.values()):
            if owner is None:
                recovery.release(ticket)
        runtime.close()


def test_execution_reservation_return_restores_capacity(tmp_path):
    """Real reserve-return interruption releases the reader and exact empty capacity."""
    import time
    import topsailai.hooks.configured_runtime as configured
    from topsailai.hooks.hook_point_plan_publication import PublicationRecovery

    script = _protocol_script(tmp_path / 'sources' / 'hook.py', 'execution-return')
    runtime, scope = _real_runtime(tmp_path, (script,))
    recovery = runtime._publication_recovery
    primary = KeyboardInterrupt('execution reservation return')
    previous_trace = sys.gettrace()
    admission = None
    armed = True
    try:
        assert runtime.register_configured('hook_execution_gap', scope, scripts=(script,)).accepted
        generation = runtime._registry.generation
        snapshot, owner = runtime._registry.configured_plan(scope.scope_id, 'hook_execution_gap')
        before = tuple(recovery._entries.values())
        reader = runtime._registry.acquire_hook_point(scope.scope_id, 'hook_execution_gap')
        admission = configured._ConfiguredAdmission(_event(runtime, scope), owner,
            generation, 1000, time.monotonic(), reader=reader, registry=runtime._registry)

        def trace(frame, event, arg):
            """Inject once on the real reserve return without mutating authority."""
            nonlocal armed
            if armed and frame.f_code is PublicationRecovery.reserve.__code__ and event == 'return':
                armed = False
                raise primary
            return trace

        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            configured._execute_configured(runtime, admission)
        sys.settrace(previous_trace)
        assert caught.value is primary
        assert not armed
        assert admission.released
        assert runtime._registry.generation == generation
        actual_snapshot, actual_owner = runtime._registry.configured_plan(scope.scope_id, 'hook_execution_gap')
        assert actual_snapshot is snapshot and actual_owner is owner
        entries = tuple(recovery._entries.values())
        debts = runtime.cleanup_debts()
        assert entries == before, f'lost {len(entries)-len(before)} empty reservations; visible debts={debts!r}'
    finally:
        sys.settrace(previous_trace)
        for ticket, owner in tuple(recovery._entries.values()):
            if owner is None:
                recovery.release(ticket)
        if admission is not None:
            admission.release()
        runtime.close()


def test_capture_return_has_cleanup_or_reachable_custody(tmp_path):
    """Interrupt the actual adapter return without modifying business authority."""
    import topsailai.hooks.configured_runtime as configured

    script = _protocol_script(tmp_path / 'sources' / 'hook.py', 'capture-return')
    runtime, scope = _real_runtime(tmp_path, (script,))
    primary = KeyboardInterrupt('real capture adapter return')
    previous = sys.gettrace()
    captured = []
    armed = True
    generation = runtime._registry.generation

    def trace(frame, event, result):
        """Observe the real candidate once then interrupt before caller receipt."""
        nonlocal armed
        if armed and frame.f_code is configured._capture_plan.__code__ and event == 'return':
            armed = False
            captured.append(result[0])
            raise primary
        return trace

    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            runtime.register_configured('hook_capture_return', scope, scripts=(script,))
        sys.settrace(previous)
        assert caught.value is primary
        assert not armed and len(captured) == 1
        assert runtime._registry.generation == generation
        assert runtime._registry.configured_plan(scope.scope_id, 'hook_capture_return')[1] is None
        paths = tuple(item.captured_path for item in captured[0].plan.default_script_hook.scripts)
        assert paths
        debts = runtime.cleanup_debts()
        entries = tuple(runtime._publication_recovery._entries.values())
        assert all(not path.exists() for path in paths) or (debts and any(owner is captured[0] for _, owner in entries)), f'live captured bytes={[str(p) for p in paths if p.exists()]}; entries={entries!r}; debts={debts!r}'
    finally:
        sys.settrace(previous)
        for candidate in captured:
            candidate.close()
        runtime.close()
