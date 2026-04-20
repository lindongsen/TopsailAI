"""
Unit tests for ai_team/common.py module.

Test coverage:
- get_session_id(): Generate or retrieve session ID for team sessions

Author: mm-m25
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, '/root/ai/TopsailAI/src')


class TestGetSessionId(unittest.TestCase):
    """Test cases for get_session_id() function"""

    def setUp(self):
        """Set up clean environment for each test"""
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()
        # Clear any cached import
        if 'topsailai.ai_team.common' in sys.modules:
            del sys.modules['topsailai.ai_team.common']
        if 'topsailai.context.common' in sys.modules:
            del sys.modules['topsailai.context.common']

    def tearDown(self):
        """Clean up environment after each test"""
        self.env_patcher.stop()

    def test_get_session_id_returns_string(self):
        """Test get_session_id returns a string"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        self.assertIsInstance(result, str)

    def test_get_session_id_returns_non_empty(self):
        """Test get_session_id returns non-empty string"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        self.assertTrue(len(result) > 0)

    def test_get_session_id_format_contains_digits_and_t(self):
        """Test get_session_id contains digits and T separator (YYYYMMDDTHHMMSS)"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        # Format: YYYYMMDDTHHMMSS = 15 characters with T separator
        self.assertRegex(result, r'^\d{8}T\d{6}$', f"Session ID should match YYYYMMDDTHHMMSS: {result}")

    def test_get_session_id_length(self):
        """Test get_session_id has correct length (15 chars for YYYYMMDDTHHMMSS)"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        # Format: YYYYMMDDTHHMMSS = 15 characters
        self.assertEqual(len(result), 15, f"Session ID should be 15 chars: {result}")

    def test_get_session_id_from_env_var(self):
        """Test get_session_id uses SESSION_ID env var when set"""
        with patch.dict(os.environ, {"SESSION_ID": "custom_session_12345"}):
            from topsailai.ai_team.common import get_session_id
            result = get_session_id()
            self.assertEqual(result, "custom_session_12345")

    def test_get_session_id_env_var_takes_precedence(self):
        """Test get_session_id prioritizes env var over generated ID"""
        with patch.dict(os.environ, {"SESSION_ID": "env_based_id"}):
            from topsailai.ai_team.common import get_session_id
            result = get_session_id()
            self.assertEqual(result, "env_based_id")

    def test_get_session_id_generated_format(self):
        """Test get_session_id generated format matches YYYYMMDDTHHMMSS pattern"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        # Should match pattern with T separator
        self.assertRegex(result, r'^\d{8}T\d{6}$', f"Session ID should match YYYYMMDDTHHMMSS: {result}")

    def test_get_session_id_no_colons(self):
        """Test get_session_id does not contain colons in output"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        self.assertNotIn(":", result, "Session ID should not contain colons")

    def test_get_session_id_no_dashes(self):
        """Test get_session_id does not contain dashes in output"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        self.assertNotIn("-", result, "Session ID should not contain dashes")

    def test_get_session_id_contains_t_separator(self):
        """Test get_session_id contains T separator between date and time"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        self.assertIn("T", result, "Session ID should contain T separator")

    def test_get_session_id_starts_with_date(self):
        """Test get_session_id starts with current date (YYYYMMDD)"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        # Extract date part (first 8 digits)
        date_part = result.split('T')[0]
        self.assertEqual(len(date_part), 8, "Date part should be 8 digits")
        self.assertTrue(date_part.isdigit(), "Date part should be all digits")

    def test_get_session_id_contains_time(self):
        """Test get_session_id contains time part after T separator"""
        from topsailai.ai_team.common import get_session_id
        result = get_session_id()
        # Extract time part (after T)
        time_part = result.split('T')[1]
        self.assertEqual(len(time_part), 6, "Time part should be 6 digits (HHMMSS)")
        self.assertTrue(time_part.isdigit(), "Time part should be all digits")


class TestGetSessionIdEdgeCases(unittest.TestCase):
    """Edge case tests for get_session_id() function"""

    def setUp(self):
        """Set up clean environment for each test"""
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        """Clean up environment after each test"""
        self.env_patcher.stop()

    def test_get_session_id_empty_env_var(self):
        """Test get_session_id when SESSION_ID env var is empty string"""
        with patch.dict(os.environ, {"SESSION_ID": ""}):
            from topsailai.ai_team.common import get_session_id
            result = get_session_id()
            # Empty string is falsy, should generate timestamp
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 0)

    def test_get_session_id_special_chars_in_env(self):
        """Test get_session_id preserves special characters from env var"""
        with patch.dict(os.environ, {"SESSION_ID": "session_with-special.123"}):
            from topsailai.ai_team.common import get_session_id
            result = get_session_id()
            self.assertEqual(result, "session_with-special.123")

    def test_get_session_id_env_var_with_spaces(self):
        """Test get_session_id preserves spaces from env var"""
        with patch.dict(os.environ, {"SESSION_ID": "my session id"}):
            from topsailai.ai_team.common import get_session_id
            result = get_session_id()
            self.assertEqual(result, "my session id")


class TestIntegration(unittest.TestCase):
    """Integration tests for common module"""

    def setUp(self):
        """Set up test environment"""
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        """Clean up environment"""
        self.env_patcher.stop()

    def test_get_session_id_multiple_sequential_calls(self):
        """Test multiple sequential calls to get_session_id"""
        from topsailai.ai_team.common import get_session_id
        # First call
        id1 = get_session_id()
        # Second call
        id2 = get_session_id()
        # Both should be valid strings
        self.assertIsInstance(id1, str)
        self.assertIsInstance(id2, str)
        self.assertTrue(len(id1) > 0)
        self.assertTrue(len(id2) > 0)

    def test_get_session_id_consistent_format(self):
        """Test get_session_id maintains consistent format across calls"""
        from topsailai.ai_team.common import get_session_id
        id1 = get_session_id()
        id2 = get_session_id()
        # Both should have same format (length and structure)
        self.assertEqual(len(id1), len(id2))
        self.assertEqual(id1[8], id2[8], "Both should have T at position 8")


if __name__ == '__main__':
    unittest.main()
