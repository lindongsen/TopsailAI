import pytest
from unittest import mock

from topsailai.utils.input_tool import input_yes_or_no


def test_input_yes_or_no_returns_true_for_yes():
    input_func = mock.Mock(side_effect=["yes"])
    assert input_yes_or_no("prompt? ", input_func) is True
    input_func.assert_called_once_with("prompt? ")


def test_input_yes_or_no_returns_false_for_no():
    input_func = mock.Mock(side_effect=["no"])
    assert input_yes_or_no("prompt? ", input_func) is False


def test_input_yes_or_no_case_insensitive():
    input_func = mock.Mock(side_effect=["YES"])
    assert input_yes_or_no("prompt? ", input_func) is True


def test_input_yes_or_no_strips_whitespace():
    input_func = mock.Mock(side_effect=["  yes  "])
    assert input_yes_or_no("prompt? ", input_func) is True


def test_input_yes_or_no_loops_until_valid():
    input_func = mock.Mock(side_effect=["maybe", "YES"])
    with mock.patch("builtins.print") as mock_print:
        assert input_yes_or_no("prompt? ", input_func) is True
    assert input_func.call_count == 2
    mock_print.assert_called_once_with("Please enter 'yes' or 'no'.")


def test_input_yes_or_no_none_input_func_uses_builtin():
    with mock.patch("builtins.input", return_value="no") as mock_input:
        assert input_yes_or_no("prompt? ", None) is False
    mock_input.assert_called_once_with("prompt? ")


def test_input_yes_or_no_eof_treated_as_no():
    input_func = mock.Mock(return_value=None)
    assert input_yes_or_no("prompt? ", input_func) is False
