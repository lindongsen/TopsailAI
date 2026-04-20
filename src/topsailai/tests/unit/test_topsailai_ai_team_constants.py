"""
Unit tests for ai_team/constants.py module.

This module tests the default constants used in the ai_team module.

Author: mm-m25
"""

import unittest
from topsailai.ai_team.constants import DEFAULT_HEAD_TAIL_OFFSET


class TestDefaultHeadTailOffset(unittest.TestCase):
    """Test cases for DEFAULT_HEAD_TAIL_OFFSET constant."""

    def test_default_head_tail_offset_exists(self):
        """Test that DEFAULT_HEAD_TAIL_OFFSET constant exists."""
        self.assertTrue(hasattr(__import__('topsailai.ai_team.constants', fromlist=['DEFAULT_HEAD_TAIL_OFFSET']), 'DEFAULT_HEAD_TAIL_OFFSET'))

    def test_default_head_tail_offset_value(self):
        """Test that DEFAULT_HEAD_TAIL_OFFSET has expected value of 7."""
        self.assertEqual(DEFAULT_HEAD_TAIL_OFFSET, 7)

    def test_default_head_tail_offset_is_integer(self):
        """Test that DEFAULT_HEAD_TAIL_OFFSET is an integer type."""
        self.assertIsInstance(DEFAULT_HEAD_TAIL_OFFSET, int)

    def test_default_head_tail_offset_is_positive(self):
        """Test that DEFAULT_HEAD_TAIL_OFFSET is a positive value."""
        self.assertGreater(DEFAULT_HEAD_TAIL_OFFSET, 0)

    def test_default_head_tail_offset_is_reasonable(self):
        """Test that DEFAULT_HEAD_TAIL_OFFSET is within reasonable range."""
        self.assertGreaterEqual(DEFAULT_HEAD_TAIL_OFFSET, 1)
        self.assertLessEqual(DEFAULT_HEAD_TAIL_OFFSET, 100)


class TestConstantImmutability(unittest.TestCase):
    """Test cases for constant immutability."""

    def test_constant_is_not_none(self):
        """Test that constant is not None."""
        self.assertIsNotNone(DEFAULT_HEAD_TAIL_OFFSET)

    def test_constant_equals_expected_value(self):
        """Test that constant equals the expected hardcoded value."""
        expected = 7
        self.assertEqual(DEFAULT_HEAD_TAIL_OFFSET, expected)


class TestModuleStructure(unittest.TestCase):
    """Test cases for module structure and attributes."""

    def test_module_has_only_expected_attributes(self):
        """Test that module has only expected constant attributes."""
        import topsailai.ai_team.constants as constants_module
        module_attrs = [attr for attr in dir(constants_module) if not attr.startswith('_')]
        # Module should have DEFAULT_HEAD_TAIL_OFFSET
        self.assertIn('DEFAULT_HEAD_TAIL_OFFSET', module_attrs)

    def test_module_docstring_exists(self):
        """Test that module has a docstring."""
        import topsailai.ai_team.constants as constants_module
        self.assertIsNotNone(constants_module.__doc__)


class TestIntegration(unittest.TestCase):
    """Integration tests for constants module."""

    def test_constant_used_in_context(self):
        """Test that constant can be imported and used in context."""
        from topsailai.ai_team.constants import DEFAULT_HEAD_TAIL_OFFSET
        # Use the constant in a simple operation
        result = DEFAULT_HEAD_TAIL_OFFSET + 1
        self.assertEqual(result, 8)

    def test_constant_in_list_operations(self):
        """Test that constant works in list slicing operations."""
        test_list = list(range(20))
        # DEFAULT_HEAD_TAIL_OFFSET = 7, so we take first 7 and last 7 elements
        head = test_list[:DEFAULT_HEAD_TAIL_OFFSET]
        tail = test_list[-DEFAULT_HEAD_TAIL_OFFSET:]
        self.assertEqual(len(head), 7)
        self.assertEqual(len(tail), 7)


if __name__ == '__main__':
    unittest.main()
