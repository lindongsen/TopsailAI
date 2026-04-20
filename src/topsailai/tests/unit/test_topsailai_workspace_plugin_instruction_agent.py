"""
Unit tests for workspace/plugin_instruction/agent.py

Author: mm-m25
Purpose: Test agent instruction handlers (system_prompt, env_prompt, tool_prompt, tools)
"""

import unittest
from unittest.mock import MagicMock, patch


class TestGetSystemPrompt(unittest.TestCase):
    """Test get_system_prompt() function"""

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_success(self, mock_print, mock_get_agent):
        """Test successful system prompt retrieval"""
        mock_agent = MagicMock()
        mock_agent.messages = [
            {"role": "system", "content": "You are a helpful assistant"}
        ]
        mock_get_agent.return_value = mock_agent
        
        from topsailai.workspace.plugin_instruction.agent import get_system_prompt
        result = get_system_prompt()
        
        mock_print.assert_called_once_with("You are a helpful assistant")
        self.assertIsNone(result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_no_agent(self, mock_print, mock_get_agent):
        """Test when no agent is available"""
        mock_get_agent.return_value = None
        
        from topsailai.workspace.plugin_instruction.agent import get_system_prompt
        result = get_system_prompt()
        
        mock_print.assert_not_called()
        self.assertIsNone(result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_empty_messages(self, mock_print, mock_get_agent):
        """Test when agent has empty messages - raises IndexError"""
        mock_agent = MagicMock()
        mock_agent.messages = []
        mock_get_agent.return_value = mock_agent
        
        from topsailai.workspace.plugin_instruction.agent import get_system_prompt
        with self.assertRaises(IndexError):
            get_system_prompt()


class TestGetEnvPrompt(unittest.TestCase):
    """Test get_env_prompt() function"""

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_success(self, mock_print, mock_get_agent):
        """Test successful env prompt retrieval"""
        mock_agent = MagicMock()
        mock_agent.messages = [
            {"role": "system", "content": "System"},
            {"role": "env", "content": "ENV_VAR=value"}
        ]
        mock_get_agent.return_value = mock_agent
        
        from topsailai.workspace.plugin_instruction.agent import get_env_prompt
        result = get_env_prompt()
        
        mock_print.assert_called_once_with("ENV_VAR=value")
        self.assertIsNone(result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_no_agent(self, mock_print, mock_get_agent):
        """Test when no agent is available"""
        mock_get_agent.return_value = None
        
        from topsailai.workspace.plugin_instruction.agent import get_env_prompt
        result = get_env_prompt()
        
        mock_print.assert_not_called()
        self.assertIsNone(result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_empty_messages(self, mock_print, mock_get_agent):
        """Test when agent has empty messages - raises IndexError"""
        mock_agent = MagicMock()
        mock_agent.messages = []
        mock_get_agent.return_value = mock_agent
        
        from topsailai.workspace.plugin_instruction.agent import get_env_prompt
        with self.assertRaises(IndexError):
            get_env_prompt()


class TestGetToolPrompt(unittest.TestCase):
    """Test get_tool_prompt() function"""

    @patch("topsailai.workspace.plugin_instruction.agent.get_tools_for_chat")
    @patch("topsailai.workspace.plugin_instruction.agent.json_tool")
    @patch("topsailai.workspace.plugin_instruction.agent.env_tool")
    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_success_with_tool_calls(self, mock_print, mock_get_agent, 
                                      mock_env_tool, mock_json_tool, mock_get_tools):
        """Test successful tool prompt with tool calls enabled"""
        mock_agent = MagicMock()
        mock_agent.messages = [
            {"role": "system", "content": "System"},
            {"role": "env", "content": "ENV"},
            {"role": "tool", "content": "Available tools: tool1, tool2"}
        ]
        mock_agent.available_tools = {"tool1": {}, "tool2": {}}
        mock_get_agent.return_value = mock_agent
        mock_env_tool.is_use_tool_calls.return_value = True
        mock_get_tools.return_value = [{"name": "tool1"}, {"name": "tool2"}]
        mock_json_tool.safe_json_dump.return_value = '{"tools": []}'
        
        from topsailai.workspace.plugin_instruction.agent import get_tool_prompt
        result = get_tool_prompt()
        
        self.assertGreaterEqual(mock_print.call_count, 2)
        self.assertIsNone(result)

    @patch("topsailai.workspace.plugin_instruction.agent.env_tool")
    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_success_without_tool_calls(self, mock_print, mock_get_agent, mock_env_tool):
        """Test successful tool prompt without tool calls"""
        mock_agent = MagicMock()
        mock_agent.messages = [
            {"role": "system", "content": "System"},
            {"role": "env", "content": "ENV"},
            {"role": "tool", "content": "Available tools: tool1, tool2"}
        ]
        mock_get_agent.return_value = mock_agent
        mock_env_tool.is_use_tool_calls.return_value = False
        
        from topsailai.workspace.plugin_instruction.agent import get_tool_prompt
        result = get_tool_prompt()
        
        mock_print.assert_called_once_with("Available tools: tool1, tool2")
        self.assertIsNone(result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_no_agent(self, mock_print, mock_get_agent):
        """Test when no agent is available"""
        mock_get_agent.return_value = None
        
        from topsailai.workspace.plugin_instruction.agent import get_tool_prompt
        result = get_tool_prompt()
        
        mock_print.assert_not_called()
        self.assertIsNone(result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_empty_messages(self, mock_print, mock_get_agent):
        """Test when agent has empty messages - raises IndexError"""
        mock_agent = MagicMock()
        mock_agent.messages = []
        mock_get_agent.return_value = mock_agent
        
        from topsailai.workspace.plugin_instruction.agent import get_tool_prompt
        with self.assertRaises(IndexError):
            get_tool_prompt()


class TestGetTools(unittest.TestCase):
    """Test get_tools() function"""

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_success(self, mock_print, mock_get_agent):
        """Test successful tools list retrieval"""
        mock_agent = MagicMock()
        mock_agent.available_tools = {"tool1": {}, "tool2": {}, "tool3": {}}
        mock_get_agent.return_value = mock_agent
        
        from topsailai.workspace.plugin_instruction.agent import get_tools
        result = get_tools()
        
        mock_print.assert_called_once_with(["tool1", "tool2", "tool3"])
        self.assertIsNone(result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_no_agent(self, mock_print, mock_get_agent):
        """Test when no agent is available"""
        mock_get_agent.return_value = None
        
        from topsailai.workspace.plugin_instruction.agent import get_tools
        result = get_tools()
        
        mock_print.assert_not_called()
        self.assertIsNone(result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("builtins.print")
    def test_empty_tools(self, mock_print, mock_get_agent):
        """Test when agent has no tools"""
        mock_agent = MagicMock()
        mock_agent.available_tools = {}
        mock_get_agent.return_value = mock_agent
        
        from topsailai.workspace.plugin_instruction.agent import get_tools
        result = get_tools()
        
        mock_print.assert_called_once_with([])
        self.assertIsNone(result)


class TestInstructions(unittest.TestCase):
    """Test INSTRUCTIONS dict"""

    def test_has_system_prompt_key(self):
        """Test INSTRUCTIONS has 'system_prompt' key"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertIn("system_prompt", INSTRUCTIONS)

    def test_has_env_prompt_key(self):
        """Test INSTRUCTIONS has 'env_prompt' key"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertIn("env_prompt", INSTRUCTIONS)

    def test_has_tool_prompt_key(self):
        """Test INSTRUCTIONS has 'tool_prompt' key"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertIn("tool_prompt", INSTRUCTIONS)

    def test_has_tools_key(self):
        """Test INSTRUCTIONS has 'tools' key"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertIn("tools", INSTRUCTIONS)

    def test_correct_count(self):
        """Test INSTRUCTIONS has correct number of entries"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertEqual(len(INSTRUCTIONS), 4)

    def test_values_are_callable(self):
        """Test all INSTRUCTIONS values are callable"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        for key, value in INSTRUCTIONS.items():
            self.assertTrue(callable(value), f"{key} is not callable")


if __name__ == "__main__":
    unittest.main()
