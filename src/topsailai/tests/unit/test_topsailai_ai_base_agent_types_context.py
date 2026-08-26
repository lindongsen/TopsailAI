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


class TestAgentContextMaxTokens(unittest.TestCase):
    """Test environment resolution for the context token limit."""

    def test_legacy_variable_is_used_as_fallback(self):
        """Use MAX_TOKENS when the preferred variable has no value."""
        from topsailai.ai_base.agent_types.context import AgentContextInstance

        environment = {
            "TOPSAILAI_MAX_COMPLETION_TOKENS": "",
            "MAX_TOKENS": "4100",
        }
        with patch.dict("os.environ", environment, clear=True):
            self.assertEqual(AgentContextInstance.max_tokens, 4100)

    def test_prefixed_variable_takes_precedence(self):
        """Use the preferred variable when both names have values."""
        from topsailai.ai_base.agent_types.context import AgentContextInstance

        environment = {
            "TOPSAILAI_MAX_COMPLETION_TOKENS": "5100",
            "MAX_TOKENS": "4100",
        }
        with patch.dict("os.environ", environment, clear=True):
            self.assertEqual(AgentContextInstance.max_tokens, 5100)


if __name__ == "__main__":
    unittest.main()
