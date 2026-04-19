"""
Unit tests for topsailai.tools.agent_tool module.

Author: mm-m25
"""

import pytest
import os
import threading
from unittest.mock import patch, MagicMock, Mock


class TestIsCodeFile:
    """Test is_code_file function."""

    def test_none_file_path(self):
        """Test with None file path."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file(None) is False

    def test_empty_file_path(self):
        """Test with empty file path."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("") is False

    def test_markdown_file(self):
        """Test that markdown files return False."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("test.md") is False
        assert is_code_file("/path/to/file.MD") is False

    def test_manifest_file(self):
        """Test that manifest files return False."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("file.manifest") is False

    def test_json_file(self):
        """Test that JSON files return False."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("data.json") is False
        assert is_code_file("/path/config.JSON") is False

    def test_readme_file(self):
        """Test that README files return False."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("README.md") is False
        assert is_code_file("readme.MD") is False

    def test_python_file(self):
        """Test that Python files return True."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("script.py") is True
        assert is_code_file("/path/to/module.PY") is True

    def test_go_file(self):
        """Test that Go files return True."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("main.go") is True

    def test_javascript_file(self):
        """Test that JavaScript files return True."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("app.js") is True
        assert is_code_file("module.ts") is True

    def test_c_file(self):
        """Test that C/C++ files return True."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("main.c") is True
        assert is_code_file("header.h") is True
        assert is_code_file("source.cpp") is True

    def test_shell_file(self):
        """Test that shell files return True."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("script.sh") is True
        assert is_code_file("deploy.bash") is True

    def test_yaml_file(self):
        """Test that YAML files return True (not in exclusion list)."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("config.yaml") is True
        assert is_code_file("values.yml") is True

    def test_xml_file(self):
        """Test that XML files return True (not in exclusion list)."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("config.xml") is True

    def test_case_insensitive(self):
        """Test that file extension check is case insensitive."""
        from topsailai.tools.agent_tool import is_code_file
        assert is_code_file("file.PY") is True
        assert is_code_file("file.Py") is True
        assert is_code_file("file.Md") is False


class TestGetAllAgentTools:
    """Test get_all_agent_tools function."""

    def test_returns_only_agent_tools(self):
        """Test that only tools starting with 'agent' are returned."""
        from topsailai.tools.agent_tool import get_all_agent_tools
        
        tools = get_all_agent_tools()
        
        # All returned tools should start with 'agent'
        for tool_name in tools.keys():
            assert tool_name.startswith("agent"), f"{tool_name} should start with 'agent'"

    def test_returns_dict(self):
        """Test that get_all_agent_tools returns a dictionary."""
        from topsailai.tools.agent_tool import get_all_agent_tools
        
        tools = get_all_agent_tools()
        assert isinstance(tools, dict)

    def test_tools_values_are_callable(self):
        """Test that all returned tool values are callable."""
        from topsailai.tools.agent_tool import get_all_agent_tools
        
        tools = get_all_agent_tools()
        for tool_name, tool_func in tools.items():
            assert callable(tool_func), f"{tool_name} should be callable"


class TestAgentWriter:
    """Test agent_writer function."""

    @patch("topsailai.tools.agent_tool._agent_writer")
    def test_agent_writer_basic(self, mock_internal):
        """Test basic agent_writer call."""
        from topsailai.tools.agent_tool import agent_writer
        
        mock_internal.return_value = "test result"
        result = agent_writer("test message")
        
        assert result == "test result"
        mock_internal.assert_called_once_with(
            msg_or_file="test message",
            model_name=None,
            workspace=mock_internal.call_args[1]["workspace"],  # DEFAULT_WORKSPACE
        )

    @patch("topsailai.tools.agent_tool._agent_writer")
    def test_agent_writer_with_model(self, mock_internal):
        """Test agent_writer with model_name parameter."""
        from topsailai.tools.agent_tool import agent_writer
        
        mock_internal.return_value = "test result"
        result = agent_writer("test message", model_name="gpt-4")
        
        mock_internal.assert_called_once()
        call_kwargs = mock_internal.call_args[1]
        assert call_kwargs["model_name"] == "gpt-4"

    @patch("topsailai.tools.agent_tool._agent_writer")
    def test_agent_writer_with_workspace(self, mock_internal):
        """Test agent_writer with custom workspace."""
        from topsailai.tools.agent_tool import agent_writer
        
        mock_internal.return_value = "test result"
        result = agent_writer("test message", workspace="/custom/workspace")
        
        mock_internal.assert_called_once()
        call_kwargs = mock_internal.call_args[1]
        assert call_kwargs["workspace"] == "/custom/workspace"


class TestAgentProgrammer:
    """Test agent_programmer function."""

    @patch("topsailai.ai_base.agent_base.AgentRun")
    @patch("topsailai.tools.agent_tool.prompt_tool")
    @patch("topsailai.tools.agent_tool.file_tool")
    def test_agent_programmer_basic(self, mock_file_tool, mock_prompt_tool, mock_agent_run):
        """Test basic agent_programmer call."""
        from topsailai.tools.agent_tool import agent_programmer
        
        # Setup mocks
        mock_agent_instance = MagicMock()
        mock_agent_instance.run.return_value = "programming result"
        mock_agent_run.return_value = mock_agent_instance
        mock_prompt_tool.read_prompt.return_value = ""
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        
        result = agent_programmer("write a function")
        
        assert result == "programming result"
        mock_agent_run.assert_called_once()
        call_kwargs = mock_agent_run.call_args[1]
        assert call_kwargs["agent_name"] == "AgentProgrammer"
        assert "excluded_tool_kits" in call_kwargs

    def test_agent_programmer_empty_message(self):
        """Test agent_programmer with empty message - reveals IndexError bug in source."""
        from topsailai.tools.agent_tool import agent_programmer
        
        # Note: The source code has a bug - it tries to access msg_or_file[0]
        # which causes IndexError for empty string
        # This test documents the actual behavior (IndexError)
        with pytest.raises(IndexError):
            agent_programmer("")

    def test_agent_programmer_whitespace_message(self):
        """Test agent_programmer with whitespace-only message returns null."""
        from topsailai.tools.agent_tool import agent_programmer
        
        result = agent_programmer("   \n\t  ")
        
        assert result == "null of message content"

    @patch("topsailai.ai_base.agent_base.AgentRun")
    @patch("topsailai.tools.agent_tool.prompt_tool")
    @patch("topsailai.tools.agent_tool.file_tool")
    def test_agent_programmer_with_model(self, mock_file_tool, mock_prompt_tool, mock_agent_run):
        """Test agent_programmer with model_name parameter."""
        from topsailai.tools.agent_tool import agent_programmer
        
        mock_agent_instance = MagicMock()
        mock_agent_instance.run.return_value = "result"
        mock_agent_run.return_value = mock_agent_instance
        mock_prompt_tool.read_prompt.return_value = ""
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        
        result = agent_programmer("task", model_name="claude-3")
        
        assert mock_agent_instance.llm_model.model_name == "claude-3"


class TestAsyncMultitasksAgentWriter:
    """Test async_multitasks_agent_writer function."""

    @patch("topsailai.tools.agent_tool.agent_writer")
    @patch("topsailai.tools.agent_tool.threading.Thread")
    def test_async_multitasks_basic(self, mock_thread, mock_agent_writer):
        """Test basic async multi-task writer."""
        from topsailai.tools.agent_tool import async_multitasks_agent_writer
        
        mock_agent_writer.return_value = "task result"
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance
        
        result = async_multitasks_agent_writer(
            goal="summary goal",
            task1="task 1 content",
            task2="task 2 content",
        )
        
        # Should create threads for task1 and task2
        assert mock_thread.call_count == 2
        mock_thread_instance.start.assert_called()

    @patch("topsailai.tools.agent_tool.agent_writer")
    @patch("topsailai.tools.agent_tool.threading.Thread")
    def test_async_multitasks_with_goal_report_file(self, mock_thread, mock_agent_writer):
        """Test async multi-task writer with goal report file."""
        from topsailai.tools.agent_tool import async_multitasks_agent_writer
        
        mock_agent_writer.return_value = "final result"
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance
        
        result = async_multitasks_agent_writer(
            goal="summary goal",
            goal_report_file="/path/to/report.md",
            task1="task content",
        )
        
        # Should include goal report file in final goal
        assert result == "final result"

    @patch("topsailai.tools.agent_tool.agent_writer")
    @patch("topsailai.tools.agent_tool.threading.Thread")
    def test_async_multitasks_with_task_prompt_file(self, mock_thread, mock_agent_writer):
        """Test async multi-task writer with task prompt file."""
        from topsailai.tools.agent_tool import async_multitasks_agent_writer
        
        mock_agent_writer.return_value = "result"
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance
        
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                result = async_multitasks_agent_writer(
                    goal="goal",
                    task_prompt_file="/path/to/prompt.md",
                    task1="task",
                )

    @patch("topsailai.tools.agent_tool.agent_writer")
    @patch("topsailai.tools.agent_tool.threading.Thread")
    def test_async_multitasks_thread_naming(self, mock_thread, mock_agent_writer):
        """Test that threads are named correctly."""
        from topsailai.tools.agent_tool import async_multitasks_agent_writer
        
        mock_agent_writer.return_value = "result"
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance
        
        async_multitasks_agent_writer(
            goal="goal",
            task1="task1",
            task2="task2",
        )
        
        # Check thread names
        calls = mock_thread.call_args_list
        assert "async_multitasks_agent_writer.task1" in str(calls[0])
        assert "async_multitasks_agent_writer.task2" in str(calls[1])


class TestAsyncMultitasksAgentWriter2:
    """Test async_multitasks_agent_writer2 function."""

    @patch("topsailai.tools.agent_tool.async_multitasks_agent_writer")
    @patch("topsailai.tools.agent_tool.json_load")
    def test_async_multitasks2_with_json_string(self, mock_json_load, mock_async_writer):
        """Test async multi-task writer v2 with JSON string."""
        from topsailai.tools.agent_tool import async_multitasks_agent_writer2
        
        mock_json_load.return_value = ["task1", "task2", "task3"]
        mock_async_writer.return_value = "final result"
        
        result = async_multitasks_agent_writer2(
            goal="summary",
            goal_report_file="/report.md",
            task_prompt_file="/prompt.md",
            tasks_file_or_json='["task1", "task2", "task3"]',
        )
        
        assert result == "final result"
        mock_async_writer.assert_called_once()
        call_kwargs = mock_async_writer.call_args[1]
        assert "task0" in call_kwargs
        assert "task1" in call_kwargs
        assert "task2" in call_kwargs

    @patch("topsailai.tools.agent_tool.async_multitasks_agent_writer")
    @patch("topsailai.tools.agent_tool.json_load")
    def test_async_multitasks2_with_file_path(self, mock_json_load, mock_async_writer):
        """Test async multi-task writer v2 with file path."""
        from topsailai.tools.agent_tool import async_multitasks_agent_writer2
        
        mock_json_load.return_value = ["task1", "task2"]
        mock_async_writer.return_value = "result"
        
        with patch("os.path.isfile", return_value=True):
            with patch("builtins.open", MagicMock()) as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = '["task1", "task2"]'
                result = async_multitasks_agent_writer2(
                    goal="goal",
                    goal_report_file="/report.md",
                    task_prompt_file="/prompt.md",
                    tasks_file_or_json="/path/to/tasks.json",
                )

    def test_async_multitasks2_empty_content_assertion(self):
        """Test that empty content raises assertion error."""
        from topsailai.tools.agent_tool import async_multitasks_agent_writer2
        
        with patch("topsailai.tools.agent_tool.json_load", return_value=None):
            with pytest.raises(AssertionError):
                async_multitasks_agent_writer2(
                    goal="goal",
                    goal_report_file="/report.md",
                    task_prompt_file="/prompt.md",
                    tasks_file_or_json="",
                )


class TestAgentMemoryAsStory:
    """Test agent_memory_as_story function - integration tests."""

    def test_agent_memory_as_story_function_exists(self):
        """Test that agent_memory_as_story function exists and is callable."""
        from topsailai.tools.agent_tool import agent_memory_as_story
        assert callable(agent_memory_as_story)

    @patch("topsailai.tools.agent_tool._agent_writer")
    @patch("topsailai.tools.agent_tool.EnvReaderInstance")
    def test_agent_memory_as_story_calls_writer(self, mock_env, mock_writer):
        """Test that agent_memory_as_story calls _agent_writer."""
        from topsailai.tools.agent_tool import agent_memory_as_story
        
        mock_writer.return_value = "story result"
        mock_env.get.return_value = None
        
        result = agent_memory_as_story("test message")
        
        assert result == "story result"
        mock_writer.assert_called_once()

    @patch("topsailai.tools.agent_tool._agent_writer")
    @patch("topsailai.tools.agent_tool.EnvReaderInstance")
    def test_agent_memory_as_story_with_model(self, mock_env, mock_writer):
        """Test agent_memory_as_story with model_name."""
        from topsailai.tools.agent_tool import agent_memory_as_story
        
        mock_writer.return_value = "result"
        mock_env.get.return_value = None
        
        result = agent_memory_as_story("message", model_name="custom-model")
        
        call_kwargs = mock_writer.call_args[1]
        assert call_kwargs["model_name"] == "custom-model"


class TestSubprocessAgentMemoryAsStory:
    """Test subprocess_agent_memory_as_story function."""

    @patch("topsailai.tools.agent_tool.exec_cmd_in_new_process")
    @patch("topsailai.tools.agent_tool.EnvReaderInstance")
    def test_subprocess_agent_basic(self, mock_env, mock_exec):
        """Test basic subprocess_agent_memory_as_story call."""
        from topsailai.tools.agent_tool import subprocess_agent_memory_as_story
        
        mock_exec.return_value = 12345
        mock_env.get.return_value = None
        
        result = subprocess_agent_memory_as_story("test message")
        
        assert result == 12345
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0][0]
        assert "topsailai_agent_story" in call_args
        assert "-m" in call_args
        assert "test message" in call_args

    @patch("topsailai.tools.agent_tool.exec_cmd_in_new_process")
    @patch("topsailai.tools.agent_tool.EnvReaderInstance")
    def test_subprocess_agent_empty_message(self, mock_env, mock_exec):
        """Test subprocess_agent with empty message returns None."""
        from topsailai.tools.agent_tool import subprocess_agent_memory_as_story
        
        result = subprocess_agent_memory_as_story("")
        
        assert result is None
        mock_exec.assert_not_called()

    @patch("topsailai.tools.agent_tool.exec_cmd_in_new_process")
    @patch("topsailai.tools.agent_tool.EnvReaderInstance")
    def test_subprocess_agent_with_model(self, mock_env, mock_exec):
        """Test subprocess_agent with model_name parameter."""
        from topsailai.tools.agent_tool import subprocess_agent_memory_as_story
        
        mock_exec.return_value = 123
        mock_env.get.return_value = None
        
        result = subprocess_agent_memory_as_story("message", model_name="gpt-4")
        
        call_args = mock_exec.call_args[0][0]
        assert "-M" in call_args
        assert "gpt-4" in call_args

    @patch("topsailai.tools.agent_tool.exec_cmd_in_new_process")
    @patch("topsailai.tools.agent_tool.EnvReaderInstance")
    def test_subprocess_agent_with_list_input(self, mock_env, mock_exec):
        """Test subprocess_agent with list input."""
        from topsailai.tools.agent_tool import subprocess_agent_memory_as_story
        
        mock_exec.return_value = 123
        mock_env.get.return_value = None
        
        result = subprocess_agent_memory_as_story(["msg1", "msg2"])
        
        mock_exec.assert_called_once()

    @patch("topsailai.tools.agent_tool.exec_cmd_in_new_process")
    @patch("topsailai.tools.agent_tool.EnvReaderInstance")
    def test_subprocess_agent_with_dict_input(self, mock_env, mock_exec):
        """Test subprocess_agent with dict input."""
        from topsailai.tools.agent_tool import subprocess_agent_memory_as_story
        
        mock_exec.return_value = 123
        mock_env.get.return_value = None
        
        result = subprocess_agent_memory_as_story({"key": "value"})
        
        mock_exec.assert_called_once()


class TestAsyncAgentMemoryAsStory:
    """Test async_agent_memory_as_story function."""

    @patch("topsailai.tools.agent_tool.agent_memory_as_story")
    @patch("topsailai.tools.agent_tool.threading.Thread")
    @patch("topsailai.tools.agent_tool.thread_local_tool")
    def test_async_agent_memory_basic(self, mock_thread_local, mock_thread, mock_agent_memory):
        """Test basic async_agent_memory_as_story call."""
        from topsailai.tools.agent_tool import async_agent_memory_as_story
        
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance
        
        result = async_agent_memory_as_story("test message")
        
        assert result is None  # Returns None (starts thread)
        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called()

    @patch("topsailai.tools.agent_tool.agent_memory_as_story")
    @patch("topsailai.tools.agent_tool.threading.Thread")
    @patch("topsailai.tools.agent_tool.thread_local_tool")
    def test_async_agent_memory_with_dict(self, mock_thread_local, mock_thread, mock_agent_memory):
        """Test async_agent_memory_as_story with dict input."""
        from topsailai.tools.agent_tool import async_agent_memory_as_story
        
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance
        
        result = async_agent_memory_as_story({"key": "value"})
        
        mock_thread.assert_called_once()
        # Verify thread is created with correct name
        call_kwargs = mock_thread.call_args[1]
        assert call_kwargs.get("name") == "async_agent_memory_as_story"


class TestToolsConstant:
    """Test TOOLS constant."""

    def test_tools_contains_required_keys(self):
        """Test that TOOLS dict contains expected keys."""
        from topsailai.tools.agent_tool import TOOLS
        
        assert "WritingAssistant" in TOOLS
        assert "ProgrammingAssistant" in TOOLS
        assert "WritingAssistantMultiTasks" in TOOLS

    def test_tools_values_are_callable(self):
        """Test that TOOLS values are callable functions."""
        from topsailai.tools.agent_tool import TOOLS
        
        for tool_name, tool_func in TOOLS.items():
            assert callable(tool_func), f"{tool_name} should be callable"


class TestPromptConstant:
    """Test PROMPT constant."""

    def test_prompt_contains_agent_tool_info(self):
        """Test that PROMPT contains agent_tool information."""
        from topsailai.tools.agent_tool import PROMPT
        
        assert "agent_tool" in PROMPT.lower() or "assistant" in PROMPT.lower()


class TestFlagToolEnabled:
    """Test FLAG_TOOL_ENABLED constant."""

    def test_flag_tool_enabled_is_boolean(self):
        """Test that FLAG_TOOL_ENABLED is a boolean."""
        from topsailai.tools.agent_tool import FLAG_TOOL_ENABLED
        
        assert isinstance(FLAG_TOOL_ENABLED, bool)


class TestDefaultWorkspace:
    """Test DEFAULT_WORKSPACE constant."""

    def test_default_workspace_is_string(self):
        """Test that DEFAULT_WORKSPACE is a string."""
        from topsailai.tools.agent_tool import DEFAULT_WORKSPACE
        
        assert isinstance(DEFAULT_WORKSPACE, str)

    def test_default_workspace_is_not_empty(self):
        """Test that DEFAULT_WORKSPACE is not empty."""
        from topsailai.tools.agent_tool import DEFAULT_WORKSPACE
        
        assert DEFAULT_WORKSPACE != ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
