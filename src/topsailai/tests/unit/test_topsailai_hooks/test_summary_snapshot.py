"""Executable SummarySnapshot v1 contract and builder regression tests.

Author: DawsonLin
"""

from dataclasses import FrozenInstanceError, replace
import json
from itertools import product

import pytest

from topsailai.hooks.configured_executor import HookOperation
from topsailai.hooks.contracts import EventDefinition, ValidationError
from topsailai.hooks.points.context import (
    SUMMARY_POINTS, SUMMARY_POINTS_BY_NAME, SummarySnapshot,
    build_summary_payload, validate_summary_payload,
)
from topsailai.hooks.points.context.summary_contracts import SummaryPointContract
from topsailai.hooks.validation import validate_payload


def _classification(point):
    """Supply the smallest safe host classification for each error family."""
    if point.outcome != "error":
        return {}
    result = {
        "error_category": "unknown",
        "failed_stage": "application_unknown" if point.is_apply_error else "generation_unknown",
    }
    if point.is_apply_error:
        result["partial_apply_possible"] = True
    return result


def _payload(point, operation_id="operation-1"):
    """Build a valid detached payload for the selected point."""
    return build_summary_payload(point, operation_id=operation_id, **_classification(point))


@pytest.mark.parametrize("point", SUMMARY_POINTS)
def test_all_ten_contracts_and_minimal_payloads(point):
    """All declarations remain metadata-only, with eight eligible and two inactive."""
    expected_names = {
        f"hook__context__{phase}__summary_{action}_{layer}"
        for phase, action in (("before", "generate"), ("after", "generate"),
                              ("after", "apply"), ("error", "generate"), ("error", "apply"))
        for layer in ("user2agent", "agent2llm")
    }
    assert set(SUMMARY_POINTS_BY_NAME) == expected_names
    assert len(SUMMARY_POINTS) == 10
    assert sum(p.phase_one_eligible for p in SUMMARY_POINTS) == 8
    assert point.definition.name == point.name
    assert point.definition.major_version == 1
    assert point.definition.payload_limit_bytes == 8192
    assert point.layer == point.name.rsplit("_", 1)[1]
    assert point.outcome == {"before": "before", "after": "success", "error": "error"}[point.name.split("__")[2]]
    assert point.phase_one_eligible == ("__after__summary_generate_" not in point.name)
    assert point.error_categories == frozenset() if point.outcome != "error" else bool(point.error_categories)
    import topsailai.hooks.points.context.summary_contracts as contracts
    assert not any(type(value).__name__ in {"HookPointCatalog", "HookRuntime", "ConfiguredHookRegistrar"}
                   for value in vars(contracts).values())
    assert point.declaration.mode == "sync"
    assert point.declaration.failure_policy == "report"
    payload = _payload(point)
    assert set(payload) == point.allowed_fields
    assert "layer" not in payload
    assert json.loads(json.dumps(payload)) == payload
    assert validate_payload(point.definition, payload) == payload
    assert validate_summary_payload(point, payload, operation_id="operation-1").to_payload() == payload


@pytest.mark.parametrize("point", [p for p in SUMMARY_POINTS if p.outcome == "error"])
def test_every_category_stage_and_partial_boolean(point):
    """All bounded classification combinations can be built without inference."""
    for category, stage, partial in product(point.error_categories, point.failed_stages, (False, True)):
        classification = {"error_category": category, "failed_stage": stage}
        if point.is_apply_error:
            classification["partial_apply_possible"] = partial
        payload = build_summary_payload(point, operation_id="_A-9", **classification)
        assert payload["error_category"] == category
        assert payload["failed_stage"] == stage
        if point.is_apply_error:
            assert payload["partial_apply_possible"] is partial


@pytest.mark.parametrize("point", SUMMARY_POINTS)
def test_required_fields_missing_null_and_wrong_types(point):
    """Presence and exact JSON types apply to every stage-specific field."""
    for field in point.allowed_fields:
        payload = _payload(point)
        del payload[field]
        with pytest.raises(ValueError):
            validate_summary_payload(point, payload, operation_id="operation-1")
        for invalid in (None, [], {}, 1.5, object()):
            payload = _payload(point)
            payload[field] = invalid
            with pytest.raises(ValueError):
                validate_summary_payload(point, payload, operation_id="operation-1")


@pytest.mark.parametrize("point", SUMMARY_POINTS)
def test_unknown_and_out_of_stage_fields(point):
    """Forbidden data is rejected even when null or apparently suffix-consistent."""
    forbidden = {"layer", "summary_text", "raw_messages", "error_text", "traceback", "api_key"}
    forbidden |= {"error_category", "failed_stage", "partial_apply_possible"} - point.allowed_fields
    for field in forbidden:
        for value in (None, point.layer):
            payload = _payload(point)
            payload[field] = value
            with pytest.raises(ValueError):
                validate_summary_payload(point, payload, operation_id="operation-1")
            with pytest.raises(ValueError):
                validate_payload(point.definition, payload)
            with pytest.raises(ValueError):
                build_summary_payload(point, operation_id="operation-1", **{field: value})


@pytest.mark.parametrize("point", SUMMARY_POINTS)
@pytest.mark.parametrize("field,invalid", [
    ("schema_version", True), ("schema_version", False), ("schema_version", "1"),
    ("schema_version", 0), ("schema_version", 2),
    ("point_name", ""), ("point_name", "x" * 129), ("point_name", 1),
    ("outcome", ""), ("outcome", "invalid_outcome"), ("outcome", True),
])
def test_invalid_common_values(point, field, invalid):
    """Common identities cannot be coerced, extended, or silently substituted."""
    payload = _payload(point)
    payload[field] = invalid
    with pytest.raises(ValueError):
        validate_summary_payload(point, payload, operation_id="operation-1")


@pytest.mark.parametrize("invalid", [None, True, 1, "", "a" * 129, "é", "a.b", "a:b", "a b", "a\n"])
def test_operation_id_boundary_and_builder(invalid):
    """Summary IDs reject custom generic operations outside the approved grammar."""
    point = SUMMARY_POINTS[0]
    payload = _payload(point)
    payload["operation_id"] = invalid
    with pytest.raises(ValueError):
        validate_summary_payload(point, payload, operation_id="operation-1")
    with pytest.raises(ValueError):
        build_summary_payload(point, operation_id=invalid)


def test_operation_id_generator_and_exact_expected_identity():
    """Default IDs pass while matching-but-invalid custom IDs cannot bypass validation."""
    point = SUMMARY_POINTS[0]
    generated = HookOperation().operation_id
    assert len(generated) == 32
    assert _payload(point, generated)["operation_id"] == generated
    assert _payload(point, "A" * 128)["operation_id"] == "A" * 128
    assert HookOperation("a.b").operation_id == "a.b"
    with pytest.raises(ValueError):
        _payload(point, HookOperation("a.b").operation_id)
    with pytest.raises(ValueError):
        validate_summary_payload(point, _payload(point), operation_id="other-valid-id")


@pytest.mark.parametrize("point", SUMMARY_POINTS)
def test_point_and_outcome_mismatch(point):
    """Other valid centralized identities and outcomes remain invalid at this point."""
    for other in SUMMARY_POINTS:
        if other.name != point.name:
            payload = _payload(point)
            payload["point_name"] = other.name
            with pytest.raises(ValueError):
                validate_summary_payload(point, payload, operation_id="operation-1")
    for outcome in {"before", "success", "error"} - {point.outcome}:
        payload = _payload(point)
        payload["outcome"] = outcome
        with pytest.raises(ValueError):
            validate_summary_payload(point, payload, operation_id="operation-1")


@pytest.mark.parametrize("point", [p for p in SUMMARY_POINTS if p.outcome == "error"])
def test_invalid_and_cross_family_classifications(point):
    """No generation/application or cross-layer stage can leak through."""
    categories = {"timeout", "transport", "provider", "invalid_response", "persistence", "state_update", "unknown"}
    stages = set().union(*(p.failed_stages for p in SUMMARY_POINTS))
    for field, invalids in (
        ("error_category", (categories - point.error_categories) | {"", "x" * 17, "other", True, 1}),
        ("failed_stage", (stages - point.failed_stages) | {"", "x" * 20, "other", True, 1}),
    ):
        for invalid in invalids:
            payload = _payload(point)
            payload[field] = invalid
            with pytest.raises(ValueError):
                validate_summary_payload(point, payload, operation_id="operation-1")
    if point.is_apply_error:
        for invalid in (0, 1, "true", "false", "", None):
            payload = _payload(point)
            payload["partial_apply_possible"] = invalid
            with pytest.raises(ValueError):
                validate_summary_payload(point, payload, operation_id="operation-1")


def test_modified_event_contracts_rejected():
    """Centralized identity, version, schema and byte budget cannot be replaced."""
    point = SUMMARY_POINTS[0]
    definitions = (
        EventDefinition("other.event", 1, point.definition.payload_schema, 8192),
        replace(point.definition, major_version=2),
        replace(point.definition, payload_limit_bytes=8193),
        EventDefinition(point.name, 1, {}, 8192),
    )
    for definition in definitions:
        if definition.name != point.name:
            with pytest.raises(ValueError):
                replace(point.declaration, definition=definition)
            continue
        modified = SummaryPointContract(replace(point.declaration, definition=definition), True)
        with pytest.raises(ValueError):
            validate_summary_payload(modified, _payload(point), operation_id="operation-1")
    with pytest.raises(ValueError):
        build_summary_payload(object(), operation_id="operation-1")
    with pytest.raises(ValueError):
        validate_summary_payload(object(), {}, operation_id="operation-1")


def test_immutable_detached_public_snapshot():
    """Source mutations and returned JSON mutations cannot modify a snapshot."""
    point = SUMMARY_POINTS[-1]
    payload = _payload(point)
    snapshot = validate_summary_payload(point, payload, operation_id="operation-1")
    payload["operation_id"] = "changed"
    returned = snapshot.to_payload()
    returned["failed_stage"] = "changed"
    assert snapshot.operation_id == "operation-1"
    assert snapshot.failed_stage == "application_unknown"
    with pytest.raises(FrozenInstanceError):
        snapshot.operation_id = "changed"
    with pytest.raises(FrozenInstanceError):
        point.phase_one_eligible = False
    with pytest.raises(TypeError):
        SUMMARY_POINTS_BY_NAME[point.name] = point
    with pytest.raises(ValueError):
        SummarySnapshot(True, "operation-1", point.name, point.outcome, **_classification(point))
    with pytest.raises(ValueError):
        SummarySnapshot(1, "operation-1", "unknown.point", "before")
    with pytest.raises(ValueError):
        SummarySnapshot(1, "operation-1", [], "before")


def test_matching_event_schema_utf8_budget_without_truncation():
    """The generic matching schema enforces 8192 bytes; strict IDs reject padding."""
    point = SUMMARY_POINTS[0]
    payload = _payload(point)
    payload["operation_id"] = ""
    base = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    remaining = 8192 - base
    payload["operation_id"] = "é" * (remaining // 2) + "a" * (remaining % 2)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) == 8192
    assert validate_payload(point.definition, payload) == payload
    with pytest.raises(ValueError):
        validate_summary_payload(point, payload, operation_id=payload["operation_id"])
    payload["operation_id"] += "a"
    with pytest.raises(ValidationError, match="maximum encoded size"):
        validate_payload(point.definition, payload)
    with pytest.raises(ValueError):
        build_summary_payload(point, operation_id=payload["operation_id"])
    payload = _payload(point)
    payload["summary_text"] = "x" * 8193
    with pytest.raises(ValueError):
        validate_summary_payload(point, payload, operation_id="operation-1")
