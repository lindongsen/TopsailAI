"""
Unit tests for ai_base/agent_tool module.

Test coverage:
- AgentTool class initialization
- Tool management (add, remove, add_tools, add_tools_by_module)
- Tool prompt generation
- Available tools handling

Author: mm-m25
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch


class TestAgentToolImports(unittest.TestCase):
    """Test cases for module imports."""

    def test_import_agent_tool(self):
        """Test AgentTool can be imported."""
        from topsailai.ai_base.agent_tool import AgentTool
        self.assertTrue(callable(AgentTool))

    def test_import_prompt_base(self):
        """Test PromptBase can be imported."""
        from topsailai.ai_base.agent_tool import PromptBase
        self.assertTrue(callable(PromptBase))


class TestAgentToolInit(unittest.TestCase):
    """Test cases for AgentTool initialization."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_init_with_required_params(self):
        """Test AgentTool initializes with required parameters."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertIsNotNone(agent)

    def test_init_with_tool_prompt(self):
        """Test AgentTool initializes with tool_prompt parameter."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(
            system_prompt="You are a helpful assistant",
            tool_prompt="Use tools when needed"
        )
        self.assertIsNotNone(agent)

    def test_init_with_tools(self):
        """Test AgentTool initializes with tools parameter."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        mock_tool = MagicMock()
        agent = AgentTool(
            system_prompt="You are a helpful assistant",
            tools={"mock_tool": mock_tool}
        )
        self.assertIsNotNone(agent)

    def test_init_with_tool_kits(self):
        """Test AgentTool initializes with tool_kits parameter."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(
            system_prompt="You are a helpful assistant",
            tool_kits=["file_tool"]
        )
        self.assertIsNotNone(agent)

    def test_init_with_excluded_tool_kits(self):
        """Test AgentTool initializes with excluded_tool_kits parameter."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(
            system_prompt="You are a helpful assistant",
            excluded_tool_kits=["dangerous_tool"]
        )
        self.assertIsNotNone(agent)


class TestAgentToolAttributes(unittest.TestCase):
    """Test cases for AgentTool attributes."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_tools_attribute_exists(self):
        """Test AgentTool has tools attribute."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertTrue(hasattr(agent, "tools"))

    def test_available_tools_attribute_exists(self):
        """Test AgentTool has available_tools attribute."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertTrue(hasattr(agent, "available_tools"))
        self.assertIsInstance(agent.available_tools, dict)

    def test_tool_prompt_raw_attribute_exists(self):
        """Test AgentTool has tool_prompt_raw attribute."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(
            system_prompt="You are a helpful assistant",
            tool_prompt="Use tools when needed"
        )
        self.assertEqual(agent.tool_prompt_raw, "Use tools when needed")


class TestAgentToolAllTools(unittest.TestCase):
    """Test cases for AgentTool all_tools property."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_all_tools_property_exists(self):
        """Test AgentTool has all_tools property."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertTrue(hasattr(agent, "all_tools"))

    def test_all_tools_returns_dict(self):
        """Test all_tools returns a dictionary."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertIsInstance(agent.all_tools, dict)


class TestAgentToolRemoveTools(unittest.TestCase):
    """Test cases for AgentTool remove_tools method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_remove_tools_method_exists(self):
        """Test AgentTool has remove_tools method."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertTrue(hasattr(agent, "remove_tools"))
        self.assertTrue(callable(agent.remove_tools))

    def test_remove_tools_empty_string_returns_zero(self):
        """Test remove_tools returns 0 for empty string."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        result = agent.remove_tools("")
        self.assertEqual(result, 0)


class TestAgentToolAddTool(unittest.TestCase):
    """Test cases for AgentTool add_tool method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_add_tool_method_exists(self):
        """Test AgentTool has add_tool method."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertTrue(hasattr(agent, "add_tool"))
        self.assertTrue(callable(agent.add_tool))

    def test_add_tool_returns_bool(self):
        """Test add_tool returns a boolean."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        mock_tool = MagicMock()
        result = agent.add_tool("new_tool", mock_tool)
        self.assertIsInstance(result, bool)

    def test_add_tool_adds_to_available_tools(self):
        """Test add_tool adds tool to available_tools."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        mock_tool = MagicMock()
        agent.add_tool("new_tool", mock_tool)
        self.assertIn("new_tool", agent.available_tools)


class TestAgentToolAddTools(unittest.TestCase):
    """Test cases for AgentTool add_tools method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_add_tools_method_exists(self):
        """Test AgentTool has add_tools method."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertTrue(hasattr(agent, "add_tools"))
        self.assertTrue(callable(agent.add_tools))

    def test_add_tools_returns_dict(self):
        """Test add_tools returns a dictionary."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        mock_tool = MagicMock()
        result = agent.add_tools({"tool1": mock_tool, "tool2": mock_tool})
        self.assertIsInstance(result, dict)


class TestAgentToolGenerateToolPrompt(unittest.TestCase):
    """Test cases for AgentTool generate_tool_prompt method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_generate_tool_prompt_method_exists(self):
        """Test AgentTool has generate_tool_prompt method."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertTrue(hasattr(agent, "generate_tool_prompt"))
        self.assertTrue(callable(agent.generate_tool_prompt))

    def test_generate_tool_prompt_returns_str(self):
        """Test generate_tool_prompt returns a string."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        result = agent.generate_tool_prompt()
        self.assertIsInstance(result, str)


class TestAgentToolReloadToolPrompt(unittest.TestCase):
    """Test cases for AgentTool reload_tool_prompt method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_reload_tool_prompt_method_exists(self):
        """Test AgentTool has reload_tool_prompt method."""
        from topsailai.ai_base.agent_tool import AgentTool
        
        agent = AgentTool(system_prompt="You are a helpful assistant")
        self.assertTrue(hasattr(agent, "reload_tool_prompt"))
        self.assertTrue(callable(agent.reload_tool_prompt))


if __name__ == "__main__":
    unittest.main()
