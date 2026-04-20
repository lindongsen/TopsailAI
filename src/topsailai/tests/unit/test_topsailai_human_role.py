"""
Unit tests for the human.role module.

This module tests the get_human_name function to ensure proper
human name handling and environment variable integration.

Author: AI (Unit Test Enhancement)
Purpose: Comprehensive test coverage for human role module
"""

import os
import unittest
from unittest.mock import patch, MagicMock

from topsailai.human.role import get_human_name, HUMAN_STARTSWITH


class TestGetHumanName(unittest.TestCase):
    """Test cases for get_human_name function."""

    def test_human_startswith_constant(self):
        """Test that HUMAN_STARTSWITH constant is correctly defined."""
        self.assertEqual(HUMAN_STARTSWITH, "Human.")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_with_explicit_name(self, mock_env):
        """Test get_human_name with explicit name parameter."""
        result = get_human_name("Alice")
        self.assertEqual(result, "Human.Alice")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_already_has_prefix(self, mock_env):
        """Test get_human_name when name already has Human. prefix."""
        result = get_human_name("Human.Bob")
        self.assertEqual(result, "Human.Bob")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_from_env_variable(self, mock_env):
        """Test get_human_name when name comes from environment variable."""
        mock_env.get.return_value = "Charlie"
        
        result = get_human_name()
        
        mock_env.get.assert_called_once_with("TOPSAILAI_HUMAN_NAME")
        self.assertEqual(result, "Human.Charlie")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_default_when_env_empty(self, mock_env):
        """Test get_human_name defaults to DawsonLin when env is empty."""
        mock_env.get.return_value = None
        
        result = get_human_name()
        
        self.assertEqual(result, "Human.DawsonLin")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_explicit_overrides_env(self, mock_env):
        """Test that explicit name parameter overrides environment variable."""
        mock_env.get.return_value = "EnvName"
        
        result = get_human_name("ExplicitName")
        
        # Env should not be called when explicit name is provided
        mock_env.get.assert_not_called()
        self.assertEqual(result, "Human.ExplicitName")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_empty_string_explicit(self, mock_env):
        """Test get_human_name with empty string as explicit name."""
        mock_env.get.return_value = "FromEnv"
        
        result = get_human_name("")
        
        # Empty string is falsy, so should fall back to env
        mock_env.get.assert_called_once()
        self.assertEqual(result, "Human.FromEnv")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_none_explicit(self, mock_env):
        """Test get_human_name with None as explicit name."""
        mock_env.get.return_value = "FromEnv"
        
        result = get_human_name(None)
        
        # None is falsy, so should fall back to env
        mock_env.get.assert_called_once()
        self.assertEqual(result, "Human.FromEnv")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_special_characters(self, mock_env):
        """Test get_human_name with special characters in name."""
        result = get_human_name("John_Doe-123")
        self.assertEqual(result, "Human.John_Doe-123")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_unicode(self, mock_env):
        """Test get_human_name with unicode characters."""
        result = get_human_name("张三")
        self.assertEqual(result, "Human.张三")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_long_name(self, mock_env):
        """Test get_human_name with a long name."""
        long_name = "A" * 1000
        result = get_human_name(long_name)
        self.assertEqual(result, f"Human.{long_name}")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_already_has_prefix_different_case(self, mock_env):
        """Test get_human_name when name has 'human.' lowercase prefix."""
        result = get_human_name("human.Alice")
        # Should NOT match because it's case-sensitive
        self.assertEqual(result, "Human.human.Alice")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_whitespace_handling(self, mock_env):
        """Test get_human_name with whitespace in name."""
        result = get_human_name("  Alice  ")
        self.assertEqual(result, "Human.  Alice  ")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_get_human_name_multiple_human_prefixes(self, mock_env):
        """Test get_human_name when name already starts with Human.Human."""
        result = get_human_name("Human.Human.Alice")
        # Already starts with Human., so no prefix added
        self.assertEqual(result, "Human.Human.Alice")


class TestGetHumanNameEdgeCases(unittest.TestCase):
    """Edge case tests for get_human_name function."""

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_env_reader_returns_empty_string(self, mock_env):
        """Test when EnvReaderInstance.get returns empty string."""
        mock_env.get.return_value = ""
        
        result = get_human_name()
        
        # Empty string is falsy, should fall back to default
        self.assertEqual(result, "Human.DawsonLin")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_env_reader_returns_whitespace(self, mock_env):
        """Test when EnvReaderInstance.get returns only whitespace."""
        mock_env.get.return_value = "   "
        
        result = get_human_name()
        
        # Whitespace is truthy in Python, so it will be used as-is
        self.assertEqual(result, "Human.   ")

    @patch('topsailai.human.role.env_tool.EnvReaderInstance')
    def test_explicit_name_whitespace_only(self, mock_env):
        """Test when explicit name is only whitespace."""
        mock_env.get.return_value = "FromEnv"
        
        result = get_human_name("   ")
        
        # Whitespace is truthy in Python, so it will be used as-is
        self.assertEqual(result, "Human.   ")


if __name__ == '__main__':
    unittest.main()
