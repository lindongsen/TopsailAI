"""Ordinary preparation rejection facts and ownership. Author: DawsonLin."""
from types import SimpleNamespace
import time
import pytest
from topsailai.hooks import ordinary_runtime as ordinary
from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import _runtime, _event


@pytest.mark.parametrize("boundary", ["before_discovery", "after_discovery", "after_capture"])
def test_preparation_expiry_preserves_deadline_and_settles_owners(tmp_path, monkeypatch, boundary):
    """Observe expiry at each original checkpoint without resetting the budget."""
    runtime, scope = _runtime(tmp_path)
    origin = time.monotonic()
    deadline = origin + 2.0
    clock = [origin]
    captured = []
    discovered = []
    original_discovery = ordinary.discover_configured_hook_scripts
    original_build = ordinary.build_hook_point_candidate

    def discovery(**kwargs):
        """Move the isolated clock only after discovery completes."""
        discovered.append(True)
        result = original_discovery(**kwargs)
        if boundary == "after_discovery":
            clock[0] = deadline
        return result

    def capture(*args, **kwargs):
        """Retain exact candidate evidence before forcing post-capture expiry."""
        assert kwargs["deadline"] == deadline
        candidate = original_build(*args, **kwargs)
        captured.append(candidate)
        clock[0] = deadline
        return candidate

    ticks = iter([origin, deadline])
    monkeypatch.setattr(ordinary, "time", SimpleNamespace(monotonic=
        (lambda: next(ticks, deadline)) if boundary == "before_discovery" else lambda: clock[0]))
    monkeypatch.setattr(ordinary, "discover_configured_hook_scripts", discovery)
    monkeypatch.setattr(ordinary, "build_hook_point_candidate", capture)
    try:
        assert runtime.register_hook_point("hook_before_chat", scope).accepted
        report = runtime.dispatch_hook_point("hook_before_chat", _event(runtime, scope))
        assert report.rejection_reason == "deadline"
        assert report.deadline_exhausted
        assert bool(discovered) is (boundary != "before_discovery")
        assert bool(captured) is (boundary == "after_capture")
        assert all(owner._closed for owner in captured)
        assert not runtime.cleanup_debts()
        assert runtime._registry.configured_plan(scope.scope_id, "hook_before_chat")[1] is None
    finally:
        runtime.close()


@pytest.mark.parametrize("reason", ["cancelled", "capacity", "closed_scope", "deadline_extra"])
def test_early_non_deadline_rejection_does_not_claim_remaining_time(tmp_path, reason):
    """Exact category mapping does not add a clock observation to early rejection."""
    runtime, scope = _runtime(tmp_path)
    try:
        report = runtime._rejected(_event(runtime, scope), reason)
        assert report.rejection_reason == reason and not report.deadline_exhausted
    finally:
        runtime.close()
