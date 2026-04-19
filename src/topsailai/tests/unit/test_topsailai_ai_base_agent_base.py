"""
Unit tests for ai_base/agent_base module.

Test coverage:
- AgentBase class initialization and configuration
- Agent name and type properties
- LLM model integration
- Run method signature

Author: mm-m25
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch


class TestAgentBaseImports(unittest.TestCase):
    """Test cases for module imports."""

    def test_import_agent_base(self):
        """Test AgentBase can be imported."""
        from topsailai.ai_base.agent_base import AgentBase
        self.assertTrue(callable(AgentBase))

    def test_import_step_call_base(self):
        """Test StepCallBase can be imported."""
        from topsailai.ai_base.agent_base import StepCallBase
        self.assertTrue(callable(StepCallBase))

    def test_import_llm_model(self):
        """Test LLMModel can be imported."""
        from topsailai.ai_base.agent_base import LLMModel
        self.assertTrue(callable(LLMModel))


class TestAgentBaseInit(unittest.TestCase):
    """Test cases for AgentBase initialization."""

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
        """Test AgentBase initializes with required parameters."""
        from topsailai.ai_base.agent_base import AgentBase
        
        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        self.assertEqual(agent.agent_name, "TestAgent")

    def test_init_with_tool_prompt(self):
        """Test AgentBase initializes with tool_prompt parameter."""
        from topsailai.ai_base.agent_base import AgentBase
        
        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent",
            tool_prompt="Use tools when needed"
        )
        self.assertIsNotNone(agent)

    def test_init_with_tool_kits(self):
        """Test AgentBase initializes with tool_kits parameter."""
        from topsailai.ai_base.agent_base import AgentBase
        
        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent",
            tool_kits=["file_tool"]
        )
        self.assertIsNotNone(agent)

    def test_init_with_excluded_tool_kits(self):
        """Test AgentBase initializes with excluded_tool_kits parameter."""
        from topsailai.ai_base.agent_base import AgentBase
        
        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent",
            excluded_tool_kits=["dangerous_tool"]
        )
        self.assertIsNotNone(agent)

    def test_agent_type_initialized_empty(self):
        """Test AgentBase initializes agent_type as empty string."""
        from topsailai.ai_base.agent_base import AgentBase
        
        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        self.assertEqual(agent.agent_type, "")


class TestAgentBaseLLMIntegration(unittest.TestCase):
    """Test cases for AgentBase LLM integration."""

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

    def test_llm_model_attribute_exists(self):
        """Test AgentBase has llm_model attribute."""
        from topsailai.ai_base.agent_base import AgentBase
        
        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        self.assertTrue(hasattr(agent, "llm_model"))

    def test_max_tokens_property_exists(self):
        """Test AgentBase has max_tokens property."""
        from topsailai.ai_base.agent_base import AgentBase
        
        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        self.assertTrue(hasattr(agent, "max_tokens"))
        # Should return an integer
        self.assertIsInstance(agent.max_tokens, int)


class TestAgentBaseMethods(unittest.TestCase):
    """Test cases for AgentBase methods."""

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

    def test_run_method_exists(self):
        """Test AgentBase has run method."""
        from topsailai.ai_base.agent_base import AgentBase
        
        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        self.assertTrue(hasattr(agent, "run"))
        self.assertTrue(callable(agent.run))


class TestAgentBaseInheritance(unittest.TestCase):
    """Test cases for AgentBase inheritance from AgentTool."""

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

    def test_inherits_from_agent_tool(self):
        """Test AgentBase inherits from AgentTool."""
        from topsailai.ai_base.agent_base import AgentBase
        from topsailai.ai_base.agent_tool import AgentTool
        
        self.assertTrue(issubclass(AgentBase, AgentTool))

    def test_has_tools_from_parent(self):
        """Test AgentBase has tools attribute from AgentTool."""
        from topsailai.ai_base.agent_base import AgentBase
        
        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        self.assertTrue(hasattr(agent, "tools"))


if __name__ == "__main__":
    unittest.main()
