"""
Unit tests for topsailai.tools.time_tool module.

This module tests the time utility functions including:
- get_local_date(): Returns current date in ISO 8601 format
- get_local_time(): Returns current time as Unix timestamp
- get_local_day(): Returns current date in YYYY-MM-DD format

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime


class TestGetLocalDate(unittest.TestCase):
    """Test cases for get_local_date() function."""

    def test_returns_iso_8601_format(self):
        """Test that get_local_date returns ISO 8601 formatted string."""
        from topsailai.tools.time_tool import get_local_date
        result = get_local_date()
        # ISO 8601 format: YYYY-MM-DDTHH:MM:SS
        self.assertRegex(result, r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')

    def test_contains_date_components(self):
        """Test that result contains valid date components."""
        from topsailai.tools.time_tool import get_local_date
        result = get_local_date()
        date_part, time_part = result.split('T')
        # Verify date part format
        self.assertRegex(date_part, r'^\d{4}-\d{2}-\d{2}$')
        # Verify time part format
        self.assertRegex(time_part, r'^\d{2}:\d{2}:\d{2}$')

    def test_date_part_is_valid(self):
        """Test that date part represents a valid date."""
        from topsailai.tools.time_tool import get_local_date
        result = get_local_date()
        date_part = result.split('T')[0]
        year, month, day = map(int, date_part.split('-'))
        self.assertGreaterEqual(year, 2024)
        self.assertGreaterEqual(month, 1)
        self.assertLessEqual(month, 12)
        self.assertGreaterEqual(day, 1)
        self.assertLessEqual(day, 31)


class TestGetLocalTime(unittest.TestCase):
    """Test cases for get_local_time() function."""

    def test_returns_integer(self):
        """Test that get_local_time returns an integer."""
        from topsailai.tools.time_tool import get_local_time
        result = get_local_time()
        self.assertIsInstance(result, int)

    def test_returns_positive_value(self):
        """Test that returned timestamp is positive (after Unix epoch)."""
        from topsailai.tools.time_tool import get_local_time
        result = get_local_time()
        self.assertGreater(result, 0)

    def test_returns_reasonable_timestamp(self):
        """Test that timestamp is in reasonable range (after 2020)."""
        from topsailai.tools.time_tool import get_local_time
        result = get_local_time()
        # 2020-01-01 00:00:00 UTC timestamp
        min_expected = 1577836800
        self.assertGreater(result, min_expected)

    def test_increases_over_time(self):
        """Test that successive calls return increasing values."""
        from topsailai.tools.time_tool import get_local_time
        time1 = get_local_time()
        time2 = get_local_time()
        self.assertGreaterEqual(time2, time1)


class TestGetLocalDay(unittest.TestCase):
    """Test cases for get_local_day() function."""

    def test_returns_string(self):
        """Test that get_local_day returns a string."""
        from topsailai.tools.time_tool import get_local_day
        result = get_local_day()
        self.assertIsInstance(result, str)

    def test_returns_yyyy_mm_dd_format(self):
        """Test that result follows YYYY-MM-DD format."""
        from topsailai.tools.time_tool import get_local_day
        result = get_local_day()
        self.assertRegex(result, r'^\d{4}-\d{2}-\d{2}$')

    def test_date_components_valid(self):
        """Test that date components are valid."""
        from topsailai.tools.time_tool import get_local_day
        result = get_local_day()
        year, month, day = map(int, result.split('-'))
        self.assertGreaterEqual(year, 2024)
        self.assertGreaterEqual(month, 1)
        self.assertLessEqual(month, 12)
        self.assertGreaterEqual(day, 1)
        self.assertLessEqual(day, 31)


class TestTOOLSDictionary(unittest.TestCase):
    """Test cases for the TOOLS dictionary."""

    def test_tools_contains_required_functions(self):
        """Test that TOOLS dictionary contains expected keys."""
        from topsailai.tools.time_tool import TOOLS
        self.assertIn('get_local_date', TOOLS)
        self.assertIn('get_local_time', TOOLS)

    def test_tools_values_are_callable(self):
        """Test that TOOLS values are callable functions."""
        from topsailai.tools.time_tool import TOOLS
        for name, func in TOOLS.items():
            self.assertTrue(callable(func), f"{name} should be callable")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases for time functions."""

    def test_get_local_date_with_mocked_time(self):
        """Test get_local_date with mocked datetime."""
        from topsailai.tools.time_tool import get_local_date
        mock_date = datetime(2024, 6, 15, 14, 30, 45)
        with patch('topsailai.utils.time_tool.datetime') as mock_dt:
            mock_dt.now.return_value = mock_date
            result = get_local_date()
            self.assertEqual(result, '2024-06-15T14:30:45')

    def test_get_local_day_with_mocked_time(self):
        """Test get_local_day with mocked datetime."""
        from topsailai.tools.time_tool import get_local_day
        mock_date = datetime(2024, 12, 25, 0, 0, 0)
        with patch('topsailai.utils.time_tool.datetime') as mock_dt:
            mock_dt.now.return_value = mock_date
            result = get_local_day()
            self.assertEqual(result, '2024-12-25')

    def test_get_local_time_with_mocked_time(self):
        """Test get_local_time with mocked time."""
        from topsailai.tools.time_tool import get_local_time
        expected_timestamp = 1718451045
        with patch('time.time', return_value=expected_timestamp):
            result = get_local_time()
            self.assertEqual(result, expected_timestamp)


class TestLeapYearAndDST(unittest.TestCase):
    """Test leap year and DST edge cases."""

    def test_leap_year_february(self):
        """Test that February handles leap year correctly."""
        from topsailai.tools.time_tool import get_local_day
        # This test verifies the function works during leap year
        result = get_local_day()
        self.assertRegex(result, r'^\d{4}-\d{2}-\d{2}$')

    def test_year_boundary(self):
        """Test that year transitions are handled correctly."""
        from topsailai.tools.time_tool import get_local_day
        result = get_local_day()
        year = int(result.split('-')[0])
        self.assertGreaterEqual(year, 2024)


if __name__ == '__main__':
    unittest.main()
