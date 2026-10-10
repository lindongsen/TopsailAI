"""Tests for the simple scope-local configured Hook Runtime API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

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
async def test_async_and_background_execution_share_the_registered_plan(
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
        receipt = runtime.emit_configured("hook_after_chat", event)

        assert report.rejection_reason is None
        assert report.outcomes == ()
        assert receipt.admitted
        assert receipt.event_id == event.event_id
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

        folder = runtime.register_configured(
            "hook_real_order", scope, folder=tmp_path / "sources"
        )
        assert folder.accepted and folder.changed
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
    try:
        assert runtime.register_configured(
            "hook_overlap", scope, scripts=(blocking,)
        ).accepted
        _, old_plan = runtime._registry.configured_plan(scope.scope_id, "hook_overlap")
        old_artifact = old_plan.entries[0].source_path.parents[1]
        receipt = runtime.emit_configured(
            "hook_overlap", _real_event(runtime, scope, log, gate)
        )
        assert receipt.admitted
        _wait_for(lambda: log.exists())

        changed = runtime.register_configured(
            "hook_overlap", scope, scripts=(replacement,)
        )
        assert changed.accepted and changed.changed
        assert old_artifact.exists()
        assert old_plan._readers == 1

        gate.touch()
        _wait_for(lambda: old_plan._readers == 0)
        _wait_for(lambda: not old_artifact.exists())
        assert old_plan.owner is None
    finally:
        runtime.close()


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
    try:
        assert runtime.register_configured(
            "hook_deadline", scope, scripts=(blocking,)
        ).accepted
        _, plan = runtime._registry.configured_plan(scope.scope_id, "hook_deadline")
        first = runtime.emit_configured(
            "hook_deadline", _real_event(runtime, scope, log, gate)
        )
        assert first.admitted
        _wait_for(lambda: log.exists())

        expired = runtime.dispatch_configured(
            "hook_deadline",
            _real_event(runtime, scope, log, gate),
            policy={"timeout_ms": 20},
        )
        assert expired.rejection_reason == "deadline"
        assert expired.deadline_exhausted
        assert plan._readers == 1

        gate.touch()
        _wait_for(lambda: plan._readers == 0)
    finally:
        runtime.close()


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
    try:
        assert runtime.register_configured(
            "hook_cancel", scope, scripts=(blocking,)
        ).accepted
        _, plan = runtime._registry.configured_plan(scope.scope_id, "hook_cancel")
        artifact = plan.entries[0].source_path.parents[1]
        assert runtime.emit_configured(
            "hook_cancel", _real_event(runtime, scope, log, gate)
        ).admitted
        _wait_for(lambda: log.exists())
        assert runtime.emit_configured(
            "hook_cancel", _real_event(runtime, scope, log, gate)
        ).admitted
        _wait_for(lambda: plan._readers == 2)

        scope.close()
        assert plan._readers == 1
        assert artifact.exists()
        gate.touch()
        _wait_for(lambda: plan._readers == 0)
        _wait_for(lambda: not artifact.exists())
        assert plan.owner is None
    finally:
        gate.touch()
        runtime.close()


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
