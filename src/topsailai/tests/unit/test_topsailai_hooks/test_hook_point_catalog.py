"""Tests for the public Hook-point declaration catalog."""

from __future__ import annotations

import pytest

from topsailai.hooks import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration


def _point(name: str, phase: str = "before", **kwargs: object) -> HookPointDeclaration:
    """Build one ordinary test declaration."""
    values = {
        "name": name,
        "definition": EventDefinition(f"test.{name}", 1),
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
