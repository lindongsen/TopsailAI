"""Behavioral coverage for private configured-preparation decision branches."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import topsailai.hooks.configured_preparation as preparation
from topsailai.hooks.configured_preparation import _PreparationBudget, _PreparationRejected, _Operation
from topsailai.hooks.configured_preparation import _ModuleWork, _CapturedWork, _capture_token, _discovery_token, _map_capture_batch


def test_budget_boundaries_and_operation_tokens(monkeypatch):
    budget = _PreparationBudget(max_scanned_entries=1, max_candidates=1, max_artifact_bytes=1)
    budget.add_scan(); budget.add_candidate(); budget.add_bytes(1)
    for method, value in ((budget.add_scan, 1), (budget.add_candidate, 1), (budget.add_bytes, 1)):
        with pytest.raises(_PreparationRejected, match="capacity_exceeded"):
            method(value)
    assert _capture_token([]) == "artifact_rejected"
    assert _capture_token(["artifact_capture_cancelled"]) == "cancelled"
    assert _capture_token(["artifact_capture_timeout"]) == "prepare_timeout"
    assert _capture_token(["artifact_capacity_exceeded"]) == "capacity_exceeded"
    assert _capture_token(["unsupported_platform"]) == "unsupported_platform"
    assert _capture_token(["other"]) == "artifact_rejected"
    assert _discovery_token("timeout") == "prepare_timeout"
    assert _discovery_token("cancelled") == "cancelled"
    assert _discovery_token("candidate limit") == "capacity_exceeded"
    assert _discovery_token("cleanup pending") == "cleanup_pending"
    assert _discovery_token("other") == "discovery_rejected"
    event = threading.Event(); event.set()
    with pytest.raises(_PreparationRejected, match="cancelled"):
        _Operation(1000, event).checkpoint()
    operation = _Operation(1000, None)
    monkeypatch.setattr(preparation.time, "monotonic", lambda: operation.deadline + 1)
    with pytest.raises(_PreparationRejected, match="prepare_timeout"):
        operation.checkpoint()


def test_map_capture_batch_rejects_all_positional_and_containment_errors(tmp_path):
    directory = tmp_path / "lease"; directory.mkdir()
    (directory / "ok.py").write_text("x")
    source = tmp_path / "source.py"; source.write_text("x")
    work = _ModuleWork(0, SimpleNamespace(), tmp_path, SimpleNamespace(source_path=source, kind="python_source", logical_name="m"))
    request = SimpleNamespace(source_path=source, kind="python_source", logical_name="m")
    base = SimpleNamespace(index=0, kind="python_source", logical_name="m", validation=SimpleNamespace(source_path=source), relative_path="ok.py")
    lease = SimpleNamespace(entries=(base,), directory=directory)
    assert _map_capture_batch((work,), lease)[0].captured_path == directory / "ok.py"
    for update in (
        {"index": 1}, {"kind": "script"}, {"logical_name": "other"},
        {"validation": SimpleNamespace(source_path=tmp_path / "other.py")},
        {"relative_path": "/tmp/escape"}, {"relative_path": "../escape"},
    ):
        item = SimpleNamespace(**{**base.__dict__, **update})
        with pytest.raises(_PreparationRejected, match="artifact_rejected"):
            _map_capture_batch((work,), SimpleNamespace(entries=(item,), directory=directory))
    with pytest.raises(_PreparationRejected, match="artifact_rejected"):
        _map_capture_batch((work,), SimpleNamespace(entries=(), directory=directory))
    missing = SimpleNamespace(index=0, kind="python_source", logical_name="m", validation=SimpleNamespace(source_path=source), relative_path="missing")
    with pytest.raises(_PreparationRejected, match="artifact_rejected"):
        _map_capture_batch((work,), SimpleNamespace(entries=(missing,), directory=directory))


def test_public_input_rejection_tokens(tmp_path):
    source_root = tmp_path / "sources"; source_root.mkdir(mode=0o700)
    runtime_root = tmp_path / "runtime"; runtime_root.mkdir(mode=0o700)
    helper = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])
    runtime, scope = helper._runtime(source_root, runtime_root)
    from topsailai.hooks.configured_contracts import ConfiguredHooks
    from topsailai.hooks import HookSettings
    generation = runtime._registry.generation
    invalid = preparation.prepare_private(runtime, object(), scope)
    assert not invalid.accepted and invalid.errors == ("invalid_configuration",)
    invalid_scope = preparation.prepare_private(runtime, ConfiguredHooks((), HookSettings()), object())
    assert not invalid_scope.accepted and invalid_scope.errors == ("invalid_scope",)
    runtime._state = "stopped"
    closed = preparation.prepare_private(runtime, ConfiguredHooks((), HookSettings()), scope)
    assert not closed.accepted and closed.errors == ("scope_closed",)
    assert closed.generation == generation


def test_mapping_and_discovery_helper_boundaries(monkeypatch, tmp_path):
    point = SimpleNamespace(module_folder=str(tmp_path), module_args=(), module_kwargs={})
    operation = SimpleNamespace(deadline=preparation.time.monotonic() + 100, cancellation=None, checkpoint=lambda: None)
    config = SimpleNamespace(policy=SimpleNamespace(max_scanned_entries=1, max_candidates=1))
    rejected = SimpleNamespace(accepted=False, errors=("candidate limit",))
    monkeypatch.setattr(preparation, "enumerate_module_candidates_owned", lambda *a, **k: rejected)
    with pytest.raises(_PreparationRejected, match="capacity_exceeded"):
        preparation._discover(point, operation, config, SimpleNamespace(add_scan=lambda: None))
    inventory = SimpleNamespace(accepted=True, candidates=())
    monkeypatch.setattr(preparation, "enumerate_module_candidates_owned", lambda *a, **k: inventory)
    assert preparation._discover(point, operation, config, SimpleNamespace(add_scan=lambda: None)) is inventory
    assert list(preparation._batches((1, 2, 3), 2)) == [(1, 2), (3,)]

pytest_plugins = ("tests.unit.test_topsailai_hooks.test_configured_preparation",)


def _nonempty_config(source_root):
    from topsailai.hooks import ConfiguredHookPoint, EventDefinition, ConfiguredHooks, HookSettings
    point = ConfiguredHookPoint("hook_alpha", EventDefinition("coverage.event", 1), module_folder=source_root)
    return ConfiguredHooks((point,), HookSettings())


def test_private_plan_and_recovery_attachment_branches():
    summary = SimpleNamespace(hook_point="hook_alpha", value=7)
    plan = preparation._PrivatePlan(summary, (1,), (("x", 2),), ("id",))
    assert plan.hook_point == "hook_alpha" and plan.value == 7
    error = RuntimeError("interrupt")
    assert preparation.get_preparation_recovery_owner(error) is None
    empty = SimpleNamespace(cleanup_debts=lambda: ())
    preparation._attach_preparation_recovery_owner(error, empty)
    assert preparation.get_preparation_recovery_owner(error) is None
    owner = SimpleNamespace(cleanup_debts=lambda: (object(),))
    preparation._attach_preparation_recovery_owner(error, owner)
    assert preparation.get_preparation_recovery_owner(error) is owner


@pytest.mark.parametrize("kind", ["keyboard", "system"])
def test_prepare_exception_cleanup_branches(secure_test_root, monkeypatch, kind):
    sources, runtime_root, _ = secure_test_root
    runtime, scope = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])._runtime(sources, runtime_root)
    config = _nonempty_config(sources)
    error_type = KeyboardInterrupt if kind == "keyboard" else SystemExit
    monkeypatch.setattr(preparation, "_build_work_sequence", lambda *args: (_ for _ in ()).throw(error_type()))
    try:
        with pytest.raises(error_type):
            preparation.prepare_private(runtime, config, scope)
    finally:
        runtime.close()


@pytest.mark.parametrize("token", ["capacity_exceeded", "cleanup_pending"])
def test_prepare_rejection_cleanup_branches(secure_test_root, monkeypatch, token):
    sources, runtime_root, _ = secure_test_root
    runtime, scope = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])._runtime(sources, runtime_root)
    monkeypatch.setattr(preparation, "_build_work_sequence", lambda *args: (_ for _ in ()).throw(_PreparationRejected(token)))
    try:
        result = preparation.prepare_private(runtime, _nonempty_config(sources), scope)
        assert not result.accepted and result.errors == (token,)
    finally:
        runtime.close()


@pytest.mark.parametrize("error, expected", [(ValueError("trust_rejected"), "trust_rejected"), (ValueError("other"), "internal_error"), (RuntimeError("other"), "internal_error")])
def test_prepare_error_mapping_branches(secure_test_root, monkeypatch, error, expected):
    sources, runtime_root, _ = secure_test_root
    runtime, scope = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])._runtime(sources, runtime_root)
    def fail(*args):
        raise error
    monkeypatch.setattr(preparation, "_build_work_sequence", fail)
    try:
        result = preparation.prepare_private(runtime, _nonempty_config(sources), scope)
        assert not result.accepted and result.errors == (expected,)
    finally:
        runtime.close()


def test_prepare_input_and_platform_rejections(secure_test_root, monkeypatch):
    sources, runtime_root, _ = secure_test_root
    runtime, scope = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])._runtime(sources, runtime_root)
    from topsailai.hooks import ConfiguredHooks, HookSettings
    try:
        runtime._configured_trust = None
        result = preparation.prepare_private(runtime, ConfiguredHooks((), HookSettings()), scope)
        assert result.errors == ("trust_policy_missing",)
        runtime._configured_trust = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])._runtime(sources, runtime_root)[0]._configured_trust
        monkeypatch.setattr(preparation.sys, "platform", "win32")
        result = preparation.prepare_private(runtime, ConfiguredHooks((), HookSettings()), scope)
        assert result.errors == ("unsupported_platform",)
    finally:
        runtime.close()


def test_capture_and_probe_rejection_branches(monkeypatch):
    root = SimpleNamespace(revalidate=lambda: None)
    ownership = SimpleNamespace(root_owner=root, register_shard=lambda shard: None)
    operation = SimpleNamespace(deadline=preparation.time.monotonic() + 100, checkpoint=lambda: None)
    budget = SimpleNamespace(max_artifact_bytes=1, artifact_bytes=0, add_bytes=lambda count: None)
    manager = SimpleNamespace(begin_candidate=lambda **kwargs: SimpleNamespace(accepted=False, group=None), close=lambda **kwargs: None)
    monkeypatch.setattr(preparation, "artifact_capture_trust", lambda trust: trust)
    monkeypatch.setattr(preparation, "ArtifactLeaseManager", lambda **kwargs: manager)
    with pytest.raises(_PreparationRejected, match="capacity_exceeded"):
        preparation._capture_work_sequence((1,), ownership, Path("/tmp"), operation, budget, SimpleNamespace(), None)
    monkeypatch.setattr(preparation, "_run_with_module_probe_session", lambda **kwargs: None)
    point = SimpleNamespace(module_folder=Path("."), hook_name="h", module_args=(), module_kwargs={}, script=None, definition=SimpleNamespace(name="e", major_version=1), max_concurrency=1)
    work = preparation._ModuleWork(0, point, Path("."), SimpleNamespace(logical_name="m", source_path=Path("m.py"), kind="python_source"))
    captured = preparation._CapturedWork(work, SimpleNamespace(identity="id"), Path("m.py"))
    with pytest.raises(_PreparationRejected, match="trust_rejected"):
        preparation._probe_and_plan(SimpleNamespace(hook_points=(point,), settings=SimpleNamespace(limits=SimpleNamespace(bindings_per_event=1))), (captured,), SimpleNamespace(register_module_owner=lambda *a: None), Path("/tmp"), operation, budget, None)

class _FakeRoot:
    def __init__(self): self.closed = 0; self.revalidated = 0
    def child(self, name): return Path('/tmp')
    def revalidate(self): self.revalidated += 1
    def close(self): self.closed += 1; return True


class _FakeOwnership:
    last = None
    pending_debts = ()
    def __init__(self, root, deadline):
        self.root_owner = root; self.debts = type(self).pending_debts; self.settled = 0; self.marked = 0
        type(self).last = self
    def adopt_root(self, root): self.root_owner = root
    def mark_pending(self): self.marked += 1
    def settle(self): self.settled += 1; return True
    def cleanup_debts(self): return self.debts
    def transfer_to_image(self): return None


def _fake_root_factory(root):
    """Bind the fake root to the aggregate ownership seam."""
    def make_root(path, ownership=None):
        if ownership is not None:
            ownership.adopt_root(root)
        return root
    return make_root


@pytest.mark.parametrize('exc', [_PreparationRejected('capacity_exceeded'), ValueError('trust_rejected'), ValueError('other'), RuntimeError('other')])
def test_prepare_exception_handlers_after_ownership(monkeypatch, tmp_path, exc):
    from topsailai.hooks import ConfiguredHooks, HookSettings
    root = _FakeRoot()
    monkeypatch.setattr(preparation, 'ConfiguredRootOwner', _fake_root_factory(root))
    monkeypatch.setattr(preparation, 'PreparationOwnership', _FakeOwnership)
    monkeypatch.setattr(preparation, '_build_work_sequence', lambda *args: (_ for _ in ()).throw(exc))
    monkeypatch.setattr(preparation, 'validate_temporary_root', lambda *args: tmp_path)
    source = tmp_path / 'sources'; source.mkdir(mode=0o700)
    runtime_root = tmp_path / 'runtime'; runtime_root.mkdir(mode=0o700)
    helper = __import__('tests.unit.test_topsailai_hooks.test_configured_preparation', fromlist=['_runtime'])
    runtime, scope = helper._runtime(source, runtime_root)
    try:
        result = preparation.prepare_private(runtime, _nonempty_config(source), scope)
        expected = exc.token if isinstance(exc, _PreparationRejected) else ('trust_rejected' if str(exc) == 'trust_rejected' else 'internal_error')
        assert not result.accepted and result.errors == (expected,)
        assert _FakeOwnership.last.settled == 1
    finally: runtime.close()


def test_prepare_keyboard_and_system_exit_attach_pending_owner(monkeypatch, tmp_path):
    from topsailai.hooks import ConfiguredHooks, HookSettings
    root = _FakeRoot()
    monkeypatch.setattr(preparation, 'ConfiguredRootOwner', _fake_root_factory(root))
    monkeypatch.setattr(preparation, 'PreparationOwnership', _FakeOwnership)
    monkeypatch.setattr(preparation, 'validate_temporary_root', lambda *args: tmp_path)
    source = tmp_path / 'sources'; source.mkdir(mode=0o700)
    runtime_root = tmp_path / 'runtime'; runtime_root.mkdir(mode=0o700)
    helper = __import__('tests.unit.test_topsailai_hooks.test_configured_preparation', fromlist=['_runtime'])
    runtime, scope = helper._runtime(source, runtime_root)
    for exc_type in (KeyboardInterrupt, SystemExit):
        marker = exc_type()
        monkeypatch.setattr(preparation, '_build_work_sequence', lambda *args, marker=marker: (_ for _ in ()).throw(marker))
        _FakeOwnership.pending_debts = (object(),)
        with pytest.raises(exc_type) as caught:
            preparation.prepare_private(runtime, _nonempty_config(source), scope)
        assert caught.value is marker
        assert preparation.get_preparation_recovery_owner(marker) is _FakeOwnership.last
    _FakeOwnership.pending_debts = ()
    runtime.close()




def test_private_capture_remaining_and_probe_terminal_branches(monkeypatch):
    op = SimpleNamespace(deadline=preparation.time.monotonic()+100, cancellation=None, checkpoint=lambda: None)
    budget = SimpleNamespace(max_artifact_bytes=0, artifact_bytes=0, add_bytes=lambda n: None)
    owner = SimpleNamespace(root_owner=SimpleNamespace(revalidate=lambda: None), register_shard=lambda x: None)
    monkeypatch.setattr(preparation, 'artifact_capture_trust', lambda trust: trust)
    with pytest.raises(_PreparationRejected, match='capacity_exceeded'):
        preparation._capture_work_sequence(tuple(object() for _ in range(preparation._MAX_CAPTURE_ENTRIES * preparation._MAX_CAPTURE_SHARDS + 1)), owner, Path('/tmp'), op, budget, object(), None)
    fake = SimpleNamespace(accepted=True, group=object())
    mgr = SimpleNamespace(begin_candidate=lambda **k: fake, close=lambda **k: None, capture=lambda *a, **k: SimpleNamespace(accepted=False, lease=None, errors=()))
    monkeypatch.setattr(preparation, 'artifact_capture_trust', lambda trust: trust)
    monkeypatch.setattr(preparation, 'ArtifactLeaseManager', lambda **k: mgr)
    budget.max_artifact_bytes = 1
    point = SimpleNamespace(script=None)
    work = preparation._ModuleWork(0, point, Path('.'), SimpleNamespace(source_path=Path('m.py'), kind='python_source', logical_name='m'))
    monkeypatch.setattr(preparation, 'artifact_capture_trust', lambda trust: trust)
    with pytest.raises(_PreparationRejected, match='artifact_rejected'):
        preparation._capture_work_sequence((work,), owner, Path('/tmp'), op, budget, object(), None)

    point = SimpleNamespace(hook_name='h', module_folder=Path('.'), module_args=(), module_kwargs={}, script=None, definition=SimpleNamespace(name='e', major_version=1), max_concurrency=1)
    work = preparation._ModuleWork(0, point, Path('.'), SimpleNamespace(logical_name='m', source_path=Path('m.py'), kind='python_source'))
    item = preparation._CapturedWork(work, SimpleNamespace(identity='id'), Path('m.py'))
    session = SimpleNamespace(state='closed', probe=lambda *a, **k: (None, SimpleNamespace(cleanup_confirmed=True)), close=lambda: False)
    monkeypatch.setattr(preparation, '_run_with_module_probe_session', lambda **k: ((SimpleNamespace(entry_valid=True, logical_name='m', source_path=Path('m.py'), load_status='loaded'), 'id'),))
    monkeypatch.setattr(preparation, 'build_hook_point_binding_plan_from_discovery', lambda **k: SimpleNamespace(accepted=False))
    with pytest.raises(_PreparationRejected, match='binding_conflict'):
        preparation._probe_and_plan(SimpleNamespace(hook_points=(point,), settings=SimpleNamespace(limits=SimpleNamespace(bindings_per_event=1))), (item,), SimpleNamespace(register_module_owner=lambda *a: None), Path('/tmp'), op, budget, None)

def test_remaining_uncovered_helper_branches(monkeypatch, tmp_path):
    assert preparation._capture_token(["artifact_capture_cancelled", "x"]) == "cancelled"
    assert preparation._discovery_token("unknown") == "discovery_rejected"
    operation = SimpleNamespace(deadline=preparation.time.monotonic() - 1)
    with pytest.raises(_PreparationRejected, match="prepare_timeout"):
        preparation._remaining_ms(operation)
    source = tmp_path / "source.py"; source.write_text("x")
    outside = tmp_path / "outside.py"; outside.write_text("x")
    directory = tmp_path / "lease"; directory.mkdir()
    link = directory / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink unavailable")
    work = _ModuleWork(0, SimpleNamespace(), tmp_path, SimpleNamespace(source_path=source, kind="python_source", logical_name="m"))
    entry = SimpleNamespace(index=0, kind="python_source", logical_name="m", validation=SimpleNamespace(source_path=source), relative_path="link.py")
    with pytest.raises(_PreparationRejected, match="artifact_rejected"):
        _map_capture_batch((work,), SimpleNamespace(entries=(entry,), directory=directory))


def test_discovery_rejected_and_capture_shard_guard(monkeypatch, tmp_path):
    point = SimpleNamespace(module_folder=str(tmp_path), module_args=(), module_kwargs={})
    operation = SimpleNamespace(deadline=preparation.time.monotonic()+100, cancellation=None, checkpoint=lambda: None)
    config = SimpleNamespace(policy=SimpleNamespace(max_scanned_entries=1, max_candidates=1))
    monkeypatch.setattr(preparation, "enumerate_module_candidates_owned", lambda *a, **k: SimpleNamespace(accepted=False, errors=()))
    with pytest.raises(_PreparationRejected, match="discovery_rejected"):
        preparation._discover(point, operation, config, SimpleNamespace(add_scan=lambda: None))
    monkeypatch.setattr(preparation, "_MAX_CAPTURE_SHARDS", 0)
    with pytest.raises(_PreparationRejected, match="capacity_exceeded"):
        preparation._capture_work_sequence((object(),), SimpleNamespace(root_owner=SimpleNamespace(revalidate=lambda: None), register_shard=lambda x: None), tmp_path, operation, SimpleNamespace(max_artifact_bytes=1, artifact_bytes=0), object(), None)


def test_prepare_invalid_cancellation_and_trust_root_paths(secure_test_root, monkeypatch):
    sources, runtime_root, _ = secure_test_root
    helper = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])
    runtime, scope = helper._runtime(sources, runtime_root)
    try:
        config = _nonempty_config(sources)
        assert preparation.prepare_private(runtime, config, scope, cancellation=object()).errors == ("invalid_configuration",)
        monkeypatch.setattr(preparation, "validate_temporary_root", lambda *args: None)
        assert preparation.prepare_private(runtime, config, scope).errors == ("trust_rejected",)
    finally:
        runtime.close()


def test_probe_cleanup_pending_and_close_failure(monkeypatch, tmp_path):
    point = SimpleNamespace(hook_name="h", module_folder=tmp_path, module_args=(), module_kwargs={}, script=None, definition=SimpleNamespace(name="e", major_version=1), max_concurrency=1)
    work = _ModuleWork(0, point, tmp_path, SimpleNamespace(logical_name="m", source_path=tmp_path / "m.py", kind="python_source"))
    item = _CapturedWork(work, SimpleNamespace(identity="id"), tmp_path / "m.py")
    result = SimpleNamespace(entry_valid=True, logical_name="m", source_path=tmp_path / "m.py", load_status="loaded")
    monkeypatch.setattr(preparation, "_run_with_module_probe_session", lambda **k: ((result, "id"),))
    monkeypatch.setattr(preparation, "build_hook_point_binding_plan_from_discovery", lambda **k: SimpleNamespace(accepted=True))
    monkeypatch.setattr(preparation, "_run_with_module_probe_session", lambda **k: (_ for _ in ()).throw(_PreparationRejected("cleanup_pending")))
    with pytest.raises(_PreparationRejected, match="cleanup_pending"):
        preparation._probe_and_plan(SimpleNamespace(hook_points=(point,), settings=SimpleNamespace(limits=SimpleNamespace(bindings_per_event=1))), (item,), SimpleNamespace(register_module_owner=lambda *a: None), tmp_path, SimpleNamespace(checkpoint=lambda: None, deadline=preparation.time.monotonic()+100), SimpleNamespace(), None)


def test_prepare_root_trust_and_capacity_rejections(secure_test_root, monkeypatch):
    sources, runtime_root, _ = secure_test_root
    helper = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])
    runtime, scope = helper._runtime(sources, runtime_root)
    config = _nonempty_config(sources)
    try:
        runtime._configured_trust = SimpleNamespace(source_roots=())
        assert preparation.prepare_private(runtime, config, scope).errors == ("trust_rejected",)
        runtime._configured_trust = helper._runtime(sources, runtime_root)[0]._configured_trust
        monkeypatch.setattr(preparation, "_build_work_sequence", lambda *a: tuple(object() for _ in range(preparation._MAX_CAPTURE_ENTRIES * preparation._MAX_CAPTURE_SHARDS + 1)))
        assert preparation.prepare_private(runtime, config, scope).errors == ("capacity_exceeded",)
    finally:
        runtime.close()


def test_prepare_root_mode_rejection_and_root_cleanup(monkeypatch, tmp_path):
    source = tmp_path / "sources"; source.mkdir(mode=0o700)
    runtime_root = tmp_path / "runtime"; runtime_root.mkdir(mode=0o700)
    helper = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])
    runtime, scope = helper._runtime(source, runtime_root)
    config = _nonempty_config(source)
    class BadStat:
        st_mode = 0
        st_uid = 0
    try:
        monkeypatch.setattr(preparation.Path, "lstat", lambda self: BadStat())
        assert preparation.prepare_private(runtime, config, scope).errors == ("trust_rejected",)
    finally:
        runtime.close()


def test_capture_remaining_and_discovery_exception_branches(monkeypatch, tmp_path):
    op = SimpleNamespace(cancellation=None, deadline=preparation.time.monotonic()+100, checkpoint=lambda: None)
    owner = SimpleNamespace(root_owner=SimpleNamespace(revalidate=lambda: None), register_shard=lambda x: None)
    work = _ModuleWork(0, SimpleNamespace(script=None), tmp_path, SimpleNamespace(source_path=tmp_path / "m.py", kind="python_source", logical_name="m"))
    budget = SimpleNamespace(max_artifact_bytes=0, artifact_bytes=0, add_bytes=lambda n: None)
    monkeypatch.setattr(preparation, "artifact_capture_trust", lambda x: x)
    monkeypatch.setattr(preparation, "ArtifactLeaseManager", lambda **k: SimpleNamespace(begin_candidate=lambda **k: SimpleNamespace(accepted=True, group=object()), close=lambda **k: None))
    with pytest.raises(_PreparationRejected, match="capacity_exceeded"):
        preparation._capture_work_sequence((work,), owner, tmp_path, op, budget, object(), None)
    monkeypatch.setattr(preparation, "_MAX_CAPTURE_SHARDS", 1)
    monkeypatch.setattr(preparation, "_MAX_CAPTURE_ENTRIES", 1)
    with pytest.raises(_PreparationRejected, match="capacity_exceeded"):
        preparation._capture_work_sequence((work, work), owner, tmp_path, op, budget, object(), None)
    point = SimpleNamespace(module_folder=str(tmp_path), module_args=(), module_kwargs={})
    config = SimpleNamespace(policy=SimpleNamespace(max_scanned_entries=1, max_candidates=1))
    monkeypatch.setattr(preparation, "enumerate_module_candidates_owned", lambda *a, **k: (_ for _ in ()).throw(preparation._DiscoveryRejected("timeout")))
    with pytest.raises(_PreparationRejected, match="prepare_timeout"):
        preparation._discover(point, op, config, SimpleNamespace(add_scan=lambda: None))
