"""Focused completion coverage for configured-preparation decision branches."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import topsailai.hooks.configured_preparation as preparation
from topsailai.hooks.configured_preparation import _PreparationRejected


def _valid_config(source):
    from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, EventDefinition, HookSettings
    point = ConfiguredHookPoint("hook_alpha", EventDefinition("event", 1), module_folder=source)
    return ConfiguredHooks((point,), HookSettings())


def _config(point):
    return SimpleNamespace(hook_points=(point,), settings=SimpleNamespace(limits=SimpleNamespace(bindings_per_event=1)))


def _point(*, module_folder=None, script=None):
    return SimpleNamespace(
        module_folder=module_folder,
        script=script,
        hook_name="hook",
        module_args=(),
        module_kwargs={},
        definition=SimpleNamespace(name="event", major_version=1),
        max_concurrency=1,
    )


def _operation():
    import time
    return SimpleNamespace(deadline=time.monotonic() + 100, cancellation=None, checkpoint=lambda: None)


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_prepare_aggregate_constructor_host_failure_precedes_root(monkeypatch, tmp_path, exc_type):
    """Aggregate host construction fails before any root custody exists."""
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(mode=0o700)
    helper = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])
    runtime, scope = helper._runtime(source, runtime_root)
    marker = exc_type("aggregate construction failure")
    calls = []

    def fail_ownership(*args):
        calls.append(args)
        raise marker

    monkeypatch.setattr(preparation, "PreparationOwnership", fail_ownership)
    monkeypatch.setattr(preparation, "ConfiguredRootOwner", lambda path: pytest.fail("root must not be constructed"))
    try:
        with pytest.raises(exc_type) as caught:
            preparation.prepare_private(runtime, _valid_config(source), scope)
        assert caught.value is marker
        assert len(calls) == 1
        assert get_recovery_owner(caught.value) is None
    finally:
        runtime.close()


@pytest.mark.parametrize("failure", [RuntimeError("ordinary aggregate failure"), ValueError("aggregate failure")])
def test_prepare_aggregate_constructor_ordinary_failure_is_stable(monkeypatch, tmp_path, failure):
    """Aggregate ordinary construction failure prevents root custody."""
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(mode=0o700)
    helper = __import__("tests.unit.test_topsailai_hooks.test_configured_preparation", fromlist=["_runtime"])
    runtime, scope = helper._runtime(source, runtime_root)
    calls = []

    def fail_ownership(*args):
        calls.append(args)
        raise failure

    monkeypatch.setattr(preparation, "PreparationOwnership", fail_ownership)
    monkeypatch.setattr(preparation, "ConfiguredRootOwner", lambda path: pytest.fail("root must not be constructed"))
    try:
        result = preparation.prepare_private(runtime, _valid_config(source), scope)
        assert result.accepted is False
        assert result.errors == ("internal_error",)
        assert "ordinary aggregate failure" not in repr(result)
        assert len(calls) == 1
        assert get_recovery_owner(result) is None
    finally:
        runtime.close()


def get_recovery_owner(error):
    """Return the public preparation recovery owner for a test exception."""
    return preparation.get_preparation_recovery_owner(error)


def test_build_work_sequence_script_absent_and_present(monkeypatch, tmp_path):
    operation = _operation()
    budget = SimpleNamespace(add_candidate=lambda count=1: None, add_scan=lambda count=1: None)
    no_script = _point()
    assert preparation._build_work_sequence(_config(no_script), operation, budget) == ()
    script = SimpleNamespace(target=tmp_path / "hook.py", platform_policy=SimpleNamespace())
    entry = SimpleNamespace(basename="hook.py", source_path=tmp_path / "hook.py")
    monkeypatch.setattr(preparation, "discover_prepared_script_entries", lambda *args, **kwargs: SimpleNamespace(accepted=True, entries=(entry,)))
    works = preparation._build_work_sequence(_config(_point(script=script)), operation, budget)
    assert len(works) == 1 and works[0].entry is entry


@pytest.mark.parametrize("result", [
    SimpleNamespace(accepted=False, entries=()),
    SimpleNamespace(accepted=True, entries=(object(), object())),
])
def test_build_work_sequence_rejects_script_discovery_shapes(monkeypatch, tmp_path, result):
    script = SimpleNamespace(target=tmp_path / "hook.py", platform_policy=SimpleNamespace())
    monkeypatch.setattr(preparation, "discover_prepared_script_entries", lambda *args, **kwargs: result)
    if not result.accepted:
        with pytest.raises(_PreparationRejected):
            preparation._build_work_sequence(_config(_point(script=script)), _operation(), SimpleNamespace())
    else:
        works = preparation._build_work_sequence(_config(_point(script=script)), _operation(), SimpleNamespace())
        assert tuple(work.entry for work in works) == result.entries


def test_probe_close_failure_is_cleanup_pending(monkeypatch, tmp_path):
    point = _point(module_folder=tmp_path)
    candidate = SimpleNamespace(logical_name="m", source_path=tmp_path / "m.py", kind="python_source")
    work = preparation._ModuleWork(0, point, tmp_path, candidate)
    item = preparation._CapturedWork(work, SimpleNamespace(identity="id"), tmp_path / "m.py")
    entry = SimpleNamespace(entry_valid=True, logical_name="m", source_path=tmp_path / "m.py", load_status="loaded")
    session = SimpleNamespace(state="closed", probe=lambda *args, **kwargs: (entry, SimpleNamespace(cleanup_confirmed=True)), close=lambda: False)
    def invoke(**kwargs):
        return kwargs["operation"](session)
    monkeypatch.setattr(preparation, "_run_with_module_probe_session", invoke)
    with pytest.raises(_PreparationRejected, match="cleanup_pending"):
        preparation._probe_and_plan(_config(point), (item,), SimpleNamespace(register_module_owner=lambda *args: None), tmp_path, _operation(), SimpleNamespace(), None)

def test_map_capture_batch_rejects_non_directory_escape(monkeypatch, tmp_path):
    directory = tmp_path / "lease"
    directory.mkdir()
    source = tmp_path / "source.py"
    source.write_text("x")
    outside = tmp_path / "outside.py"
    outside.write_text("x")
    link = directory / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink unavailable")
    work = preparation._ModuleWork(0, SimpleNamespace(), tmp_path, SimpleNamespace(source_path=source, kind="python_source", logical_name="m"))
    entry = SimpleNamespace(index=0, kind="python_source", logical_name="m", validation=SimpleNamespace(source_path=source), relative_path="link.py")
    with pytest.raises(_PreparationRejected, match="artifact_rejected"):
        preparation._map_capture_batch((work,), SimpleNamespace(entries=(entry,), directory=directory))
