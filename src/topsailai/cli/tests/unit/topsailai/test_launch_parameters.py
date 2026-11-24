"""Tests for caller-supplied launch parameter validation.

Author: DawsonLin
"""

import pytest

from cli_topsailai.launch_parameters import (
    IDENTITY_ENV_KEYS,
    LaunchParameterError,
    describe_overrides,
    parse_env_overrides,
    validate_session_id,
)


@pytest.mark.parametrize("value", ["bot-weixin", "a", "A_b-9", "x" * 128])
def test_valid_identity_is_returned_unchanged(value):
    """A well-formed identity is accepted verbatim."""
    assert validate_session_id(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "bad/id",
        "bad id",
        "bad.id",
        "x" * 129,
        "bad:name",
        "bad\nname",
    ],
)
def test_invalid_identity_is_rejected(value):
    """An unusable identity is refused instead of reaching a filename."""
    with pytest.raises(LaunchParameterError):
        validate_session_id(value)


def test_dot_identity_names_the_filename_reason():
    """The dot rejection explains why, because the rule is not obvious."""
    with pytest.raises(LaunchParameterError) as error:
        validate_session_id("bot.weixin")
    assert "dot" in str(error.value)


@pytest.mark.parametrize("value", [None, 7, ["bot"]])
def test_non_string_identity_is_rejected(value):
    """A non-string identity cannot be a filename component."""
    with pytest.raises(LaunchParameterError):
        validate_session_id(value)


def test_env_overrides_are_parsed_in_order():
    """Every KEY=VALUE entry becomes one mapping entry."""
    assert parse_env_overrides(["A=1", "B=two"]) == {"A": "1", "B": "two"}


def test_env_override_value_may_contain_equals_signs():
    """Only the first separator splits the name from the value."""
    assert parse_env_overrides(["TOKEN=a=b=c"]) == {"TOKEN": "a=b=c"}


def test_empty_env_value_is_preserved():
    """An explicitly empty value stays configured instead of becoming unset."""
    assert parse_env_overrides(["EMPTY="]) == {"EMPTY": ""}


def test_absent_env_entries_yield_an_empty_mapping():
    """No --env option means no overrides, not an error."""
    assert parse_env_overrides(None) == {}
    assert parse_env_overrides([]) == {}


def test_identical_repeat_is_accepted():
    """Repeating the same pair is harmless and keeps one entry."""
    assert parse_env_overrides(["A=1", "A=1"]) == {"A": "1"}


def test_conflicting_repeat_is_rejected():
    """Two different values for one name cannot both be honored."""
    with pytest.raises(LaunchParameterError) as error:
        parse_env_overrides(["A=1", "A=2"])
    assert "conflicting" in str(error.value)


@pytest.mark.parametrize("entry", ["NOEQUALS", "=value", "1BAD=x", "BAD NAME=x"])
def test_malformed_env_entry_is_rejected(entry):
    """A malformed entry is a usage error rather than a silent no-op."""
    with pytest.raises(LaunchParameterError):
        parse_env_overrides([entry])


@pytest.mark.parametrize("name", IDENTITY_ENV_KEYS)
def test_identity_alias_is_rejected(name):
    """The identity has one channel, so --env must not set it."""
    with pytest.raises(LaunchParameterError) as error:
        parse_env_overrides([f"{name}=other"])
    assert "--session-id" in str(error.value)


def test_non_string_env_entry_is_rejected():
    """A non-string entry cannot be parsed as KEY=VALUE."""
    with pytest.raises(LaunchParameterError):
        parse_env_overrides([7])


def test_describe_overrides_is_sorted_and_value_free():
    """The description names variables only, in a stable order."""
    described = describe_overrides({"B": "secret-b", "A": "secret-a"})
    assert described == "A, B"
    assert "secret" not in described


def test_describe_overrides_of_empty_mapping_is_empty():
    """No overrides produce no description."""
    assert describe_overrides({}) == ""
