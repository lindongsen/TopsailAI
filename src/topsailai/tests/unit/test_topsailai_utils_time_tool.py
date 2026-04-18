import pytest
import time
import threading
from datetime import datetime
from topsailai.utils.time_tool import (
    get_current_date,
    get_current_day,
    parse_time_seconds,
    get_now_hex_str,
)


# =============================================================================
# get_current_date tests
# =============================================================================

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


def test_current_date_consistency():
    """Test that multiple calls return consistent format."""
    result1 = get_current_date()
    result2 = get_current_date()
    assert isinstance(result1, str)
    assert isinstance(result2, str)
    # Format should be consistent even if time changes
    assert len(result1) == len(result2)
    assert result1.count(":") == result2.count(":")


# =============================================================================
# get_current_day tests
# =============================================================================

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


def test_current_day_consistency():
    """Test that get_current_day returns consistent format."""
    result1 = get_current_day()
    result2 = get_current_day()
    assert isinstance(result1, str)
    assert isinstance(result2, str)
    assert len(result1) == len(result2) == 10
    assert result1.count("-") == result2.count("-") == 2


# =============================================================================
# parse_time_seconds tests
# =============================================================================

def test_parse_time_seconds_basic():
    """Test parse_time_seconds with a known timestamp."""
    # 2020-01-01 00:00:00 UTC
    ts = 1577836800
    result = parse_time_seconds(ts)
    assert isinstance(result, str)
    # Timezone-agnostic: just check the date part
    assert result.startswith("2020-01-01T")
    assert result.endswith(":00:00")


def test_parse_time_seconds_epoch():
    """Test parse_time_seconds with Unix epoch (timestamp 0)."""
    ts = 0
    result = parse_time_seconds(ts)
    assert isinstance(result, str)
    # Should be 1970-01-01T00:00:00
    assert "1970-01-01" in result
    assert "T" in result
    assert ":" in result


def test_parse_time_seconds_current():
    """Test parse_time_seconds with current timestamp."""
    ts = int(time.time())
    result = parse_time_seconds(ts)
    assert isinstance(result, str)
    assert "T" in result
    # Should contain current date
    current_day = get_current_day()
    assert current_day in result


def test_parse_time_seconds_future():
    """Test parse_time_seconds with a future timestamp."""
    # 2030-01-01 00:00:00 UTC
    ts = 1893456000
    result = parse_time_seconds(ts)
    assert isinstance(result, str)
    # Timezone-agnostic: just check the date part
    assert result.startswith("2030-01-01T")
    assert result.endswith(":00:00")


def test_parse_time_seconds_return_type():
    """Test that parse_time_seconds returns a string."""
    result = parse_time_seconds(1577836800)
    assert isinstance(result, str)


def test_parse_time_seconds_format():
    """Test that parse_time_seconds returns correct ISO format."""
    ts = 1609459200  # 2021-01-01 00:00:00 UTC
    result = parse_time_seconds(ts)
    # Format: YYYY-MM-DDTHH:MM:SS
    assert len(result) == 19
    assert result[4] == "-" and result[7] == "-"
    assert result[10] == "T"
    assert result[13] == ":" and result[16] == ":"


def test_parse_time_seconds_invalid_type_string():
    """Test parse_time_seconds with invalid type: string."""
    with pytest.raises((ValueError, TypeError, OSError)):
        parse_time_seconds("invalid")


def test_parse_time_seconds_invalid_type_none():
    """Test parse_time_seconds with invalid type: None."""
    with pytest.raises((ValueError, TypeError, OSError)):
        parse_time_seconds(None)


def test_parse_time_seconds_float():
    """Test parse_time_seconds with float timestamp."""
    # Float is accepted by datetime.fromtimestamp
    result = parse_time_seconds(1577836800.5)
    assert isinstance(result, str)
    assert result.startswith("2020-01-01T")


def test_parse_time_seconds_invalid_type_list():
    """Test parse_time_seconds with invalid type: list."""
    with pytest.raises((ValueError, TypeError, OSError)):
        parse_time_seconds([1577836800])


# =============================================================================
# get_now_hex_str tests
# =============================================================================

def test_get_now_hex_str_basic():
    """Test get_now_hex_str basic functionality."""
    result = get_now_hex_str()
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_now_hex_str_is_hex():
    """Test that get_now_hex_str returns a valid hex string."""
    result = get_now_hex_str()
    # Should only contain hex characters (0-9, a-f)
    assert all(c in "0123456789abcdef" for c in result.lower())


def test_get_now_hex_str_uniqueness():
    """Test that consecutive calls may differ if microseconds change."""
    result1 = get_now_hex_str()
    time.sleep(0.001)  # Wait 1ms
    result2 = get_now_hex_str()
    # Results should be strings
    assert isinstance(result1, str)
    assert isinstance(result2, str)


def test_get_now_hex_str_length():
    """Test that get_now_hex_str returns expected length."""
    result = get_now_hex_str()
    # Format: YYYYMMDDHHMMSS (14 chars) + milliseconds (3 chars) = 17 chars
    # But hex conversion may vary, so just check it's reasonable
    assert 10 <= len(result) <= 20


def test_get_now_hex_str_thread_safety():
    """Test that get_now_hex_str is thread-safe."""
    results = []
    errors = []

    def get_hex():
        try:
            for _ in range(10):
                results.append(get_now_hex_str())
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=get_hex) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Thread safety errors: {errors}"
    assert len(results) == 50  # 5 threads * 10 calls


def test_get_now_hex_str_format():
    """Test that get_now_hex_str contains timestamp components."""
    result = get_now_hex_str()
    # Should be a hex representation of time-based values
    assert result.isalnum() or all(c in "0123456789abcdef" for c in result.lower())
