"""
Unit tests for ai_base/constants module.

Test coverage:
- Role constant definitions (ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_TOOL)

Author: mm-m25
"""

import unittest


class TestRoleConstants(unittest.TestCase):
    """Test cases for role constants."""

    def test_role_user_value(self):
        """Test ROLE_USER constant has correct value."""
        from topsailai.ai_base.constants import ROLE_USER
        self.assertEqual(ROLE_USER, "user")

    def test_role_assistant_value(self):
        """Test ROLE_ASSISTANT constant has correct value."""
        from topsailai.ai_base.constants import ROLE_ASSISTANT
        self.assertEqual(ROLE_ASSISTANT, "assistant")

    def test_role_system_value(self):
        """Test ROLE_SYSTEM constant has correct value."""
        from topsailai.ai_base.constants import ROLE_SYSTEM
        self.assertEqual(ROLE_SYSTEM, "system")

    def test_role_tool_value(self):
        """Test ROLE_TOOL constant has correct value."""
        from topsailai.ai_base.constants import ROLE_TOOL
        self.assertEqual(ROLE_TOOL, "tool")

    def test_role_constants_are_strings(self):
        """Test all role constants are string type."""
        from topsailai.ai_base.constants import ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_TOOL
        
        self.assertIsInstance(ROLE_USER, str)
        self.assertIsInstance(ROLE_ASSISTANT, str)
        self.assertIsInstance(ROLE_SYSTEM, str)
        self.assertIsInstance(ROLE_TOOL, str)

    def test_role_constants_are_unique(self):
        """Test all role constants have unique values."""
        from topsailai.ai_base.constants import ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_TOOL
        
        roles = [ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_TOOL]
        self.assertEqual(len(roles), len(set(roles)), "Role constants should be unique")


    def test_agent_role_constants(self):
        """Test agent_role constants and default value."""
        from topsailai.ai_base.constants import (
            AGENT_ROLE_MANAGER,
            AGENT_ROLE_WORKER,
            DEFAULT_AGENT_ROLE,
            AGENT_ROLE_VALUES,
        )

        self.assertEqual(AGENT_ROLE_MANAGER, "manager")
        self.assertEqual(AGENT_ROLE_WORKER, "worker")
        self.assertEqual(DEFAULT_AGENT_ROLE, "worker")
        self.assertEqual(set(AGENT_ROLE_VALUES), {"manager", "worker"})
        self.assertIn(DEFAULT_AGENT_ROLE, AGENT_ROLE_VALUES)


if __name__ == "__main__":
    unittest.main()
