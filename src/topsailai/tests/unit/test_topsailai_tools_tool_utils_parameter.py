"""Direct unit tests for registered-tool parameter coercion helpers."""

import math

import pytest

from topsailai.tools.tool_utils.parameter import (
    invalid_request,
    resolve_finite_int,
    resolve_int_flag,
    resolve_json_container,
    resolve_str_list,
    resolve_str_param,
)


def test_invalid_request_builds_machine_readable_error():
    """The shared error builder identifies the parameter and supplied value."""
    result = invalid_request("timeout", "bad", "must be finite")
    assert result == {"status": "invalid_request", "reason": "invalid timeout='bad': must be finite"}


@pytest.mark.parametrize(("value", "expected"), [(" 30 ", 30), ("1e2", 100), ("1.9", 1), (3, 3), (3.9, 3)])
def test_resolve_finite_int_accepts_finite_numeric_values(value, expected):
    """Finite native and string numerics retain integer truncation semantics."""
    assert resolve_finite_int(value, "timeout") == (expected, None)


@pytest.mark.parametrize("value", [None, True, False, "", "   ", "abc", "NaN", "inf", "-inf", math.nan, math.inf, -math.inf])
def test_resolve_finite_int_rejects_invalid_or_nonfinite_values(value):
    """Missing, boolean, malformed, and non-finite values are parameter errors."""
    resolved, error = resolve_finite_int(value, "timeout")
    assert resolved is None
    assert error["status"] == "invalid_request"
    assert "timeout" in error["reason"]


@pytest.mark.parametrize(("value", "expected"), [(1, True), (0, False), ("1", True), ("0", False), (" 1 ", True), (" 0 ", False)])
def test_resolve_int_flag_accepts_only_integer_flag_forms(value, expected):
    """Integer flags accept native and whitespace-padded 1/0 forms."""
    assert resolve_int_flag(value, "delete") == (expected, None)


@pytest.mark.parametrize("value", [True, False, 2, -1, "2", "-1", "yes", "", None, 1.0, []])
def test_resolve_int_flag_rejects_bool_and_non_flag_values(value):
    """Booleans and all values outside the strict integer 1/0 contract fail."""
    resolved, error = resolve_int_flag(value, "delete")
    assert resolved is None
    assert error["status"] == "invalid_request"
    assert "delete" in error["reason"]


@pytest.mark.parametrize(("value", "expected_type", "expected"), [(["a"], list, ["a"]), ({"a": 1}, dict, {"a": 1}), ('["a"]', list, ["a"]), ('{"a": 1}', dict, {"a": 1})])
def test_resolve_json_container_accepts_native_and_json_containers(value, expected_type, expected):
    """Native containers and JSON strings decode to the requested shape."""
    assert resolve_json_container(value, "items", expected_type) == (expected, None)


@pytest.mark.parametrize("value", ["[bad", '{"a": 1}', "1", 1, None])
def test_resolve_json_container_rejects_invalid_or_wrong_list_values(value):
    """Malformed JSON and values with the wrong shape fail without fallback."""
    resolved, error = resolve_json_container(value, "items", list)
    assert resolved is None
    assert error["status"] == "invalid_request"
    assert "items" in error["reason"]


def test_resolve_json_container_allows_none_when_requested():
    """Optional JSON containers preserve an explicitly allowed None value."""
    assert resolve_json_container(None, "environ", dict, allow_none=True) == (None, None)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(["a", "b"], ["a", "b"]), ('["a", "b"]', ["a", "b"]), (" path/a ", [" path/a "])],
)
def test_resolve_str_list_accepts_native_json_and_bare_values(value, expected):
    """String-list parameters accept lists, JSON lists, and one bare string unchanged."""
    assert resolve_str_list(value, "items") == (expected, None)


@pytest.mark.parametrize("value", ["[bad", '{"a": 1}', "", "   ", None, 1, 1.5, True, {}])
def test_resolve_str_list_rejects_json_shaped_invalid_and_non_string_values(value):
    """Malformed JSON-shaped, empty, and unsupported values are parameter errors."""
    resolved, error = resolve_str_list(value, "items")
    assert resolved is None
    assert error["status"] == "invalid_request"
    assert "items" in error["reason"]


@pytest.mark.parametrize("value", ["", " text ", '{"a": 1}', "[1]"])
def test_resolve_str_param_preserves_all_string_content(value):
    """String parameters are returned unchanged without JSON interpretation."""
    assert resolve_str_param(value, "title") == (value, None)


@pytest.mark.parametrize("value", [None, True, 1, 1.5, [], {}])
def test_resolve_str_param_rejects_non_string_scalars_and_containers(value):
    """Every non-string value returns a machine-readable parameter error."""
    resolved, error = resolve_str_param(value, "title")
    assert resolved is None
    assert error["status"] == "invalid_request"
    assert "title" in error["reason"]
