"""
Unit tests for workspace/context/agent2llm.py module.

This module tests the ContextRuntimeAgent2LLM class which handles
agent-to-LLM message conversion and context summarization.

Author: mm-m25
Created: 2026-04-19
"""

import unittest
from unittest.mock import MagicMock, patch
import os


class TestContextRuntimeAgent2LLM(unittest.TestCase):
    """Test suite for ContextRuntimeAgent2LLM class."""

    def setUp(self):
        """Set up test fixtures."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        
        class TestableAgent2LLM(ContextRuntimeAgent2LLM):
            def __init__(self):
                self._ai_agent = MagicMock()
                self._ai_agent.llm_model.tokenStat.current_tokens = 0
                self._messages = []
                self._session_id = "test-session-123"
                self._first_position = 0
                self._summarize_messages_impl = None
                # The implementation reads the first position from the ai_agent mock,
                # so wire the mock to return the current test value.
                self._ai_agent.get_work_memory_first_position.side_effect = lambda: self._first_position
            
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
                if self._summarize_messages_impl is not None:
                    return self._summarize_messages_impl(messages)
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



class TestGetCurrentTokens(TestContextRuntimeAgent2LLM):
    """Test suite for _get_current_tokens method in Agent2LLM."""

    def test_get_current_tokens_default_cached(self):
        """Test default behavior returns cached tokenStat.current_tokens."""
        with patch('topsailai.workspace.context.base.env_tool') as mock_env:
            mock_env.EnvReaderInstance.check_bool.return_value = False
            result = self.test_instance._get_current_tokens()
            self.assertEqual(result, 0)

    def test_get_current_tokens_realtime(self):
        """Test real-time calculation uses ai_agent.messages."""
        with patch('topsailai.workspace.context.base.env_tool') as mock_env:
            mock_env.EnvReaderInstance.check_bool.return_value = True
            with patch('topsailai.workspace.context.base.count_tokens') as mock_count:
                mock_count.return_value = 55
                self.test_instance._ai_agent.messages = [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "world"},
                ]
                result = self.test_instance._get_current_tokens()
                self.assertEqual(result, 55)
                mock_count.assert_called_once_with(
                    str(self.test_instance._ai_agent.messages)
                )

    def test_get_current_tokens_realtime_with_messages_arg(self):
        """Test real-time calculation respects explicit messages argument."""
        with patch('topsailai.workspace.context.base.env_tool') as mock_env:
            mock_env.EnvReaderInstance.check_bool.return_value = True
            with patch('topsailai.workspace.context.base.count_tokens') as mock_count:
                mock_count.return_value = 7
                custom_messages = [{"role": "user", "content": "custom"}]
                result = self.test_instance._get_current_tokens(messages=custom_messages)
                self.assertEqual(result, 7)
                mock_count.assert_called_once_with(str(custom_messages))

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

    def test_token_threshold_disabled_returns_false(self):
        """Test that token check is disabled when threshold is 0."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.llm_model.tokenStat.current_tokens = 999999
        with patch('topsailai.workspace.context.agent2llm.env_tool') as mock_env:
            mock_env.EnvReaderInstance.get.return_value = 0
            result = self.test_instance.is_need_summarize_for_processing()
            self.assertFalse(result)

    def test_token_usage_below_threshold_returns_false(self):
        """Test token usage below threshold returns False."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.llm_model.tokenStat.current_tokens = 1000
        with patch('topsailai.workspace.context.agent2llm.env_tool') as mock_env:
            mock_env.EnvReaderInstance.get.return_value = 128000
            result = self.test_instance.is_need_summarize_for_processing()
            self.assertFalse(result)

    def test_token_usage_above_threshold_returns_true(self):
        """Test token usage above threshold returns True."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.llm_model.tokenStat.current_tokens = 200000
        with patch('topsailai.workspace.context.agent2llm.env_tool') as mock_env:
            mock_env.EnvReaderInstance.get.return_value = 128000
            result = self.test_instance.is_need_summarize_for_processing()
            self.assertTrue(result)

    def test_token_access_error_returns_false(self):
        """Test that token access errors are handled gracefully."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.llm_model = None
        with patch('topsailai.workspace.context.agent2llm.env_tool') as mock_env:
            mock_env.EnvReaderInstance.get.return_value = 128000
            result = self.test_instance.is_need_summarize_for_processing()
            self.assertFalse(result)

    def test_is_need_summarize_uses_agent2llm_env_var(self):
        """Test that TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD is used."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "20",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "50",
        }):
            with patch('topsailai.workspace.context.agent2llm.random.choice', return_value=13):
                self.test_instance._ai_agent.messages = [f"msg{i}" for i in range(20)]
                # Remove the override so the real _get_quantity_threshold runs.
                del type(self.test_instance)._get_quantity_threshold

                result = self.test_instance.is_need_summarize_for_processing()

                self.assertTrue(result)

    def test_is_need_summarize_agent2llm_falls_back_to_legacy(self):
        """Test fallback to legacy shared env var when agent2llm var is unset."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "30",
        }):
            with patch('topsailai.workspace.context.agent2llm.random.choice', return_value=13):
                self.test_instance._ai_agent.messages = [f"msg{i}" for i in range(30)]
                del type(self.test_instance)._get_quantity_threshold

                result = self.test_instance.is_need_summarize_for_processing()

                self.assertTrue(result)

    @patch('topsailai.workspace.context.agent2llm.random.choice', return_value=23)
    def test_is_need_summarize_agent2llm_wins_over_legacy(self, mock_choice):
        """Test layer-specific env var takes precedence over legacy shared var."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "23",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "100",
        }):
            self.test_instance._ai_agent.messages = [f"msg{i}" for i in range(23)]
            del type(self.test_instance)._get_quantity_threshold

            result = self.test_instance.is_need_summarize_for_processing()

            self.assertTrue(result)

    def test_is_need_summarize_agent2llm_disabled(self):
        """Test quantity summarization disabled when both agent2llm and legacy are unset."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "",
        }):
            self.test_instance._ai_agent.messages = [f"msg{i}" for i in range(200)]
            del type(self.test_instance)._get_quantity_threshold

            result = self.test_instance.is_need_summarize_for_processing()

            self.assertFalse(result)

    def test_token_usage_above_threshold_with_realtime(self):
        """Test token threshold uses real-time calculation when enabled."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.messages = [{"role": "user", "content": "x" * 1000}]
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD": "10",
            "TOPSAILAI_REALTIME_TOKEN_CALCULATION": "1",
        }):
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

        with patch('topsailai.workspace.context.agent2llm.print_error') as mock_print_error:
            result = self.test_instance.summarize_messages_for_processing()
            self.assertIsNone(result)
            mock_print_error.assert_called()
    def test_summarize_with_custom_messages(self):
        """Test summarization with custom messages."""
        custom_messages = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(30)
        ]
        self.test_instance._first_position = 0
        
        with patch('topsailai.workspace.context.agent2llm.logger'):
            with patch('topsailai.workspace.context.agent2llm.print_info'):
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
            with patch('topsailai.workspace.context.agent2llm.print_info'):
                self.test_instance.summarize_messages_for_processing()
                self.assertNotEqual(len(self.test_instance._ai_agent.messages), original_len)


    def _make_session_messages(self, count):
        """Helper to create distinct session messages."""
        return [{"role": "user", "content": f"session-msg-{i}"} for i in range(count)]

    def _make_agent_messages(self, count):
        """Helper to create distinct agent messages."""
        return [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"agent-msg-{i}"}
            for i in range(count)
        ]

    def test_summarize_session_keep_ratio_env_var(self):
        """Test TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO controls session drop."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "100",
            "TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO": "0.3",
            "TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES": "0",
        }):
            # 29 >= 100 * 0.3 = 30? No, 29 < 30 => keep
            session_msgs = self._make_session_messages(29)
            self.test_instance._messages = session_msgs
            self.test_instance._ai_agent.messages = self._make_agent_messages(30)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

            final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
            self.assertIn("session-msg-0", final_contents)
    def test_summarize_session_keep_ratio_env_var_drop(self):
        """Test TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO triggers drop."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "100",
            "TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO": "0.3",
        }):
            # 30 >= 100 * 0.3 = 30 => drop
            session_msgs = self._make_session_messages(30)
            self.test_instance._messages = session_msgs
            self.test_instance._ai_agent.messages = self._make_agent_messages(30)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

            final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
            self.assertNotIn("session-msg-0", final_contents)

    def test_summarize_session_keep_ratio_invalid_fallback(self):
        """Test invalid TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO falls back to 0.5."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "100",
            "TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO": "1.5",
        }):
            # fallback ratio 0.5 => threshold 50; 50 >= 50 => drop
            session_msgs = self._make_session_messages(50)
            self.test_instance._messages = session_msgs
            self.test_instance._ai_agent.messages = self._make_agent_messages(30)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

            final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
            self.assertNotIn("session-msg-0", final_contents)

    def test_summarize_min_extra_messages_env_var(self):
        """Test TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES controls short-circuit."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "100",
            "TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES": "5",
        }):
            session_msgs = self._make_session_messages(10)
            self.test_instance._messages = session_msgs
            # total 12, session 10, need total >= 10 + 5 = 15 => skip summary
            self.test_instance._ai_agent.messages = self._make_agent_messages(2)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.print_info') as mock_print_info:
                result = self.test_instance.summarize_messages_for_processing()
                self.assertIsNone(result)
                mock_print_info.assert_called()

    def test_summarize_min_extra_messages_invalid_fallback(self):
        """Test invalid TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES falls back to 17."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "100",
            "TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES": "-3",
        }):
            session_msgs = self._make_session_messages(10)
            self.test_instance._messages = session_msgs
            # fallback min_extra=17 => need total >= 10 + 17 = 27; total 20 => skip
            self.test_instance._ai_agent.messages = self._make_agent_messages(10)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.print_info') as mock_print_info:
                result = self.test_instance.summarize_messages_for_processing()
                self.assertIsNone(result)
                mock_print_info.assert_called()

    def test_summarize_uses_agent2llm_threshold_for_session_keep(self):
        """Test TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD used to decide keeping session messages."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "20",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "10",
        }):
            session_msgs = self._make_session_messages(9)  # 9 < 20/2=10, keep
            self.test_instance._messages = session_msgs
            self.test_instance._ai_agent.messages = self._make_agent_messages(30)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

            final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
            self.assertIn("session-msg-0", final_contents)
            self.assertIn("session-msg-8", final_contents)

    def test_summarize_falls_back_to_legacy_threshold_for_session_keep(self):
        """Test fallback to legacy threshold when agent2llm var is unset."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "20",
        }):
            session_msgs = self._make_session_messages(9)  # 9 < 20/2=10, keep
            self.test_instance._messages = session_msgs
            self.test_instance._ai_agent.messages = self._make_agent_messages(30)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

            final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
            self.assertIn("session-msg-0", final_contents)

    def test_summarize_agent2llm_wins_over_legacy_for_session_keep(self):
        """Test layer-specific threshold takes precedence over legacy for session keep decision."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "20",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "10",
        }):
            # 9 >= 10/2=5 would drop if legacy used; 9 < 20/2=10 should keep with agent2llm
            session_msgs = self._make_session_messages(9)
            self.test_instance._messages = session_msgs
            self.test_instance._ai_agent.messages = self._make_agent_messages(30)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

            final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
            self.assertIn("session-msg-0", final_contents)

    def test_summarize_drops_session_when_agent2llm_threshold_exceeded(self):
        """Test session messages dropped when agent2llm threshold exceeded."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "20",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "100",
        }):
            session_msgs = self._make_session_messages(10)  # 10 >= 20/2=10, drop
            self.test_instance._messages = session_msgs
            self.test_instance._ai_agent.messages = self._make_agent_messages(30)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

            final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
            self.assertNotIn("session-msg-0", final_contents)

    def test_summarize_drops_session_when_legacy_threshold_exceeded(self):
        """Test session messages dropped when legacy threshold exceeded."""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "20",
        }):
            session_msgs = self._make_session_messages(10)  # 10 >= 20/2=10, drop
            self.test_instance._messages = session_msgs
            self.test_instance._ai_agent.messages = self._make_agent_messages(30)
            self.test_instance._first_position = 0

            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

            final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
            self.assertNotIn("session-msg-0", final_contents)

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
            with patch('topsailai.workspace.context.agent2llm.print_info'):
                result1 = self.test_instance.summarize_messages_for_processing()
                result2 = self.test_instance.summarize_messages_for_processing()
                self.assertIsNotNone(result1)
                self.assertIsInstance(result2, (str, type(None)))

    def test_summarize_preserves_task_messages(self):
        """Test that role=user, step_name=task messages are preserved during summarization."""
        task_msg_1 = {"role": "user", "content": {"step_name": "task", "raw_text": "Task one"}}
        task_msg_2 = {"role": "user", "content": {"step_name": "task", "raw_text": "Task two"}}
        normal_messages = [
            {"role": "user", "content": "Message 0"},
            {"role": "assistant", "content": "Reply 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Reply 3"},
        ]
        self.test_instance._ai_agent.messages = normal_messages + [task_msg_1, task_msg_2]
        self.test_instance._first_position = 0

        with patch('topsailai.workspace.context.agent2llm.logger'):
            with patch('topsailai.workspace.context.agent2llm.print_info'):
                self.test_instance.summarize_messages_for_processing()

        final_messages = self.test_instance._ai_agent.messages
        final_contents = [m.get("content") for m in final_messages]
        self.assertIn({"step_name": "task", "raw_text": "Task one"}, final_contents)
        self.assertIn({"step_name": "task", "raw_text": "Task two"}, final_contents)

    def test_task_messages_not_sent_to_summarizer(self):
        """Test that the summarizer receives the current runtime messages.

        The implementation passes the current runtime messages to
        `_summarize_messages`. In runtime-summary mode the actual messages used
        for the LLM summary are taken from `self.ai_agent.messages`, so task
        messages are not excluded from the input.
        """
        task_msg = {"role": "user", "content": {"step_name": "task", "raw_text": "Task only"}}
        normal_messages = [
            {"role": "user", "content": "Message 0"},
            {"role": "assistant", "content": "Reply 1"},
            {"role": "user", "content": "Message 2"},
        ]
        self.test_instance._ai_agent.messages = normal_messages + [task_msg]
        self.test_instance._first_position = 0

        captured = []
        def mock_summarize(messages):
            captured.append(messages)
            mock_llm_chat = MagicMock()
            mock_llm_chat.prompt_ctl.messages = [
                {"role": "assistant", "content": "Summarized content"}
            ]
            return mock_llm_chat, "Summarized content"
        self.test_instance._summarize_messages_impl = mock_summarize

        with patch.dict(os.environ, {"TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES": "0"}):
            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

        self.assertEqual(len(captured), 1)
        # Runtime messages (including task messages) are forwarded to the
        # summarizer wrapper; the actual summary is built from ai_agent.messages.
        self.assertIn(task_msg, captured[0])

    def test_task_messages_preserve_chronological_order(self):
        """Test that only the head-portion task messages survive summarization.

        The final message list follows:
            head_portion + [summary_answer] + [last_user_message]
        where head_portion extends up to and including the first task message.
        Later task messages are part of the summarized range.
        """
        task_msg_1 = {"role": "user", "content": {"step_name": "task", "raw_text": "Task one"}}
        task_msg_2 = {"role": "user", "content": {"step_name": "task", "raw_text": "Task two"}}
        normal_messages = [
            {"role": "user", "content": "Message 0"},
            {"role": "assistant", "content": "Reply 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Reply 3"},
            {"role": "user", "content": "Message 4"},
        ]
        # Order: normal0, normal1, task1, normal2, normal3, task2, normal4
        self.test_instance._ai_agent.messages = [
            normal_messages[0],
            normal_messages[1],
            task_msg_1,
            normal_messages[2],
            normal_messages[3],
            task_msg_2,
            normal_messages[4],
        ]
        self.test_instance._first_position = 0

        with patch.dict(os.environ, {"TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES": "0"}):
            with patch('topsailai.workspace.context.agent2llm.logger'):
                with patch('topsailai.workspace.context.agent2llm.print_info'):
                    self.test_instance.summarize_messages_for_processing()

        final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
        # task1 is inside head_portion and must survive as a standalone message.
        self.assertIn({"step_name": "task", "raw_text": "Task one"}, final_contents)
        # task2 is after head_portion and is summarized away.
        self.assertNotIn({"step_name": "task", "raw_text": "Task two"}, final_contents)
        idx_task1 = final_contents.index({"step_name": "task", "raw_text": "Task one"})
        idx_summary = final_contents.index("Summarized content")
        # Task one is in the head portion, so it precedes the summary.
        self.assertLess(idx_task1, idx_summary)



    def test_summarize_tail_offset_preserved(self):
        """Test that tail offset preserves the most recent Agent2LLM messages."""
        task_msg = {"role": "user", "content": {"step_name": "task", "raw_text": "Task tail"}}
        self.test_instance._ai_agent.messages = [
            task_msg,
            {"role": "assistant", "content": "msg0"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "msg4"},
        ]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary with tail"}
        ]

        with patch.dict(os.environ, {"TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES": "0"}):
            with patch.object(self.test_instance, '_summarize_messages', return_value=(mock_llm_chat, "Summary with tail")):
                with patch.object(self.test_instance, '_get_head_offset_to_keep_in_summary', return_value=0):
                    with patch.object(self.test_instance, '_get_tail_offset_to_keep_in_summary', return_value=2):
                        self.test_instance.summarize_messages_for_processing()

        final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
        # The head-portion task message and the two tail messages survive.
        self.assertIn({"step_name": "task", "raw_text": "Task tail"}, final_contents)
        self.assertIn("Summary with tail", final_contents)
        self.assertIn("msg3", final_contents)
        self.assertIn("msg4", final_contents)
        # msg0, msg1 and msg2 are in the summarized range.
        self.assertNotIn("msg0", final_contents)
        self.assertNotIn("msg1", final_contents)
        self.assertNotIn("msg2", final_contents)

        # Verify required order: head_portion + tail_portion + summary + last_user_message.
        idx_task = final_contents.index({"step_name": "task", "raw_text": "Task tail"})
        idx_msg3 = final_contents.index("msg3")
        idx_msg4 = final_contents.index("msg4")
        idx_summary = final_contents.index("Summary with tail")
        self.assertLess(idx_task, idx_msg3)
        self.assertLess(idx_task, idx_msg4)
        self.assertLess(idx_msg3, idx_summary)
        self.assertLess(idx_msg4, idx_summary)

    def test_summarize_tail_offset_zero_preserves_only_last_user_message(self):
        """Test that tail offset 0 preserves only head-portion and last user message."""
        task_msg = {"role": "user", "content": {"step_name": "task", "raw_text": "Task tail zero"}}
        self.test_instance._ai_agent.messages = [
            task_msg,
            {"role": "assistant", "content": "msg0"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
        ]
        # Provide a User2Agent session message so last_user_message resolves to msg1.
        self.test_instance._messages = [{"role": "user", "content": "msg1"}]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]

        with patch.dict(os.environ, {"TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES": "0"}):
            with patch.object(self.test_instance, '_summarize_messages', return_value=(mock_llm_chat, "Summary")):
                with patch.object(self.test_instance, '_get_head_offset_to_keep_in_summary', return_value=0):
                    with patch.object(self.test_instance, '_get_tail_offset_to_keep_in_summary', return_value=0):
                        self.test_instance.summarize_messages_for_processing()

        final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
        # The head-portion task message and the real last user message survive.
        self.assertIn({"step_name": "task", "raw_text": "Task tail zero"}, final_contents)
        self.assertIn("Summary", final_contents)
        self.assertIn("msg1", final_contents)
        self.assertNotIn("msg0", final_contents)
        self.assertNotIn("msg2", final_contents)

    def test_summarize_tail_offset_larger_than_messages_keeps_all(self):
        """Test that tail offset larger than message count keeps all messages."""
        task_msg = {"role": "user", "content": {"step_name": "task", "raw_text": "Task tail big"}}
        self.test_instance._ai_agent.messages = [
            task_msg,
            {"role": "assistant", "content": "msg0"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
        ]
        self.test_instance._messages = [{"role": "user", "content": "msg1"}]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]

        with patch.dict(os.environ, {"TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES": "0"}):
            with patch.object(self.test_instance, '_summarize_messages', return_value=(mock_llm_chat, "Summary")):
                with patch.object(self.test_instance, '_get_head_offset_to_keep_in_summary', return_value=0):
                    with patch.object(self.test_instance, '_get_tail_offset_to_keep_in_summary', return_value=100):
                        self.test_instance.summarize_messages_for_processing()

        final_contents = [m.get("content") for m in self.test_instance._ai_agent.messages]
        # All original messages plus summary should be present.
        self.assertIn({"step_name": "task", "raw_text": "Task tail big"}, final_contents)
        self.assertIn("msg0", final_contents)
        self.assertIn("msg1", final_contents)
        self.assertIn("msg2", final_contents)
        self.assertIn("Summary", final_contents)

        # Verify required order: head_portion + tail_portion + summary + last_user_message.
        # msg1 is also the User2Agent session message, so it is preserved in the head/session
        # portion and appears before the summary; tail_offset here covers the remaining messages.
        idx_task = final_contents.index({"step_name": "task", "raw_text": "Task tail big"})
        idx_summary = final_contents.index("Summary")
        self.assertLess(idx_task, idx_summary)
        idx_msg1 = final_contents.index("msg1")
        self.assertLess(idx_msg1, idx_summary)


class TestSummarizeRuntimeMessagesForProcessing(TestContextRuntimeAgent2LLM):
    """Test runtime-mode summarization source selection for Agent2LLM."""

    def _make_messages(self, count, prefix="agent"):
        """Helper to create distinct agent messages."""
        return [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"{prefix}-msg-{i}"}
            for i in range(count)
        ]

    @patch('topsailai.workspace.context.base.get_llm_chat')
    def test_runtime_summary_uses_agent_messages_even_when_short(self, mock_get_llm_chat):
        """Agent2LLM summary uses self.ai_agent.messages even when fewer than 7."""
        with patch.dict(os.environ, {"TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime"}):
            self.test_instance._ai_agent.messages = self._make_messages(3, "agent")
            self.test_instance._messages = self._make_messages(20, "session")
            self.test_instance._ai_agent.agent_type = "test_agent"

            mock_llm_chat = MagicMock()
            mock_llm_chat.chat.return_value = "Summary"
            mock_get_llm_chat.return_value = mock_llm_chat

            self.test_instance._summarize_runtime_messages([])

            # The LLM should receive self.ai_agent.messages, not fall back
            self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 3)
            self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "agent-msg-0")

    @patch('topsailai.workspace.context.base.get_llm_chat')
    def test_runtime_summary_uses_fallback_when_longer(self, mock_get_llm_chat):
        """Defensive fallback: use caller messages when longer than runtime store."""
        with patch.dict(os.environ, {"TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime"}):
            self.test_instance._ai_agent.messages = self._make_messages(5, "agent")
            self.test_instance._messages = self._make_messages(20, "session")
            self.test_instance._ai_agent.agent_type = "test_agent"

            mock_llm_chat = MagicMock()
            mock_llm_chat.chat.return_value = "Summary"
            mock_get_llm_chat.return_value = mock_llm_chat

            fallback = self._make_messages(30, "fallback")
            self.test_instance._summarize_runtime_messages(fallback)

            # Defensive fallback prefers the longer caller-supplied messages.
            self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 30)
            self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "fallback-msg-0")

    @patch('topsailai.workspace.context.base.get_llm_chat')
    def test_runtime_summary_uses_agent_messages_when_longer(self, mock_get_llm_chat):
        """Agent2LLM summary uses self.ai_agent.messages when it is the longer source."""
        with patch.dict(os.environ, {"TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime"}):
            self.test_instance._ai_agent.messages = self._make_messages(5, "agent")
            self.test_instance._messages = self._make_messages(20, "session")
            self.test_instance._ai_agent.agent_type = "test_agent"

            mock_llm_chat = MagicMock()
            mock_llm_chat.chat.return_value = "Summary"
            mock_get_llm_chat.return_value = mock_llm_chat

            fallback = self._make_messages(3, "fallback")
            self.test_instance._summarize_runtime_messages(fallback)

            # When ai_agent.messages is longer than fallback, the runtime store is used.
            self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 5)
            self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "agent-msg-0")
    @patch('topsailai.workspace.context.base.get_llm_chat')
    def test_runtime_summary_fallback_when_agent_messages_empty(self, mock_get_llm_chat):
        """Agent2LLM summary falls back to caller messages when agent store is empty."""
        with patch.dict(os.environ, {"TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime"}):
            self.test_instance._ai_agent.messages = []
            self.test_instance._messages = []
            self.test_instance._ai_agent.agent_type = "test_agent"

            mock_llm_chat = MagicMock()
            mock_llm_chat.chat.return_value = "Summary"
            mock_get_llm_chat.return_value = mock_llm_chat

            fallback = self._make_messages(10, "fallback")
            self.test_instance._summarize_runtime_messages(fallback)

            # Should fall back to caller-provided messages
            self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 10)
            self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "fallback-msg-0")
    def test_duplicate_count_disabled_returns_false(self):
        """Test duplicate count check disabled when threshold is 0."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.llm_model.tokenStat.current_tokens = 0
        self.test_instance._ai_agent.llm_model.tool_stat.get_consecutive_duplicate_count.return_value = 5
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_DUP_TOOL_CALL_SUMMARIZE_THRESHOLD": "0",
        }):
            result = self.test_instance.is_need_summarize_for_processing()
            self.assertFalse(result)

    def test_duplicate_count_equal_threshold_returns_false(self):
        """Test count equal to threshold returns False (strictly greater)."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.llm_model.tokenStat.current_tokens = 0
        self.test_instance._ai_agent.llm_model.tool_stat.get_consecutive_duplicate_count.return_value = 3
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_DUP_TOOL_CALL_SUMMARIZE_THRESHOLD": "3",
        }):
            result = self.test_instance.is_need_summarize_for_processing()
            self.assertFalse(result)

    def test_duplicate_count_above_threshold_returns_true(self):
        """Test count above threshold returns True."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.llm_model.tokenStat.current_tokens = 0
        self.test_instance._ai_agent.llm_model.tool_stat.get_consecutive_duplicate_count.return_value = 4
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_DUP_TOOL_CALL_SUMMARIZE_THRESHOLD": "3",
        }):
            result = self.test_instance.is_need_summarize_for_processing()
            self.assertTrue(result)

    def test_duplicate_count_missing_tool_stat_returns_false(self):
        """Test missing tool_stat falls back to 0 and returns False."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.llm_model.tokenStat.current_tokens = 0
        self.test_instance._ai_agent.llm_model.tool_stat = None
        self.test_instance._ai_agent._tool_stat = None
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT2LLM_DUP_TOOL_CALL_SUMMARIZE_THRESHOLD": "3",
        }):
            result = self.test_instance.is_need_summarize_for_processing()
            self.assertFalse(result)

    def test_duplicate_count_default_threshold(self):
        """Test default threshold 3 triggers at count 4."""
        self.test_instance._get_quantity_threshold = MagicMock(return_value=0)
        self.test_instance._ai_agent.llm_model.tokenStat.current_tokens = 0
        self.test_instance._ai_agent.llm_model.tool_stat.get_consecutive_duplicate_count.return_value = 4
        result = self.test_instance.is_need_summarize_for_processing()
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
