"""RED contracts for the framework-owned terminal hook_script binding."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from topsailai.tests.unit.test_topsailai_hooks.hook_script_terminal_helpers import (
    build_plan,
    module_binding,
    plan_bindings,
    require_terminal_contract,
)


def test_each_hook_point_has_exactly_one_framework_owned_terminal_binding() -> None:
    """Every independent hook point reserves exactly one terminal script binding."""
    first = build_plan((), hook_point="conversation.started")
    second = build_plan((), hook_point="agent2llm.finished")

    for result, hook_point in (
        (first, "conversation.started"),
        (second, "agent2llm.finished"),
    ):
        bindings = plan_bindings(result)
        assert result.accepted
        assert [item.binding_id for item in bindings].count("hook_script") == 1
        reserved = bindings[-1]
        assert reserved.binding_id == "hook_script"
        assert reserved.hook_point == hook_point
        assert reserved.framework_owned is True
        assert reserved.terminal is True


def test_reserved_binding_cannot_be_deleted_renamed_reprioritized_or_reordered() -> None:
    """The immutable framework plan exposes no mutation or removal authority."""
    result = build_plan((module_binding("alpha"),))
    bindings = plan_bindings(result)
    original_plan = result.bindings
    reserved = bindings[-1]

    for name, value in (
        ("binding_id", "renamed"),
        ("priority", -1),
        ("after", ()),
        ("terminal", False),
        ("framework_owned", False),
    ):
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            setattr(reserved, name, value)
        assert result.bindings is original_plan
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        result.bindings = tuple(reversed(bindings))
    assert result.bindings is original_plan
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        del result.bindings
    assert result.bindings is original_plan
    with pytest.raises(TypeError):
        bindings[-1] = bindings[0]
    with pytest.raises(TypeError):
        del bindings[-1]
    assert result.bindings is original_plan
    assert [item.binding_id for item in result.bindings] == ["module:alpha", "hook_script"]
    assert not hasattr(result, "move")


def test_user_cannot_duplicate_reserved_identity_or_append_dependency_after_it() -> None:
    """Reserved identity claims and dependencies on the terminal node reject atomically."""
    duplicate = module_binding("user", binding_id="hook_script")
    dependent = module_binding("later", after=("hook_script",))

    duplicate_result = build_plan((duplicate,))
    dependent_result = build_plan((dependent,))

    assert not duplicate_result.accepted
    assert plan_bindings(duplicate_result) == ()
    assert duplicate_result.errors == ("hook_script binding is framework-owned",)
    assert not dependent_result.accepted
    assert plan_bindings(dependent_result) == ()
    assert dependent_result.errors == ("no binding may depend on terminal hook_script",)


def test_reserved_binding_counts_toward_capacity() -> None:
    """Capacity includes the reserved terminal slot at exact and overflow boundaries."""
    exact = build_plan((module_binding("alpha"),), capacity=2)
    overflow = build_plan((module_binding("alpha"), module_binding("beta")), capacity=2)

    assert exact.accepted
    assert [item.binding_id for item in plan_bindings(exact)] == [
        "module:alpha",
        "hook_script",
    ]
    assert not overflow.accepted
    assert plan_bindings(overflow) == ()
    assert overflow.errors == ("bindings_per_event limit exceeded",)


def test_unconfigured_hook_script_is_successful_zero_entry_noop() -> None:
    """An unconfigured reserved terminal binding settles successfully without entries."""
    result = build_plan((), configured=False)
    _, _, settle = require_terminal_contract()

    outcome = settle(plan_bindings(result)[0])

    assert outcome.status == "success"
    assert outcome.entry_results == ()
    assert outcome.started is False


def test_module_order_is_deterministic_and_hook_script_is_last() -> None:
    """Module names form a deterministic completion-before-start dependency chain."""
    modules = tuple(module_binding(name) for name in ("zeta", "Alpha", "beta"))

    first = build_plan(modules)
    second = build_plan(tuple(reversed(modules)))

    expected = ["module:Alpha", "module:beta", "module:zeta", "hook_script"]
    first_bindings = plan_bindings(first)
    second_bindings = plan_bindings(second)
    assert [item.binding_id for item in first_bindings] == expected
    assert [item.binding_id for item in second_bindings] == expected
    for bindings in (first_bindings, second_bindings):
        modules_in_order = bindings[:-1]
        assert modules_in_order[0].after == ()
        for previous, current in zip(modules_in_order, modules_in_order[1:]):
            assert current.after == (previous.binding_id,)
        assert bindings[-1].after == tuple(expected[:-1])


def test_forward_requires_success_cycle_is_rejected_atomically() -> None:
    """A forward success dependency cannot conflict with the compiled module chain."""
    result = build_plan(
        (
            module_binding("Alpha", requires_success=("module:beta",)),
            module_binding("beta"),
        )
    )

    assert not result.accepted
    assert plan_bindings(result) == ()
    assert result.errors == (
        "discovered module requires_success dependencies are not supported",
    )


def test_backward_requires_success_cannot_suppress_failure_continuation() -> None:
    """A backward success dependency cannot suppress continuation after module error."""
    result = build_plan(
        (
            module_binding("Alpha"),
            module_binding("beta", requires_success=("module:Alpha",)),
        )
    )

    assert not result.accepted
    assert plan_bindings(result) == ()
    assert result.errors == (
        "discovered module requires_success dependencies are not supported",
    )


def test_terminal_binding_waits_for_every_cleanup_safe_terminal_predecessor() -> None:
    """Last means readiness after settlement, never bypassing unfinished module work."""
    result = build_plan((module_binding("alpha"), module_binding("beta")))
    _, ready, _ = require_terminal_contract()
    terminal = plan_bindings(result)[-1]

    assert not ready(terminal, {"module:alpha": "success"})
    assert not ready(
        terminal,
        {"module:alpha": "error", "module:beta": "cleanup_pending"},
    )
    assert ready(
        terminal,
        {"module:alpha": "error", "module:beta": "success"},
    )


@pytest.mark.parametrize("handler_ref", ("plugin:main", "package.plugin:main", "missing_plugin:main"))
def test_main_reference_accepts_registered_alias_without_host_import(handler_ref: str) -> None:
    """Validate reference metadata without importing a plugin or coupling its name."""
    binding = module_binding("display_alias", handler_ref=handler_ref)

    result = build_plan((binding,))

    assert result.accepted
    assert result.errors == ()
    assert [item.binding_id for item in result.bindings] == ["module:display_alias", "hook_script"]
    assert result.bindings[0].handler_ref == handler_ref
    assert result.bindings[0] is not binding
    assert binding.handler_ref == handler_ref
    assert binding.after == ()


@pytest.mark.parametrize(
    "handler_ref",
    (None, False, 1, [], {}, "", "main", ":main", "plugin", "plugin:",
     "plugin:run", "plugin:Main", "plugin:main:extra", "plugin::main",
     "plugin.main", " :main", "plugin..child:main", ".plugin:main", "plugin.:main",
     "plugin name:main", "plugin:main\n"),
)
def test_invalid_main_reference_rejects_whole_candidate(handler_ref: object) -> None:
    """Reject malformed or non-main entries without exposing a partial terminal plan."""
    valid = module_binding("alpha")
    invalid = module_binding("beta", handler_ref=handler_ref)
    candidate = (valid, invalid)

    result = build_plan(candidate)

    assert not result.accepted
    assert result.bindings == ()
    assert result.errors == ("module handler_ref must use non-empty module:main format",)
    assert candidate == (valid, invalid)
    assert invalid.handler_ref is handler_ref
    assert valid.after == invalid.after == ()
