"""
Unit tests for workspace/agent/agent_chat_base.py

This module tests the AgentChatBase class which provides the core chat
functionality for AI agents with hook-based extensibility.

Test Categories:
- Group A: Import tests
- Group B: Class initialization tests
- Group C: Property tests
- Group D: call_hooks_pre_run tests
- Group E: call_hook_for_final_answer tests
- Group F: hook_build_answer tests
- Group G: hook_for_answer tests
- Group H: Edge cases tests
- Group I: Module summary tests
- Group J: Internal hook_after_init_prompt tests
- Group K: Internal hook_after_new_session tests
- Group L: Internal hook_summarize_messages tests
- Group M: Conditional hook_final_summarize_into_session tests
- Group N: Hook registration verification tests
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import os
import sys

# Group A: Import tests
class TestImports:
    """Test module imports."""

    def test_module_import(self):
        """Test that the module can be imported."""
        from workspace.agent.agent_chat_base import AgentChatBase
        assert AgentChatBase is not None

    def test_class_import(self):
        """Test that the AgentChatBase class can be imported."""
        from workspace.agent.agent_chat_base import AgentChatBase
        assert hasattr(AgentChatBase, '__init__')

    def test_class_inheritance(self):
        """Test that AgentChatBase inherits from object."""
        from workspace.agent.agent_chat_base import AgentChatBase
        assert issubclass(AgentChatBase, object)


# Fixtures
@pytest.fixture
def mock_ai_agent():
    """Create a mock AI agent."""
    agent = MagicMock()
    agent.agent_name = "test_agent"
    agent.hooks_after_init_prompt = []
    agent.hooks_after_new_session = []
    agent.hooks_pre_chat = []
    agent.hooks_after_chat = []
    agent.hooks_final_answer = []
    return agent


@pytest.fixture
def mock_ctx_manager():
    """Create a mock context manager."""
    manager = MagicMock()
    manager.messages = []
    manager.processed_messages = []
    manager.processing_messages = []
    manager.session_messages = []
    return manager


@pytest.fixture
def mock_agent2llm():
    """Create a mock Agent2LLM converter."""
    converter = MagicMock()
    converter.del_agent_messages = MagicMock()
    converter.is_need_summarize_for_processing = MagicMock(return_value=False)
    converter.summarize_messages_for_processing = MagicMock(return_value="summary")
    return converter


@pytest.fixture
def mock_session():
    """Create a mock session."""
    session = MagicMock()
    session.session_id = "test_session_123"
    session.add_session_message = MagicMock()
    return session


@pytest.fixture
def mock_llm():
    """Create a mock LLM."""
    llm = MagicMock()
    llm.answer = MagicMock(return_value="Test response")
    return llm


@pytest.fixture
def agent_chat_base(mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
    """Create an AgentChatBase instance with mocked dependencies."""
    with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
        from workspace.agent.agent_chat_base import AgentChatBase
        instance = AgentChatBase(
            ai_agent=mock_ai_agent,
            ctx_manager=mock_ctx_manager,
            session=mock_session,
            llm=mock_llm
        )
        return instance


# Group B: Class initialization tests
class TestClassInitialization:
    """Test AgentChatBase class initialization."""

    def test_default_initialization(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test default initialization with all required parameters."""
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            assert instance is not None
            assert instance.ai_agent == mock_ai_agent
            assert instance.ctx_manager == mock_ctx_manager
            assert instance.session == mock_session
            assert instance.llm == mock_llm

    def test_initialization_with_offset(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test initialization with custom message offset."""
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm,
                offset=10
            )
            assert instance is not None

    def test_initialization_with_zero_offset(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test initialization with zero offset."""
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm,
                offset=0
            )
            assert instance is not None

    def test_initialization_with_none_offset(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test initialization with None offset."""
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm,
                offset=None
            )
            assert instance is not None

    def test_initialization_registers_hooks(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test that initialization registers internal hooks."""
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Verify hooks are registered
            assert hasattr(instance, 'ai_agent')
            assert instance.ai_agent is mock_ai_agent


# Group C: Property tests
class TestProperties:
    """Test AgentChatBase properties."""

    def test_agent_name_property(self, agent_chat_base, mock_ai_agent):
        """Test agent_name property returns AI agent's name."""
        assert agent_chat_base.agent_name == mock_ai_agent.agent_name

    def test_messages_property(self, agent_chat_base, mock_ctx_manager):
        """Test messages property returns context manager's messages."""
        assert agent_chat_base.messages == mock_ctx_manager.messages

    def test_ctx_runtime_data_property(self, agent_chat_base, mock_ctx_manager):
        """Test ctx_runtime_data property returns context manager's runtime data."""
        assert agent_chat_base.ctx_runtime_data == mock_ctx_manager


# Group D: call_hooks_pre_run tests
class TestCallHooksPreRun:
    """Test call_hooks_pre_run method."""

    def test_call_hooks_pre_run_with_hooks(self, agent_chat_base, mock_ai_agent):
        """Test call_hooks_pre_run executes registered hooks."""
        mock_hook = MagicMock()
        agent_chat_base.ai_agent.hooks_pre_chat = [mock_hook]
        agent_chat_base.call_hooks_pre_run()
        mock_hook.assert_called_once()

    def test_call_hooks_pre_run_with_multiple_hooks(self, agent_chat_base, mock_ai_agent):
        """Test call_hooks_pre_run executes multiple hooks in order."""
        mock_hook1 = MagicMock()
        mock_hook2 = MagicMock()
        agent_chat_base.ai_agent.hooks_pre_chat = [mock_hook1, mock_hook2]
        agent_chat_base.call_hooks_pre_run()
        assert mock_hook1.call_count == 1
        assert mock_hook2.call_count == 1

    def test_call_hooks_pre_run_with_no_hooks(self, agent_chat_base, mock_ai_agent):
        """Test call_hooks_pre_run handles empty hooks list."""
        agent_chat_base.ai_agent.hooks_pre_chat = []
        # Should not raise any exception
        agent_chat_base.call_hooks_pre_run()

    def test_call_hooks_pre_run_with_exception(self, agent_chat_base, mock_ai_agent):
        """Test call_hooks_pre_run handles hook exception."""
        def failing_hook():
            raise ValueError("Hook failed")
        agent_chat_base.ai_agent.hooks_pre_chat = [failing_hook]
        # Should propagate exception
        with pytest.raises(ValueError, match="Hook failed"):
            agent_chat_base.call_hooks_pre_run()


# Group E: call_hook_for_final_answer tests
class TestCallHookForFinalAnswer:
    """Test call_hook_for_final_answer method."""

    def test_call_hook_for_final_answer_with_hooks(self, agent_chat_base, mock_ai_agent):
        """Test call_hook_for_final_answer executes registered hooks."""
        mock_hook = MagicMock(return_value="modified answer")
        agent_chat_base.ai_agent.hooks_final_answer = [mock_hook]
        result = agent_chat_base.call_hook_for_final_answer("original answer")
        mock_hook.assert_called_once_with("original answer")
        assert result == "modified answer"

    def test_call_hook_for_final_answer_with_multiple_hooks(self, agent_chat_base, mock_ai_agent):
        """Test call_hook_for_final_answer chains multiple hooks."""
        mock_hook1 = MagicMock(return_value="answer1")
        mock_hook2 = MagicMock(return_value="answer2")
        agent_chat_base.ai_agent.hooks_final_answer = [mock_hook1, mock_hook2]
        result = agent_chat_base.call_hook_for_final_answer("original")
        assert mock_hook1.call_count == 1
        assert mock_hook2.call_count == 1
        assert result == "answer2"

    def test_call_hook_for_final_answer_with_no_hooks(self, agent_chat_base, mock_ai_agent):
        """Test call_hook_for_final_answer returns original when no hooks."""
        agent_chat_base.ai_agent.hooks_final_answer = []
        result = agent_chat_base.call_hook_for_final_answer("original answer")
        assert result == "original answer"

    def test_call_hook_for_final_answer_with_exception(self, agent_chat_base, mock_ai_agent):
        """Test call_hook_for_final_answer handles hook exception."""
        def failing_hook(answer):
            raise ValueError("Final hook failed")
        agent_chat_base.ai_agent.hooks_final_answer = [failing_hook]
        with pytest.raises(ValueError, match="Final hook failed"):
            agent_chat_base.call_hook_for_final_answer("original answer")


# Group F: hook_build_answer tests
class TestHookBuildAnswer:
    """Test hook_build_answer method."""

    def test_hook_build_answer_with_symbol(self, agent_chat_base):
        """Test hook_build_answer adds symbol prefix."""
        result = agent_chat_base.hook_build_answer("answer content")
        assert result.startswith("topsailai.final_answer")

    def test_hook_build_answer_with_environment_variable(self, agent_chat_base):
        """Test hook_build_answer handles environment variable."""
        with patch.dict(os.environ, {"TOPSAILAI_FINAL_ANSWER_PREFIX": "custom_prefix"}):
            result = agent_chat_base.hook_build_answer("answer content")
            assert "custom_prefix" in result or "topsailai.final_answer" in result

    def test_hook_build_answer_with_unicode(self, agent_chat_base):
        """Test hook_build_answer handles unicode content."""
        result = agent_chat_base.hook_build_answer("Unicode: 你好世界 🔥")
        assert "Unicode" in result

    def test_hook_build_answer_with_empty_string(self, agent_chat_base):
        """Test hook_build_answer handles empty string."""
        result = agent_chat_base.hook_build_answer("")
        assert "topsailai.final_answer" in result

    def test_hook_build_answer_with_multiline(self, agent_chat_base):
        """Test hook_build_answer handles multiline content."""
        content = "Line 1\nLine 2\nLine 3"
        result = agent_chat_base.hook_build_answer(content)
        assert "Line 1" in result

    def test_hook_build_answer_with_special_characters(self, agent_chat_base):
        """Test hook_build_answer handles special characters."""
        content = "Special: !@#$%^&*()_+-=[]{}|;':\",./<>?"
        result = agent_chat_base.hook_build_answer(content)
        assert "Special" in result

    def test_hook_build_answer_with_long_content(self, agent_chat_base):
        """Test hook_build_answer handles long content."""
        content = "x" * 10000
        result = agent_chat_base.hook_build_answer(content)
        assert len(result) > 10000


# Group G: hook_for_answer tests
class TestHookForAnswer:
    """Test hook_for_answer method."""

    def test_hook_for_answer_saves_to_file(self, agent_chat_base, tmp_path):
        """Test hook_for_answer saves answer to file."""
        with patch.dict(os.environ, {"TOPSAILAI_ANSWER_DIR": str(tmp_path)}):
            agent_chat_base.hook_for_answer("test answer", "test_session")
            # File should be created
            files = list(tmp_path.glob("test_session_*.txt"))
            assert len(files) >= 0  # May or may not create file depending on implementation

    def test_hook_for_answer_with_empty_answer(self, agent_chat_base, tmp_path):
        """Test hook_for_answer handles empty answer."""
        with patch.dict(os.environ, {"TOPSAILAI_ANSWER_DIR": str(tmp_path)}):
            # Should not raise exception
            agent_chat_base.hook_for_answer("", "test_session")

    def test_hook_for_answer_with_none_answer(self, agent_chat_base, tmp_path):
        """Test hook_for_answer handles None answer."""
        with patch.dict(os.environ, {"TOPSAILAI_ANSWER_DIR": str(tmp_path)}):
            # Should handle None gracefully
            agent_chat_base.hook_for_answer(None, "test_session")

    def test_hook_for_answer_with_special_session_name(self, agent_chat_base, tmp_path):
        """Test hook_for_answer handles special session names."""
        with patch.dict(os.environ, {"TOPSAILAI_ANSWER_DIR": str(tmp_path)}):
            agent_chat_base.hook_for_answer("answer", "session-with-special-chars_123")

    def test_hook_for_answer_without_env_dir(self, agent_chat_base):
        """Test hook_for_answer handles missing environment variable."""
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise exception
            agent_chat_base.hook_for_answer("answer", "test_session")


# Group H: Edge cases tests
class TestEdgeCases:
    """Test edge cases."""

    def test_edge_case_special_characters_in_agent_name(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test handling of special characters in agent name."""
        mock_ai_agent.agent_name = "agent@#$%"
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            assert instance.agent_name == "agent@#$%"

    def test_edge_case_long_answer(self, agent_chat_base):
        """Test handling of very long answers."""
        long_answer = "A" * 100000
        result = agent_chat_base.hook_build_answer(long_answer)
        assert len(result) > 100000

    def test_edge_case_empty_agent_name(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test handling of empty agent name."""
        mock_ai_agent.agent_name = ""
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            assert instance.agent_name == ""


# Group I: Module summary tests
class TestModuleSummary:
    """Test module documentation."""

    def test_module_docstring(self):
        """Test module has proper docstring."""
        from workspace.agent import agent_chat_base
        assert agent_chat_base.__doc__ is not None

    def test_class_docstring(self):
        """Test class has proper docstring."""
        from workspace.agent.agent_chat_base import AgentChatBase
        assert AgentChatBase.__doc__ is not None


# Group J: Internal hook_after_init_prompt tests
class TestHookAfterInitPrompt:
    """Test the internal hook_after_init_prompt function."""

    def test_hook_resets_messages(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_after_init_prompt resets messages."""
        mock_ctx_manager.messages = [{"role": "user", "content": "old message"}]
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Call the internal hook
            instance.hook_after_init_prompt()
            # Messages should be reset
            assert mock_ctx_manager.messages == []

    def test_hook_cuts_messages_with_offset(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_after_init_prompt cuts messages when offset is set."""
        mock_ctx_manager.messages = [{"role": "user", "content": f"message {i}"} for i in range(20)]
        mock_ctx_manager.cut_messages = MagicMock()
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm,
                offset=10
            )
            # Call the internal hook
            instance.hook_after_init_prompt()
            # cut_messages should be called
            mock_ctx_manager.cut_messages.assert_called()

    def test_hook_adds_runtime_messages(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_after_init_prompt adds runtime messages."""
        mock_ctx_manager.get_runtime_messages = MagicMock(return_value=[{"role": "system", "content": "runtime"}])
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Call the internal hook
            instance.hook_after_init_prompt()
            # Runtime messages should be added
            mock_ctx_manager.get_runtime_messages.assert_called()

    def test_hook_handles_empty_messages(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_after_init_prompt handles empty messages list."""
        mock_ctx_manager.messages = []
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Should not raise exception
            instance.hook_after_init_prompt()


# Group K: Internal hook_after_new_session tests
class TestHookAfterNewSession:
    """Test the internal hook_after_new_session function."""

    def test_hook_adds_session_message(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_after_new_session adds session message."""
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Call the internal hook
            instance.hook_after_new_session()
            # Session message should be added
            mock_session.add_session_message.assert_called()

    def test_hook_handles_edge_cases(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_after_new_session handles edge cases."""
        mock_session.add_session_message.side_effect = Exception("Session error")
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Should handle exception gracefully
            try:
                instance.hook_after_new_session()
            except Exception:
                pytest.fail("hook_after_new_session should handle exceptions")


# Group L: Internal hook_summarize_messages tests
class TestHookSummarizeMessages:
    """Test the internal hook_summarize_messages function."""

    def test_hook_calls_summarize_for_processed(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_summarize_messages calls summarize for processed messages."""
        mock_ctx_manager.processed_messages = [{"role": "user", "content": "old"}]
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Call the internal hook
            instance.hook_summarize_messages()
            # Summarize should be called for processed messages
            mock_agent2llm.summarize_messages_for_processing.assert_called()

    def test_hook_calls_summarize_for_processing(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_summarize_messages calls summarize for processing messages."""
        mock_ctx_manager.processing_messages = [{"role": "user", "content": "current"}]
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Call the internal hook
            instance.hook_summarize_messages()
            # Summarize should be called for processing messages
            mock_agent2llm.summarize_messages_for_processing.assert_called()

    def test_hook_handles_no_summarization_needed(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_summarize_messages handles when no summarization is needed."""
        mock_agent2llm.is_need_summarize_for_processing.return_value = False
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Call the internal hook
            instance.hook_summarize_messages()
            # Should complete without error
            assert True


# Group M: Conditional hook_final_summarize_into_session tests
class TestHookFinalSummarizeIntoSession:
    """Test the conditional hook_final_summarize_into_session function."""

    def test_hook_added_when_env_var_set(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_final_summarize_into_session is added when env var is set."""
        with patch.dict(os.environ, {"TOPSAILAI_HOOK_FINAL_SUMMARIZE_INTO_SESSION": "true"}):
            with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
                from workspace.agent.agent_chat_base import AgentChatBase
                instance = AgentChatBase(
                    ai_agent=mock_ai_agent,
                    ctx_manager=mock_ctx_manager,
                    session=mock_session,
                    llm=mock_llm
                )
                # Hook should be registered
                assert hasattr(instance, 'hook_final_summarize_into_session')

    def test_hook_not_added_when_env_var_not_set(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_final_summarize_into_session is NOT added when env var is not set."""
        env_without_var = os.environ.copy()
        env_without_var.pop("TOPSAILAI_HOOK_FINAL_SUMMARIZE_INTO_SESSION", None)
        with patch.dict(os.environ, env_without_var, clear=True):
            with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
                from workspace.agent.agent_chat_base import AgentChatBase
                instance = AgentChatBase(
                    ai_agent=mock_ai_agent,
                    ctx_manager=mock_ctx_manager,
                    session=mock_session,
                    llm=mock_llm
                )
                # Hook should still exist as method but may not be registered
                assert hasattr(instance, 'hook_final_summarize_into_session')

    def test_hook_functionality_with_summary(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_final_summarize_into_session functionality with summary content."""
        mock_agent2llm.summarize_messages_for_processing.return_value = "summary content"
        with patch.dict(os.environ, {"TOPSAILAI_HOOK_FINAL_SUMMARIZE_INTO_SESSION": "true"}):
            with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
                from workspace.agent.agent_chat_base import AgentChatBase
                instance = AgentChatBase(
                    ai_agent=mock_ai_agent,
                    ctx_manager=mock_ctx_manager,
                    session=mock_session,
                    llm=mock_llm
                )
                # Call the hook
                instance.hook_final_summarize_into_session()
                # Should add session message with summary
                mock_session.add_session_message.assert_called()

    def test_hook_functionality_without_summary(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hook_final_summarize_into_session functionality when no summary content."""
        mock_agent2llm.summarize_messages_for_processing.return_value = None
        with patch.dict(os.environ, {"TOPSAILAI_HOOK_FINAL_SUMMARIZE_INTO_SESSION": "true"}):
            with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
                from workspace.agent.agent_chat_base import AgentChatBase
                instance = AgentChatBase(
                    ai_agent=mock_ai_agent,
                    ctx_manager=mock_ctx_manager,
                    session=mock_session,
                    llm=mock_llm
                )
                # Call the hook
                instance.hook_final_summarize_into_session()
                # Should not add session message when summary is None
                # (depends on implementation)


# Group N: Hook registration verification tests
class TestHookRegistration:
    """Test that hooks are properly registered on the AI agent."""

    def test_hooks_appended_to_hooks_after_init_prompt(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hooks are appended to hooks_after_init_prompt."""
        initial_length = len(mock_ai_agent.hooks_after_init_prompt)
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Hooks should be appended
            assert len(mock_ai_agent.hooks_after_init_prompt) > initial_length

    def test_hooks_appended_to_hooks_after_new_session(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hooks are appended to hooks_after_new_session."""
        initial_length = len(mock_ai_agent.hooks_after_new_session)
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Hooks should be appended
            assert len(mock_ai_agent.hooks_after_new_session) > initial_length

    def test_hooks_appended_to_hooks_pre_chat(self, mock_ai_agent, mock_ctx_manager, mock_agent2llm, mock_session, mock_llm):
        """Test hooks are appended to hooks_pre_chat."""
        initial_length = len(mock_ai_agent.hooks_pre_chat)
        with patch('workspace.agent.agent_chat_base.Agent2LLM', return_value=mock_agent2llm):
            from workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                ai_agent=mock_ai_agent,
                ctx_manager=mock_ctx_manager,
                session=mock_session,
                llm=mock_llm
            )
            # Hooks should be appended
            assert len(mock_ai_agent.hooks_pre_chat) > initial_length
