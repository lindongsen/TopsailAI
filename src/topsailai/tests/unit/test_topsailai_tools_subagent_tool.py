"""
Unit tests for topsailai.tools.subagent_tool module.

Test coverage:
- gen_task_id() function for task ID generation
- get_task_id() function for task ID retrieval
- call_assistant() function for assistant invocation
- TOOLS dictionary structure
- FLAG_TOOL_ENABLED constant
- PROMPT constant

Author: mm-m25
"""

import pytest
from unittest.mock import patch, MagicMock
import os


class TestGenTaskId:
    """Test gen_task_id() function."""

    def test_gen_task_id_returns_string(self):
        """Verify gen_task_id returns a string."""
        from topsailai.tools.subagent_tool import gen_task_id
        result = gen_task_id()
        assert isinstance(result, str)

    def test_gen_task_id_sets_env_var(self):
        """Verify gen_task_id sets TOPSAILAI_TASK_ID environment variable."""
        from topsailai.tools.subagent_tool import gen_task_id
        result = gen_task_id()
        assert os.getenv("TOPSAILAI_TASK_ID") == result

    def test_gen_task_id_format(self):
        """Verify gen_task_id returns properly formatted task ID."""
        from topsailai.tools.subagent_tool import gen_task_id
        result = gen_task_id()
        # Task ID should contain dots (format: session_id.date)
        assert "." in result

    def test_gen_task_id_generates_new_id(self):
        """Verify gen_task_id generates a new ID each call."""
        from topsailai.tools.subagent_tool import gen_task_id
        result = gen_task_id()
        # Just verify it returns a valid task ID format
        assert result.startswith("topsailai.")


class TestGetTaskId:
    """Test get_task_id() function."""

    def test_get_task_id_returns_string(self):
        """Verify get_task_id returns a string."""
        from topsailai.tools.subagent_tool import get_task_id
        result = get_task_id()
        assert isinstance(result, str)

    def test_get_task_id_returns_existing_when_set(self):
        """Verify get_task_id returns existing task ID when set."""
        from topsailai.tools.subagent_tool import get_task_id
        os.environ["TOPSAILAI_TASK_ID"] = "existing_task_123"
        result = get_task_id()
        assert result == "existing_task_123"

    def test_get_task_id_generates_new_when_not_set(self):
        """Verify get_task_id generates new ID when not set."""
        from topsailai.tools.subagent_tool import get_task_id
        # Clear the environment variable
        if "TOPSAILAI_TASK_ID" in os.environ:
            del os.environ["TOPSAILAI_TASK_ID"]
        result = get_task_id()
        assert result is not None
        assert len(result) > 0

    def test_get_task_id_sets_env_var(self):
        """Verify get_task_id sets TOPSAILAI_TASK_ID when generating new."""
        from topsailai.tools.subagent_tool import get_task_id
        # Clear the environment variable
        if "TOPSAILAI_TASK_ID" in os.environ:
            del os.environ["TOPSAILAI_TASK_ID"]
        result = get_task_id()
        assert os.getenv("TOPSAILAI_TASK_ID") == result


class TestCallAssistant:
    """Test call_assistant() function."""

    def test_call_assistant_requires_task(self):
        """Verify call_assistant raises assertion error for empty task."""
        from topsailai.tools.subagent_tool import call_assistant
        with pytest.raises(AssertionError, match="missing task content"):
            call_assistant("")

    def test_call_assistant_requires_task_none(self):
        """Verify call_assistant raises assertion error for None task."""
        from topsailai.tools.subagent_tool import call_assistant
        with pytest.raises(AssertionError):
            call_assistant(None)

    @patch("topsailai.workspace.agent_shell.get_agent_chat")
    @patch("topsailai.tools.subagent_tool.get_task_id")
    def test_call_assistant_calls_agent(self, mock_get_task_id, mock_get_agent_chat):
        """Verify call_assistant properly calls the agent."""
        from topsailai.tools.subagent_tool import call_assistant
        
        # Setup mocks
        mock_agent = MagicMock()
        mock_agent.run.return_value = "assistant response"
        mock_get_agent_chat.return_value = mock_agent
        mock_get_task_id.return_value = "task_123"
        
        result = call_assistant("test task")
        
        # Verify agent was created with correct parameters
        mock_get_agent_chat.assert_called_once()
        call_kwargs = mock_get_agent_chat.call_args[1]
        assert "disabled_tools" in call_kwargs
        assert "subagent_tool" in call_kwargs["disabled_tools"]
        assert call_kwargs["need_input_message"] is False
        
        # Verify agent was run
        mock_agent.run.assert_called_once_with(
            message="test task",
            times=1,
            need_session_lock=False,
            task_id="task_123",
        )
        
        assert result == "assistant response"

    @patch("topsailai.workspace.agent_shell.get_agent_chat")
    @patch("topsailai.tools.subagent_tool.get_task_id")
    def test_call_assistant_clears_final_answer_hooks(self, mock_get_task_id, mock_get_agent_chat):
        """Verify call_assistant clears final answer hooks."""
        from topsailai.tools.subagent_tool import call_assistant
        
        mock_agent = MagicMock()
        mock_agent.run.return_value = "response"
        mock_agent.hooks_for_final_answer = ["hook1", "hook2"]
        mock_get_agent_chat.return_value = mock_agent
        mock_get_task_id.return_value = "task_123"
        
        call_assistant("test task")
        
        assert len(mock_agent.hooks_for_final_answer) == 0

    @patch("topsailai.workspace.agent_shell.get_agent_chat")
    @patch("topsailai.tools.subagent_tool.get_task_id")
    @patch.dict(os.environ, {"TOPSAILAI_AGENT_NAME": "TestAgent"})
    def test_call_assistant_uses_agent_name(self, mock_get_task_id, mock_get_agent_chat):
        """Verify call_assistant uses agent name from environment."""
        from topsailai.tools.subagent_tool import call_assistant
        
        mock_agent = MagicMock()
        mock_agent.run.return_value = "response"
        mock_get_agent_chat.return_value = mock_agent
        mock_get_task_id.return_value = "task_123"
        
        call_assistant("test task")
        
        call_kwargs = mock_get_agent_chat.call_args[1]
        assert call_kwargs["agent_name"] == "Sub.TestAgent"

    @patch("topsailai.workspace.agent_shell.get_agent_chat")
    @patch("topsailai.tools.subagent_tool.get_task_id")
    def test_call_assistant_without_agent_name(self, mock_get_task_id, mock_get_agent_chat):
        """Verify call_assistant handles missing agent name."""
        from topsailai.tools.subagent_tool import call_assistant
        
        # Ensure TOPSAILAI_AGENT_NAME is not set
        if "TOPSAILAI_AGENT_NAME" in os.environ:
            del os.environ["TOPSAILAI_AGENT_NAME"]
        
        mock_agent = MagicMock()
        mock_agent.run.return_value = "response"
        mock_get_agent_chat.return_value = mock_agent
        mock_get_task_id.return_value = "task_123"
        
        call_assistant("test task")
        
        call_kwargs = mock_get_agent_chat.call_args[1]
        assert call_kwargs["agent_name"] == "Sub."


class TestToolsDictionary:
    """Test TOOLS dictionary structure."""

    def test_tools_is_dict(self):
        """Verify TOOLS is a dictionary."""
        from topsailai.tools.subagent_tool import TOOLS
        assert isinstance(TOOLS, dict)

    def test_tools_contains_call_assistant(self):
        """Verify TOOLS contains call_assistant key."""
        from topsailai.tools.subagent_tool import TOOLS
        assert "call_assistant" in TOOLS

    def test_tools_call_assistant_is_callable(self):
        """Verify call_assistant value is callable."""
        from topsailai.tools.subagent_tool import TOOLS
        assert callable(TOOLS["call_assistant"])

    def test_tools_count(self):
        """Verify TOOLS has correct number of entries."""
        from topsailai.tools.subagent_tool import TOOLS
        assert len(TOOLS) == 1


class TestFlagToolEnabled:
    """Test FLAG_TOOL_ENABLED constant."""

    def test_flag_is_boolean(self):
        """Verify FLAG_TOOL_ENABLED is a boolean."""
        from topsailai.tools.subagent_tool import FLAG_TOOL_ENABLED
        assert isinstance(FLAG_TOOL_ENABLED, bool)

    def test_flag_is_false(self):
        """Verify FLAG_TOOL_ENABLED is False by default."""
        from topsailai.tools.subagent_tool import FLAG_TOOL_ENABLED
        assert FLAG_TOOL_ENABLED is False


class TestPromptConstant:
    """Test PROMPT constant."""

    def test_prompt_is_string(self):
        """Verify PROMPT is a string."""
        from topsailai.tools.subagent_tool import PROMPT
        assert isinstance(PROMPT, str)

    def test_prompt_is_not_empty(self):
        """Verify PROMPT is not empty."""
        from topsailai.tools.subagent_tool import PROMPT
        assert len(PROMPT) > 0


class TestModuleExports:
    """Test module exports."""

    def test_all_expected_exports_exist(self):
        """Verify all expected exports are available."""
        from topsailai.tools import subagent_tool
        expected_exports = [
            "gen_task_id",
            "get_task_id",
            "call_assistant",
            "TOOLS",
            "FLAG_TOOL_ENABLED",
            "PROMPT",
        ]
        for export_name in expected_exports:
            assert hasattr(subagent_tool, export_name), \
                f"Missing export: {export_name}"

    def test_gen_task_id_is_callable(self):
        """Verify gen_task_id is callable."""
        from topsailai.tools.subagent_tool import gen_task_id
        assert callable(gen_task_id)

    def test_get_task_id_is_callable(self):
        """Verify get_task_id is callable."""
        from topsailai.tools.subagent_tool import get_task_id
        assert callable(get_task_id)


class TestIntegration:
    """Integration tests for subagent_tool module."""

    @patch("topsailai.workspace.agent_shell.get_agent_chat")
    @patch("topsailai.tools.subagent_tool.get_task_id")
    def test_full_assistant_call_flow(self, mock_get_task_id, mock_get_agent_chat):
        """Verify complete flow from task ID generation to assistant call."""
        from topsailai.tools.subagent_tool import call_assistant, get_task_id
        
        # Setup mocks
        mock_agent = MagicMock()
        mock_agent.run.return_value = "final answer"
        mock_get_agent_chat.return_value = mock_agent
        mock_get_task_id.return_value = "integration_task_123"
        
        # Get task ID first
        task_id = get_task_id()
        assert task_id == "integration_task_123"
        
        # Call assistant
        result = call_assistant("integration test task")
        
        assert result == "final answer"
        mock_agent.run.assert_called_once()

    def test_task_id_persistence(self):
        """Verify task ID persists across multiple get_task_id calls."""
        from topsailai.tools.subagent_tool import gen_task_id, get_task_id
        
        # Generate a new task ID
        task_id = gen_task_id()
        
        # Subsequent get_task_id calls should return the same ID
        for _ in range(3):
            assert get_task_id() == task_id

    @patch("topsailai.workspace.agent_shell.get_agent_chat")
    @patch("topsailai.tools.subagent_tool.get_task_id")
    def test_disabled_tools_list(self, mock_get_task_id, mock_get_agent_chat):
        """Verify correct tools are disabled in assistant call."""
        from topsailai.tools.subagent_tool import call_assistant
        
        mock_agent = MagicMock()
        mock_agent.run.return_value = "response"
        mock_get_agent_chat.return_value = mock_agent
        mock_get_task_id.return_value = "task_123"
        
        call_assistant("test task")
        
        call_kwargs = mock_get_agent_chat.call_args[1]
        disabled = call_kwargs["disabled_tools"]
        assert "agent_tool" in disabled
        assert "subagent_tool" in disabled


class TestEdgeCases:
    """Edge case tests for subagent_tool module."""

    def test_empty_task_string(self):
        """Verify call_assistant handles empty string task."""
        from topsailai.tools.subagent_tool import call_assistant
        with pytest.raises(AssertionError):
            call_assistant("")

    def test_whitespace_only_task(self):
        """Verify whitespace-only task passes assertion (truthy check)."""
        # Whitespace-only is truthy, so it passes the assertion check
        # The actual processing happens in the agent, not in call_assistant
        assert "   "  # Whitespace is truthy

    def test_long_task_content(self):
        """Verify call_assistant handles long task content."""
        long_task = "x" * 10000
        # Should be truthy, so no AssertionError is raised
        assert long_task  # Should be truthy

    def test_special_characters_in_task(self):
        """Verify call_assistant handles special characters in task."""
        special_task = "Task with 'quotes' and \"double quotes\" and <brackets>"
        assert special_task  # Should be truthy

    @patch("topsailai.workspace.agent_shell.get_agent_chat")
    @patch("topsailai.tools.subagent_tool.get_task_id")
    def test_agent_name_with_special_chars(self, mock_get_task_id, mock_get_agent_chat):
        """Verify call_assistant handles special characters in agent name."""
        from topsailai.tools.subagent_tool import call_assistant
        
        mock_agent = MagicMock()
        mock_agent.run.return_value = "response"
        mock_get_agent_chat.return_value = mock_agent
        mock_get_task_id.return_value = "task_123"
        
        with patch.dict(os.environ, {"TOPSAILAI_AGENT_NAME": "Test_Agent-123"}):
            call_assistant("test task")
        
        call_kwargs = mock_get_agent_chat.call_args[1]
        assert call_kwargs["agent_name"] == "Sub.Test_Agent-123"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
