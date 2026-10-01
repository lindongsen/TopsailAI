"""RED contracts for pure static-discovery to terminal-plan composition."""

from __future__ import annotations

import importlib
import os
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from topsailai.tests.unit.test_topsailai_hooks.hook_script_planning_helpers import (
    accepted_discovery,
    build_plan,
    module_binding,
    plan_bindings,
    rejected_discovery,
    terminal_entries,
)


def test_valid_discovery_entries_feed_one_terminal_binding_in_order(tmp_path: Path) -> None:
    """Accepted static entries become one ordered framework terminal node."""
    discovery = accepted_discovery("Zulu", "alpha", "beta", root=tmp_path)

    result = build_plan(discovery)

    bindings = plan_bindings(result)
    assert result.accepted and result.errors == ()
    assert [binding.binding_id for binding in bindings].count("hook_script") == 1
    terminal = bindings[-1]
    assert terminal.framework_owned is True
    assert terminal.terminal is True
    assert [entry.basename for entry in terminal_entries(result)] == [
        "Zulu",
        "alpha",
        "beta",
    ]


def test_unconfigured_and_accepted_empty_discovery_keep_terminal_noop(tmp_path: Path) -> None:
    """Both legal no-entry forms retain one configured-state-aware terminal no-op."""
    unconfigured = build_plan(None, configured=False)
    configured_empty = build_plan(accepted_discovery(root=tmp_path), configured=True)

    for result, configured in ((unconfigured, False), (configured_empty, True)):
        bindings = plan_bindings(result)
        assert result.accepted
        assert len([item for item in bindings if item.binding_id == "hook_script"]) == 1
        assert bindings[-1].configured is configured
        assert terminal_entries(result) == ()


def test_rejected_config_including_empty_target_rejects_whole_candidate() -> None:
    """Explicit discovery rejection is never converted to an unconfigured no-op."""
    from topsailai.hooks import ExecutablePlatformPolicy, discover_hook_script_entries

    empty_target = discover_hook_script_entries(
        "",
        ExecutablePlatformPolicy(platform="posix"),
    )
    assert not empty_target.accepted
    assert empty_target.entries == ()
    for discovery in (
        empty_target,
        rejected_discovery("hook_script path escapes configured root"),
    ):
        result = build_plan(
            discovery,
            modules=(module_binding("alpha"),),
            configured=True,
        )

        assert not result.accepted
        assert plan_bindings(result) == ()
        assert result.errors == discovery.errors


def test_terminal_entry_metadata_is_a_detached_immutable_ordered_snapshot(
    tmp_path: Path,
) -> None:
    """Planning snapshots metadata without claiming referenced file immutability."""
    discovery = accepted_discovery("first", "second", root=tmp_path)

    result = build_plan(discovery)

    entries = terminal_entries(result)
    assert entries is not discovery.entries
    assert [(entry.source_path, entry.basename) for entry in entries] == [
        (entry.source_path, entry.basename) for entry in discovery.entries
    ]
    with pytest.raises(TypeError):
        entries[0] = entries[1]
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        entries[0].basename = "changed"
    assert [entry.basename for entry in terminal_entries(result)] == ["first", "second"]


def test_bridge_preserves_uniqueness_capacity_and_completion_before_start(
    tmp_path: Path,
) -> None:
    """Composition retains existing reserved-node capacity and dependency rules."""
    discovery = accepted_discovery("script", root=tmp_path)
    exact = build_plan(
        discovery,
        modules=(module_binding("beta"), module_binding("Alpha")),
        capacity=3,
    )
    overflow = build_plan(
        discovery,
        modules=(module_binding("Alpha"), module_binding("beta")),
        capacity=2,
    )

    bindings = plan_bindings(exact)
    assert exact.accepted
    assert [item.binding_id for item in bindings] == [
        "module:Alpha",
        "module:beta",
        "hook_script",
    ]
    assert bindings[0].after == ()
    assert bindings[1].after == ("module:Alpha",)
    assert bindings[2].after == ("module:Alpha", "module:beta")
    assert not overflow.accepted
    assert plan_bindings(overflow) == ()
    assert overflow.errors == ("bindings_per_event limit exceeded",)


def test_bridge_preserves_reserved_identity_and_requires_success_rejections(
    tmp_path: Path,
) -> None:
    """Composition cannot weaken terminal ownership or module dependency policy."""
    discovery = accepted_discovery("script", root=tmp_path)
    reserved = build_plan(
        discovery,
        modules=(module_binding("user", binding_id="hook_script"),),
    )
    success_gated = build_plan(
        discovery,
        modules=(module_binding("beta", requires_success=("module:Alpha",)),),
    )

    assert not reserved.accepted and plan_bindings(reserved) == ()
    assert reserved.errors == ("hook_script binding is framework-owned",)
    assert not success_gated.accepted and plan_bindings(success_gated) == ()
    assert success_gated.errors == (
        "discovered module requires_success dependencies are not supported",
    )


def test_bridge_is_pure_and_has_no_discovery_import_process_or_runtime_side_effects(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Planning consumes the result without rescanning, importing, executing, or publishing."""
    discovery = accepted_discovery("script", root=tmp_path)
    observed: list[str] = []

    def forbidden(name: str):
        def fail(*args: object, **kwargs: object) -> None:
            observed.append(name)
            raise AssertionError(f"pure planning attempted {name}")

        return fail

    monkeypatch.setattr(Path, "iterdir", forbidden("filesystem rescan"))
    monkeypatch.setattr(importlib, "import_module", forbidden("module import"))
    monkeypatch.setattr(subprocess, "Popen", forbidden("process launch"))
    monkeypatch.setattr(subprocess, "run", forbidden("process run"))
    monkeypatch.setattr(os, "system", forbidden("shell launch"))

    result = build_plan(discovery)

    assert result.accepted
    assert observed == []
    assert not hasattr(result, "runtime")
    assert not hasattr(result, "registry")
    assert not hasattr(result, "scheduler")
    assert not hasattr(result, "generation")
