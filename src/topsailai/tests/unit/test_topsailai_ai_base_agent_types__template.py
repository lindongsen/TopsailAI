"""
Unit tests for ai_base/agent_types/_template module.

Test coverage:
- SYSTEM_PROMPT constant
- AGENT_NAME constant
- AgentStepCall class reference

Author: mm-m25
"""

import unittest


class TestTemplateConstants(unittest.TestCase):
    """Test cases for template module constants."""

    def test_system_prompt_is_string(self):
        """Test SYSTEM_PROMPT is a string."""
        from topsailai.ai_base.agent_types._template import SYSTEM_PROMPT
        
        self.assertIsInstance(SYSTEM_PROMPT, str)

    def test_agent_name_is_string(self):
        """Test AGENT_NAME is a string."""
        from topsailai.ai_base.agent_types._template import AGENT_NAME
        
        self.assertIsInstance(AGENT_NAME, str)

    def test_agent_step_call_is_object(self):
        """Test AgentStepCall is an object type (placeholder)."""
        from topsailai.ai_base.agent_types._template import AgentStepCall
        
        # In template, AgentStepCall is just object (placeholder)
        self.assertIs(AgentStepCall, object)


class TestTemplateExports(unittest.TestCase):
    """Test cases for template module exports."""

    def test_all_exports_defined(self):
        """Test all items in __all__ are defined."""
        from topsailai.ai_base.agent_types._template import __all__
        
        self.assertIn("SYSTEM_PROMPT", __all__)
        self.assertIn("AGENT_NAME", __all__)
        self.assertIn("AgentStepCall", __all__)

    def test_all_exports_count(self):
        """Test __all__ contains exactly 3 items."""
        from topsailai.ai_base.agent_types._template import __all__
        
        self.assertEqual(len(__all__), 3)


if __name__ == "__main__":
    unittest.main()
