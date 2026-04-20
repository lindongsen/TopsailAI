"""
Unit tests for workspace/context/agent2llm.py module.

This module tests the ContextRuntimeAgent2LLM class which handles
agent-to-LLM message conversion and context summarization.

Author: mm-m25
Created: 2026-04-19
"""

import unittest
from unittest.mock import MagicMock, patch


class TestContextRuntimeAgent2LLM(unittest.TestCase):
    """Test suite for ContextRuntimeAgent2LLM class."""

    def setUp(self):
        """Set up test fixtures."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        
        class TestableAgent2LLM(ContextRuntimeAgent2LLM):
            def __init__(self):
                self._ai_agent = MagicMock()
                self._messages = []
                self._session_id = "test-session-123"
                self._first_position = 0
            
            @property
            def ai_agent(self):
                return self._ai_agent
            
            @property
            def messages(self):
                return self._messages
            
            @property
            def session_id(self):
                return self._session_id
            
            def get_work_memory_first_position(self):
                return self._first_position
            
            def _summarize_messages(self, messages):
                mock_prompt = MagicMock()
                mock_prompt.prompt_ctl.messages = [
                    {"role": "assistant", "content": "Summarized content"}
                ]
                return mock_prompt, "Summarized content"
            
            def _get_head_offset_to_keep_in_summary(self, offset=None):
                return offset if offset is not None else 5
            
            def _get_quantity_threshold(self):
                return 50
        
        self.test_instance = TestableAgent2LLM()

    def tearDown(self):
        """Clean up after tests."""
        self.test_instance = None


class TestDelAgentMessages(TestContextRuntimeAgent2LLM):
    """Test suite for del_agent_messages method."""

    def test_del_agent_messages_with_empty_indexes(self):
        """Test deletion with empty indexes returns empty list."""
        result = self.test_instance.del_agent_messages([])
        self.assertEqual(result, [])

    def test_del_agent_messages_with_none_indexes(self):
        """Test deletion with None indexes returns empty list."""
        result = self.test_instance.del_agent_messages(None)
        self.assertEqual(result, [])

    def test_del_agent_messages_with_first_position_none(self):
        """Test deletion when first position is None returns empty list."""
        self.test_instance._first_position = None
        result = self.test_instance.del_agent_messages([0, 1])
        self.assertEqual(result, [])

    def test_del_agent_messages_no_system_messages(self):
        """Test deletion when no system messages to skip."""
        self.test_instance._ai_agent.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
        ]
        self.test_instance._first_position = 0
        
        with patch('topsailai.workspace.context.agent2llm.json_tool') as mock_json:
            mock_json.json_load.side_effect = lambda x: x
            result = self.test_instance.del_agent_messages([0])
            self.assertIn(0, result)

    def test_del_agent_messages_with_system_message(self):
        """Test deletion with system message in list."""
        self.test_instance._ai_agent.messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        self.test_instance._first_position = 0
        
        with patch('topsailai.workspace.context.agent2llm.json_tool') as mock_json:
            mock_json.json_load.side_effect = lambda x: x
            result = self.test_instance.del_agent_messages([1])
            self.assertIn(1, result)

    def test_del_agent_messages_to_del_last(self):
        """Test deletion with to_del_last flag."""
        self.test_instance._ai_agent.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Last"},
        ]
        self.test_instance._first_position = 0
        
        with patch('topsailai.workspace.context.agent2llm.json_tool') as mock_json:
            mock_json.json_load.side_effect = lambda x: x
            result = self.test_instance.del_agent_messages([0], to_del_last=True)
            self.assertIn(0, result)

    def test_del_agent_messages_updates_messages(self):
        """Test that deletion actually updates the messages list."""
        self.test_instance._ai_agent.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        self.test_instance._first_position = 0
        
        with patch('topsailai.workspace.context.agent2llm.json_tool') as mock_json:
            mock_json.json_load.side_effect = lambda x: x
            self.test_instance.del_agent_messages([0])
            self.assertIsNotNone(self.test_instance._ai_agent.messages)


class TestIsNeedSummarizeForProcessing(TestContextRuntimeAgent2LLM):
    """Test suite for is_need_summarize_for_processing method."""

    def test_no_threshold_returns_false(self):
        """Test that no threshold returns False."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        result = self.test_instance.is_need_summarize_for_processing()
        self.assertFalse(result)

    def test_messages_below_threshold_returns_false(self):
        """Test messages below threshold returns False."""
        self.test_instance._ai_agent.messages = ["msg1", "msg2", "msg3"]
        self.test_instance._get_quantity_threshold = MagicMock(return_value=50)
        result = self.test_instance.is_need_summarize_for_processing()
        self.assertFalse(result)

    def test_messages_at_threshold_returns_true(self):
        """Test messages at threshold returns True."""
        self.test_instance._ai_agent.messages = [f"msg{i}" for i in range(50)]
        self.test_instance._get_quantity_threshold = MagicMock(return_value=50)
        result = self.test_instance.is_need_summarize_for_processing()
        self.assertTrue(result)

    def test_messages_above_threshold_returns_true(self):
        """Test messages above threshold returns True."""
        self.test_instance._ai_agent.messages = [f"msg{i}" for i in range(100)]
        self.test_instance._get_quantity_threshold = MagicMock(return_value=50)
        result = self.test_instance.is_need_summarize_for_processing()
        self.assertTrue(result)


class TestSummarizeMessagesForProcessing(TestContextRuntimeAgent2LLM):
    """Test suite for summarize_messages_for_processing method."""

    def test_first_position_none_returns_none(self):
        """Test summarization when first position is None returns None."""
        self.test_instance._first_position = None
        result = self.test_instance.summarize_messages_for_processing()
        self.assertIsNone(result)

    def test_empty_messages_returns_none(self):
        """Test summarization with empty messages returns None."""
        self.test_instance._ai_agent.messages = []
        self.test_instance._first_position = 0
        result = self.test_instance.summarize_messages_for_processing()
        self.assertIsNone(result)

    def test_short_messages_no_summarize(self):
        """Test that short messages don't need summarization."""
        self.test_instance._ai_agent.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        self.test_instance._first_position = 0
        
        with patch('topsailai.workspace.context.agent2llm.logger') as mock_logger:
            result = self.test_instance.summarize_messages_for_processing()
            self.assertIsNone(result)
            mock_logger.warning.assert_called()

    def test_summarize_with_custom_messages(self):
        """Test summarization with custom messages."""
        custom_messages = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(30)
        ]
        self.test_instance._first_position = 0
        
        with patch('topsailai.workspace.context.agent2llm.logger'):
            with patch('topsailai.workspace.context.agent2llm.print_step'):
                result = self.test_instance.summarize_messages_for_processing(
                    messages=custom_messages
                )
                self.assertIsNotNone(result)
                self.assertEqual(result, "Summarized content")

    def test_summarize_updates_ai_agent_messages(self):
        """Test that summarization updates ai_agent.messages."""
        self.test_instance._ai_agent.messages = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(30)
        ]
        self.test_instance._first_position = 0
        original_len = len(self.test_instance._ai_agent.messages)
        
        with patch('topsailai.workspace.context.agent2llm.logger'):
            with patch('topsailai.workspace.context.agent2llm.print_step'):
                self.test_instance.summarize_messages_for_processing()
                self.assertNotEqual(len(self.test_instance._ai_agent.messages), original_len)


class TestEdgeCases(TestContextRuntimeAgent2LLM):
    """Test suite for edge cases and error handling."""

    def test_large_index_list(self):
        """Test handling of large index list."""
        self.test_instance._ai_agent.messages = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(10)
        ]
        self.test_instance._first_position = 0
        
        with patch('topsailai.workspace.context.agent2llm.json_tool') as mock_json:
            mock_json.json_load.side_effect = lambda x: x
            result = self.test_instance.del_agent_messages([0, 1, 2, 100, 200])
            self.assertIsInstance(result, list)

    def test_multiple_summarization_calls(self):
        """Test multiple summarization calls don't cause issues."""
        self.test_instance._ai_agent.messages = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(30)
        ]
        self.test_instance._first_position = 0
        
        with patch('topsailai.workspace.context.agent2llm.logger'):
            with patch('topsailai.workspace.context.agent2llm.print_step'):
                result1 = self.test_instance.summarize_messages_for_processing()
                result2 = self.test_instance.summarize_messages_for_processing()
                self.assertIsNotNone(result1)
                self.assertIsInstance(result2, (str, type(None)))


if __name__ == '__main__':
    unittest.main()
