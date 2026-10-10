"""Explicit Script registered-name contracts.

Author: DawsonLin
"""
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path
import threading

import pytest

from topsailai.hooks import (
    HookScriptDiscoveryResult, HookScriptEntry, HookScriptEntryResult,
    HookScriptExecutionOptions, HookScriptExecutionPolicy,
    execute_configured_hook_script,
)
from topsailai.tests.unit.test_topsailai_hooks.hook_script_planning_helpers import (
    build_plan, module_binding,
)
from topsailai.tests.unit.test_topsailai_hooks.hook_script_execution_helpers import (
    Clock, FakeHookScriptRunner,
)
from topsailai.tests.unit.test_topsailai_hooks.test_hook_script_execution_red import _event
from topsailai.hooks import HookContext


def _entry(index, name, basename="physical"):
    """Build metadata without touching the filesystem."""
    return HookScriptEntry(Path(f"/metadata/{index}/physical"), basename, name)


def test_legacy_fallback_and_verbatim_frozen_explicit_name():
    """Keep positional compatibility and unrestricted explicit identity."""
    legacy = HookScriptEntry(Path("/metadata/physical"), "physical")
    assert legacy.registered_name is None
    assert legacy.final_registered_name == "physical"
    for name in ("", " ", "a/b", "a\\b", "! no-extension", "é", "e\u0301"):
        entry = _entry(0, name)
        assert entry.registered_name == name
        assert entry.final_registered_name == name
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            entry.final_registered_name = "changed"
        plan = build_plan(HookScriptDiscoveryResult(True, (entry,)))
        assert plan.accepted
        assert plan.bindings[-1].entries[0] == entry
        assert plan.bindings[-1].entries[0] is not entry


def test_final_names_authorize_order_not_paths_or_basenames():
    """Sort exact Unicode strings without normalizing or mutating inputs."""
    names = ("中", "é", "e\u0301", "a2", "a10", "a", "Z", "9", "")
    entries = tuple(_entry(i, name, f"base{i}") for i, name in enumerate(names))
    discovery = HookScriptDiscoveryResult(True, entries)
    result = build_plan(discovery, modules=(module_binding("Z"),))
    assert result.accepted
    output = result.bindings[-1].entries
    assert [e.final_registered_name for e in output] == sorted(names)
    assert {e.final_registered_name for e in output} >= {"é", "e\u0301"}
    assert tuple(e.registered_name for e in entries) == names
    assert discovery.entries is entries
    assert all(out is not original for out in output for original in entries)
    assert [b.binding_id for b in result.bindings] == ["module:Z", "hook_script"]


@pytest.mark.parametrize("names", (("alias", "alias"), (None, "physical"), ("", "")))
def test_duplicate_final_names_reject_whole_candidate(names):
    """Different paths and list positions cannot rescue duplicate identities."""
    entries = (_entry(0, names[0]), _entry(1, "unique"), _entry(2, names[1]))
    snapshot = tuple(asdict(e) for e in entries)
    result = build_plan(HookScriptDiscoveryResult(True, entries))
    assert not result.accepted
    assert result.bindings == () and result.errors
    assert tuple(asdict(e) for e in entries) == snapshot


@pytest.mark.parametrize("name", (0, False, [], {}, object()))
def test_invalid_explicit_name_rejects_atomically(name):
    """Reject unsupported shapes before hashing, ordering or dependent use."""
    entry = _entry(1, name)
    result = build_plan(HookScriptDiscoveryResult(True, (_entry(0, "valid"), entry)))
    assert not result.accepted and result.bindings == ()
    assert entry.registered_name is name


def test_duplicate_source_path_remains_rejected():
    """Separate registered identities do not authorize duplicate source custody."""
    entries = (_entry(0, "first"), _entry(0, "second"))
    result = build_plan(HookScriptDiscoveryResult(True, entries))
    assert not result.accepted and result.bindings == ()


def test_distinct_registered_names_accept_same_physical_basename_and_execute():
    """Runner metadata retains aliases in planned order with legacy result fields."""
    entries = (_entry(0, "z/path"), _entry(1, "A\\name"))
    clock = Clock()
    runner = FakeHookScriptRunner(lambda local: HookScriptEntryResult(**asdict(local)), clock)
    context = HookContext(_event(), "delivery", "hook_script", 1, 10000)
    result = execute_configured_hook_script(
        hook_point="conversation.started", module_bindings=(), bindings_per_event=1,
        discovery_result=HookScriptDiscoveryResult(True, entries), context=context,
        options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
        runner=runner, dispatch_deadline=10.0, cancellation=threading.Event(), clock=clock,
    )
    assert result.status == "success"
    assert [c["entry"].final_registered_name for c in runner.calls] == ["A\\name", "z/path"]
    assert all(c["entry"].basename == "physical" for c in runner.calls)
    assert tuple(e.registered_name for e in entries) == ("z/path", "A\\name")
