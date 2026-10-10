"""Validate the public hook-script planning bridge input-state matrix."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from topsailai.hooks import (
    HookScriptDiscoveryResult,
    HookScriptEntry,
    build_hook_point_binding_plan_from_discovery,
)


def _build(
    *,
    configured: Any,
    discovery_result: Any,
):
    """Invoke the public bridge with a minimal valid base planning request."""
    return build_hook_point_binding_plan_from_discovery(
        hook_point="conversation.started",
        module_bindings=(),
        bindings_per_event=1,
        hook_script_configured=configured,
        discovery_result=discovery_result,
    )


def _assert_rejected(result: Any, error: str) -> None:
    """Require one fixed atomic planning rejection."""
    assert result.accepted is False
    assert result.bindings == ()
    assert result.errors == (error,)


def test_configuration_flag_requires_an_exact_boolean() -> None:
    """Reject truthy and falsey non-boolean configuration values."""
    for configured in (None, 0, 1, "true", (), [], {}):
        result = _build(configured=configured, discovery_result=None)

        _assert_rejected(result, "hook_script_configured must be a boolean")


def test_unconfigured_state_rejects_every_discovery_result() -> None:
    """Allow only a missing discovery result for an unconfigured script."""
    entry = HookScriptEntry(Path("/metadata/script"), "script")
    candidates = (
        HookScriptDiscoveryResult(True),
        HookScriptDiscoveryResult(True, entries=(entry,)),
        HookScriptDiscoveryResult(False, errors=("rejected",)),
        object(),
    )

    for discovery_result in candidates:
        result = _build(configured=False, discovery_result=discovery_result)

        _assert_rejected(
            result,
            "unconfigured hook_script must not have a discovery result",
        )


def test_configured_state_rejects_missing_and_wrong_result_types() -> None:
    """Require the exact discovery result class when a script is configured."""
    missing = _build(configured=True, discovery_result=None)
    _assert_rejected(missing, "configured hook_script requires a discovery result")

    for discovery_result in ({}, [], object()):
        result = _build(configured=True, discovery_result=discovery_result)

        _assert_rejected(
            result,
            "discovery_result must be a HookScriptDiscoveryResult",
        )


def test_discovery_accepted_field_requires_an_exact_boolean() -> None:
    """Reject integer and string substitutes for the accepted boolean."""
    for accepted in (0, 1, "true", "false"):
        discovery_result = HookScriptDiscoveryResult(accepted=accepted)

        result = _build(configured=True, discovery_result=discovery_result)

        _assert_rejected(result, "discovery_result accepted must be a boolean")


def test_discovery_entries_require_a_tuple_of_exact_entry_values() -> None:
    """Reject malformed entry containers and mixed members without partial output."""
    entry = HookScriptEntry(Path("/metadata/script"), "script")
    malformed_entries = ([], None, ("wrong",), (entry, "wrong"))

    for entries in malformed_entries:
        discovery_result = HookScriptDiscoveryResult(True, entries=entries)

        result = _build(configured=True, discovery_result=discovery_result)

        _assert_rejected(
            result,
            "discovery_result entries must contain HookScriptEntry values",
        )


def test_discovery_errors_require_nonempty_string_tuple_members() -> None:
    """Reject malformed diagnostic containers and members."""
    malformed_errors = ([], None, ("",), (1,), ("valid", ""))

    for errors in malformed_errors:
        discovery_result = HookScriptDiscoveryResult(False, errors=errors)

        result = _build(configured=True, discovery_result=discovery_result)

        _assert_rejected(
            result,
            "discovery_result errors must contain non-empty strings",
        )


def test_contradictory_discovery_states_reject_and_valid_errors_survive() -> None:
    """Reject contradictory states while preserving a valid rejection tuple."""
    entry = HookScriptEntry(Path("/metadata/script"), "script")
    contradictions = (
        (
            HookScriptDiscoveryResult(True, errors=("unexpected",)),
            "accepted discovery result must not contain errors",
        ),
        (
            HookScriptDiscoveryResult(
                False,
                entries=(entry,),
                errors=("rejected",),
            ),
            "rejected discovery result must not contain entries",
        ),
        (
            HookScriptDiscoveryResult(False),
            "rejected discovery result must contain errors",
        ),
    )
    for discovery_result, error in contradictions:
        result = _build(configured=True, discovery_result=discovery_result)

        _assert_rejected(result, error)

    errors = ("first rejection", "second rejection")
    rejected = _build(
        configured=True,
        discovery_result=HookScriptDiscoveryResult(False, errors=errors),
    )
    assert rejected.accepted is False
    assert rejected.bindings == ()
    assert rejected.errors is errors


def test_valid_states_sort_names_and_preserve_detached_metadata() -> None:
    """Accept all legal states without mutating or aliasing entry metadata."""
    entries = (
        HookScriptEntry(Path("/metadata/alpha"), "alpha"),
        HookScriptEntry(Path("/metadata/Zulu"), "Zulu"),
    )
    discovery_result = HookScriptDiscoveryResult(True, entries=entries)
    cases = (
        (False, None, ()),
        (True, HookScriptDiscoveryResult(True), ()),
        (True, discovery_result, tuple(reversed(entries))),
    )

    for configured, candidate, expected_entries in cases:
        result = _build(configured=configured, discovery_result=candidate)

        assert result.accepted is True
        assert result.errors == ()
        terminal = result.bindings[-1]
        assert terminal.configured is configured
        assert terminal.entries == expected_entries

    terminal_entries = _build(
        configured=True,
        discovery_result=discovery_result,
    ).bindings[-1].entries
    assert terminal_entries is not entries
    assert terminal_entries[0] is not entries[0]
    assert [entry.basename for entry in terminal_entries] == ["Zulu", "alpha"]
    assert discovery_result.entries is entries
    with pytest.raises(TypeError):
        terminal_entries[0] = terminal_entries[1]
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        terminal_entries[0].basename = "changed"
    assert [entry.basename for entry in discovery_result.entries] == ["alpha", "Zulu"]


@pytest.mark.parametrize("handler_ref", (None, "", ":main", "plugin:", "plugin:run", "plugin:main:extra",
                                       "a²:main", "1plugin:main", "package.1plugin:main",
                                       "plugin name:main", "plugin..child:main", ".plugin:main",
                                       "plugin.:main"))
def test_discovery_bridge_rejects_invalid_module_entry(handler_ref: object) -> None:
    """An accepted script discovery cannot bypass the unified Module entry check."""
    from topsailai.tests.unit.test_topsailai_hooks.hook_script_terminal_helpers import module_binding

    discovery = HookScriptDiscoveryResult(True)
    binding = module_binding("alias", handler_ref=handler_ref)
    result = build_hook_point_binding_plan_from_discovery(
        hook_point="conversation.started",
        module_bindings=(module_binding("alpha"), binding),
        bindings_per_event=3,
        hook_script_configured=True,
        discovery_result=discovery,
    )

    _assert_rejected(result, "module handler_ref must use non-empty module:main format")
    assert discovery == HookScriptDiscoveryResult(True)
    assert binding.handler_ref is handler_ref
    assert binding.after == ()


@pytest.mark.parametrize(
    "handler_ref", ("插件:main", "package.插件:main", "éclair:main", "a\u0301:main"),
)
def test_discovery_bridge_accepts_python_identifiers_without_mutation(handler_ref: str) -> None:
    """Preserve valid Unicode import names independently of the registered alias."""
    from topsailai.tests.unit.test_topsailai_hooks.hook_script_terminal_helpers import module_binding

    discovery = HookScriptDiscoveryResult(True)
    binding = module_binding("display_alias", handler_ref=handler_ref)
    candidate = (module_binding("alpha"), binding)
    result = build_hook_point_binding_plan_from_discovery(
        hook_point="conversation.started",
        module_bindings=candidate,
        bindings_per_event=3,
        hook_script_configured=True,
        discovery_result=discovery,
    )

    assert result.accepted
    assert result.errors == ()
    assert [item.binding_id for item in result.bindings] == [
        "module:alpha", "module:display_alias", "hook_script",
    ]
    assert result.bindings[1].handler_ref == handler_ref
    assert binding.handler_ref == handler_ref
    assert all(item.after == () for item in candidate)
    assert discovery == HookScriptDiscoveryResult(True)


@pytest.mark.parametrize("source, basename", (("not-path", "physical"), (Path("relative"), "physical"), (Path("/metadata/a"), 1), (Path("/metadata/a"), ""), (Path("/metadata/a"), "a/b"), (Path("/metadata/a"), "a\\b")))
def test_invalid_physical_metadata_rejects_atomically(source, basename):
    """Validate physical admission metadata independently of registered identity."""
    entry = HookScriptEntry(source, basename)
    candidate = HookScriptDiscoveryResult(True, (entry,))
    result = _build(configured=True, discovery_result=candidate)
    assert not result.accepted and result.bindings == ()
    assert candidate.entries == (entry,)
