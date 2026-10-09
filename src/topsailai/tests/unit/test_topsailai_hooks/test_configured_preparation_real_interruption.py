"""Integrated interruption regression at the public private-preparation boundary."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import topsailai.hooks.configured_preparation as preparation
from topsailai.hooks.artifact_leases import ArtifactLeaseManager
from topsailai.hooks.configured_preparation import get_preparation_recovery_owner, prepare_private
from topsailai.hooks.configured_preparation_ownership import CaptureShard
from topsailai.hooks.configured_trust import artifact_capture_trust
from topsailai.hooks.module_discovery import ModuleCleanupOwner, ModuleProbeSession
from topsailai.hooks.process_state import CleanupDebt
from topsailai.hooks.temporary_storage import TemporaryStorageOwner

from tests.unit.test_topsailai_hooks.test_configured_preparation import _runtime


@pytest.fixture
def secure_test_root(tmp_path):
    """Create owner-only source and runtime roots for this integrated test."""
    root = tmp_path / "phase-b-real-interruption"
    root.mkdir(mode=0o700)
    sources = root / "sources"
    runtime = root / "runtime"
    sources.mkdir(mode=0o700)
    runtime.mkdir(mode=0o700)
    try:
        yield sources, runtime, root
    finally:
        for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_file() or path.is_symlink():
                print(f"Deleted integrated test file: {path}")
                path.unlink()
            elif path.is_dir():
                print(f"Deleted integrated test directory: {path}")
                path.rmdir()
        print(f"Deleted integrated test directory: {root}")
        root.rmdir()


class _Backend:
    """Backend seam exposing one real module-session cleanup debt."""

    def __init__(self) -> None:
        self.debts = [CleanupDebt("u03-backend", "process", None, "injected cleanup")]
        self.calls: list[str] = []
        self.fail_once = True

    def cleanup_debts(self):
        return tuple(self.debts)

    def retry_cleanup(self, debt_id):
        self.calls.append(debt_id)
        if debt_id != "u03-backend" or self.fail_once:
            self.fail_once = False
            return False
        self.debts.clear()
        return True


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_prepare_private_real_u03_interruption_retains_and_settles_resources(
    secure_test_root, monkeypatch, exception_type
):
    """A real ModuleProbeSession owner retains U03, U07, and root resources."""
    sources, runtime_root, _ = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, EventDefinition, HookSettings

    primary = exception_type("injected helper-return interruption")
    backend_holder = {}
    events = []

    def capture_boundary(works, ownership, artifact_root, operation, budget, trust, cancellation):
        """Arm real U07 and U03 authorities, then interrupt at helper return."""
        manager = ArtifactLeaseManager(
            artifact_root=str(artifact_root), trust=artifact_capture_trust(trust)
        )
        candidate = manager.begin_candidate(deadline=operation.deadline)
        assert candidate.accepted and candidate.group is not None
        ownership.register_shard(CaptureShard(0, manager, candidate.group))

        storage = TemporaryStorageOwner(Path(runtime_root))
        assert storage.allocate()
        backend = _Backend()
        backend_holder["backend"] = backend
        owner = ModuleCleanupOwner(backend, storage)
        ownership.register_module_owner(owner, "hook_alpha")
        session = ModuleProbeSession(sources, "hook_alpha", backend, storage, owner=owner)
        assert session.state == "open"
        session._state = "cleanup_pending"
        storage.retain_cleanup_debt()
        events.append(("u03_pending", session.state))
        # This is the documented backend cleanup-result seam; no host process is touched.
        raise primary

    monkeypatch.setattr(preparation, "_build_work_sequence", lambda *args: (object(),))
    monkeypatch.setattr(preparation, "_capture_work_sequence", capture_boundary)
    point = ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=sources)
    configuration = ConfiguredHooks((point,), HookSettings())
    try:
        with pytest.raises(exception_type) as caught:
            prepare_private(runtime, configuration, scope)
        assert caught.value is primary
        aggregate = get_preparation_recovery_owner(primary)
        assert aggregate is not None
        debts = aggregate.cleanup_debts()
        u03_debt = next(item for item in debts if item.category == "u03")
        assert aggregate.root_owner is not None
        assert not aggregate.root_owner._closed
        assert len(aggregate.shards) == 1
        assert aggregate.shards[0].manager.snapshot().manager_state == "open"
        assert events == [("u03_pending", "cleanup_pending")]
        # The interrupted path performed no successor probe/plan/transfer work.
        assert aggregate.state == "cleanup_pending"

        # The interruption cleanup pass already made one bounded U03 retry;
        # the exact aggregate retry is therefore idempotently successful.
        assert aggregate.retry_cleanup(u03_debt.debt_id) is True
        assert backend_holder["backend"].calls == ["u03-backend", "u03-backend"]
        assert aggregate.settle() is True
        assert aggregate.state == "closed"
        assert aggregate.cleanup_debts() == ()
        assert aggregate.root_owner._closed
        assert aggregate.shards[0].manager.snapshot().manager_state == "closed"
    finally:
        runtime.close()


def test_prepare_private_root_revalidation_precedes_shard_probe_and_transfer(
    secure_test_root, monkeypatch
):
    """The public composition boundary revalidates root before every handoff."""
    sources, runtime_root, _ = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, EventDefinition, HookSettings

    events = []

    class Root:
        _closed = False

        def child(self, name):
            return Path(runtime_root) / name

        def revalidate(self):
            events.append("revalidate")

        def close(self):
            events.append("close")
            return True

    root = Root()

    def make_root(path, ownership=None):
        """Bind the fake root to the aggregate ownership seam."""
        if ownership is not None:
            ownership.adopt_root(root)
        return root

    monkeypatch.setattr(preparation, "ConfiguredRootOwner", make_root)
    monkeypatch.setattr(preparation, "_build_work_sequence", lambda *args: (object(),))

    def capture(works, ownership, *args):
        ownership.root_owner.revalidate()
        events.append("shard")
        events.append("shard_handoff")
        return ()

    def probe(*args):
        events.append("probe")
        return ()

    monkeypatch.setattr(preparation, "_capture_work_sequence", capture)
    monkeypatch.setattr(preparation, "_probe_and_plan", probe)
    point = ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=sources)
    try:
        image = prepare_private(runtime, ConfiguredHooks((point,), HookSettings()), scope)
        assert image.accepted
        assert image.close().accepted
        assert events.index("revalidate") < events.index("shard")
        assert events.index("shard_handoff") < events.index("probe")
        assert events.count("revalidate") >= 2
        assert events[-1] == "close"
    finally:
        runtime.close()


def test_prepare_private_real_root_ordinary_failure_retains_exact_recovery(
    secure_test_root, monkeypatch
):
    """An ordinary failure retains only stable pending cleanup authority."""
    sources, runtime_root, _ = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, EventDefinition, HookSettings
    import topsailai.hooks.configured_preparation_ownership as ownership_module

    configuration = ConfiguredHooks(
        (ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=sources),),
        HookSettings(),
    )
    failure = RuntimeError("ordinary helper failure")
    aggregate_holder = {}
    failed_descriptor = {"value": None}
    fail_once = {"value": True}
    original_close = ownership_module.os.close

    def close_with_one_deterministic_failure(fd):
        """Inject one cleanup failure for a real configured-root descriptor."""
        aggregate = aggregate_holder.get("value")
        if aggregate is not None and failed_descriptor["value"] is None:
            failed_descriptor["value"] = next(iter(aggregate.root_owner._children.values()))
        if fd == failed_descriptor["value"] and fail_once["value"]:
            fail_once["value"] = False
            raise OSError("deterministic cleanup failure")
        return original_close(fd)

    def fail_after_real_root(*args):
        """Raise after public preparation has created its real root owner."""
        aggregate_holder["value"] = args[1]
        raise failure

    monkeypatch.setattr(preparation, "_build_work_sequence", lambda *args: (object(),))
    monkeypatch.setattr(preparation, "_capture_work_sequence", fail_after_real_root)
    monkeypatch.setattr(ownership_module.os, "close", close_with_one_deterministic_failure)
    try:
        with pytest.raises(preparation._PreparationCleanupPending) as caught:
            prepare_private(runtime, configuration, scope)
        error = caught.value
        assert error.token == "internal_error"
        assert str(error) == "internal_error"
        assert error.__dict__["token"] == "internal_error"
        assert "ordinary helper failure" not in repr(error)
        aggregate = get_preparation_recovery_owner(error)
        assert aggregate is aggregate_holder["value"] and aggregate.state == "cleanup_pending"
        assert set(error.__dict__) == {"token", "__topsailai_preparation_recovery_owner__"}
        root_debts = tuple(debt for debt in aggregate.cleanup_debts() if debt.category == "root")
        assert len(root_debts) == 1
        debt_id = root_debts[0].debt_id
        assert "/" not in debt_id and str(failed_descriptor["value"]) not in repr(error)
        assert aggregate.retry_cleanup(debt_id) is True
        assert aggregate.cleanup_debts() == ()
        assert aggregate.settle() is True
        assert aggregate.state == "closed"
        assert aggregate.root_owner._closed
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "child_name, exception_type, cleanup_type",
    [
        ("configured-artifacts", KeyboardInterrupt, OSError),
        ("configured-discovery", SystemExit, OSError),
        ("configured-artifacts", SystemExit, KeyboardInterrupt),
        ("configured-discovery", KeyboardInterrupt, SystemExit),
        ("configured-artifacts", KeyboardInterrupt, None),
        ("configured-discovery", SystemExit, None),
    ],
)
def test_prepare_private_root_handoff_preserves_recovery_authority(
    secure_test_root, monkeypatch, child_name, exception_type, cleanup_type
):
    """A child-boundary interruption keeps exact aggregate root custody."""
    sources, runtime_root, _ = secure_test_root
    runtime, scope = _runtime(sources, runtime_root)
    from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, EventDefinition, HookSettings
    import topsailai.hooks.configured_preparation_ownership as ownership_module

    primary = exception_type("root child interruption")
    cleanup_error = cleanup_type("one-shot cleanup interruption") if cleanup_type else None
    original_child = preparation.ConfiguredRootOwner.child
    original_close = ownership_module.os.close
    child_reached = []
    cleanup_calls = []

    def interrupt_child(owner, name):
        """Interrupt only at the selected descriptor-relative child boundary."""
        child_reached.append(name)
        if name == child_name:
            raise primary
        return original_child(owner, name)

    def interrupt_cleanup(fd):
        """Inject one cleanup failure after aggregate custody is established."""
        cleanup_calls.append(fd)
        if len(cleanup_calls) == 1:
            raise cleanup_error
        return original_close(fd)

    monkeypatch.setattr(preparation.ConfiguredRootOwner, "child", interrupt_child)
    if cleanup_error is not None:
        monkeypatch.setattr(ownership_module.os, "close", interrupt_cleanup)

    configuration = ConfiguredHooks(
        (ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=sources),),
        HookSettings(),
    )
    try:
        with pytest.raises(exception_type) as caught:
            prepare_private(runtime, configuration, scope)
        assert caught.value is primary
        assert child_reached == (["configured-artifacts"] if child_name == "configured-artifacts" else [
            "configured-artifacts", "configured-discovery"
        ])
        aggregate = get_preparation_recovery_owner(primary)
        if cleanup_error is None:
            assert aggregate is None
            return

        assert aggregate is not None
        assert aggregate.state == "cleanup_pending"
        assert aggregate.root_owner is not None
        assert not aggregate.root_owner._closed
        assert set(primary.__dict__) == {"__topsailai_preparation_recovery_owner__"}
        assert "/" not in repr(primary)
        root_debts = tuple(debt for debt in aggregate.cleanup_debts() if debt.category == "root")
        assert root_debts
        assert all(debt.debt_id.startswith("root:") for debt in root_debts)

        monkeypatch.setattr(ownership_module.os, "close", original_close)
        for debt in root_debts:
            assert aggregate.retry_cleanup(debt.debt_id) is True
        assert aggregate.cleanup_debts() == ()
        assert aggregate.settle() is True
        assert aggregate.state == "closed"
        assert aggregate.root_owner._closed
    finally:
        runtime.close()
