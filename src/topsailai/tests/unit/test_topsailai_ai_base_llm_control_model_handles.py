"""Unit tests for provider-neutral LLM model handle ownership."""

from unittest.mock import MagicMock

from topsailai.ai_base.llm_control.model_handles import LLMModelHandleRegistry


def test_register_preserves_order_and_snapshot_uses_handle_identity():
    """Registration keeps acquisition order and snapshots exact handles."""
    registry = LLMModelHandleRegistry()
    first_model = object()
    second_model = object()
    first_handle = MagicMock()
    second_handle = MagicMock()

    registry.register(first_model, first_handle)
    registry.register(second_model, second_handle)

    assert registry.records == [
        (first_model, first_handle),
        (second_model, second_handle),
    ]
    assert registry.snapshot() == (first_handle, second_handle)


def test_release_handles_distinguishes_shared_model_resource():
    """Exact handle release preserves another lease for the same model object."""
    registry = LLMModelHandleRegistry()
    shared_model = object()
    old_handle = MagicMock()
    new_handle = MagicMock()
    registry.register(shared_model, old_handle)
    registry.register(shared_model, new_handle)

    assert registry.release_handles((old_handle,)) == 1

    assert registry.snapshot() == (new_handle,)
    old_handle.release.assert_called_once_with()
    new_handle.release.assert_not_called()


def test_release_after_preserves_snapshot_and_releases_new_handles():
    """Snapshot cleanup releases only handles acquired after the snapshot."""
    registry = LLMModelHandleRegistry()
    retained_handle = MagicMock()
    first_new_handle = MagicMock()
    second_new_handle = MagicMock()
    registry.register(object(), retained_handle)
    snapshot = registry.snapshot()
    registry.register(object(), first_new_handle)
    registry.register(object(), second_new_handle)

    assert registry.release_after(snapshot) == 2

    assert registry.snapshot() == (retained_handle,)
    retained_handle.release.assert_not_called()
    first_new_handle.release.assert_called_once_with()
    second_new_handle.release.assert_called_once_with()


def test_find_and_release_model_use_latest_identity_match():
    """Model lookup and release choose the newest identity-matching record."""
    registry = LLMModelHandleRegistry()
    shared_model = object()
    equal_but_distinct_model = MagicMock()
    equal_but_distinct_model.__eq__.return_value = True
    first_handle = MagicMock()
    second_handle = MagicMock()
    unrelated_handle = MagicMock()
    registry.register(shared_model, first_handle)
    registry.register(equal_but_distinct_model, unrelated_handle)
    registry.register(shared_model, second_handle)

    assert registry.find_handle(shared_model) is second_handle
    assert registry.release_model(shared_model) is True
    assert registry.find_handle(shared_model) is first_handle

    second_handle.release.assert_called_once_with()
    first_handle.release.assert_not_called()
    unrelated_handle.release.assert_not_called()


def test_missing_targets_do_not_mutate_registry():
    """Unknown handles and models leave all ownership records unchanged."""
    handle = MagicMock()
    registry = LLMModelHandleRegistry([(object(), handle)])
    snapshot = list(registry.records)

    assert registry.release_handles((object(),)) == 0
    assert registry.find_handle(object()) is None
    assert registry.release_model(object()) is False

    assert registry.records == snapshot
    handle.release.assert_not_called()


def test_release_all_is_idempotent():
    """All owned handles are released once across repeated cleanup calls."""
    first_handle = MagicMock()
    second_handle = MagicMock()
    registry = LLMModelHandleRegistry([
        (object(), first_handle),
        (object(), second_handle),
    ])

    assert registry.release_all() == 2
    assert registry.release_all() == 0

    assert registry.records == []
    first_handle.release.assert_called_once_with()
    second_handle.release.assert_called_once_with()


class HandleLifecycleModel:
    """Minimal provider model using the optional handle lifecycle mixin."""


class EqualObject:
    """Object that compares equal to every value but remains identity-distinct."""

    def __eq__(self, other):
        """Return true to prove lifecycle matching does not use equality."""
        return True


def test_mixin_is_optional_and_initializes_state_lazily():
    """The mixin creates ownership state only when its lifecycle is used."""
    from topsailai.ai_base.llm_control.model_handles import (
        LLMModelHandleLifecycleMixin,
    )

    model = type(
        "OptionalHandleLifecycleModel",
        (LLMModelHandleLifecycleMixin, HandleLifecycleModel),
        {},
    )()

    assert not hasattr(model, "_llm_model_handles")
    assert model.snapshot_llm_model_leases() == ()
    assert model._llm_model_handles == []


def test_mixin_preserves_identity_order_and_wrapper_composition():
    """Mixin ownership uses identity and release-all honors override seams."""
    from topsailai.ai_base.llm_control.model_handles import (
        LLMModelHandleLifecycleMixin,
    )

    class Model(LLMModelHandleLifecycleMixin):
        """Record lifecycle wrapper calls around the reusable implementation."""

        def __init__(self):
            """Initialize wrapper observations without eager registry state."""
            self.snapshot_calls = 0
            self.release_calls = []

        def snapshot_llm_model_leases(self):
            """Observe snapshot composition before delegating to the mixin."""
            self.snapshot_calls += 1
            return super().snapshot_llm_model_leases()

        def release_llm_model_leases(self, handles):
            """Observe exact release composition before delegating to the mixin."""
            self.release_calls.append(handles)
            return super().release_llm_model_leases(handles)

    model = Model()
    first_model = EqualObject()
    second_model = EqualObject()
    first_handle = MagicMock()
    second_handle = MagicMock()
    model._register_llm_model_handle(first_model, first_handle)
    model._register_llm_model_handle(second_model, second_handle)

    assert model._find_llm_model_handle(first_model) is first_handle
    assert model.release_all_llm_models() == 2
    assert model.snapshot_calls == 1
    assert model.release_calls == [(first_handle, second_handle)]


def test_mixin_honors_overridden_handle_record_list():
    """An overridden record-list seam authoritatively controls all ownership."""
    from topsailai.ai_base.llm_control.model_handles import (
        LLMModelHandleLifecycleMixin,
    )

    records = []

    class Model(LLMModelHandleLifecycleMixin):
        """Expose externally owned compatibility records."""

        def _get_llm_model_handles(self):
            """Return the authoritative externally supplied record list."""
            return records

    model = Model()
    resource = object()
    handle = MagicMock()

    model._register_llm_model_handle(resource, handle)

    assert records == [(resource, handle)]
    assert model.snapshot_llm_model_leases() == (handle,)
    assert model.release_llm_model(resource) is True
    assert records == []


def test_llm_model_base_without_mixin_keeps_noop_lifecycle_semantics():
    """Base-only providers do not inherit optional handle ownership behavior."""
    from topsailai.ai_base.llm_control.base_class import LLMModelBase
    from topsailai.ai_base.llm_control.model_handles import (
        LLMModelHandleLifecycleMixin,
    )

    model = object.__new__(LLMModelBase)

    assert not isinstance(model, LLMModelHandleLifecycleMixin)
    assert model.snapshot_llm_model_leases() is None
    assert model.release_llm_model_leases((object(),)) == 0
    assert model.release_llm_model_leases_after(None) == 0
    assert model.release_all_llm_models() == 0
    assert not hasattr(model, "_llm_model_handles")
