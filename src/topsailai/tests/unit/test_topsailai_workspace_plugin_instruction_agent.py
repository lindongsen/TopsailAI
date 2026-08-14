"""
Unit tests for workspace/plugin_instruction/agent.py

Author: mm-m25
Purpose: Test agent instruction handlers (system_prompt, env_prompt, tool_prompt, tools)
"""

import os
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


class TestGetMessages(unittest.TestCase):
    """Test get_messages() function"""

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent.json_tool")
    def test_success(self, mock_json_tool, mock_get_agent):
        """Test successful messages retrieval including TotalCount footer."""
        mock_agent = MagicMock()
        mock_agent.messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"}
        ]
        mock_get_agent.return_value = mock_agent
        mock_json_tool.json_dump.return_value = '[{"role": "system", "content": "System"}]'
        
        from topsailai.workspace.plugin_instruction.agent import get_messages
        result = get_messages()
        
        mock_json_tool.json_dump.assert_called_once_with(mock_agent.messages)
        self.assertTrue(result.startswith('[{"role": "system", "content": "System"}]'))
        self.assertIn("TotalCount: 2", result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    def test_no_agent(self, mock_get_agent):
        """Test when no agent is available"""
        mock_get_agent.return_value = None
        
        from topsailai.workspace.plugin_instruction.agent import get_messages
        result = get_messages()
        
        self.assertIsNone(result)


class TestSetLlm(unittest.TestCase):
    """Test set_llm() function"""

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    def test_set_llm_by_positional_arg(self, mock_get_agent):
        """Test /set_llm <model_name>"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_get_agent.return_value = mock_agent

        from topsailai.workspace.plugin_instruction.agent import set_llm
        result = set_llm("NewModel")

        self.assertEqual(mock_agent.llm_model.model_name, "NewModel")
        self.assertIn("OldModel -> NewModel", result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    def test_set_llm_by_key_value(self, mock_get_agent):
        """Test /set_llm model=<model_name>"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_get_agent.return_value = mock_agent

        from topsailai.workspace.plugin_instruction.agent import set_llm
        result = set_llm("model=NewModel")

        self.assertEqual(mock_agent.llm_model.model_name, "NewModel")
        self.assertIn("OldModel -> NewModel", result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    def test_set_llm_with_endpoint(self, mock_get_agent):
        """Test /set_llm model=<model_name> base_url=<api_base> api_key=<api_key>"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_agent.llm_model.get_llm_model.return_value = "new_client"
        mock_get_agent.return_value = mock_agent

        from topsailai.workspace.plugin_instruction.agent import set_llm
        result = set_llm(
            "model=NewModel",
            "base_url=https://example.com/v1",
            "api_key=secret",
        )

        self.assertEqual(mock_agent.llm_model.model_name, "NewModel")
        mock_agent.llm_model.get_llm_model.assert_called_once_with(
            api_key="secret",
            api_base="https://example.com/v1",
        )
        self.assertEqual(mock_agent.llm_model.model, "new_client")
        self.assertEqual(mock_agent.llm_model.models, [])
        self.assertIn("NewModel", result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    def test_set_llm_api_key_env(self, mock_get_agent):
        """Test /set_llm model=<model_name> api_key_env=MY_API_KEY"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_agent.llm_model.get_llm_model.return_value = "new_client"
        mock_get_agent.return_value = mock_agent

        with patch.dict(os.environ, {"MY_API_KEY": "env_secret"}):
            from topsailai.workspace.plugin_instruction.agent import set_llm
            result = set_llm("model=NewModel", "api_key_env=MY_API_KEY")

        self.assertEqual(mock_agent.llm_model.model_name, "NewModel")
        mock_agent.llm_model.get_llm_model.assert_called_once_with(
            api_key="env_secret",
            api_base="",
        )
        self.assertEqual(mock_agent.llm_model.model, "new_client")

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    def test_set_llm_no_agent(self, mock_get_agent):
        """Test set_llm when no agent is available"""
        mock_get_agent.return_value = None

        from topsailai.workspace.plugin_instruction.agent import set_llm
        result = set_llm("NewModel")

        self.assertEqual(result, "No active agent")

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    def test_set_llm_no_args(self, mock_get_agent):
        """Test /set_llm with no arguments returns current model"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "CurrentModel"
        mock_get_agent.return_value = mock_agent

        from topsailai.workspace.plugin_instruction.agent import set_llm
        result = set_llm()

        self.assertEqual(result, "Current model: CurrentModel")


class TestSelectModel(unittest.TestCase):
    """Test select_model() function"""

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_list_models(self, mock_load_registry, mock_get_agent):
        """Test /models lists available models with indices and marks current model"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "ModelA"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "ModelA": {"name": "ModelA", "api_base": "https://a.example.com"},
            "ModelB": {"name": "ModelB", "api_base": "https://b.example.com"},
        }

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model()

        self.assertIn("Available models:", result)
        self.assertIn("1. * ModelA (https://a.example.com)", result)
        self.assertIn("2. ModelB (https://b.example.com)", result)
        self.assertNotIn("not in registry", result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_select_model_by_index(self, mock_load_registry, mock_get_agent):
        """Test /models <number> selects model by 1-based index"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_agent.llm_model.get_llm_model.return_value = "new_client"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "ModelA": {"name": "ModelA", "api_base": "https://a.example.com", "api_key": "key_a"},
            "ModelB": {"name": "ModelB", "api_base": "https://b.example.com", "api_key": "key_b"},
        }

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model("2")

        self.assertEqual(mock_agent.llm_model.model_name, "ModelB")
        mock_agent.llm_model.get_llm_model.assert_called_once_with(
            api_key="key_b",
            api_base="https://b.example.com",
        )
        self.assertEqual(mock_agent.llm_model.model, "new_client")
        self.assertEqual(mock_agent.llm_model.models, [])
        self.assertIn("ModelB", result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_select_model_by_invalid_index(self, mock_load_registry, mock_get_agent):
        """Test /models with out-of-range numeric index returns error"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "ModelA": {"name": "ModelA", "api_base": "https://a.example.com"},
        }

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model("5")

        self.assertEqual(result, "Invalid model index: 5. Valid range: 1-1")
        mock_agent.llm_model.get_llm_model.assert_not_called()

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_select_model_by_zero_index(self, mock_load_registry, mock_get_agent):
        """Test /models with 0 index returns error"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "ModelA": {"name": "ModelA", "api_base": "https://a.example.com"},
        }

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model("0")

        self.assertEqual(result, "Invalid model index: 0. Valid range: 1-1")

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_list_models_current_not_in_registry(self, mock_load_registry, mock_get_agent):
        """Test /models prints current model when it is not in the registry"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "CustomModel"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "ModelA": {"name": "ModelA", "api_base": "https://a.example.com"},
            "ModelB": {"name": "ModelB", "api_base": "https://b.example.com"},
        }

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model()

        self.assertIn("Current model: CustomModel (not in registry)", result)
        self.assertIn("Available models:", result)
        self.assertIn("1. ModelA (https://a.example.com)", result)
        self.assertIn("2. ModelB (https://b.example.com)", result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_select_model_by_name(self, mock_load_registry, mock_get_agent):
        """Test /models <model_name> applies the selected model"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_agent.llm_model.get_llm_model.return_value = "new_client"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "ModelA": {"name": "ModelA", "api_base": "https://a.example.com", "api_key": "key_a"},
        }

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model("ModelA")

        self.assertEqual(mock_agent.llm_model.model_name, "ModelA")
        mock_agent.llm_model.get_llm_model.assert_called_once_with(
            api_key="key_a",
            api_base="https://a.example.com",
        )
        self.assertEqual(mock_agent.llm_model.model, "new_client")
        self.assertEqual(mock_agent.llm_model.models, [])
        self.assertIn("ModelA", result)


    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_select_model_uses_model_field_over_name(self, mock_load_registry, mock_get_agent):
        """Test /models uses the model field (API ID) over the display name"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_agent.llm_model.get_llm_model.return_value = "new_client"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "gpt56luna-tester": {"name": "gpt56luna-tester", "model": "gpt-5.6-luna", "api_base": "https://a.example.com", "api_key": "key_a"},
        }

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model("gpt56luna-tester")

        self.assertEqual(mock_agent.llm_model.model_name, "gpt-5.6-luna")
        mock_agent.llm_model.get_llm_model.assert_called_once_with(
            api_key="key_a",
            api_base="https://a.example.com",
        )
        self.assertEqual(mock_agent.llm_model.model, "new_client")
        self.assertEqual(mock_agent.llm_model.models, [])
        self.assertIn("gpt-5.6-luna", result)

    @patch("topsailai.workspace.plugin_instruction.agent.print_info")
    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_select_model_applies_environment(self, mock_load_registry, mock_get_agent, mock_print_info):
        """Test /models applies environment variables from the model config"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_agent.llm_model.get_llm_model.return_value = "new_client"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "ModelA": {
                "name": "ModelA",
                "api_base": "https://a.example.com",
                "api_key": "key_a",
                "environment": {"MY_CUSTOM_VAR": "custom_value", "ANOTHER_VAR": "123"},
            },
        }

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model("ModelA")

        self.assertEqual(os.environ.get("MY_CUSTOM_VAR"), "custom_value")
        self.assertEqual(os.environ.get("ANOTHER_VAR"), "123")
        self.assertIn("ModelA", result)
        self.assertEqual(mock_print_info.call_count, 2)
        mock_print_info.assert_any_call("Set environment variable: MY_CUSTOM_VAR=custom_value")
        mock_print_info.assert_any_call("Set environment variable: ANOTHER_VAR=123")

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_select_model_synchronizes_openai_environment(self, mock_load_registry, mock_get_agent):
        """Test /models synchronizes canonical OpenAI-compatible environment variables."""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_agent.llm_model.get_llm_model.return_value = "new_client"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "ModelA": {
                "name": "ModelA",
                "model": "provider-model-a",
                "base_url": "https://a.example.com/v1",
                "api_key_env": "MODEL_A_API_KEY",
                "organization_env": "MODEL_A_ORG",
                "project_env": "MODEL_A_PROJECT",
                "environment": {"OPENAI_MODEL": "stale-model"},
            },
        }

        selected_keys = {
            "MODEL_A_API_KEY": "key_a",
            "MODEL_A_ORG": "org_a",
            "MODEL_A_PROJECT": "project_a",
        }
        with patch.dict(os.environ, selected_keys, clear=False):
            from topsailai.workspace.plugin_instruction.agent import select_model
            result = select_model("ModelA")

            self.assertEqual(os.environ["OPENAI_MODEL"], "provider-model-a")
            self.assertEqual(os.environ["OPENAI_BASE_URL"], "https://a.example.com/v1")
            self.assertEqual(os.environ["OPENAI_API_BASE"], "https://a.example.com/v1")
            self.assertEqual(os.environ["OPENAI_API_KEY"], "key_a")
            self.assertEqual(os.environ["OPENAI_ORG_ID"], "org_a")
            self.assertEqual(os.environ["OPENAI_PROJECT_ID"], "project_a")

        mock_agent.llm_model.get_llm_model.assert_called_once_with(
            api_key="key_a",
            api_base="https://a.example.com/v1",
        )
        self.assertIn("provider-model-a", result)


    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_select_model_no_environment(self, mock_load_registry, mock_get_agent):
        """Test /models without environment field does not set env vars"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "OldModel"
        mock_agent.llm_model.model_config = {"api_key": "", "api_base": ""}
        mock_agent.llm_model.get_llm_model.return_value = "new_client"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {
            "ModelA": {"name": "ModelA", "api_base": "https://a.example.com", "api_key": "key_a"},
        }

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model("ModelA")

        self.assertNotIn("MY_CUSTOM_VAR", os.environ)
        self.assertIn("ModelA", result)

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_select_model_not_found(self, mock_load_registry, mock_get_agent):
        """Test /models with unknown model name"""
        mock_agent = MagicMock()
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {}

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model("Unknown")

        self.assertEqual(result, "Model not found: Unknown")

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    def test_select_model_no_agent(self, mock_get_agent):
        """Test select_model when no agent is available"""
        mock_get_agent.return_value = None

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model()

        self.assertEqual(result, "No active agent")

    @patch("topsailai.workspace.plugin_instruction.agent.get_ai_agent")
    @patch("topsailai.workspace.plugin_instruction.agent._load_models_registry")
    def test_list_models_empty_registry(self, mock_load_registry, mock_get_agent):
        """Test /models with empty registry shows current model"""
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "CurrentModel"
        mock_get_agent.return_value = mock_agent
        mock_load_registry.return_value = {}

        from topsailai.workspace.plugin_instruction.agent import select_model
        result = select_model()

        self.assertIn("Current model: CurrentModel", result)
        self.assertIn("No models found in", result)


class TestLoadModelsRegistry(unittest.TestCase):
    """Test _load_models_registry() function"""

    @patch("topsailai.workspace.plugin_instruction.agent.os.path.exists")
    @patch("builtins.open")
    def test_load_registry(self, mock_open, mock_exists):
        """Test loading a valid models registry"""
        mock_exists.return_value = True
        mock_file = MagicMock()
        mock_file.__iter__.return_value = iter([
            '{"name": "ModelA", "api_base": "https://a.example.com"}\n',
            '{"name": "ModelB", "api_base": "https://b.example.com"}\n',
        ])
        mock_open.return_value.__enter__.return_value = mock_file

        from topsailai.workspace.plugin_instruction.agent import _load_models_registry
        registry = _load_models_registry()

        self.assertEqual(len(registry), 2)
        self.assertEqual(registry["ModelA"]["api_base"], "https://a.example.com")

    @patch("topsailai.workspace.plugin_instruction.agent.os.path.exists")
    def test_missing_registry(self, mock_exists):
        """Test missing registry file returns empty dict"""
        mock_exists.return_value = False

        from topsailai.workspace.plugin_instruction.agent import _load_models_registry
        registry = _load_models_registry()

        self.assertEqual(registry, {})


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

    def test_has_set_llm_key(self):
        """Test INSTRUCTIONS has 'set_llm' key"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertIn("set_llm", INSTRUCTIONS)

    def test_has_models_key(self):
        """Test INSTRUCTIONS has 'models' key"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertIn("models", INSTRUCTIONS)

    def test_has_llm_key(self):
        """Test INSTRUCTIONS has 'llm' key"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertIn("llm", INSTRUCTIONS)

    def test_has_messages_key(self):
        """Test INSTRUCTIONS has 'messages' key"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertIn("messages", INSTRUCTIONS)

    def test_correct_count(self):
        """Test INSTRUCTIONS has correct number of entries"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        self.assertEqual(len(INSTRUCTIONS), 8)

    def test_values_are_callable(self):
        """Test all INSTRUCTIONS values are callable"""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS
        for key, value in INSTRUCTIONS.items():
            self.assertTrue(callable(value), f"{key} is not callable")


if __name__ == "__main__":
    unittest.main()
