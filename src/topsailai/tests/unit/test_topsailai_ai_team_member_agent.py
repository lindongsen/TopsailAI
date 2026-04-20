"""
Unit tests for ai_team/member_agent.py

This module contains unit tests for the member_agent module which handles
system prompt generation for team member agents.

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock


class TestExtendSystemPrompt(unittest.TestCase):
    """Tests for extend_system_prompt() function."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Store original env var if it exists
        self.original_env = None
        if "SYSTEM_PROMPT_EXTRA_FILES" in __import__('os').environ:
            self.original_env = __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"]
    
    def tearDown(self):
        """Clean up test environment."""
        if self.original_env is not None:
            __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"] = self.original_env
        elif "SYSTEM_PROMPT_EXTRA_FILES" in __import__('os').environ:
            del __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"]
    
    def test_returns_none(self):
        """Test that extend_system_prompt returns None."""
        from topsailai.ai_team.member_agent import extend_system_prompt
        result = extend_system_prompt()
        self.assertIsNone(result)
    
    def test_sets_default_when_not_set(self):
        """Test that extend_system_prompt sets default value when env var not set."""
        # Ensure env var is not set
        if "SYSTEM_PROMPT_EXTRA_FILES" in __import__('os').environ:
            del __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"]
        
        from topsailai.ai_team.member_agent import extend_system_prompt
        extend_system_prompt()
        
        self.assertEqual(
            __import__('os').environ.get("SYSTEM_PROMPT_EXTRA_FILES"),
            "work_mode/sop/work_agreement.md"
        )
    
    def test_does_not_override_existing(self):
        """Test that extend_system_prompt does not override existing env var."""
        __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"] = "custom/path.md"
        
        from topsailai.ai_team.member_agent import extend_system_prompt
        extend_system_prompt()
        
        self.assertEqual(
            __import__('os').environ.get("SYSTEM_PROMPT_EXTRA_FILES"),
            "custom/path.md"
        )


class TestGetSystemPrompt(unittest.TestCase):
    """Tests for get_system_prompt() function."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_file_content = "You are a helpful AI assistant."
        self.mock_member_prompt = "\n\n## Role\nYou are a team member."
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_returns_string_type(self, mock_extend, mock_get_member, mock_file):
        """Test that get_system_prompt returns string type."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        self.assertIsInstance(result, str)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_contains_base_system_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that result contains base system prompt content."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        self.assertIn(self.mock_file_content, result)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_appends_member_prompt_when_not_present(self, mock_extend, mock_get_member, mock_file):
        """Test that member prompt is appended when not in system prompt."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        self.assertIn(self.mock_member_prompt, result)
        mock_get_member.assert_called_once_with("mm-m25")
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_does_not_append_duplicate_member_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that member prompt is not appended twice when already present."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        # Member prompt already in system prompt
        combined_content = self.mock_file_content + self.mock_member_prompt
        mock_file.return_value = (None, combined_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        # Should only appear once
        self.assertEqual(result.count(self.mock_member_prompt), 1)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_calls_extend_system_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that extend_system_prompt is called."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        get_system_prompt("mm-m25")
        
        mock_extend.assert_called_once()
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_handles_empty_system_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that function handles empty system prompt gracefully."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, "")
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        self.assertIn(self.mock_member_prompt, result)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_handles_empty_member_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that function handles empty member prompt gracefully."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = ""
        
        result = get_system_prompt("mm-m25")
        
        self.assertEqual(result, self.mock_file_content)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_uses_agent_name_parameter(self, mock_extend, mock_get_member, mock_file):
        """Test that agent_name parameter is passed to get_member_prompt."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        get_system_prompt("test-agent-42")
        
        mock_get_member.assert_called_once_with("test-agent-42")


if __name__ == '__main__':
    unittest.main()
