"""
Test suite for AgentChatBase class.
"""

import os
import pytest
from unittest.mock import MagicMock, patch


# Mock fixtures
@pytest.fixture
def mock_hook_instruction():
    """Create a mock HookInstruction."""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_ctx_rt_aiagent():
    """Create a mock ContextRuntimeAIAgent."""
    mock = MagicMock()
    mock.ai_agent.agent_name = "test_agent"
    mock.ai_agent.messages = []
    mock.ai_agent.hooks_after_init_prompt = []
    mock.ai_agent.hooks_after_new_session = []
    mock.ai_agent.hooks_pre_chat = []
    mock.ctx_runtime_data.messages = []
    mock.ctx_runtime_data.is_need_summarize_for_processed.return_value = False
    mock.ctx_runtime_data.is_need_summarize_for_processing.return_value = False
    return mock


@pytest.fixture
def mock_ctx_rt_instruction():
    """Create a mock ContextRuntimeInstructions."""
    mock = MagicMock()
    return mock


@pytest.fixture
def agent_chat_base(mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
    """Create an AgentChatBase instance with mocked dependencies."""
    from topsailai.workspace.agent.agent_chat_base import AgentChatBase
    with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[]):
        instance = AgentChatBase(
            hook_instruction=mock_hook_instruction,
            ctx_rt_aiagent=mock_ctx_rt_aiagent,
            ctx_rt_instruction=mock_ctx_rt_instruction,
            session_head_tail_offset=7
        )
        return instance


# Group A: Class initialization tests
class TestClassInitialization:
    """Test AgentChatBase class initialization."""

    def test_default_initialization(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test default initialization with all required parameters."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[]):
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction
            )
            assert instance is not None
            assert instance.hook_instruction == mock_hook_instruction
            assert instance.ctx_rt_aiagent == mock_ctx_rt_aiagent
            assert instance.ctx_rt_instruction == mock_ctx_rt_instruction

    def test_initialization_with_offset(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test initialization with custom message offset."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[]):
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction,
                session_head_tail_offset=10
            )
            assert instance is not None
            assert instance.session_head_tail_offset == 10

    def test_initialization_with_zero_offset(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test initialization with zero offset."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[]):
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction,
                session_head_tail_offset=0
            )
            assert instance is not None

    def test_initialization_with_none_offset(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test initialization with None offset."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[]):
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction,
                session_head_tail_offset=None
            )
            assert instance is not None
            # Should default to DEFAULT_HEAD_TAIL_OFFSET
            assert instance.session_head_tail_offset is not None


# Group B: Property tests
class TestProperties:
    """Test AgentChatBase properties."""

    def test_agent_name_property(self, agent_chat_base, mock_ctx_rt_aiagent):
        """Test agent_name property returns AI agent's name."""
        assert agent_chat_base.agent_name == mock_ctx_rt_aiagent.ai_agent.agent_name

    def test_messages_property(self, agent_chat_base, mock_ctx_rt_aiagent):
        """Test messages property returns AI agent's messages."""
        assert agent_chat_base.messages == mock_ctx_rt_aiagent.ai_agent.messages

    def test_ctx_runtime_data_property(self, agent_chat_base, mock_ctx_rt_aiagent):
        """Test ctx_runtime_data property returns context runtime data."""
        assert agent_chat_base.ctx_runtime_data == mock_ctx_rt_aiagent.ctx_runtime_data


# Group C: call_hooks_pre_run tests
class TestCallHooksPreRun:
    """Test call_hooks_pre_run method."""

    def test_call_hooks_pre_run_with_hooks(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test call_hooks_pre_run executes registered hooks."""
        mock_hook = MagicMock()
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[mock_hook]):
            from topsailai.workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction
            )
            instance.call_hooks_pre_run()
            mock_hook.assert_called_once_with(instance)

    def test_call_hooks_pre_run_with_multiple_hooks(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test call_hooks_pre_run executes multiple hooks in order."""
        mock_hook1 = MagicMock()
        mock_hook2 = MagicMock()
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[mock_hook1, mock_hook2]):
            from topsailai.workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction
            )
            instance.call_hooks_pre_run()
            assert mock_hook1.call_count == 1
            assert mock_hook2.call_count == 1

    def test_call_hooks_pre_run_with_no_hooks(self, agent_chat_base):
        """Test call_hooks_pre_run handles empty hooks list."""
        # Should not raise any exception
        agent_chat_base.call_hooks_pre_run()

    def test_call_hooks_pre_run_with_exception(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test call_hooks_pre_run handles hook exception gracefully."""
        def failing_hook(_):
            raise ValueError("Hook failed")
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[failing_hook]):
            from topsailai.workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction
            )
            # Should not raise, just log the exception
            instance.call_hooks_pre_run()


# Group D: call_hook_for_final_answer tests
class TestCallHookForFinalAnswer:
    """Test call_hook_for_final_answer method."""

    def test_call_hook_for_final_answer_with_hooks(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test call_hook_for_final_answer executes registered hooks."""
        mock_hook = MagicMock()
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[]):
            from topsailai.workspace.agent.agent_chat_base import AgentChatBase
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction
            )
            instance.hooks_for_final_answer = [mock_hook]
            instance.call_hook_for_final_answer()
            mock_hook.assert_called_once_with(instance)

    def test_call_hook_for_final_answer_with_no_hooks(self, agent_chat_base):
        """Test call_hook_for_final_answer handles empty hooks list."""
        agent_chat_base.hooks_for_final_answer = []
        # Should not raise any exception
        agent_chat_base.call_hook_for_final_answer()


# Group E: hook_build_answer tests
class TestHookBuildAnswer:
    """Test hook_build_answer method."""

    def test_hook_build_answer_returns_same_answer(self, agent_chat_base):
        """Test hook_build_answer returns answer when need_symbol is False."""
        result = agent_chat_base.hook_build_answer("test answer", need_symbol=False)
        assert result == "test answer"

    def test_hook_build_answer_with_symbol(self, agent_chat_base):
        """Test hook_build_answer adds symbol prefix when need_symbol is True."""
        result = agent_chat_base.hook_build_answer("answer content", need_symbol=True)
        assert "answer content" in result

    def test_hook_build_answer_with_environment_variable(self, agent_chat_base):
        """Test hook_build_answer handles environment variable."""
        with patch.dict(os.environ, {"TOPSAILAI_SYMBOL_STARTSWITH_ANSWER": "custom_prefix"}):
            result = agent_chat_base.hook_build_answer("answer content", need_symbol=True)
            assert "custom_prefix" in result or "answer content" in result

    def test_hook_build_answer_with_unicode(self, agent_chat_base):
        """Test hook_build_answer handles unicode content."""
        result = agent_chat_base.hook_build_answer("Unicode: 你好世界 🔥", need_symbol=False)
        assert "Unicode" in result

    def test_hook_build_answer_with_empty_string(self, agent_chat_base):
        """Test hook_build_answer handles empty string."""
        result = agent_chat_base.hook_build_answer("")
        assert result == ""

    def test_hook_build_answer_with_multiline(self, agent_chat_base):
        """Test hook_build_answer handles multiline content."""
        content = "Line 1\nLine 2\nLine 3"
        result = agent_chat_base.hook_build_answer(content, need_symbol=False)
        assert "Line 1" in result

    def test_hook_build_answer_with_special_characters(self, agent_chat_base):
        """Test hook_build_answer handles special characters."""
        content = "Special: !@#$%^&*()_+-=[]{}|;':\",./<>?"
        result = agent_chat_base.hook_build_answer(content, need_symbol=False)
        assert "Special" in result


# Group F: hook_for_answer tests
class TestHookForAnswer:
    """Test hook_for_answer method."""

    def test_hook_for_answer_with_empty_answer(self, agent_chat_base):
        """Test hook_for_answer handles empty answer."""
        # Should not raise exception
        agent_chat_base.hook_for_answer("")

    def test_hook_for_answer_with_none_answer(self, agent_chat_base):
        """Test hook_for_answer handles None answer."""
        # Should handle None gracefully
        agent_chat_base.hook_for_answer(None)

    def test_hook_for_answer_without_env_dir(self, agent_chat_base):
        """Test hook_for_answer handles missing environment variable."""
        # Should not raise exception
        agent_chat_base.hook_for_answer("answer")

    def test_hook_for_answer_saves_to_file(self, agent_chat_base, tmp_path):
        """Test hook_for_answer saves answer to file."""
        file_path = tmp_path / "result.txt"
        with patch.dict(os.environ, {"TOPSAILAI_SAVE_RESULT_TO_FILE": str(file_path)}):
            agent_chat_base.hook_for_answer("test answer")
            assert file_path.exists()
            assert file_path.read_text() == "test answer"


# Group G: Edge cases tests
class TestEdgeCases:
    """Test edge cases."""

    def test_edge_case_special_characters_in_agent_name(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test handling of special characters in agent name."""
        mock_ctx_rt_aiagent.ai_agent.agent_name = "agent@#$%"
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[]):
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction
            )
            assert instance.agent_name == "agent@#$%"

    def test_edge_case_empty_agent_name(self, mock_hook_instruction, mock_ctx_rt_aiagent, mock_ctx_rt_instruction):
        """Test handling of empty agent name."""
        mock_ctx_rt_aiagent.ai_agent.agent_name = ""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        with patch('topsailai.workspace.agent.hooks.base.init.get_hooks', return_value=[]):
            instance = AgentChatBase(
                hook_instruction=mock_hook_instruction,
                ctx_rt_aiagent=mock_ctx_rt_aiagent,
                ctx_rt_instruction=mock_ctx_rt_instruction
            )
            assert instance.agent_name == ""


# Group H: Module summary tests
class TestModuleSummary:
    """Test module documentation."""

    def test_module_docstring(self):
        """Test module has proper docstring."""
        from topsailai.workspace.agent import agent_chat_base
        assert agent_chat_base.__doc__ is not None

    def test_class_docstring(self):
        """Test class has proper docstring."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        assert AgentChatBase.__doc__ is not None
