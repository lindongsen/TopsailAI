"""Freeze the approved arbitration budgets without executing the process fixture."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

_TARGET = Path(__file__).with_name("test_script_runner_process.py")
_FUNCTION = "test_real_transport_arbitrates_exit_timeout_and_enforcement"
_POLICY = {
    "nonzero": (2.25, "ERROR", "hook_script_nonzero_exit"),
    "signal": (2.25, "WORKER_LOST", "hook_script_signal_exit"),
    "missing": (2.25, "INVALID_OUTPUT", "hook_script_missing_result"),
    "hang": (0.15, "TIMEOUT", "hook_script_timeout"),
    "overflow": (2.25, "INVALID_OUTPUT", "hook_script_output_limit"),
    "malformed": (2.25, "INVALID_OUTPUT", "hook_script_invalid_result"),
}


def _only(nodes, description):
    """Reject missing or ambiguous source constructs rather than guessing."""
    assert len(nodes) == 1, f"Expected exactly one {description}, found {len(nodes)}"
    return nodes[0]


def _literal(node):
    """Decode only scalar constants; never execute target expressions."""
    assert isinstance(node, ast.Constant), "Unsupported nonliteral parameter"
    assert type(node.value) in (str, int, float), "Unsupported parameter type"
    return node.value


def _seconds(node, bindings):
    """Resolve a literal numeric timeout or a row-bound parameter name."""
    if isinstance(node, ast.Name):
        assert node.id in bindings, f"Unbound timeout parameter: {node.id}"
        node = bindings[node.id]
    value = _literal(node)
    assert type(value) in (int, float) and math.isfinite(value), "Invalid timeout"
    return value


def _effective_timeouts():
    """Resolve the six rows through a bounded, explicitly supported AST subset."""
    source = _TARGET.read_text(encoding="utf-8")
    assert len(source.encode("utf-8")) <= 131072, "Target source exceeds AST budget"
    tree = ast.parse(source, filename=str(_TARGET))
    assert sum(1 for _ in ast.walk(tree)) <= 20000, "Target AST exceeds node budget"
    function = _only([n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == _FUNCTION], _FUNCTION)
    decorators = [d for d in function.decorator_list if isinstance(d, ast.Call)
                  and isinstance(d.func, ast.Attribute) and d.func.attr == "parametrize"
                  and isinstance(d.func.value, ast.Attribute)
                  and d.func.value.attr == "mark"
                  and isinstance(d.func.value.value, ast.Name)
                  and d.func.value.value.id == "pytest"]
    decorator = _only(decorators, "pytest.mark.parametrize")
    assert len(decorator.args) == 2 and not decorator.keywords, "Unsupported parametrization"
    names_node, rows_node = decorator.args
    if isinstance(names_node, ast.Constant):
        names = [n.strip() for n in _literal(names_node).split(",")]
    else:
        assert isinstance(names_node, (ast.Tuple, ast.List)), "Unsupported parameter names"
        names = [_literal(n) for n in names_node.elts]
    assert all(type(n) is str for n in names), "Parameter names must be strings"
    assert len(set(names)) == len(names), "Duplicate parameter names"
    assert set(names) in ({"mode", "expected_status", "expected_category"},
                          {"mode", "expected_status", "expected_category", "timeout"}), "Unexpected parameters"
    assert isinstance(rows_node, (ast.List, ast.Tuple)) and len(rows_node.elts) == 6, "Expected six rows"
    call = _only([n for n in ast.walk(function) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id == "_execute"], "_execute call")
    assert not any(k.arg is None for k in call.keywords), "Unsupported expanded keywords"
    timeouts = [k.value for k in call.keywords if k.arg == "timeout"]
    assert len(timeouts) <= 1, "Ambiguous timeout"
    if timeouts:
        timeout_node = timeouts[0]
    else:
        helper = _only([n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "_execute"], "_execute helper")
        defaults = dict(zip((n.arg for n in helper.args.kwonlyargs), helper.args.kw_defaults))
        assert defaults.get("timeout") is not None, "Missing timeout default"
        timeout_node = defaults["timeout"]
    resolved = {}
    for row in rows_node.elts:
        assert isinstance(row, (ast.Tuple, ast.List)) and len(row.elts) == len(names), "Unsupported row"
        bindings = dict(zip(names, row.elts))
        mode = _literal(bindings["mode"])
        assert mode in _POLICY and mode not in resolved, "Unknown or duplicate mode"
        status = bindings["expected_status"]
        assert isinstance(status, ast.Attribute) and isinstance(status.value, ast.Name), "Unsupported status"
        assert status.value.id == "HookStatus" and status.attr == _POLICY[mode][1], "Classification changed"
        assert _literal(bindings["expected_category"]) == _POLICY[mode][2], "Category changed"
        resolved[mode] = _seconds(timeout_node, bindings)
    assert set(resolved) == set(_POLICY), "Mode inventory changed"
    return resolved


@pytest.mark.parametrize("mode", tuple(_POLICY))
def test_arbitration_mode_has_approved_effective_timeout(mode):
    """Functional arbitration must not borrow the intentional-expiry budget."""
    actual = _effective_timeouts()[mode]
    expected = _POLICY[mode][0]
    assert actual == expected, f"{mode}: expected timeout={expected}, actual timeout={actual}"
