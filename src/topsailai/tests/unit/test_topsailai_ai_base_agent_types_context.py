"""
Unit tests for ai_base/agent_types/context module.

Test coverage:
- get_count_of_action_for_current_agent function

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock


class TestGetCountOfActionForCurrentAgent(unittest.TestCase):
    """Test cases for get_count_of_action_for_current_agent function."""

    def test_returns_minus_one_when_no_agent(self):
        """Test function returns -1 when no agent object is available."""
        from topsailai.ai_base.agent_types.context import get_count_of_action_for_current_agent
        
        with patch('topsailai.ai_base.agent_types.context.get_agent_object', return_value=None):
            result = get_count_of_action_for_current_agent()
            self.assertEqual(result, -1)

    def test_returns_action_count_when_agent_exists(self):
        """Test function returns action count from agent messages."""
        from topsailai.ai_base.agent_types.context import get_count_of_action_for_current_agent
        
        mock_agent = MagicMock()
        mock_agent.messages = [{"role": "user"}, {"role": "assistant"}]
        
        with patch('topsailai.ai_base.agent_types.context.get_agent_object', return_value=mock_agent):
            with patch('topsailai.ai_base.agent_types.context.get_count_of_action', return_value=2):
                result = get_count_of_action_for_current_agent()
                self.assertEqual(result, 2)

    def test_returns_zero_for_empty_messages(self):
        """Test function returns 0 when agent has no messages."""
        from topsailai.ai_base.agent_types.context import get_count_of_action_for_current_agent
        
        mock_agent = MagicMock()
        mock_agent.messages = []
        
        with patch('topsailai.ai_base.agent_types.context.get_agent_object', return_value=mock_agent):
            with patch('topsailai.ai_base.agent_types.context.get_count_of_action', return_value=0):
                result = get_count_of_action_for_current_agent()
                self.assertEqual(result, 0)

    def test_returns_action_count_with_tool_messages(self):
        """Test function correctly counts actions in messages with tool calls."""
        from topsailai.ai_base.agent_types.context import get_count_of_action_for_current_agent
        
        mock_agent = MagicMock()
        mock_agent.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "I'll help you"},
            {"role": "tool", "content": "Tool result"}
        ]
        
        with patch('topsailai.ai_base.agent_types.context.get_agent_object', return_value=mock_agent):
            with patch('topsailai.ai_base.agent_types.context.get_count_of_action', return_value=1):
                result = get_count_of_action_for_current_agent()
                self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
