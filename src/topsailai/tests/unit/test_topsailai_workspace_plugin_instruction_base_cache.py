"""
Unit tests for topsailai.workspace.plugin_instruction.base.cache module.

Author: mm-m25
Purpose: Test agent object management functions
"""

import unittest
from unittest.mock import MagicMock, patch
import importlib


class TestSetAiAgent(unittest.TestCase):
    """Test cases for set_ai_agent function."""

    def setUp(self):
        """Set up test fixtures."""
        # Import the module fresh for each test
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        importlib.reload(cache_module)
        self.cache_module = cache_module

    def tearDown(self):
        """Clean up after tests."""
        # Reset global variable
        self.cache_module.g_ai_agent = None

    def test_set_ai_agent_with_valid_agent(self):
        """Test setting a valid agent object."""
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"
        
        self.cache_module.set_ai_agent(mock_agent)
        
        self.assertIs(self.cache_module.g_ai_agent, mock_agent)

    def test_set_ai_agent_with_none(self):
        """Test setting None does not change global agent."""
        mock_agent = MagicMock()
        self.cache_module.g_ai_agent = mock_agent
        
        self.cache_module.set_ai_agent(None)
        
        # Should remain unchanged
        self.assertIs(self.cache_module.g_ai_agent, mock_agent)

    def test_set_ai_agent_returns_none(self):
        """Test that set_ai_agent returns None."""
        mock_agent = MagicMock()
        
        result = self.cache_module.set_ai_agent(mock_agent)
        
        self.assertIsNone(result)


class TestGetAiAgent(unittest.TestCase):
    """Test cases for get_ai_agent function."""

    def setUp(self):
        """Set up test fixtures."""
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        importlib.reload(cache_module)
        self.cache_module = cache_module

    def tearDown(self):
        """Clean up after tests."""
        self.cache_module.g_ai_agent = None

    def test_get_ai_agent_when_set(self):
        """Test getting agent when it has been set."""
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"
        self.cache_module.g_ai_agent = mock_agent
        
        result = self.cache_module.get_ai_agent()
        
        self.assertIs(result, mock_agent)

    def test_get_ai_agent_when_not_set(self):
        """Test getting agent when it has not been set (None)."""
        self.cache_module.g_ai_agent = None
        
        result = self.cache_module.get_ai_agent()
        
        self.assertIsNone(result)

    def test_get_ai_agent_returns_correct_type(self):
        """Test that get_ai_agent returns the correct object."""
        from topsailai.ai_base.agent_base import AgentBase
        mock_agent = MagicMock(spec=AgentBase)
        self.cache_module.g_ai_agent = mock_agent
        
        result = self.cache_module.get_ai_agent()
        
        self.assertIsInstance(result, MagicMock)


class TestGlobalVariable(unittest.TestCase):
    """Test cases for global variable g_ai_agent."""

    def setUp(self):
        """Set up test fixtures."""
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        importlib.reload(cache_module)
        self.cache_module = cache_module

    def tearDown(self):
        """Clean up after tests."""
        self.cache_module.g_ai_agent = None

    def test_global_agent_initially_none(self):
        """Test that global agent is initially None."""
        # After reload, should be None
        self.assertIsNone(self.cache_module.g_ai_agent)

    def test_global_agent_persists_between_calls(self):
        """Test that global agent persists between function calls."""
        mock_agent = MagicMock()
        mock_agent.name = "persistent_agent"
        
        self.cache_module.set_ai_agent(mock_agent)
        result1 = self.cache_module.get_ai_agent()
        result2 = self.cache_module.get_ai_agent()
        
        self.assertIs(result1, mock_agent)
        self.assertIs(result2, mock_agent)
        self.assertIs(result1, result2)


if __name__ == "__main__":
    unittest.main()
