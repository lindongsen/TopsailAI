"""
Unit tests for ai_base/agent_types/__init__ module.

Test coverage:
- get_agent_type function
- get_agent_step_call function

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock


class TestGetAgentType(unittest.TestCase):
    """Test cases for get_agent_type function."""

    def test_returns_react_for_default(self):
        """Test get_agent_type returns react module for 'default'."""
        from topsailai.ai_base.agent_types.init import get_agent_type, AGENT_TYPE_MAP
        
        result = get_agent_type("default")
        self.assertEqual(result, AGENT_TYPE_MAP["default"])

    def test_returns_react_for_react_type(self):
        """Test get_agent_type returns react module for 'react'."""
        from topsailai.ai_base.agent_types.init import get_agent_type, AGENT_TYPE_MAP
        
        result = get_agent_type("react")
        self.assertEqual(result, AGENT_TYPE_MAP["react"])

    def test_returns_plan_and_execute_for_valid_type(self):
        """Test get_agent_type returns plan_and_execute module."""
        from topsailai.ai_base.agent_types.init import get_agent_type, AGENT_TYPE_MAP
        
        result = get_agent_type("plan_and_execute")
        self.assertEqual(result, AGENT_TYPE_MAP["plan_and_execute"])

    def test_returns_react_community_for_valid_type(self):
        """Test get_agent_type returns react_community module."""
        from topsailai.ai_base.agent_types.init import get_agent_type, AGENT_TYPE_MAP
        
        result = get_agent_type("react_community")
        self.assertEqual(result, AGENT_TYPE_MAP["react_community"])

    def test_defaults_to_react_when_none_provided(self):
        """Test get_agent_type defaults to react when no type provided."""
        from topsailai.ai_base.agent_types.init import get_agent_type, AGENT_TYPE_MAP
        
        with patch('topsailai.ai_base.agent_types.init.env_tool.EnvReaderInstance.get', return_value=None):
            result = get_agent_type(None)
            self.assertEqual(result, AGENT_TYPE_MAP["default"])

    def test_defaults_to_react_when_invalid_type(self):
        """Test get_agent_type defaults to react for invalid type."""
        from topsailai.ai_base.agent_types.init import get_agent_type, AGENT_TYPE_MAP
        
        result = get_agent_type("invalid_type")
        self.assertEqual(result, AGENT_TYPE_MAP["default"])

    def test_uses_env_var_when_no_type_provided(self):
        """Test get_agent_type uses environment variable when no type provided."""
        from topsailai.ai_base.agent_types.init import get_agent_type, AGENT_TYPE_MAP
        
        with patch('topsailai.ai_base.agent_types.init.env_tool.EnvReaderInstance.get', return_value="plan_and_execute"):
            result = get_agent_type(None)
            self.assertEqual(result, AGENT_TYPE_MAP["plan_and_execute"])

    def test_explicit_type_overrides_env_var(self):
        """Test explicit type parameter overrides environment variable."""
        from topsailai.ai_base.agent_types.init import get_agent_type, AGENT_TYPE_MAP
        
        with patch('topsailai.ai_base.agent_types.init.env_tool.EnvReaderInstance.get', return_value="plan_and_execute"):
            result = get_agent_type("react")
            self.assertEqual(result, AGENT_TYPE_MAP["react"])


class TestGetAgentStepCall(unittest.TestCase):
    """Test cases for get_agent_step_call function."""

    def test_returns_step_call_instance(self):
        """Test get_agent_step_call returns an instance."""
        from topsailai.ai_base.agent_types.init import get_agent_step_call
        from topsailai.ai_base.tool_call import StepCallBase
        
        result = get_agent_step_call()
        self.assertIsInstance(result, StepCallBase)

    def test_returns_react_step_call_by_default(self):
        """Test get_agent_step_call returns ReAct step call by default."""
        from topsailai.ai_base.agent_types.init import get_agent_step_call
        from topsailai.ai_base.agent_types.react import Step4ReAct
        
        result = get_agent_step_call()
        self.assertIsInstance(result, Step4ReAct)

    def test_returns_plan_and_execute_step_call(self):
        """Test get_agent_step_call returns PlanAndExecute step call."""
        from topsailai.ai_base.agent_types.init import get_agent_step_call
        from topsailai.ai_base.agent_types.plan_and_execute import StepCall4PlanAndExecute
        
        result = get_agent_step_call(agent_type="plan_and_execute")
        self.assertIsInstance(result, StepCall4PlanAndExecute)

    def test_handles_empty_kwargs(self):
        """Test get_agent_step_call handles empty kwargs."""
        from topsailai.ai_base.agent_types.init import get_agent_step_call
        
        result = get_agent_step_call(kwargs={})
        self.assertIsNotNone(result)


class TestAgentTypeMap(unittest.TestCase):
    """Test cases for AGENT_TYPE_MAP constant."""

    def test_map_contains_default_key(self):
        """Test AGENT_TYPE_MAP contains 'default' key."""
        from topsailai.ai_base.agent_types.init import AGENT_TYPE_MAP
        
        self.assertIn("default", AGENT_TYPE_MAP)

    def test_map_contains_react_key(self):
        """Test AGENT_TYPE_MAP contains 'react' key."""
        from topsailai.ai_base.agent_types.init import AGENT_TYPE_MAP
        
        self.assertIn("react", AGENT_TYPE_MAP)

    def test_map_contains_plan_and_execute_key(self):
        """Test AGENT_TYPE_MAP contains 'plan_and_execute' key."""
        from topsailai.ai_base.agent_types.init import AGENT_TYPE_MAP
        
        self.assertIn("plan_and_execute", AGENT_TYPE_MAP)

    def test_map_contains_react_community_key(self):
        """Test AGENT_TYPE_MAP contains 'react_community' key."""
        from topsailai.ai_base.agent_types.init import AGENT_TYPE_MAP
        
        self.assertIn("react_community", AGENT_TYPE_MAP)

    def test_default_and_react_point_to_same_module(self):
        """Test 'default' and 'react' point to the same module."""
        from topsailai.ai_base.agent_types.init import AGENT_TYPE_MAP
        
        self.assertIs(AGENT_TYPE_MAP["default"], AGENT_TYPE_MAP["react"])


class TestGetAgentRole(unittest.TestCase):
    """Test cases for get_agent_role function."""

    def test_returns_worker_for_default(self):
        """Test get_agent_role defaults to worker when no role provided."""
        from topsailai.ai_base.agent_types.init import get_agent_role
        from topsailai.ai_base.constants import DEFAULT_AGENT_ROLE

        with patch('topsailai.ai_base.agent_types.init.env_tool.EnvReaderInstance.get', return_value=None):
            result = get_agent_role(None)
            self.assertEqual(result, DEFAULT_AGENT_ROLE)
            self.assertEqual(result, "worker")

    def test_returns_manager_for_valid_role(self):
        """Test get_agent_role returns manager for explicit manager."""
        from topsailai.ai_base.agent_types.init import get_agent_role

        result = get_agent_role("manager")
        self.assertEqual(result, "manager")

    def test_returns_worker_for_valid_role(self):
        """Test get_agent_role returns worker for explicit worker."""
        from topsailai.ai_base.agent_types.init import get_agent_role

        result = get_agent_role("worker")
        self.assertEqual(result, "worker")

    def test_falls_back_to_worker_for_invalid_role(self):
        """Test get_agent_role falls back to worker for invalid role."""
        from topsailai.ai_base.agent_types.init import get_agent_role

        result = get_agent_role("invalid_role")
        self.assertEqual(result, "worker")

    def test_uses_env_var_when_no_role_provided(self):
        """Test get_agent_role uses environment variable when no role provided."""
        from topsailai.ai_base.agent_types.init import get_agent_role

        with patch('topsailai.ai_base.agent_types.init.env_tool.EnvReaderInstance.get', return_value="manager"):
            result = get_agent_role(None)
            self.assertEqual(result, "manager")

    def test_explicit_role_overrides_env_var(self):
        """Test explicit role parameter overrides environment variable."""
        from topsailai.ai_base.agent_types.init import get_agent_role

        with patch('topsailai.ai_base.agent_types.init.env_tool.EnvReaderInstance.get', return_value="manager"):
            result = get_agent_role("worker")
            self.assertEqual(result, "worker")

    def test_env_var_invalid_falls_back_to_worker(self):
        """Test invalid environment variable role falls back to worker."""
        from topsailai.ai_base.agent_types.init import get_agent_role

        with patch('topsailai.ai_base.agent_types.init.env_tool.EnvReaderInstance.get', return_value="supervisor"):
            result = get_agent_role(None)
            self.assertEqual(result, "worker")


if __name__ == "__main__":
    unittest.main()
