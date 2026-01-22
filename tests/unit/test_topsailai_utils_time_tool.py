import pytest
from datetime import datetime
from src.topsailai.utils.time_tool import get_current_date, get_current_day


def test_get_current_date_basic():
    """Test get_current_date with default parameters."""
    result = get_current_date()
    assert isinstance(result, str)
    assert len(result) == 19  # YYYY-MM-DD HH:MM:SS
    assert " " in result  # Space separator
    assert ":" in result  # Time format


def test_get_current_date_with_t():
    """Test get_current_date with with_t=True."""
    result = get_current_date(with_t=True)
    assert isinstance(result, str)
    assert "T" in result  # T separator for ISO format
    assert " " not in result  # No space separator


def test_get_current_date_with_ms():
    """Test get_current_date with include_ms=True."""
    result = get_current_date(include_ms=True)
    assert isinstance(result, str)
    assert "." in result  # Should contain milliseconds
    assert len(result) > 19  # Should be longer than basic format


def test_get_current_date_with_t_and_ms():
    """Test get_current_date with both with_t=True and include_ms=True."""
    result = get_current_date(with_t=True, include_ms=True)
    assert isinstance(result, str)
    assert "T" in result  # T separator
    assert "." in result  # Milliseconds
    assert " " not in result  # No space


def test_get_current_day():
    """Test get_current_day function."""
    result = get_current_day()
    assert isinstance(result, str)
    assert len(result) == 10  # YYYY-MM-DD
    assert result.count("-") == 2  # Two hyphens
    # Should be valid date format
    year, month, day = result.split("-")
    assert len(year) == 4 and year.isdigit()
    assert len(month) == 2 and month.isdigit()
    assert len(day) == 2 and day.isdigit()


def test_current_date_consistency():
    """Test that multiple calls return consistent format."""
    result1 = get_current_date()
    result2 = get_current_date()
    assert isinstance(result1, str)
    assert isinstance(result2, str)
    # Format should be consistent even if time changes
    assert len(result1) == len(result2)
    assert result1.count(":") == result2.count(":")
    assert result1.count("-") == result2.count("-")


def test_current_day_consistency():
    """Test that get_current_day returns consistent format."""
    result1 = get_current_day()
    result2 = get_current_day()
    assert isinstance(result1, str)
    assert isinstance(result2, str)
    assert len(result1) == len(result2) == 10
    assert result1.count("-") == result2.count("-") == 2
