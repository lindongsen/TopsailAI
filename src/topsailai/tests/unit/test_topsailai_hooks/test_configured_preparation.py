"""Focused U09-B configured preparation regressions."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import uuid
from pathlib import Path

import pytest

from topsailai.hooks import (
    ArtifactClosureAssertion,
    ArtifactPythonRuntimeAuthority,
    ConfiguredHookPoint,
    ConfiguredHooks,
    ConfiguredTrustPolicy,
    EventDefinition,
    HookRuntime,
    HookSettings,
)
from topsailai.hooks.artifact_identity import python_runtime_fingerprint, shebang_runtime_fingerprint
from topsailai.hooks.configured_preparation import prepare_private


_PHASE_B_ROOT = Path("/TopsailAI/src/topsailai/.tmp/u09-b-phase-b/tests")


@pytest.fixture
def secure_test_root():
    """Provide one owner-only source/runtime tree beneath the task workspace."""
    base = _PHASE_B_ROOT.resolve()
    base.mkdir(parents=True, exist_ok=True)
    test_root = base / f"main-{uuid.uuid4().hex}"
    test_root.mkdir(mode=0o700)
    sources = test_root / "sources"
    runtime = test_root / "runtime"
    sources.mkdir(mode=0o700)
    runtime.mkdir(mode=0o700)
    root_status = test_root.lstat()
    for directory in (test_root, sources, runtime):
        status = directory.lstat()
        assert directory.resolve().is_relative_to(base)
        assert directory.is_dir() and not directory.is_symlink()
        assert status.st_uid == os.geteuid()
        assert (status.st_mode & 0o777) == 0o700
    pinned_root = (root_status.st_dev, root_status.st_ino, root_status.st_uid, stat.S_IFMT(root_status.st_mode))
    try:
        yield sources, runtime, test_root
    finally:
        current = test_root.lstat()
        current_identity = (current.st_dev, current.st_ino, current.st_uid, stat.S_IFMT(current.st_mode))
        assert current_identity == pinned_root, "test root identity changed; refusing cleanup"
        for path in sorted(test_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_file() or path.is_symlink():
                print(f"Deleted configured preparation test file: {path}")
                path.unlink()
            elif path.is_dir():
                print(f"Deleted configured preparation test directory: {path}")
                path.rmdir()
        print(f"Deleted configured preparation test directory: {test_root}")
        test_root.rmdir()


def _runtime(source_root: Path, runtime_root: Path, *, settings: HookSettings | None = None) -> tuple[HookRuntime, object]:
    """Create one trusted runtime with explicit secure source and temp roots."""
    source_root = source_root.resolve(strict=True)
    runtime_root = runtime_root.resolve(strict=True)
    executable = Path(sys.executable).resolve(strict=True)
    executable_bytes = executable.read_bytes()
    executable_digest = hashlib.sha256(executable_bytes).hexdigest()
    status = executable.stat()
    runtime_digest = python_runtime_fingerprint(
        executable,
        executable_digest,
        device=status.st_dev,
        inode=status.st_ino,
    )
    trust = ConfiguredTrustPolicy(
        (source_root,),
        python_runtime=ArtifactPythonRuntimeAuthority(executable, executable_digest),
    )
    runtime = HookRuntime(
        HookSettings() if settings is None else settings,
        temp_root=str(runtime_root),
        configured_trust=trust,
    )
    return runtime, runtime.open_scope()


def _assertion(source: Path, logical_name: str, kind: str = "python_source") -> ArtifactClosureAssertion:
    """Create the exact source assertion required by U07 capture."""
    content = source.read_bytes()
    executable = Path(sys.executable).resolve(strict=True)
    executable_status = executable.stat()
    executable_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    if kind == "script":
        runtime_digest = shebang_runtime_fingerprint(
            executable,
            executable_digest,
            device=executable_status.st_dev,
            inode=executable_status.st_ino,
        )
    else:
        runtime_digest = python_runtime_fingerprint(
            executable,
            executable_digest,
            device=executable_status.st_dev,
            inode=executable_status.st_ino,
        )
    return ArtifactClosureAssertion(
        source, kind, logical_name, hashlib.sha256(content).hexdigest(),
        runtime_digest, "0" * 64,
    )


def test_empty_configuration_produces_private_unpublished_image(secure_test_root) -> None:
    """Empty trusted configuration is prepared without changing Runtime state."""
    sources, runtime_root, test_root = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    try:
        configuration = ConfiguredHooks((), HookSettings())
        generation = runtime._registry.generation
        image = prepare_private(runtime, configuration, scope)
        assert image.accepted
        assert image.plans == ()
        assert image.generation == generation
        assert image.close().accepted
        assert runtime._registry.generation == generation
    finally:
        runtime.close()


def test_module_failure_is_retained_without_calling_main(secure_test_root) -> None:
    """A recognized module with no callable main remains a planned failure."""
    sources, runtime_root, test_root = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    source = sources / "broken.py"
    source.write_text("called = False\n", encoding="utf-8")
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(
        trust.source_roots,
        closure_assertions=(_assertion(source, "broken"),),
        python_runtime=trust.python_runtime,
    )
    point = ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=source.parent)
    try:
        image = prepare_private(runtime, ConfiguredHooks((point,), HookSettings()), scope)
        assert image.accepted, image.errors
        assert image.plans[0].module_failures
        assert image.plans[0].module_failures[0].category == "invalid_entry"
        assert image.close().accepted
    finally:
        runtime.close()


def test_invalid_scope_is_rejected_without_private_allocation(secure_test_root) -> None:
    """Private preparation rejects a foreign scope before filesystem work."""
    sources, runtime_root, test_root = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    other_root = test_root / "other-sources"
    other_root.mkdir(mode=0o700)
    other_runtime_root = test_root / "runtime-other"
    other_runtime_root.mkdir(mode=0o700)
    other, foreign = _runtime(other_root, other_runtime_root)
    try:
        result = prepare_private(runtime, ConfiguredHooks((), HookSettings()), foreign)
        assert not result.accepted
        assert result.errors == ("invalid_scope",)
    finally:
        runtime.close()
        other.close()


def test_probe_uses_captured_bytes_after_source_replacement(secure_test_root) -> None:
    """Preparation probes the sealed artifact rather than the mutable source."""
    sources, runtime_root, test_root = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    source = sources / "stable.py"
    source.write_text("def main(*args, **kwargs):\n    return 'captured'\n", encoding="utf-8")
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(
        trust.source_roots,
        closure_assertions=(_assertion(source, "stable"),),
        python_runtime=trust.python_runtime,
    )
    point = ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=source.parent)
    try:
        original = source.read_bytes()
        image = prepare_private(runtime, ConfiguredHooks((point,), HookSettings()), scope)
        source.write_bytes(b"def main(*args, **kwargs):\n    return 'replaced'\n")
        assert image.accepted, image.errors
        assert image.plans[0].module_failures == ()
        assert source.read_bytes() != original
        assert image.close().accepted
    finally:
        runtime.close()


def test_preparation_cancellation_releases_candidate_resources(secure_test_root) -> None:
    """Cancellation rejects preparation without leaving lease cleanup debt."""
    import threading

    sources, runtime_root, test_root = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    cancellation = threading.Event()
    cancellation.set()
    try:
        result = prepare_private(runtime, ConfiguredHooks((), HookSettings()), scope, cancellation=cancellation)
        assert not result.accepted
        assert result.errors == ("cancelled",)
        assert not tuple(runtime._backend.script_temp_root and Path(runtime._backend.script_temp_root).glob("configured-artifacts/*"))
    finally:
        runtime.close()


def test_runtime_active_state_is_unchanged_after_success(secure_test_root) -> None:
    """Successful private preparation does not replace Runtime-owned state."""
    sources, runtime_root, test_root = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    try:
        registry = runtime._registry
        settings = runtime._settings
        backend = runtime._backend
        generation = registry.generation
        result = prepare_private(runtime, ConfiguredHooks((), settings), scope)
        assert result.accepted
        assert runtime._registry is registry
        assert runtime._settings is settings
        assert runtime._backend is backend
        assert runtime._registry.generation == generation
        assert result.close().accepted
    finally:
        runtime.close()


def test_cancellation_is_reported_before_empty_fast_path(secure_test_root, monkeypatch) -> None:
    """A latched cancellation wins without allocating capture resources."""
    import threading

    sources, runtime_root, test_root = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    cancellation = threading.Event()
    cancellation.set()
    from topsailai.hooks.artifact_leases import ArtifactLeaseManager
    called = False

    def fail_if_allocated(manager, *args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("cancelled empty preparation allocated a capture manager")

    monkeypatch.setattr(ArtifactLeaseManager, "begin_candidate", fail_if_allocated)
    try:
        result = prepare_private(runtime, ConfiguredHooks((), HookSettings()), scope, cancellation=cancellation)
        assert not result.accepted
        assert result.errors == ("cancelled",)
        assert not called
    finally:
        runtime.close()

def test_script_preparation_reserves_without_execution(secure_test_root) -> None:
    """Configured script discovery is preparation-only and reserves one terminal slot."""
    import os
    from topsailai.hooks.configured_contracts import ConfiguredScript
    from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy

    sources, runtime_root, test_root = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    executable = Path(sys.executable).resolve(strict=True)
    script = sources / "script.py"
    script.write_text(
        "#!%s\nfrom pathlib import Path\nPath(%r).write_text('executed')\n"
        % (str(executable), str(test_root / "executed")),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | os.X_OK)
    policy = ExecutablePlatformPolicy(platform="posix", allowed_interpreters=(str(executable),))
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(
        trust.source_roots,
        allowed_interpreters=(executable,),
        closure_assertions=(_assertion(script, script.name, "script"),),
        python_runtime=trust.python_runtime,
    )
    point = ConfiguredHookPoint(
        "hook_alpha", EventDefinition("test.alpha", 1),
        script=ConfiguredScript(script, policy),
    )
    try:
        result = prepare_private(runtime, ConfiguredHooks((point,), HookSettings()), scope)
        assert result.accepted, getattr(result, "errors", ())
        assert result.plans[0].binding_ids[-1] == "hook_script"
        assert not (test_root / "executed").exists()
        assert result.close().accepted
    finally:
        runtime.close()


def test_world_writable_source_ancestry_is_rejected_without_successors(secure_test_root) -> None:
    """Configured capture rejects an unsafe source ancestry without publication."""
    sources, runtime_root, test_root = secure_test_root
    unsafe_parent = test_root / "unsafe-parent"
    unsafe_parent.mkdir(mode=0o700)
    unsafe_source = unsafe_parent / "sources"
    unsafe_source.mkdir(mode=0o700)
    source = unsafe_source / "unsafe.py"
    source.write_text("called = False\n", encoding="utf-8")
    unsafe_parent.chmod(0o777)
    runtime, scope = _runtime(unsafe_source, runtime_root)
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(
        trust.source_roots,
        closure_assertions=(_assertion(source, "unsafe"),),
        python_runtime=trust.python_runtime,
    )
    point = ConfiguredHookPoint(
        "hook_alpha", EventDefinition("test.alpha", 1), module_folder=unsafe_source,
    )
    registry = runtime._registry
    entries_before = dict(registry._state.bindings)
    generation_before = registry.generation
    try:
        result = prepare_private(runtime, ConfiguredHooks((point,), HookSettings()), scope)
        assert not result.accepted
        assert result.errors == ("artifact_rejected",)
        assert str(unsafe_source) not in repr(result.errors)
        assert runtime._registry is registry
        assert dict(registry._state.bindings) == entries_before
        assert registry.generation == generation_before
    finally:
        runtime.close()
        unsafe_parent.chmod(0o700)



def test_preparation_budget_aggregates_scan_candidates_and_bytes() -> None:
    """One private budget accounts limits across every configured Hook point."""
    from topsailai.hooks.configured_preparation import _PreparationBudget

    budget = _PreparationBudget(
        max_scanned_entries=3,
        max_candidates=2,
        max_artifact_bytes=10,
    )
    budget.add_scan(2)
    budget.add_candidate()
    budget.add_bytes(4)
    budget.add_scan(1)
    budget.add_candidate()
    budget.add_bytes(6)
    assert budget.scanned_entries == 3
    assert budget.candidates == 2
    assert budget.artifact_bytes == 10
    with pytest.raises(Exception):
        budget.add_scan(1)


def test_scan_limit_is_aggregate_across_configured_hooks(secure_test_root) -> None:
    """One shared scan limit rejects the second Hook without successors."""
    from topsailai.hooks import ConfiguredPreparationPolicy

    sources, runtime_root, _ = secure_test_root
    first_root = sources / "first"
    second_root = sources / "second"
    first_root.mkdir(mode=0o700)
    second_root.mkdir(mode=0o700)
    first = first_root / "first.py"
    second = second_root / "second.py"
    first.write_text("def main(*args, **kwargs):\n    return None\n", encoding="utf-8")
    second.write_text("def main(*args, **kwargs):\n    return None\n", encoding="utf-8")
    runtime, scope = _runtime(sources, runtime_root)
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(
        trust.source_roots,
        closure_assertions=(_assertion(first, "first"), _assertion(second, "second")),
        python_runtime=trust.python_runtime,
    )
    points = (
        ConfiguredHookPoint("hook_first", EventDefinition("test.first", 1), module_folder=first_root),
        ConfiguredHookPoint("hook_second", EventDefinition("test.second", 1), module_folder=second_root),
    )
    configuration = ConfiguredHooks(
        points,
        HookSettings(),
        ConfiguredPreparationPolicy(max_scanned_entries=1),
    )
    registry = runtime._registry
    generation_before = registry.generation
    try:
        result = prepare_private(runtime, configuration, scope)
        assert not result.accepted
        assert result.errors == ("capacity_exceeded",)
        assert registry.generation == generation_before
    finally:
        runtime.close()


def test_global_work_sequence_orders_modules_then_terminal_script(monkeypatch):
    """Global preparation ordering is Hook order, module name order, then script."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation

    candidate = lambda name: SimpleNamespace(logical_name=name, source_path=Path(f"/src/{name}"), kind="python_source")
    points = (
        SimpleNamespace(module_folder=Path("/hook-a"), script=SimpleNamespace(target=Path("/script-a"), platform_policy=object())),
        SimpleNamespace(module_folder=Path("/hook-b"), script=None),
    )
    configuration = SimpleNamespace(hook_points=points, policy=SimpleNamespace(max_scanned_entries=100, max_candidates=100))
    monkeypatch.setattr(preparation, "_discover", lambda point, operation, configuration, preparation_budget: SimpleNamespace(root=point.module_folder, candidates=(candidate("z"), candidate("a"))))
    monkeypatch.setattr(preparation, "discover_hook_script_entries", lambda target, policy: SimpleNamespace(accepted=True, entries=(SimpleNamespace(source_path=target, basename=target.name),)))
    operation = SimpleNamespace(checkpoint=lambda: None)
    budget = preparation._PreparationBudget(max_scanned_entries=100, max_candidates=100, max_artifact_bytes=100)

    works = preparation._build_work_sequence(configuration, operation, budget)

    assert [(type(item).__name__, item.hook_index, getattr(item, "candidate", getattr(item, "entry", None)).logical_name if type(item).__name__ == "_ModuleWork" else item.entry.basename) for item in works] == [
        ("_ModuleWork", 0, "z"), ("_ModuleWork", 0, "a"), ("_ScriptWork", 0, "script-a"),
        ("_ModuleWork", 1, "z"), ("_ModuleWork", 1, "a"),
    ]


def test_capture_batches_have_independent_shards_and_stop_after_failure(monkeypatch):
    """Each consecutive batch owns one manager and a failed batch has no successor."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation

    class FakeManager:
        instances = []

        def __init__(self, **kwargs):
            self.index = len(type(self).instances)
            self.group = SimpleNamespace(index=self.index)
            type(self).instances.append(self)

        def begin_candidate(self, *, deadline):
            return SimpleNamespace(accepted=True, group=self.group)

        def capture(self, group, requests, **kwargs):
            if self.index == 1:
                return SimpleNamespace(accepted=False, lease=None, errors=("failure",))
            entries = tuple(SimpleNamespace(index=i, kind=req.kind, logical_name=req.logical_name,
                validation=SimpleNamespace(source_path=req.source_path), relative_path=f"{i}.bin") for i, req in enumerate(requests))
            lease = SimpleNamespace(entries=entries, directory=Path("/capture"), total_bytes=len(requests), identity=f"lease-{self.index}")
            return SimpleNamespace(accepted=True, lease=lease, errors=())

        def close(self, *, deadline):
            return SimpleNamespace(accepted=True, cleanup_pending=False)

    class FakeRoot:
        def revalidate(self):
            return None

    class FakeOwnership:
        root_owner = FakeRoot()
        shards = []

        def register_shard(self, shard):
            self.shards.append(shard)

    monkeypatch.setattr(preparation, "ArtifactLeaseManager", FakeManager)
    monkeypatch.setattr(preparation, "artifact_capture_trust", lambda trust: trust)
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: self)
    works = tuple(preparation._ModuleWork(0, SimpleNamespace(), Path("/src"), SimpleNamespace(source_path=Path(f"/src/{i}"), kind="python_source", logical_name=str(i))) for i in range(256))
    ownership = FakeOwnership()
    budget = preparation._PreparationBudget(max_scanned_entries=1000, max_candidates=1000, max_artifact_bytes=1000)
    operation = SimpleNamespace(deadline=10**12, checkpoint=lambda: None)

    with pytest.raises(preparation._PreparationRejected, match="artifact_rejected"):
        preparation._capture_work_sequence(works, ownership, Path("/artifacts"), operation, budget, None, None)

    assert len(FakeManager.instances) == 2
    assert [len(shard.leases) for shard in ownership.shards] == [1, 0]


def test_map_capture_batch_rejects_metadata_and_path_escape(tmp_path):
    """The sole positional mapper rejects metadata drift and containment escape."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation
    from topsailai.hooks.configured_preparation import _PreparationRejected, _map_capture_batch

    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    (capture_root / "a.py").write_text("x", encoding="utf-8")
    work = preparation._ModuleWork(0, SimpleNamespace(), Path("/src"), SimpleNamespace(source_path=Path("/src/a.py"), kind="python_source", logical_name="a"))
    request = SimpleNamespace(source_path=Path("/src/a.py"), kind="python_source", logical_name="a")

    escaping = SimpleNamespace(index=0, kind=request.kind, logical_name=request.logical_name,
        validation=SimpleNamespace(source_path=request.source_path), relative_path="../escape")
    lease = SimpleNamespace(entries=(escaping,), directory=capture_root)
    with pytest.raises(_PreparationRejected, match="artifact_rejected"):
        _map_capture_batch((work,), lease)

    mismatch = SimpleNamespace(index=1, kind=request.kind, logical_name=request.logical_name,
        validation=SimpleNamespace(source_path=request.source_path), relative_path="a.py")
    lease = SimpleNamespace(entries=(mismatch,), directory=capture_root)
    with pytest.raises(_PreparationRejected, match="artifact_rejected"):
        _map_capture_batch((work,), lease)


def test_preparation_ownership_uses_stable_tiered_debt_ids():
    """Aggregate cleanup exposes bounded IDs and routes unknown IDs safely."""
    from topsailai.hooks.configured_preparation_ownership import PreparationOwnership

    class Owner:
        def __init__(self):
            self.calls = []
        def cleanup_debts(self):
            return (SimpleDebt("backend-1"),)
        def retry_cleanup(self, debt_id):
            self.calls.append(debt_id)
            return True

    class SimpleDebt:
        def __init__(self, debt_id):
            self.debt_id = debt_id

    from types import SimpleNamespace
    owner = Owner()
    aggregate = PreparationOwnership(None, 10**12)
    aggregate.module_owners.append(owner)
    debts = aggregate.cleanup_debts()
    assert [item.debt_id for item in debts] == ["u03:0:backend-1"]
    assert aggregate.retry_cleanup("unknown") is False
    assert aggregate.retry_cleanup("u03:0:backend-1") is True
    assert owner.calls == ["backend-1"]


def test_preparation_ownership_rejects_duplicate_shard_identity():
    """The aggregate refuses manager/group identity reuse."""
    from topsailai.hooks.configured_preparation_ownership import CaptureShard, PreparationOwnership
    from types import SimpleNamespace

    manager = object()
    group = object()
    aggregate = PreparationOwnership(None, 10**12)
    aggregate.register_shard(CaptureShard(0, manager, group))
    with pytest.raises(RuntimeError, match="cleanup_pending"):
        aggregate.register_shard(CaptureShard(1, manager, object()))
    with pytest.raises(RuntimeError, match="cleanup_pending"):
        aggregate.register_shard(CaptureShard(2, object(), group))


@pytest.mark.parametrize(
    ("work_count", "expected_shapes"),
    ((129, (128, 1)), (256, (128, 128)), (1024, (128,) * 8)),
)
def test_capture_work_sequence_uses_exact_bounded_shard_shapes(monkeypatch, work_count, expected_shapes):
    """Global capture uses one independent shard for every consecutive batch."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation

    class FakeManager:
        instances = []

        def __init__(self, **kwargs):
            self.index = len(type(self).instances)
            self.group = SimpleNamespace(index=self.index)
            type(self).instances.append(self)

        def begin_candidate(self, *, deadline):
            return SimpleNamespace(accepted=True, group=self.group)

        def capture(self, group, requests, **kwargs):
            capture_root = kwargs.pop("capture_root", None)
            directory = Path(kwargs.pop("directory", "/tmp"))
            directory.mkdir(parents=True, exist_ok=True)
            entries = tuple(
                SimpleNamespace(
                    index=index,
                    kind=request.kind,
                    logical_name=request.logical_name,
                    validation=SimpleNamespace(source_path=request.source_path),
                    relative_path=f"{self.index}-{index}.bin",
                )
                for index, request in enumerate(requests)
            )
            for entry in entries:
                (directory / entry.relative_path).write_bytes(b"x")
            return SimpleNamespace(
                accepted=True,
                lease=SimpleNamespace(
                    entries=entries,
                    directory=directory,
                    total_bytes=len(entries),
                    identity=f"lease-{self.index}",
                ),
                errors=(),
            )

        def close(self, *, deadline):
            return SimpleNamespace(accepted=True, cleanup_pending=False)

    class FakeRoot:
        def revalidate(self):
            return None

    class FakeOwnership:
        root_owner = FakeRoot()

        def __init__(self):
            self.shards = []

        def register_shard(self, shard):
            self.shards.append(shard)

    monkeypatch.setattr(preparation, "ArtifactLeaseManager", FakeManager)
    monkeypatch.setattr(preparation, "artifact_capture_trust", lambda trust: trust)
    base = Path("/TopsailAI/src/topsailai/.tmp/u09-b-phase-b/tests/shard-shapes")
    base.mkdir(parents=True, exist_ok=True)
    works = tuple(
        preparation._ModuleWork(
            0,
            SimpleNamespace(),
            Path("/src"),
            SimpleNamespace(
                source_path=Path(f"/src/{index}.py"),
                kind="python_source",
                logical_name=str(index),
            ),
        )
        for index in range(work_count)
    )
    ownership = FakeOwnership()
    budget = preparation._PreparationBudget(
        max_scanned_entries=work_count + 1,
        max_candidates=work_count + 1,
        max_artifact_bytes=work_count + 1,
    )
    operation = SimpleNamespace(deadline=10**12, checkpoint=lambda: None)

    captured = preparation._capture_work_sequence(
        works, ownership, base, operation, budget, None, None
    )

    assert len(captured) == work_count
    assert tuple(len(shard.leases[0].entries) for shard in ownership.shards) == expected_shapes
    assert tuple(manager.index for manager in FakeManager.instances) == tuple(range(len(expected_shapes)))


def test_capture_work_sequence_rejects_before_ninth_shard(monkeypatch):
    """Capacity rejects 1025 work items before allocating a ninth manager."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation

    class NeverManager:
        instances = []

        def __init__(self, **kwargs):
            type(self).instances.append(self)

    monkeypatch.setattr(preparation, "ArtifactLeaseManager", NeverManager)
    configuration = SimpleNamespace()
    operation = SimpleNamespace(checkpoint=lambda: None)
    budget = preparation._PreparationBudget(
        max_scanned_entries=2000, max_candidates=2000, max_artifact_bytes=2000
    )
    with pytest.raises(preparation._PreparationRejected, match="capacity_exceeded"):
        preparation._capture_work_sequence(
            tuple(
                preparation._ModuleWork(
                    0, configuration, Path("/src"),
                    SimpleNamespace(
                        source_path=Path(f"/src/{index}.py"),
                        kind="python_source", logical_name=str(index),
                    ),
                ) for index in range(1025)
            ),
            SimpleNamespace(root_owner=SimpleNamespace(revalidate=lambda: None), register_shard=lambda shard: None),
            Path("/artifacts"), operation, budget, None, None,
        )
    assert NeverManager.instances == []


def test_capture_work_sequence_cancellation_stops_batch_three(monkeypatch):
    """A cancellation checkpoint after batch two prevents a third shard."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation

    class FakeManager:
        instances = []

        def __init__(self, **kwargs):
            self.index = len(type(self).instances)
            self.group = object()
            type(self).instances.append(self)

        def begin_candidate(self, *, deadline):
            return SimpleNamespace(accepted=True, group=self.group)

        def capture(self, group, requests, **kwargs):
            directory = Path(f"/TopsailAI/src/topsailai/.tmp/u09-b-phase-b/tests/cancel-{self.index}")
            directory.mkdir(parents=True, exist_ok=True)
            entries = tuple(SimpleNamespace(index=index, kind=request.kind, logical_name=request.logical_name, validation=SimpleNamespace(source_path=request.source_path), relative_path=f"{index}.bin") for index, request in enumerate(requests))
            for entry in entries:
                (directory / entry.relative_path).write_bytes(b"x")
            return SimpleNamespace(accepted=True, lease=SimpleNamespace(entries=entries, directory=directory, total_bytes=len(entries), identity=str(self.index)), errors=())

    class Operation:
        deadline = 10**12
        def __init__(self):
            self.checkpoints = 0
        def checkpoint(self):
            self.checkpoints += 1
            if self.checkpoints == 5:
                raise preparation._PreparationRejected("cancelled")

    ownership = SimpleNamespace(root_owner=SimpleNamespace(revalidate=lambda: None), shards=[], register_shard=lambda shard: ownership.shards.append(shard))
    monkeypatch.setattr(preparation, "ArtifactLeaseManager", FakeManager)
    monkeypatch.setattr(preparation, "artifact_capture_trust", lambda trust: trust)
    works = tuple(preparation._ModuleWork(0, SimpleNamespace(), Path("/src"), SimpleNamespace(source_path=Path(f"/src/{i}"), kind="python_source", logical_name=str(i))) for i in range(384))
    budget = preparation._PreparationBudget(max_scanned_entries=1000, max_candidates=1000, max_artifact_bytes=1000)
    with pytest.raises(preparation._PreparationRejected, match="cancelled"):
        preparation._capture_work_sequence(works, ownership, Path("/artifacts"), Operation(), budget, None, None)
    assert len(FakeManager.instances) == 2



def _public_prepare_probe_harness(monkeypatch, sources, runtime_root, points, candidates_by_hook, *, pending=False):
    """Drive public preparation with deterministic captured module/session seams."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation
    from topsailai.hooks.module_discovery import ModuleCandidate, ModuleManifestEntry

    runtime, scope = _runtime(sources, runtime_root)
    owners = []
    probes = []
    works = []
    captured_by_hook = {}
    for hook_index, point in enumerate(points):
        hook_works = tuple(
            preparation._ModuleWork(hook_index, point, sources, candidate)
            for candidate in candidates_by_hook[hook_index]
        )
        works.extend(hook_works)
        captured_by_hook[hook_index] = tuple(
            preparation._CapturedWork(
                work,
                SimpleNamespace(identity=(f"{hook_index + 1:064x}")),
                runtime_root / f"captured-{hook_index}-{index}.py",
            )
            for index, work in enumerate(hook_works)
        )

    monkeypatch.setattr(preparation, "_build_work_sequence", lambda *args: tuple(works))
    monkeypatch.setattr(
        preparation,
        "_capture_work_sequence",
        lambda all_works, *args: tuple(
            item for hook_index in range(len(points)) for item in captured_by_hook[hook_index]
        ),
    )
    original_owner_factory = preparation._make_cleanup_owner

    def record_owner(backend, storage):
        owner = original_owner_factory(backend, storage)
        owners.append(owner)
        return owner

    monkeypatch.setattr(preparation, "_make_cleanup_owner", record_owner)

    def run_session(*, root, hook_name, temp_root, owner, operation, budget):
        class Session:
            state = "open"

            def probe(self, candidate, *, captured_path, timeout_ms):
                probes.append((hook_name, candidate, captured_path))
                captured_path.write_bytes(b"captured")
                candidate.source_path.write_bytes(b"replaced-after-capture")
                assert captured_path.read_bytes() == b"captured"
                entry = ModuleManifestEntry(
                    candidate.logical_name,
                    captured_path,
                    ("dev", str(len(probes)), candidate.logical_name),
                    "main",
                    not pending,
                    "ok" if not pending else "invalid_entry",
                )
                return entry, SimpleNamespace(
                    cleanup_confirmed=not pending,
                    status="ok",
                )

            def close(self):
                return not pending

        return operation(Session())

    monkeypatch.setattr(preparation, "_run_with_module_probe_session", run_session)
    return runtime, scope, owners, probes


def test_public_prepare_uses_distinct_u03_owner_and_exact_candidate_path(secure_test_root, monkeypatch):
    """Each Hook owns one U03 session and probes its original candidate once at its mapped path."""
    from types import SimpleNamespace
    from topsailai.hooks.module_discovery import ModuleCandidate

    sources, runtime_root, _ = secure_test_root
    candidates = [
        ModuleCandidate("same", sources / "a.py", "python_source"),
        ModuleCandidate("same", sources / "b.py", "python_source"),
    ]
    points = (
        ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=sources),
        ConfiguredHookPoint("hook_beta", EventDefinition("test.beta", 1), module_folder=sources),
    )
    runtime, scope, owners, probes = _public_prepare_probe_harness(
        monkeypatch, sources, runtime_root, points, ((candidates[0],), (candidates[1],))
    )
    try:
        result = prepare_private(runtime, ConfiguredHooks(points, HookSettings()), scope)
        assert result.accepted, getattr(result, "errors", ())
        assert len(owners) == 2
        assert owners[0] is not owners[1]
        assert [candidate is expected for _, candidate, _ in probes for expected in candidates if candidate is expected] == [True, True]
        assert len(probes) == 2
        assert probes[0][2] == runtime_root / "captured-0-0.py"
        assert probes[1][2] == runtime_root / "captured-1-0.py"
        assert probes[0][2] != probes[1][2]
        assert result.close().accepted
    finally:
        runtime.close()


def test_public_prepare_retained_failure_continues_only_after_confirmed_cleanup(secure_test_root, monkeypatch):
    """A confirmed invalid probe is retained, while pending cleanup suppresses all successors."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation
    from topsailai.hooks.module_discovery import ModuleManifestEntry

    sources, runtime_root, _ = secure_test_root
    first = SimpleNamespace(logical_name="first", source_path=sources / "first.py", kind="python_source")
    second = SimpleNamespace(logical_name="second", source_path=sources / "second.py", kind="python_source")
    third = SimpleNamespace(logical_name="third", source_path=sources / "third.py", kind="python_source")
    points = (
        ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=sources),
        ConfiguredHookPoint("hook_beta", EventDefinition("test.beta", 1), module_folder=sources),
    )
    runtime, scope = _runtime(sources, runtime_root)
    works = tuple(
        preparation._ModuleWork(index // 2, points[index // 2], sources, candidate)
        for index, candidate in enumerate((first, second, third))
    )
    captured = tuple(
        preparation._CapturedWork(work, SimpleNamespace(identity=(f"{index + 1:064x}")), runtime_root / f"captured-{index}.py")
        for index, work in enumerate(works)
    )
    probes = []
    monkeypatch.setattr(preparation, "_build_work_sequence", lambda *args: works)
    monkeypatch.setattr(preparation, "_capture_work_sequence", lambda *args: captured)
    monkeypatch.setattr(preparation, "_make_cleanup_owner", lambda backend, storage: preparation.ModuleCleanupOwner(backend, storage))

    def run_session(*, root, hook_name, temp_root, owner, operation, budget):
        class Session:
            state = "open"
            def probe(self, candidate, *, captured_path, timeout_ms):
                probes.append((hook_name, candidate.logical_name))
                return ModuleManifestEntry(candidate.logical_name, captured_path, ("d", candidate.logical_name, "i"), "main", False, "invalid_entry"), SimpleNamespace(cleanup_confirmed=True, status="ok")
            def close(self):
                return True
        return operation(Session())

    monkeypatch.setattr(preparation, "_run_with_module_probe_session", run_session)
    try:
        result = prepare_private(runtime, ConfiguredHooks(points, HookSettings()), scope)
        assert result.accepted, getattr(result, "errors", ())
        assert probes == [("hook_alpha", "first"), ("hook_alpha", "second"), ("hook_beta", "third")]
        assert len(result.plans[0].module_failures) == 2
        assert result.close().accepted
    finally:
        runtime.close()

    runtime, scope = _runtime(sources, runtime_root)
    probes.clear()
    def pending_run_session(*, root, hook_name, temp_root, owner, operation, budget):
        class Session:
            state = "open"
            def probe(self, candidate, *, captured_path, timeout_ms):
                probes.append((hook_name, candidate.logical_name))
                return ModuleManifestEntry(candidate.logical_name, captured_path, ("d", candidate.logical_name, "i"), "main", False, "invalid_entry"), SimpleNamespace(cleanup_confirmed=False, status="cleanup_pending")
            def close(self):
                return False
        return operation(Session())
    monkeypatch.setattr(preparation, "_run_with_module_probe_session", pending_run_session)
    try:
        result = prepare_private(runtime, ConfiguredHooks(points, HookSettings()), scope)
        assert not result.accepted
        assert result.errors == ("cleanup_pending",)
        assert probes == [("hook_alpha", "first")]
    finally:
        runtime.close()
