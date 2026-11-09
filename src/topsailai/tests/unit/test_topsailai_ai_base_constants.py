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


class TestSessionCategoryConstants(unittest.TestCase):
    """Test cases for session category constants."""

    def test_session_category_values(self):
        """Test each session category constant has the stored value."""
        from topsailai.ai_base.constants import (
            SESSION_CATEGORY_AGENT,
            SESSION_CATEGORY_CHAT,
            SESSION_CATEGORY_AGENT_DRIVER,
        )

        self.assertEqual(SESSION_CATEGORY_AGENT, "agent")
        self.assertEqual(SESSION_CATEGORY_CHAT, "chat")
        self.assertEqual(SESSION_CATEGORY_AGENT_DRIVER, "agent_driver")

    def test_session_category_values_tuple(self):
        """Test SESSION_CATEGORY_VALUES lists every defined category once."""
        from topsailai.ai_base.constants import (
            SESSION_CATEGORY_AGENT,
            SESSION_CATEGORY_CHAT,
            SESSION_CATEGORY_AGENT_DRIVER,
            SESSION_CATEGORY_VALUES,
        )

        self.assertEqual(
            set(SESSION_CATEGORY_VALUES),
            {SESSION_CATEGORY_AGENT, SESSION_CATEGORY_CHAT, SESSION_CATEGORY_AGENT_DRIVER},
        )
        self.assertEqual(len(SESSION_CATEGORY_VALUES), 3)

    def test_session_category_values_match_storage_pattern(self):
        """Test every category satisfies the stored lowercase pattern."""
        import re

        from topsailai.ai_base.constants import SESSION_CATEGORY_VALUES

        for category in SESSION_CATEGORY_VALUES:
            self.assertIsInstance(category, str)
            self.assertRegex(category, re.compile(r"[a-z0-9_]+"))

    def test_retention_exclusion_uses_the_shared_constant(self):
        """Test the retention exclusion set cannot drift from the constant."""
        from topsailai.ai_base.constants import SESSION_CATEGORY_AGENT_DRIVER
        from topsailai.context.session_cleanup import RETENTION_EXCLUDED_CATEGORIES

        self.assertEqual(RETENTION_EXCLUDED_CATEGORIES, frozenset({SESSION_CATEGORY_AGENT_DRIVER}))


if __name__ == "__main__":
    unittest.main()
