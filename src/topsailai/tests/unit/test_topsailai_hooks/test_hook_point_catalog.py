"""Tests for the public Hook-point declaration catalog."""

from __future__ import annotations

import pytest

from topsailai.hooks import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration


def _point(
    name: str, phase: str = "before", *, event_name: str | None = None, **kwargs: object
) -> HookPointDeclaration:
    """Build one ordinary test declaration."""
    values = {
        "name": name,
        "definition": EventDefinition(f"test.{name}" if event_name is None else event_name, 1),
        "phase": phase,
        "mode": "sync",
        "owner": "tests/example.py:operation",
    }
    values.update(kwargs)
    return HookPointDeclaration(**values)


def test_catalog_indexes_stable_names_and_rejects_duplicates() -> None:
    """Catalog names and event identities must be unique."""
    point = _point("hook_test_before")
    catalog = HookPointCatalog((point,))
    assert catalog.require(point.name) == point
    with pytest.raises(ValueError, match="invalid Hook-point catalog"):
        HookPointCatalog((point, point))


def test_block_requires_security_approval_and_success_risk_opt_in() -> None:
    """Blocking declarations need explicit catalog authority."""
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point("hook_test_before", failure_policy="block")
    before = _point(
        "hook_test_before", failure_policy="block", security_critical=True
    )
    assert before.failure_policy == "block"
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point(
            "hook_test_success", phase="success", failure_policy="block",
            security_critical=True,
        )
    success = _point(
        "hook_test_success", phase="success", failure_policy="block",
        security_critical=True, allow_post_success_block=True,
    )
    assert success.allow_post_success_block is True


def test_declaration_detaches_sensitive_fields_and_validates_mode() -> None:
    """Sensitive-field allowlists are immutable and modes are exact."""
    fields = ["record_id"]
    point = _point("hook_test_error", phase="error", sensitive_fields=fields)
    fields.append("secret")
    assert point.sensitive_fields == ("record_id",)
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point("hook_test_invalid", mode="sometimes")


def test_declaration_rejects_post_success_flag_duplicates_and_invalid_catalog() -> None:
    """Risk flags, sensitive fields, unknown names, and catalog shape stay exact."""
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point("hook_test_before", allow_post_success_block=True)
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point("hook_test_error", phase="error", sensitive_fields=("secret", "secret"))
    with pytest.raises(ValueError, match="invalid Hook-point catalog"):
        HookPointCatalog([_point("hook_test_before")])

    catalog = HookPointCatalog((_point("hook_test_before"),))
    assert catalog.get(1) is None
    with pytest.raises(KeyError):
        catalog.require("hook_missing")


def test_background_mode_is_rejected_without_async_conversion() -> None:
    """Only explicit sync and async waiting declarations are supported."""
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point("hook_test_background", mode="background")
    for mode in ("sync", "async"):
        assert _point("hook_test_waiting", mode=mode).mode == mode


@pytest.mark.parametrize(("name_phase", "phase"), [
    ("before", "before"), ("after", "success"), ("error", "error"),
])
def test_unified_declaration_identity_and_phase_survive_catalog(
    name_phase: str, phase: str
) -> None:
    """Catalog defensive reconstruction preserves valid unified declarations."""
    name = f"hook__context__{name_phase}__summary_generate_user2agent"
    point = _point(name, phase, event_name=name)
    catalog = HookPointCatalog((point,))
    assert catalog.require(name) == point
    assert catalog.require(name).definition.name == name
    assert catalog.require(name).phase == phase


@pytest.mark.parametrize(("name_phase", "phase"), [
    ("before", "before"), ("after", "success"), ("error", "error"),
])
def test_unified_declaration_rejects_independent_event_name(
    name_phase: str, phase: str
) -> None:
    """A valid new-format point cannot publish under another event identity."""
    name = f"hook__context__{name_phase}__summary_generate_agent2llm"
    with pytest.raises(ValueError, match="^invalid Hook-point declaration$"):
        _point(name, phase, event_name="event.independent")


@pytest.mark.parametrize(("name_phase", "phase"), [
    ("before", "success"), ("before", "error"),
    ("after", "before"), ("after", "error"),
    ("error", "before"), ("error", "success"),
])
def test_unified_declaration_rejects_phase_mismatch(name_phase: str, phase: str) -> None:
    """Each unified name phase permits only its corresponding framework phase."""
    name = f"hook__context__{name_phase}__summary_generate_user2agent"
    with pytest.raises(ValueError, match="^invalid Hook-point declaration$"):
        _point(name, phase, event_name=name)


@pytest.mark.parametrize("phase", ["before", "success", "error"])
def test_legacy_declaration_keeps_independent_name_and_phase(phase: str) -> None:
    """Legacy names retain independent event identity without deriving a phase."""
    point = _point("hook_legacy_before", phase, event_name="event.independent")
    catalog = HookPointCatalog((point,))
    assert catalog.require(point.name).definition.name == "event.independent"
    assert catalog.require(point.name).phase == phase
