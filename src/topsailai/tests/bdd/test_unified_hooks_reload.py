"""Gherkin bindings and focused regressions for Unified Hooks reload behavior."""

import pytest
from pytest_bdd import scenarios

from tests.bdd.steps.unified_hooks_reload_steps import *  # noqa: F403
from tests.bdd.unified_hooks_reload_harness import UnifiedHooksReloadScenario


scenarios("features/unified_hooks_reload.feature")


def test_initialization_interrupt_survives_cleanup_interrupt(monkeypatch, tmp_path) -> None:
    """Keep the original initialization interruption and attach cleanup diagnostics."""
    initialization_error = KeyboardInterrupt("initialize")
    cleanup_error = SystemExit("cleanup")
    monkeypatch.setattr(
        UnifiedHooksReloadScenario,
        "_initialize_reload_runtime",
        lambda self: (_ for _ in ()).throw(initialization_error),
    )
    monkeypatch.setattr(
        UnifiedHooksReloadScenario,
        "close",
        lambda self: (_ for _ in ()).throw(cleanup_error),
    )

    with pytest.raises(KeyboardInterrupt) as captured:
        UnifiedHooksReloadScenario(tmp_path)

    assert captured.value is initialization_error
    assert any("SystemExit('cleanup')" in note for note in captured.value.__notes__)


def test_cleanup_interrupt_survives_ordinary_initialization_error(
    monkeypatch, tmp_path
) -> None:
    """Propagate cleanup interruption while retaining initialization diagnostics."""
    initialization_error = RuntimeError("initialize")
    cleanup_error = SystemExit("cleanup")
    monkeypatch.setattr(
        UnifiedHooksReloadScenario,
        "_initialize_reload_runtime",
        lambda self: (_ for _ in ()).throw(initialization_error),
    )
    monkeypatch.setattr(
        UnifiedHooksReloadScenario,
        "close",
        lambda self: (_ for _ in ()).throw(cleanup_error),
    )

    with pytest.raises(SystemExit) as captured:
        UnifiedHooksReloadScenario(tmp_path)

    assert captured.value is cleanup_error
    assert any("RuntimeError('initialize')" in note for note in captured.value.__notes__)
