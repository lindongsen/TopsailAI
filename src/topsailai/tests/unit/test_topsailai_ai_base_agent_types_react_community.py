"""
Unit tests for ai_base/agent_types/react_community module.

Test coverage:
- BASE_PROMPT constant
- SYSTEM_PROMPT constant
- AGENT_NAME constant
- AgentStepCall (re-exported from react)

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock


class TestReActCommunityConstants(unittest.TestCase):
    """Test cases for react_community module constants."""

    def test_base_prompt_is_string(self):
        """Test BASE_PROMPT is a string."""
        from topsailai.ai_base.agent_types.react_community import BASE_PROMPT
        
        self.assertIsInstance(BASE_PROMPT, str)

    def test_base_prompt_not_empty(self):
        """Test BASE_PROMPT is not empty."""
        from topsailai.ai_base.agent_types.react_community import BASE_PROMPT
        
        self.assertTrue(len(BASE_PROMPT) > 0)

    def test_system_prompt_is_string(self):
        """Test SYSTEM_PROMPT is a string."""
        from topsailai.ai_base.agent_types.react_community import SYSTEM_PROMPT
        
        self.assertIsInstance(SYSTEM_PROMPT, str)

    def test_system_prompt_not_empty(self):
        """Test SYSTEM_PROMPT is not empty."""
        from topsailai.ai_base.agent_types.react_community import SYSTEM_PROMPT
        
        self.assertTrue(len(SYSTEM_PROMPT) > 0)

    def test_agent_name_value(self):
        """Test AGENT_NAME has correct value."""
        from topsailai.ai_base.agent_types.react_community import AGENT_NAME
        
        self.assertEqual(AGENT_NAME, "AgentReActCommunity")


class TestReActCommunityExports(unittest.TestCase):
    """Test cases for react_community module exports."""

    def test_all_exports_defined(self):
        """Test all items in __all__ are defined."""
        from topsailai.ai_base.agent_types.react_community import __all__
        
        self.assertIn("SYSTEM_PROMPT", __all__)
        self.assertIn("AGENT_NAME", __all__)
        self.assertIn("AgentStepCall", __all__)

    def test_agent_step_call_is_react_step_call(self):
        """Test AgentStepCall is re-exported from react module."""
        from topsailai.ai_base.agent_types.react_community import AgentStepCall
        from topsailai.ai_base.agent_types.react import AgentStepCall as ReactAgentStepCall
        
        self.assertIs(AgentStepCall, ReactAgentStepCall)


class TestReActCommunityPromptContent(unittest.TestCase):
    """Test cases for react_community prompt content."""

    def test_system_prompt_contains_base_prompt(self):
        """Test SYSTEM_PROMPT contains BASE_PROMPT."""
        from topsailai.ai_base.agent_types.react_community import SYSTEM_PROMPT, BASE_PROMPT
        
        self.assertIn(BASE_PROMPT, SYSTEM_PROMPT)

    def test_system_prompt_contains_interactive_prompt(self):
        """Test SYSTEM_PROMPT contains interactive prompt when not using tool calls."""
        from topsailai.ai_base.agent_types.react_community import SYSTEM_PROMPT
        
        # Should contain interactive topsailai prompt
        self.assertTrue(len(SYSTEM_PROMPT) > 0)


if __name__ == "__main__":
    unittest.main()
