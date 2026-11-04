"""Plugin export contracts; author: DawsonLin."""

class TestToolsConstant:
    """Test TOOLS constant."""

    def test_tools_contains_required_keys(self):
        """Test that TOOLS dict contains expected keys."""
        from agent_tool import TOOLS

        assert "WritingAssistant" in TOOLS
        assert "ProgrammingAssistant" in TOOLS
        assert "WritingAssistantMultiTasks" in TOOLS

    def test_tools_values_are_callable(self):
        """Test that TOOLS values are callable functions."""
        from agent_tool import TOOLS

        for tool_name, tool_func in TOOLS.items():
            assert callable(tool_func), f"{tool_name} should be callable"


class TestPromptConstant:
    """Test PROMPT constant."""

    def test_prompt_contains_agent_tool_info(self):
        """Test that PROMPT contains agent_tool information."""
        from agent_tool import PROMPT

        assert "agent_tool" in PROMPT.lower() or "assistant" in PROMPT.lower()


class TestFlagToolEnabled:
    """Test FLAG_TOOL_ENABLED constant."""

    def test_flag_tool_enabled_is_boolean(self):
        """Test that FLAG_TOOL_ENABLED is a boolean."""
        from agent_tool import FLAG_TOOL_ENABLED

        assert isinstance(FLAG_TOOL_ENABLED, bool)
