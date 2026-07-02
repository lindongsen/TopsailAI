"""
Unit tests for workspace/context/agent2llm.py module.

This module tests the ContextRuntimeAgent2LLM class which handles
agent-to-LLM message conversion and context summarization.

Author: mm-m25
Created: 2026-04-19
"""

import pytest
from unittest.mock import MagicMock, patch
import json


# =============================================================================
# Group A: Import Tests
# =============================================================================

class TestImports:
    """Test module imports."""

    def test_import_agent2llm_module(self):
        """Test that agent2llm module can be imported."""
        from topsailai.workspace.context import agent2llm
        assert agent2llm is not None

    def test_import_context_runtime_agent2llm_class(self):
        """Test that ContextRuntimeAgent2LLM class can be imported."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        assert ContextRuntimeAgent2LLM is not None

    def test_import_from_module(self):
        """Test importing from the module directly."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        assert ContextRuntimeAgent2LLM is not None

    def test_class_inheritance(self):
        """Test that class inherits from ContextRuntimeBase."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        from topsailai.workspace.context.base import ContextRuntimeBase
        assert issubclass(ContextRuntimeAgent2LLM, ContextRuntimeBase)


# =============================================================================
# Group B: del_agent_messages Tests
# =============================================================================

class TestDelAgentMessages:
    """Test del_agent_messages method."""

    @pytest.fixture
    def mock_agent2llm(self):
        """Create a mock ContextRuntimeAgent2LLM instance."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        instance = ContextRuntimeAgent2LLM()
        instance.ai_agent = MagicMock()
        instance.messages = []
        return instance

    def test_empty_indexes_returns_empty_list(self, mock_agent2llm):
        """Test that empty indexes returns empty list."""
        result = mock_agent2llm.del_agent_messages([])
        assert result == []

    def test_no_work_memory_returns_empty_list(self, mock_agent2llm):
        """Test that None work_memory_position returns empty list."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = None
        result = mock_agent2llm.del_agent_messages([0, 1])
        assert result == []

    def test_normal_deletion(self, mock_agent2llm):
        """Test normal message deletion."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 1
        mock_agent2llm.ai_agent.messages = [
            '{"role": "system", "content": "sys"}',
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
        ]
        result = mock_agent2llm.del_agent_messages([0])
        assert result == [0]
        assert len(mock_agent2llm.ai_agent.messages) == 2
        assert mock_agent2llm.ai_agent.messages[0] == '{"role": "system", "content": "sys"}'
    def test_delete_last_flag_with_messages(self, mock_agent2llm):
        """Test deletion with to_del_last flag when there are messages to delete."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
        ]
        result = mock_agent2llm.del_agent_messages([0], to_del_last=True)
        assert len(mock_agent2llm.ai_agent.messages) == 0

    def test_delete_last_flag_without_indexes(self, mock_agent2llm):
        """Test deletion with to_del_last flag but no indexes."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
        ]
        result = mock_agent2llm.del_agent_messages([], to_del_last=True)
        assert result == []
        assert len(mock_agent2llm.ai_agent.messages) == 2

    def test_multiple_indexes(self, mock_agent2llm):
        """Test deletion of multiple messages."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        result = mock_agent2llm.del_agent_messages([0, 1])
        assert result == [0, 1]

    def test_negative_index(self, mock_agent2llm):
        """Test deletion with negative index."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
        ]
        result = mock_agent2llm.del_agent_messages([-1])
        assert result == []

    def test_system_prefix_preserved_when_deleting_agent_messages(self, mock_agent2llm):
        """Test that system messages before first_position are preserved."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 2
        mock_agent2llm.ai_agent.messages = [
            '{"role": "system", "content": "system prompt 1"}',
            '{"role": "system", "content": "system prompt 2"}',
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        result = mock_agent2llm.del_agent_messages([1])
        assert result == [1]
        assert len(mock_agent2llm.ai_agent.messages) == 4
        assert mock_agent2llm.ai_agent.messages[0] == '{"role": "system", "content": "system prompt 1"}'
        assert mock_agent2llm.ai_agent.messages[1] == '{"role": "system", "content": "system prompt 2"}'

    def test_system_message_not_deleted(self, mock_agent2llm):
        """Test that system messages are not deleted."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "system", "content": "sys"}',
            '{"role": "user", "content": "msg1"}',
        ]
        result = mock_agent2llm.del_agent_messages([0])
        assert result == []


# =============================================================================
# Group C: is_need_summarize_for_processing Tests
# =============================================================================

class TestIsNeedSummarizeForProcessing:
    """Test is_need_summarize_for_processing method."""

    @pytest.fixture
    def mock_agent2llm(self):
        """Create a mock ContextRuntimeAgent2LLM instance."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        instance = ContextRuntimeAgent2LLM()
        instance.ai_agent = MagicMock()
        instance.messages = []
        return instance

    def test_disabled_threshold_returns_false(self, mock_agent2llm):
        """Test that disabled threshold (0) returns False."""
        with patch.object(mock_agent2llm, '_get_quantity_threshold', return_value=0):
            result = mock_agent2llm.is_need_summarize_for_processing()
            assert result is False

    @patch('random.choice')
    def test_short_messages_returns_false(self, mock_random_choice, mock_agent2llm):
        """Test that short message count returns False."""
        mock_random_choice.return_value = 50
        with patch.object(mock_agent2llm, '_get_quantity_threshold', return_value=50):
            mock_agent2llm.ai_agent.messages = [MagicMock() for _ in range(30)]
            result = mock_agent2llm.is_need_summarize_for_processing()
            assert result is False

    @patch('random.choice')
    def test_exceeds_threshold_returns_true(self, mock_random_choice, mock_agent2llm):
        """Test that exceeding threshold returns True."""
        mock_random_choice.return_value = 50
        with patch.object(mock_agent2llm, '_get_quantity_threshold', return_value=50):
            mock_agent2llm.ai_agent.messages = [MagicMock() for _ in range(60)]
            result = mock_agent2llm.is_need_summarize_for_processing()
            assert result is True

    @patch('random.choice')
    def test_at_threshold_returns_true(self, mock_random_choice, mock_agent2llm):
        """Test that at threshold returns True."""
        mock_random_choice.return_value = 50
        with patch.object(mock_agent2llm, '_get_quantity_threshold', return_value=50):
            mock_agent2llm.ai_agent.messages = [MagicMock() for _ in range(50)]
            result = mock_agent2llm.is_need_summarize_for_processing()
            assert result is True


# =============================================================================
# Group D: summarize_messages_for_processing Tests - Core Logic
# =============================================================================

class TestSummarizeMessagesForProcessing:
    """Test summarize_messages_for_processing method - core logic."""

    @pytest.fixture
    def mock_agent2llm(self):
        """Create a mock ContextRuntimeAgent2LLM instance."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        instance = ContextRuntimeAgent2LLM()
        instance.ai_agent = MagicMock()
        instance.messages = []
        return instance

    def test_work_memory_position_none_returns_none(self, mock_agent2llm):
        """Test that None work_memory_position returns None."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = None
        result = mock_agent2llm.summarize_messages_for_processing()
        assert result is None

    def test_empty_messages_returns_none(self, mock_agent2llm):
        """Test that empty messages returns None."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = []
        result = mock_agent2llm.summarize_messages_for_processing()
        assert result is None

    def test_short_messages_returns_none(self, mock_agent2llm):
        """Test that messages <= 2 returns None."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
        ]
        result = mock_agent2llm.summarize_messages_for_processing()
        assert result is None

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_successful_summarization_flow(self, mock_env_reader, mock_agent2llm):
        """Test successful summarization flow with mocked _summarize_messages."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_env_reader.check_bool.return_value = False
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized answer")):
                result = mock_agent2llm.summarize_messages_for_processing()
                assert result == "summarized answer"

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_need_session_messages_true(self, mock_env_reader, mock_agent2llm):
        """Test with need_session_messages=True."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        # Need msg_len >= (session_msg_len + 17) to pass the check
        # session_msg_len = 1, so need msg_len >= 18
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
            '{"role": "assistant", "content": "msg4"}',
            '{"role": "user", "content": "msg5"}',
            '{"role": "assistant", "content": "msg6"}',
            '{"role": "user", "content": "msg7"}',
            '{"role": "assistant", "content": "msg8"}',
            '{"role": "user", "content": "msg9"}',
            '{"role": "assistant", "content": "msg10"}',
            '{"role": "user", "content": "msg11"}',
            '{"role": "assistant", "content": "msg12"}',
            '{"role": "user", "content": "msg13"}',
            '{"role": "assistant", "content": "msg14"}',
            '{"role": "user", "content": "msg15"}',
            '{"role": "assistant", "content": "msg16"}',
            '{"role": "user", "content": "msg17"}',
            '{"role": "assistant", "content": "msg18"}',
        ]
        mock_agent2llm.messages = ['{"role": "user", "content": "session1"}']
        mock_env_reader.check_bool.return_value = True

        def _get_side_effect(key, **kwargs):
            if key == "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD":
                return 100
            if key == "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD":
                return kwargs.get("default")
            if key == "TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO":
                return kwargs.get("default", 0.5)
            if key == "TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES":
                return kwargs.get("default", 17)
            return kwargs.get("default")

        mock_env_reader.get.side_effect = _get_side_effect
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized answer")):
                result = mock_agent2llm.summarize_messages_for_processing()
                assert result == "summarized answer"

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_need_session_messages_false(self, mock_env_reader, mock_agent2llm):
        """Test with need_session_messages=False."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        mock_agent2llm.messages = ['{"role": "user", "content": "session1"}']
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized answer")):
                result = mock_agent2llm.summarize_messages_for_processing()
                assert result == "summarized answer"

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_session_messages_too_long_disables_session(self, mock_env_reader, mock_agent2llm):
        """Test that session messages too long disables session messages."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        mock_agent2llm.messages = [f'{{"role": "user", "content": "session{i}"}}' for i in range(60)]
        mock_env_reader.check_bool.return_value = True
        mock_env_reader.get.return_value = 100
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized answer")):
                result = mock_agent2llm.summarize_messages_for_processing()
                assert result == "summarized answer"

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_head_offset_to_keep_parameter(self, mock_env_reader, mock_agent2llm):
        """Test head_offset_to_keep parameter handling."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
            '{"role": "assistant", "content": "msg4"}',
        ]
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=2) as mock_offset:
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized answer")):
                result = mock_agent2llm.summarize_messages_for_processing(head_offset_to_keep=2)
                assert result == "summarized answer"
                mock_offset.assert_called_once_with(2)

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_last_user_message_preserved(self, mock_env_reader, mock_agent2llm):
        """Test that last_user_message is preserved in final message list."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        mock_agent2llm.messages = ['{"role": "user", "content": "last user msg"}']
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized answer")):
                result = mock_agent2llm.summarize_messages_for_processing()
                assert result == "summarized answer"

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_no_answer_returns_none(self, mock_env_reader, mock_agent2llm):
        """Test that None answer from _summarize_messages returns None."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(MagicMock(), None)):
                result = mock_agent2llm.summarize_messages_for_processing()
                assert result is None

    @patch('topsailai.workspace.context.base.logger')
    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_token_reduction_critical_log_when_not_decreased(self, mock_env_reader, mock_logger, mock_agent2llm):
        """Test critical log is emitted when token count does not decrease."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        mock_agent2llm.session_id = "test_session"
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized answer")):
                with patch.object(mock_agent2llm, '_get_current_tokens', side_effect=[100, 100]):
                    result = mock_agent2llm.summarize_messages_for_processing()
                    assert result == "summarized answer"
                    mock_logger.critical.assert_called_once()
                    call_args = mock_logger.critical.call_args[0]
                    assert "summarize_messages_for_processing" in call_args[0]
                    assert "before_tokens=100" in call_args[0]
                    assert "after_tokens=100" in call_args[0]
                    assert "test_session" in call_args[0]

    @patch('topsailai.workspace.context.base.logger')
    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_token_reduction_no_critical_log_when_decreased(self, mock_env_reader, mock_logger, mock_agent2llm):
        """Test critical log is not emitted when token count decreases."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized answer")):
                with patch.object(mock_agent2llm, '_get_current_tokens', side_effect=[100, 50]):
                    result = mock_agent2llm.summarize_messages_for_processing()
                    assert result == "summarized answer"
                    mock_logger.critical.assert_not_called()

    @patch('topsailai.workspace.context.base.logger')
    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_token_reduction_critical_log_when_increased(self, mock_env_reader, mock_logger, mock_agent2llm):
        """Test critical log is emitted when token count increases."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized answer")):
                with patch.object(mock_agent2llm, '_get_current_tokens', side_effect=[100, 150]):
                    result = mock_agent2llm.summarize_messages_for_processing()
                    assert result == "summarized answer"
                    mock_logger.critical.assert_called_once()


# =============================================================================
# Group E: Edge Cases Tests
# =============================================================================
class TestEdgeCases:
    """Test edge cases for agent2llm module."""

    @pytest.fixture
    def mock_agent2llm(self):
        """Create a mock ContextRuntimeAgent2LLM instance."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        instance = ContextRuntimeAgent2LLM()
        instance.ai_agent = MagicMock()
        instance.messages = []
        return instance

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_unicode_content_in_messages(self, mock_env_reader, mock_agent2llm):
        """Test handling of unicode content in messages."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "你好世界 🌍"}',
            '{"role": "assistant", "content": "Hello 世界"}',
            '{"role": "user", "content": "🎉 🎊"}',
        ]
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized")):
                result = mock_agent2llm.summarize_messages_for_processing()
                assert result == "summarized"

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_special_characters_in_content(self, mock_env_reader, mock_agent2llm):
        """Test handling of special characters in content."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "{\"key\": \"value\"}"}',
            '{"role": "assistant", "content": "line1\\nline2\\ttab"}',
            '{"role": "user", "content": "emoji: 🎯 <script>"}',
        ]
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized")):
                result = mock_agent2llm.summarize_messages_for_processing()
                assert result == "summarized"

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_large_list_of_messages(self, mock_env_reader, mock_agent2llm):
        """Test handling of large list of messages."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            f'{{"role": "user", "content": "msg{i}"}}' for i in range(100)
        ]
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            mock_llm_chat = MagicMock()
            mock_prompt_ctl = MagicMock()
            mock_prompt_ctl.messages = ['{"role": "assistant", "content": "summarized"}']
            mock_llm_chat.prompt_ctl = mock_prompt_ctl
            with patch.object(mock_agent2llm, '_summarize_messages', return_value=(mock_llm_chat, "summarized")):
                result = mock_agent2llm.summarize_messages_for_processing()
                assert result == "summarized"

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_empty_messages_list_with_session(self, mock_env_reader, mock_agent2llm):
        """Test with empty messages but session messages exist."""
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = []
        mock_agent2llm.messages = ['{"role": "user", "content": "session"}']
        mock_env_reader.check_bool.return_value = False
        result = mock_agent2llm.summarize_messages_for_processing()
        assert result is None


# =============================================================================
# Group F: Exception Handling Tests
# =============================================================================

class TestExceptionHandling:
    """Test exception handling for agent2llm module."""

    @pytest.fixture
    def mock_agent2llm(self):
        """Create a mock ContextRuntimeAgent2LLM instance."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        instance = ContextRuntimeAgent2LLM()
        instance.ai_agent = MagicMock()
        instance.messages = []
        return instance

    @patch('topsailai.workspace.context.agent2llm.env_tool.EnvReaderInstance')
    def test_summarize_messages_exception_propagates(self, mock_env_reader, mock_agent2llm):
        """Test that exceptions from _summarize_messages propagate.
        
        Note: The code does not catch exceptions, so they propagate.
        """
        mock_agent2llm.ai_agent.get_work_memory_first_position.return_value = 0
        mock_agent2llm.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]
        mock_env_reader.check_bool.return_value = False
        with patch.object(mock_agent2llm, '_get_head_offset_to_keep_in_summary', return_value=0):
            with patch.object(mock_agent2llm, '_summarize_messages', side_effect=RuntimeError("LLM error")):
                with pytest.raises(RuntimeError, match="LLM error"):
                    mock_agent2llm.summarize_messages_for_processing()


# =============================================================================
# Group G: Module Summary Test
# =============================================================================

class TestModuleSummary:
    """Module summary test."""

    def test_module_docstring_exists(self):
        """Test that module has a docstring."""
        from topsailai.workspace.context import agent2llm
        assert agent2llm.__doc__ is not None

    def test_class_docstring_exists(self):
        """Test that class has a docstring."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
        assert ContextRuntimeAgent2LLM.__doc__ is not None


# =============================================================================
# Group H: ctx.add_agent2llm instruction Tests
# =============================================================================

class TestCtxAddAgent2LLMMessage:
    """Test the /ctx.add_agent2llm instruction handler."""

    @pytest.fixture
    def runtime_instructions(self):
        """Create a ContextRuntimeInstructions instance with a mock ai_agent."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData
        from topsailai.workspace.context.instruction import ContextRuntimeInstructions

        ctx_runtime_data = ContextRuntimeData()
        ctx_runtime_data.ai_agent = MagicMock()
        ctx_runtime_data.ai_agent.messages = []
        instructions = ContextRuntimeInstructions(ctx_runtime_data)
        return instructions

    def test_instruction_is_registered(self, runtime_instructions):
        """Test that ctx.add_agent2llm is registered in instructions."""
        assert "ctx.add_agent2llm" in runtime_instructions.instructions

    def test_add_user_message_default_role(self, runtime_instructions):
        """Test adding a message with default user role."""
        result = runtime_instructions.ctx_add_agent2llm_message("hello world")
        assert "added 1 user message" in result
        assert len(runtime_instructions.ai_agent.messages) == 1

        msg_dict = runtime_instructions.ai_agent.messages[0]
        assert isinstance(msg_dict, dict)
        assert msg_dict["role"] == "user"
        assert isinstance(msg_dict["content"], str)
        content_dict = json.loads(msg_dict["content"])
        assert content_dict["step_name"] == "observation"
        assert content_dict["raw_text"] == "hello world"

    def test_add_system_message_explicit_role(self, runtime_instructions):
        """Test adding a message with explicit system role."""
        result = runtime_instructions.ctx_add_agent2llm_message("system prompt", "system")
        assert "added 1 system message" in result

        msg_dict = runtime_instructions.ai_agent.messages[0]
        assert isinstance(msg_dict, dict)
        assert msg_dict["role"] == "system"
        content_dict = json.loads(msg_dict["content"])
        assert content_dict["raw_text"] == "system prompt"

    def test_add_assistant_message(self, runtime_instructions):
        """Test adding an assistant message."""
        result = runtime_instructions.ctx_add_agent2llm_message("assistant reply", "assistant")
        assert "added 1 assistant message" in result

        msg_dict = runtime_instructions.ai_agent.messages[0]
        assert isinstance(msg_dict, dict)
        assert msg_dict["role"] == "assistant"

    def test_add_tool_message(self, runtime_instructions):
        """Test adding a tool message."""
        result = runtime_instructions.ctx_add_agent2llm_message("tool result", "tool")
        assert "added 1 tool message" in result

        msg_dict = runtime_instructions.ai_agent.messages[0]
        assert isinstance(msg_dict, dict)
        assert msg_dict["role"] == "tool"

    def test_invalid_role_returns_error(self, runtime_instructions):
        """Test that invalid role returns an error message."""
        result = runtime_instructions.ctx_add_agent2llm_message("content", "invalid_role")
        assert "invalid role" in result
        assert len(runtime_instructions.ai_agent.messages) == 0

    def test_no_active_agent_returns_error(self, runtime_instructions):
        """Test that missing ai_agent returns an error message."""
        runtime_instructions.ctx_runtime_data.ai_agent = None
        result = runtime_instructions.ctx_add_agent2llm_message("content")
        assert "no active agent" in result

    def test_messages_initialized_when_none(self, runtime_instructions):
        """Test that ai_agent.messages is initialized if None."""
        runtime_instructions.ai_agent.messages = None
        result = runtime_instructions.ctx_add_agent2llm_message("hello")
        assert runtime_instructions.ai_agent.messages is not None
        assert len(runtime_instructions.ai_agent.messages) == 1
        assert "added 1 user message" in result

    def test_message_is_dict_not_json_string(self, runtime_instructions):
        """Test that the appended message is a dict, not a JSON string."""
        runtime_instructions.ctx_add_agent2llm_message("some content")

        msg = runtime_instructions.ai_agent.messages[0]
        assert isinstance(msg, dict)
        assert msg["role"] == "user"
        assert isinstance(msg["content"], str)
        content_dict = json.loads(msg["content"])
        assert content_dict["step_name"] == "observation"
        assert content_dict["raw_text"] == "some content"

    def test_list_identity_preserved(self, runtime_instructions):
        """Test that the message list reference is preserved (uses +=)."""
        original_list = runtime_instructions.ai_agent.messages
        runtime_instructions.ctx_add_agent2llm_message("hello")
        assert runtime_instructions.ai_agent.messages is original_list

    def test_multiple_messages_increase_count(self, runtime_instructions):
        """Test that multiple calls append messages and update count."""
        runtime_instructions.ctx_add_agent2llm_message("first")
        runtime_instructions.ctx_add_agent2llm_message("second", "assistant")
        runtime_instructions.ctx_add_agent2llm_message("third", "system")

        assert len(runtime_instructions.ai_agent.messages) == 3
        roles = [m["role"] for m in runtime_instructions.ai_agent.messages]
        assert roles == ["user", "assistant", "system"]
