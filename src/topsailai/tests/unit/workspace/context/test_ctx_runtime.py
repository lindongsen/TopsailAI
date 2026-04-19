"""
Unit tests for workspace/context/ctx_runtime.py module.

This module tests the ContextRuntimeData, ContextRuntimeAgent2LLM, and
ContextRuntimeBase classes for runtime context management.

Author: mm-m25
Created: 2026-04-19
"""

import pytest
from unittest.mock import MagicMock, patch


# ==============================================================================
# Group A: Import Tests
# ==============================================================================

class TestImports:
    """Test module imports."""

    def test_import_ctx_runtime(self):
        """Test that ctx_runtime module can be imported."""
        from topsailai.workspace.context import ctx_runtime
        assert ctx_runtime is not None

    def test_import_context_runtime_data(self):
        """Test ContextRuntimeData class import."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData
        assert ContextRuntimeData is not None

    def test_import_context_runtime_agent2llm(self):
        """Test ContextRuntimeAgent2LLM class import."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeAgent2LLM
        assert ContextRuntimeAgent2LLM is not None

    def test_import_context_runtime_base(self):
        """Test ContextRuntimeBase class import."""
        from topsailai.workspace.context.base import ContextRuntimeBase
        assert ContextRuntimeBase is not None


# ==============================================================================
# Group B: ContextRuntimeBase Tests
# ==============================================================================

class TestContextRuntimeBaseInit:
    """Test ContextRuntimeBase initialization."""

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_init_default_values(self, mock_ctx_manager):
        """Test default initialization values."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()

        assert runtime.session_id == ""
        assert runtime.messages == []
        assert runtime.ai_agent is None

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_init_with_session_id(self, mock_ctx_manager):
        """Test initialization with session_id."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.session_id = "test_session_123"

        assert runtime.session_id == "test_session_123"
        assert runtime.messages == []


class TestContextRuntimeBaseProperties:
    """Test ContextRuntimeBase properties."""

    @patch('topsailai.workspace.context.base.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_last_user_message_with_user_message(self, mock_ctx_manager, mock_json_tool):
        """Test last_user_message property returns last user message."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_json_tool.json_load.side_effect = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
        ]

        runtime = ContextRuntimeBase()
        runtime.messages = [
            '{"role": "user", "content": "Hello"}',
            '{"role": "assistant", "content": "Hi there"}',
            '{"role": "user", "content": "How are you?"}',
        ]

        result = runtime.last_user_message

        assert result == '{"role": "user", "content": "How are you?"}'

    @patch('topsailai.workspace.context.base.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_last_user_message_no_user_message(self, mock_ctx_manager, mock_json_tool):
        """Test last_user_message property returns None when no user message."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_json_tool.json_load.side_effect = [
            {"role": "assistant", "content": "Hi there"},
            {"role": "system", "content": "System prompt"},
        ]

        runtime = ContextRuntimeBase()
        runtime.messages = [
            '{"role": "assistant", "content": "Hi there"}',
            '{"role": "system", "content": "System prompt"}',
        ]

        result = runtime.last_user_message

        assert result is None

    @patch('topsailai.workspace.context.base.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_last_user_message_empty_messages(self, mock_ctx_manager, mock_json_tool):
        """Test last_user_message property returns None for empty messages."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = []

        result = runtime.last_user_message

        assert result is None


class TestContextRuntimeBaseMethods:
    """Test ContextRuntimeBase methods."""

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_init_method(self, mock_ctx_manager):
        """Test init method sets session_id and ai_agent."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        mock_ai_agent = MagicMock()

        runtime.init("session_123", mock_ai_agent)

        assert runtime.session_id == "session_123"
        assert runtime.ai_agent == mock_ai_agent

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_append_message_normal(self, mock_ctx_manager):
        """Test append_message adds message to list."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        message = {"role": "user", "content": "Test message"}

        runtime.append_message(message)

        assert len(runtime.messages) == 1
        assert runtime.messages[0] == message

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_append_message_empty(self, mock_ctx_manager):
        """Test append_message does nothing for empty message."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = ["existing"]

        runtime.append_message(None)
        runtime.append_message({})

        assert len(runtime.messages) == 1

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_set_messages_normal(self, mock_ctx_manager):
        """Test set_messages replaces messages list."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = ["old"]

        new_messages = [{"role": "user", "content": "new"}]
        runtime.set_messages(new_messages)

        assert len(runtime.messages) == 1
        assert runtime.messages[0] == {"role": "user", "content": "new"}

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_set_messages_empty(self, mock_ctx_manager):
        """Test set_messages handles empty list."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = ["old"]

        runtime.set_messages([])

        assert runtime.messages == []

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_set_messages_none(self, mock_ctx_manager):
        """Test set_messages handles None."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = ["old"]

        runtime.set_messages(None)

        assert runtime.messages == []

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_reset_messages_with_session(self, mock_ctx_manager):
        """Test reset_messages retrieves from session storage."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.session_id = "test_session"
        mock_ctx_manager.get_messages_by_session.return_value = [
            {"role": "user", "content": "test"}
        ]

        runtime.reset_messages()

        mock_ctx_manager.get_messages_by_session.assert_called_once_with("test_session")
        assert len(runtime.messages) == 1

    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_reset_messages_no_session(self, mock_ctx_manager):
        """Test reset_messages does nothing without session_id."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.session_id = ""

        runtime.reset_messages()

        mock_ctx_manager.get_messages_by_session.assert_not_called()


class TestContextRuntimeBaseEnvMethods:
    """Test ContextRuntimeBase environment methods."""

    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_get_quantity_threshold_disabled(self, mock_ctx_manager, mock_env_tool):
        """Test _get_quantity_threshold returns 0 when disabled."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = 0

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold()

        assert result == 0

    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_get_quantity_threshold_negative(self, mock_ctx_manager, mock_env_tool):
        """Test _get_quantity_threshold returns 0 for negative value."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = -10

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold()

        assert result == 0

    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_get_quantity_threshold_positive(self, mock_ctx_manager, mock_env_tool):
        """Test _get_quantity_threshold returns positive value."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = 50

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold()

        assert result >= 50

    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_get_head_offset_to_keep_explicit(self, mock_ctx_manager, mock_env_tool):
        """Test _get_head_offset_to_keep_in_summary with explicit value."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        result = runtime._get_head_offset_to_keep_in_summary(5)

        assert result == 5
        mock_env_tool.EnvReaderInstance.get.assert_not_called()

    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_get_head_offset_to_keep_from_env(self, mock_ctx_manager, mock_env_tool):
        """Test _get_head_offset_to_keep_in_summary from environment."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = 10

        runtime = ContextRuntimeBase()
        result = runtime._get_head_offset_to_keep_in_summary(None)

        assert result == 10

    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_get_head_offset_to_keep_negative(self, mock_ctx_manager, mock_env_tool):
        """Test _get_head_offset_to_keep_in_summary handles negative value."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = -5

        runtime = ContextRuntimeBase()
        result = runtime._get_head_offset_to_keep_in_summary(None)

        assert result == 0


# ==============================================================================
# Group C: ContextRuntimeAgent2LLM Tests
# ==============================================================================

class TestContextRuntimeAgent2LLM:
    """Test ContextRuntimeAgent2LLM class methods."""

    @patch('topsailai.workspace.context.agent2llm.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_agent_messages_empty_indexes(self, mock_ctx_manager, mock_json_tool):
        """Test del_agent_messages with empty indexes."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeAgent2LLM

        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.get_work_memory_first_position.return_value = 0
        runtime.ai_agent.messages = []

        result = runtime.del_agent_messages([])

        assert result == []

    @patch('topsailai.workspace.context.agent2llm.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_agent_messages_no_work_memory(self, mock_ctx_manager, mock_json_tool):
        """Test del_agent_messages when work_memory_position is None."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeAgent2LLM

        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.get_work_memory_first_position.return_value = None

        result = runtime.del_agent_messages([0, 1])

        assert result == []

    @patch('topsailai.workspace.context.agent2llm.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_agent_messages_normal(self, mock_ctx_manager, mock_json_tool):
        """Test del_agent_messages deletes specified messages."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeAgent2LLM

        mock_json_tool.json_load.side_effect = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
        ]

        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.get_work_memory_first_position.return_value = 0
        runtime.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]

        result = runtime.del_agent_messages([1])

        assert result == [1]
        assert len(runtime.ai_agent.messages) == 2

    @patch('topsailai.workspace.context.agent2llm.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_agent_messages_with_to_del_last(self, mock_ctx_manager, mock_json_tool):
        """Test del_agent_messages with to_del_last flag removes additional message."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeAgent2LLM

        mock_json_tool.json_load.return_value = {"role": "user", "content": "msg"}

        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.get_work_memory_first_position.return_value = 0
        runtime.ai_agent.messages = [
            '{"role": "user", "content": "msg1"}',
            '{"role": "assistant", "content": "msg2"}',
            '{"role": "user", "content": "msg3"}',
        ]

        result = runtime.del_agent_messages([0], to_del_last=True)

        # to_del_last removes the last message as well when last_index not in indexes
        assert len(runtime.ai_agent.messages) == 1

    @patch('topsailai.workspace.context.agent2llm.json_tool')
    @patch('topsailai.workspace.context.agent2llm.logger')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_is_need_summarize_for_processing_short_messages(
        self, mock_ctx_manager, mock_logger, mock_json_tool
    ):
        """Test is_need_summarize_for_processing with short messages."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeAgent2LLM

        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.messages = ["msg1", "msg2"]

        with patch.object(runtime, '_get_quantity_threshold', return_value=50):
            result = runtime.is_need_summarize_for_processing()

        assert result is False

    @patch('topsailai.workspace.context.agent2llm.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_is_need_summarize_for_processing_threshold_disabled(
        self, mock_ctx_manager, mock_json_tool
    ):
        """Test is_need_summarize_for_processing when threshold is 0."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeAgent2LLM

        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.messages = ["msg"] * 100

        with patch.object(runtime, '_get_quantity_threshold', return_value=0):
            result = runtime.is_need_summarize_for_processing()

        assert result is False


# ==============================================================================
# Group D: ContextRuntimeData Tests
# ==============================================================================

class TestContextRuntimeDataSessionMessages:
    """Test ContextRuntimeData session message methods."""

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_add_session_message_normal(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test add_session_message adds message correctly."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.session_id = "test_session"

        runtime.add_session_message("user", "Hello")

        assert len(runtime.messages) == 1
        assert runtime.messages[0]["role"] == "user"
        assert runtime.messages[0]["content"] == "Hello"
        mock_ctx_manager.add_session_message.assert_called_once()

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_add_session_message_none_role(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test add_session_message uses assistant role when role is None."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.session_id = "test_session"

        runtime.add_session_message(None, "Hello")

        assert runtime.messages[0]["role"] == "assistant"

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_add_session_message_dict_normal(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test add_session_message_dict adds message correctly."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.session_id = "test_session"
        message = {"role": "assistant", "content": "Hi there"}

        runtime.add_session_message_dict(message)

        assert len(runtime.messages) == 1
        assert runtime.messages[0] == message

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_add_session_message_dict_no_session(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test add_session_message_dict without session_id."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.session_id = ""
        message = {"role": "user", "content": "test"}

        runtime.add_session_message_dict(message)

        assert len(runtime.messages) == 1
        mock_ctx_manager.add_session_message.assert_not_called()

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_session_message_normal(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test del_session_message deletes message correctly."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        mock_raw_msg = MagicMock()
        mock_raw_msg.msg_id = "msg_id_1"
        mock_ctx_manager.get_messages_by_session.return_value = [mock_raw_msg]

        runtime = ContextRuntimeData()
        runtime.session_id = "test_session"
        runtime.messages = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
        ]

        runtime.del_session_message(0)

        assert len(runtime.messages) == 1
        mock_ctx_manager.del_session_messages.assert_called_once()

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_session_message_invalid_index(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test del_session_message raises assertion for invalid index."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.messages = [{"role": "user", "content": "msg1"}]

        with pytest.raises(AssertionError, match="nothing can be deleted"):
            runtime.del_session_message(5)

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_session_messages_normal(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test del_session_messages deletes multiple messages."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        mock_raw_msg1 = MagicMock()
        mock_raw_msg1.msg_id = "msg_id_1"
        mock_raw_msg2 = MagicMock()
        mock_raw_msg2.msg_id = "msg_id_2"
        mock_ctx_manager.get_messages_by_session.return_value = [mock_raw_msg1, mock_raw_msg2]

        runtime = ContextRuntimeData()
        runtime.session_id = "test_session"
        runtime.messages = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
        ]

        result = runtime.del_session_messages([0, 2])

        assert result == [0, 2]
        assert len(runtime.messages) == 1

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_session_messages_empty_indexes(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test del_session_messages with empty indexes."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.messages = [{"role": "user", "content": "msg1"}]

        result = runtime.del_session_messages([])

        assert result == []

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_session_messages_skips_system(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test del_session_messages skips system messages."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "msg1"},
        ]

        result = runtime.del_session_messages([0])

        assert result == []
        assert len(runtime.messages) == 2


# ==============================================================================
# Group E: Edge Case Tests
# ==============================================================================

class TestEdgeCases:
    """Test edge cases for ctx_runtime module."""

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_add_session_message_empty_content(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test adding session message with empty content."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.session_id = "test_session"

        runtime.add_session_message("user", "")

        assert len(runtime.messages) == 1
        assert runtime.messages[0]["content"] == ""

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_add_session_message_unicode_content(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test adding session message with unicode content."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.session_id = "test_session"

        runtime.add_session_message("user", "你好世界 🌍")

        assert len(runtime.messages) == 1
        assert runtime.messages[0]["content"] == "你好世界 🌍"

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_add_session_message_special_characters(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test adding session message with special characters."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.session_id = "test_session"

        runtime.add_session_message("user", '{"key": "value"}')

        assert len(runtime.messages) == 1
        assert runtime.messages[0]["content"] == '{"key": "value"}'

    @patch('topsailai.workspace.context.ctx_runtime.ctx_manager')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_large_message_list(self, mock_ctx_manager_base, mock_ctx_manager):
        """Test handling of large message list."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

        runtime = ContextRuntimeData()
        runtime.session_id = "test_session"

        for i in range(100):
            runtime.add_session_message("user", f"Message {i}")

        assert len(runtime.messages) == 100


# ==============================================================================
# Group F: Exception Handling Tests
# ==============================================================================

class TestExceptionHandling:
    """Test exception handling for ctx_runtime module."""

    @patch('topsailai.workspace.context.base.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_last_user_message_invalid_json(self, mock_ctx_manager, mock_json_tool):
        """Test last_user_message raises exception for invalid JSON."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_json_tool.json_load.side_effect = Exception("Invalid JSON")

        runtime = ContextRuntimeBase()
        runtime.messages = ["invalid json"]

        with pytest.raises(Exception, match="Invalid JSON"):
            _ = runtime.last_user_message

    @patch('topsailai.workspace.context.agent2llm.json_tool')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_del_agent_messages_invalid_json(self, mock_ctx_manager, mock_json_tool):
        """Test del_agent_messages raises exception for invalid JSON."""
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeAgent2LLM

        mock_json_tool.json_load.side_effect = Exception("Invalid JSON")

        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.get_work_memory_first_position.return_value = 0
        runtime.ai_agent.messages = ["invalid json"]

        with pytest.raises(Exception, match="Invalid JSON"):
            runtime.del_agent_messages([0])


# ==============================================================================
# Test Summary
# ==============================================================================

def test_module_summary():
    """Summary of test coverage for ctx_runtime module."""
    from topsailai.workspace.context.ctx_runtime import (
        ContextRuntimeAgent2LLM,
        ContextRuntimeData,
    )
    from topsailai.workspace.context.base import ContextRuntimeBase

    assert issubclass(ContextRuntimeAgent2LLM, ContextRuntimeBase)
    assert issubclass(ContextRuntimeData, ContextRuntimeAgent2LLM)

    test_classes = [
        TestImports,
        TestContextRuntimeBaseInit,
        TestContextRuntimeBaseProperties,
        TestContextRuntimeBaseMethods,
        TestContextRuntimeBaseEnvMethods,
        TestContextRuntimeAgent2LLM,
        TestContextRuntimeDataSessionMessages,
        TestEdgeCases,
        TestExceptionHandling,
    ]

    total_tests = sum(
        len([m for m in dir(cls) if m.startswith('test_')])
        for cls in test_classes
    )

    print(f"\nTotal tests in ctx_runtime module: {total_tests}")
    assert total_tests >= 35, f"Expected at least 35 tests, got {total_tests}"
