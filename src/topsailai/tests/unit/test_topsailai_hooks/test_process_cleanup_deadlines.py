"""Resource-free backend cleanup profile regressions. Author: DawsonLin."""

import pytest

from pathlib import Path
from types import SimpleNamespace
import threading
import time

from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.hook_point_plan_contracts import CapturedModule, ModuleSource
from topsailai.hooks.result_contracts import HandlerIdentity
from topsailai.hooks import script_runner
from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions, HookScriptExecutionPolicy
from topsailai.hooks.hook_script_discovery import HookScriptEntry
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context


@pytest.fixture(autouse=True)
def reap_focused_hook_processes():
    """This exclusively resource-free suite never creates process cleanup obligations."""
    yield


def _forbidden(*args, **kwargs):
    """Fail on any unexpected resource acquisition or foreign observation."""
    raise AssertionError("unexpected resource access")


class _Poison:
    """Reject observation of supplied records, locks and inventories."""

    def __getattribute__(self, name):
        """Make premature record or inventory observation immediately visible."""
        if name == "__class__":
            return object.__getattribute__(self, name)
        return _forbidden()

    def __enter__(self):
        """Reject legacy lock acquisition."""
        return _forbidden()


@pytest.mark.parametrize("profile", [None, True, 1, [], {}, "", "Legacy", "legacy ", "other"])
def test_profile_exact_validation(tmp_path, profile):
    """Reject malformed profile values without constructing backend state."""
    with pytest.raises(ValueError):
        IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_profile=profile)


def test_profile_string_subclass_rejected(tmp_path):
    """String lookalikes must not mint profile authority."""
    class Text(str):
        """Represent a nonexact string without conversion hooks."""
    with pytest.raises(ValueError):
        IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_profile=Text("legacy"))


@pytest.mark.parametrize("profile", ["legacy", "custodian_v1"])
def test_profile_write_once_and_reinitialization(tmp_path, profile):
    """Protect only profile selection and preserve live state on repeated initialization."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_profile=profile)
    backend._debts["sentinel"] = object()
    debts = backend._debts
    for name in ("cleanup_profile", "_cleanup_profile"):
        with pytest.raises(AttributeError):
            setattr(backend, name, "legacy")
        with pytest.raises(AttributeError):
            delattr(backend, name)
    for other in ("legacy", "custodian_v1"):
        with pytest.raises(RuntimeError):
            backend.__init__(temp_root=str(tmp_path), cleanup_profile=other)
        with pytest.raises(RuntimeError):
            backend._initialize_cleanup_profile(other)
    assert backend.cleanup_profile == profile
    assert backend._debts is debts and "sentinel" in debts
    backend._output_limit = 7
    backend.note = "mutable"
    del backend.note
    assert backend._output_limit == 7


def test_profile_constructor_resource_free_and_independent(tmp_path, monkeypatch):
    """Construction selects per-instance modes without starting or creating anything."""
    from topsailai.hooks import process_backend as module
    real_os = module.os
    monkeypatch.setattr(module, "os", SimpleNamespace(path=real_os.path, makedirs=_forbidden, pipe=_forbidden))
    monkeypatch.setattr(module, "threading", SimpleNamespace(Lock=threading.Lock, Thread=_forbidden))
    monkeypatch.setattr(module, "subprocess", SimpleNamespace(Popen=_forbidden))
    legacy = IsolatedProcessBackend(temp_root=str(tmp_path))
    closed = IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_profile="custodian_v1")
    assert (legacy.cleanup_profile, closed.cleanup_profile) == ("legacy", "custodian_v1")
    assert legacy._profile_rejection() is None
    assert legacy.script_temp_root == str(tmp_path)
    assert legacy.cleanup_debts() == ()
    assert legacy.cleanup_debts_for_record(SimpleNamespace(debt_id="absent")) == ()
    assert legacy.retry_cleanup("absent")


def _closed_backend(tmp_path, monkeypatch):
    """Poison every downstream resource seam after closed-profile construction."""
    from topsailai.hooks import process_backend as module
    from topsailai.hooks import process_execution as execution
    backend = IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_profile="custodian_v1")
    monkeypatch.setattr(module, "os", _Poison())
    monkeypatch.setattr(module, "threading", _Poison())
    monkeypatch.setattr(module, "subprocess", _Poison())
    monkeypatch.setattr(execution, "os", _Poison())
    monkeypatch.setattr(execution, "_LaunchRecord", _forbidden)
    backend._resolve_interpreter = _forbidden
    backend._debt_lock = backend._debts = backend._debt_processes = _Poison()
    backend._launch_debt_records = _Poison()
    return backend


@pytest.mark.parametrize("entry", ["preflight", "execute", "module", "captured", "spawn", "script"])
def test_profile_execution_rejects_before_acquisition(tmp_path, monkeypatch, entry):
    """Every closed execution entry rejects without records, callbacks or launch."""
    source = ModuleSource("observer", tmp_path / "observer.py", "observer", "python_source", "observer:main")
    captured = CapturedModule(HandlerIdentity("id", "observer", "module"), source,
                              "a" * 64, 0, "entry-000000/observer.py",
                              tmp_path / "entry-000000" / "observer.py", "b" * 64, "c" * 64)
    context = _context()
    backend = _closed_backend(tmp_path, monkeypatch)
    if entry == "preflight":
        result = backend._preflight(0)
    elif entry == "execute":
        result = backend.execute("observer:main", context, 100)
    elif entry == "module":
        result = backend.execute_module("observer:main", context, 100)
    elif entry == "captured":
        result = backend.execute_captured_module(captured, context, 100, record_receiver=_forbidden)
    elif entry == "spawn":
        result = backend._spawn("unused", 10, _Poison())
    else:
        result = backend.launch_script(argv=(), cwd="unused", environment={},
                                       argument_environment_limit_bytes=1, deadline=10, record=_Poison())
    assert result.status == "unsupported_backend"
    assert result.error_category == "cleanup_profile_not_ready"
    assert result.cleanup_confirmed and result.cleanup_debt is None
    assert result.value is None and not result.returned.present


@pytest.mark.parametrize("entry", ["root", "debts", "record_debts", "retry"])
def test_profile_legacy_authority_is_closed(tmp_path, monkeypatch, entry):
    """Never query legacy locks or claim settlement for foreign record custody."""
    backend = _closed_backend(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="^cleanup_profile_not_ready$"):
        if entry == "root":
            backend.script_temp_root
        elif entry == "debts":
            backend.cleanup_debts()
        elif entry == "record_debts":
            backend.cleanup_debts_for_record(_Poison())
        else:
            backend.retry_cleanup(_Poison(), record=_Poison())


def test_profile_uninitialized_fails_closed():
    """An uninitialized backend cannot silently acquire legacy authority."""
    backend = IsolatedProcessBackend.__new__(IsolatedProcessBackend)
    with pytest.raises(RuntimeError, match="cleanup_profile_not_ready"):
        backend._preflight(100)
    with pytest.raises(RuntimeError, match="cleanup_profile_not_ready"):
        backend.cleanup_debts()


def test_profile_actual_script_runner_preallocation(tmp_path, monkeypatch):
    """The real runner rejects storage-root access before allocating its owner."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_profile="custodian_v1")
    runner = script_runner.OwnedHookScriptRunner(backend)
    monkeypatch.setattr(script_runner, "TemporaryStorageOwner", _forbidden)
    deadline = time.monotonic() + 10
    with pytest.raises(RuntimeError, match="^cleanup_profile_not_ready$"):
        runner.execute_entry(entry_index=0, entry=HookScriptEntry(tmp_path / "audit", "audit"),
                             context=_context(), options=HookScriptExecutionOptions(),
                             policy=HookScriptExecutionPolicy(), execution_deadline=deadline,
                             cleanup_deadline=deadline + 1, output_remaining_bytes=100,
                             cancellation=threading.Event())
    assert not runner._storage and not runner._process_storage


def test_profile_legacy_preflight_and_invalid_capture(tmp_path):
    """Preserve legacy validation and resource-free invalid-capture precedence."""
    legacy = IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_profile="legacy")
    assert legacy._preflight(0).error_category == "invalid_timeout"
    assert legacy._preflight(100) is None
    closed = IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_profile="custodian_v1")
    assert closed.execute_captured_module(object(), _context(), 100).status == "invalid_request"


def test_profile_preserves_actual_supplied_record(tmp_path):
    """Rejection preserves existing custody without claiming its settlement."""
    from topsailai.hooks.process_state import LaunchRecord
    backend = IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_profile="custodian_v1")
    record = LaunchRecord("foreign", state="published", cleanup_confirmed=False,
                          cleanup_debt="existing-debt")
    condition, cleanup = record.condition, record.cleanup
    for result in (
        backend._spawn("unused", 10, record),
        backend.launch_script(argv=(), cwd="unused", environment={},
                              argument_environment_limit_bytes=1, deadline=10, record=record),
    ):
        assert result.status == "unsupported_backend"
    for call in (lambda: backend.cleanup_debts_for_record(record),
                 lambda: backend.retry_cleanup("foreign", record=record)):
        with pytest.raises(RuntimeError, match="cleanup_profile_not_ready"):
            call()
    assert record.condition is condition and record.cleanup is cleanup
    assert record.state == "published" and not record.cleanup_confirmed
    assert record.cleanup_debt == "existing-debt" and record.process is None
    assert record.result_fd is None and record.error is None
