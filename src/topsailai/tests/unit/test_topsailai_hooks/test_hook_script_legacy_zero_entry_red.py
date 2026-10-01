"""RED contracts for legacy unconfigured hook_script zero-entry settlement."""

from __future__ import annotations

from pathlib import Path

from topsailai.hooks import (
    HookScriptBinding,
    HookScriptEntry,
    settle_unconfigured_hook_script,
)


def _unconfigured_terminal(
    entries: tuple[HookScriptEntry, ...] = (),
) -> HookScriptBinding:
    """Build one framework-owned reserved terminal with the supplied metadata."""
    return HookScriptBinding(
        binding_id="hook_script",
        hook_point="conversation.started",
        priority=2_147_483_647,
        after=(),
        framework_owned=True,
        terminal=True,
        configured=False,
        entries=entries,
    )


def test_unconfigured_empty_entries_preserve_successful_settlement() -> None:
    """A valid unconfigured empty terminal retains its successful no-op record."""
    terminal = _unconfigured_terminal()

    outcome = settle_unconfigured_hook_script(terminal)

    assert outcome.status == "success"
    assert outcome.entry_results == ()
    assert outcome.started is False
    assert outcome.error_category is None
    assert terminal == _unconfigured_terminal()


def test_unconfigured_nonempty_entries_are_rejected() -> None:
    """An unconfigured terminal cannot discard pending entries as zero work."""
    entries = (HookScriptEntry(Path("/in-memory/hook"), "hook"),)
    terminal = _unconfigured_terminal(entries)

    outcome = settle_unconfigured_hook_script(terminal)

    assert outcome.status == "error"
    assert outcome.error_category == "hook_script_nonempty_entries"
    assert outcome.entry_results == ()
    assert outcome.started is False
    assert terminal.entries is entries
    assert terminal == _unconfigured_terminal(entries)
