"""Tests for atomic hook registration and deterministic dependency plans."""

from __future__ import annotations

from dataclasses import replace

from topsailai.hooks import Binding, EventDefinition, HookRegistry


def _definition() -> EventDefinition:
    """Return a reusable valid event definition."""
    return EventDefinition("conversation.started", 1, {"type": "object", "properties": {}})


def _binding(binding_id: str, **changes: object) -> Binding:
    """Return a valid binding with optional field replacements."""
    return replace(
        Binding(binding_id, "conversation.started", 1, "example.handlers:handle"),
        **changes,
    )


def test_register_snapshot_and_unregister_advance_generations() -> None:
    """Successful mutations publish generations while snapshots remain stable."""
    registry = HookRegistry()
    first = registry.register(_definition(), _binding("alpha"), "scope-a")
    old_snapshot = registry.snapshot("scope-a", "conversation.started", 1)
    removed = registry.unregister(first.handle)
    assert first.accepted and removed.accepted
    assert removed.generation == 2
    assert [item.binding_id for item in old_snapshot.bindings] == ["alpha"]
    assert registry.snapshot("scope-a", "conversation.started", 1).bindings == ()
    duplicate = registry.unregister(first.handle)
    assert not duplicate.accepted
    assert duplicate.generation == 2


def test_duplicate_binding_is_scope_local_and_rejected_atomically() -> None:
    """Duplicate IDs in one scope must not partially replace active state."""
    registry = HookRegistry()
    assert registry.register(_definition(), _binding("same"), "scope-a").accepted
    duplicate = registry.register(_definition(), _binding("same", priority=1), "scope-a")
    other_scope = registry.register(_definition(), _binding("same", priority=1), "scope-b")
    assert not duplicate.accepted and other_scope.accepted
    assert registry.snapshot("scope-a", "conversation.started", 1).bindings[0].priority == 100


def test_unknown_dependency_rejection_does_not_activate_candidate() -> None:
    """Unknown dependency updates must leave the previous generation untouched."""
    registry = HookRegistry()
    result = registry.register(_definition(), _binding("dependent", after=("missing",)), "scope-a")
    assert not result.accepted
    assert result.generation == 0
    assert registry.snapshot("scope-a", "conversation.started", 1).bindings == ()


def test_unregister_rejects_dependent_graph_atomically() -> None:
    """Removing a required predecessor must preserve active state and generation."""
    registry = HookRegistry()
    first = registry.register(_definition(), _binding("alpha"), "scope-a")
    assert registry.register(
        _definition(), _binding("beta", after=("alpha",)), "scope-a"
    ).accepted
    rejected = registry.unregister(first.handle)
    assert not rejected.accepted
    assert rejected.generation == 2
    assert "unknown dependencies" in rejected.errors[0]
    assert [item.binding_id for item in registry.snapshot("scope-a", "conversation.started", 1).bindings] == [
        "alpha",
        "beta",
    ]


def test_stale_handle_cannot_remove_replacement_but_handles_survive_unrelated_changes() -> None:
    """Registration identity is stable and independent of global generation changes."""
    registry = HookRegistry()
    first = registry.register(_definition(), _binding("alpha"), "scope-a")
    unrelated = registry.register(_definition(), _binding("other"), "scope-b")
    assert registry.unregister(first.handle).accepted
    replacement = registry.register(_definition(), _binding("alpha"), "scope-a")
    stale = registry.unregister(first.handle)
    assert not stale.accepted
    assert "stale" in stale.errors[0]
    assert registry.unregister(unrelated.handle).accepted
    assert registry.unregister(replacement.handle).accepted


def test_registration_rejects_bad_types_without_mutation_or_raw_exceptions() -> None:
    """Malformed fields must return structured failures before unsafe operations."""
    registry = HookRegistry()
    cases = [
        (_binding(None), "scope-a"),
        (_binding("a", after=None), "scope-a"),
        (_binding("a", after=([],)), "scope-a"),
        (_binding("a"), []),
    ]
    for binding, scope in cases:
        result = registry.register(_definition(), binding, scope)
        assert not result.accepted
        assert result.generation == 0


def test_invalid_object_schema_fields_preserve_registry_state() -> None:
    """Invalid object fields must fail structurally without publishing candidate state."""
    import pytest

    from topsailai.hooks import ValidationError, validate_payload

    registry = HookRegistry()
    accepted = registry.register(_definition(), _binding("alpha"), "scope-a")
    before = registry.snapshot("scope-a", "conversation.started", 1)

    invalid_schemas = (
        {"type": "object", "properties": None},
        {"type": "object", "properties": 1},
        {"type": "object", "properties": False},
        {"type": "object", "properties": {}, "required": None},
        {"type": "object", "properties": {}, "required": 1},
        {"type": "object", "properties": {}, "required": False},
    )
    for index, schema in enumerate(invalid_schemas):
        definition = EventDefinition("conversation.started", 1, schema)
        result = registry.register(definition, _binding(f"invalid-{index}"), "scope-a")
        assert not result.accepted
        assert result.generation == accepted.generation == 1
        assert result.errors
        with pytest.raises(ValidationError):
            validate_payload(definition, {})
        after = registry.snapshot("scope-a", "conversation.started", 1)
        assert after.generation == before.generation
        assert after.bindings == before.bindings


def test_object_schema_allows_missing_required_and_valid_required_array() -> None:
    """Required may be omitted or provided as a valid array of known properties."""
    from topsailai.hooks import validate_payload

    without_required = EventDefinition(
        "conversation.started",
        1,
        {"type": "object", "properties": {"owner": {"type": "string"}}},
    )
    with_required = EventDefinition(
        "conversation.started",
        1,
        {
            "type": "object",
            "properties": {"owner": {"type": "string"}},
            "required": ["owner"],
        },
    )
    assert validate_payload(without_required, {}) == {}
    assert validate_payload(with_required, {"owner": "a"}) == {"owner": "a"}


def test_dependency_plan_reselects_best_ready_node_after_each_completion() -> None:
    """A newly ready high-priority node must precede an older low-priority peer."""
    registry = HookRegistry()
    definition = _definition()
    assert registry.register(definition, _binding("A", priority=10), "scope-a").accepted
    assert registry.register(definition, _binding("B", priority=1, after=("A",)), "scope-a").accepted
    assert registry.register(definition, _binding("Z", priority=100), "scope-a").accepted
    plan = registry.snapshot("scope-a", "conversation.started", 1)
    assert [item.binding_id for item in plan.bindings] == ["A", "B", "Z"]


def test_requires_success_is_an_ordering_dependency() -> None:
    """Success requirements must contribute the same ordering edge to the plan."""
    registry = HookRegistry()
    assert registry.register(_definition(), _binding("first", priority=100), "scope-a").accepted
    assert registry.register(
        _definition(), _binding("second", priority=1, requires_success=("first",)), "scope-a"
    ).accepted
    assert [
        item.binding_id
        for item in registry.snapshot("scope-a", "conversation.started", 1).bindings
    ] == ["first", "second"]


def test_cycle_planner_rejects_a_real_cycle() -> None:
    """The graph planner must reject a cycle even though incremental registration cannot create it."""
    from topsailai.hooks.registry import _validate_and_plan

    ordered, errors = _validate_and_plan(
        (_binding("alpha", after=("beta",)), _binding("beta", after=("alpha",)))
    )
    assert ordered == ()
    assert errors == ("binding dependency graph contains a cycle",)


def test_registration_rejects_mismatch_and_binding_limit() -> None:
    """Contract mismatches and caps must not alter active registry state."""
    registry = HookRegistry(bindings_per_event=1)
    mismatch = registry.register(_definition(), replace(_binding("wrong"), event_version=2), "scope-a")
    assert not mismatch.accepted
    assert registry.register(_definition(), _binding("first"), "scope-a").accepted
    overflow = registry.register(_definition(), _binding("second"), "scope-a")
    assert not overflow.accepted and overflow.generation == 1


def test_invalid_max_items_and_foreign_handles_preserve_registry_state() -> None:
    """Rejected schemas and handles from another registry must not mutate ownership state."""
    first = HookRegistry()
    second = HookRegistry()
    first_result = first.register(_definition(), _binding("alpha"), "scope-a")
    second_result = second.register(_definition(), _binding("alpha"), "scope-a")

    rejected = second.unregister(first_result.handle)
    assert not rejected.accepted
    assert "another registry" in rejected.errors[0]
    assert rejected.generation == second_result.generation == 1
    assert second.snapshot("scope-a", "conversation.started", 1).bindings[0].binding_id == "alpha"

    invalid_definition = EventDefinition(
        "conversation.started",
        1,
        {"type": "array", "items": {"type": "integer"}, "max_items": None},
    )
    invalid = second.register(
        invalid_definition,
        replace(_binding("bad"), event_name="conversation.started"),
        "scope-b",
    )
    assert not invalid.accepted
    assert invalid.generation == 1
