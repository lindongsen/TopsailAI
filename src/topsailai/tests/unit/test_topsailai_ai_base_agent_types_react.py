"""
Unit tests for ai_base/agent_types/react module.

Test coverage:
- SYSTEM_PROMPT constant
- AGENT_NAME constant
- Step4ReAct class

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock


class TestReActConstants(unittest.TestCase):
    """Test cases for react module constants."""

    def test_system_prompt_is_string(self):
        """Test SYSTEM_PROMPT is a string."""
        from topsailai.ai_base.agent_types.react import SYSTEM_PROMPT
        
        self.assertIsInstance(SYSTEM_PROMPT, str)

    def test_system_prompt_not_empty(self):
        """Test SYSTEM_PROMPT is not empty."""
        from topsailai.ai_base.agent_types.react import SYSTEM_PROMPT
        
        self.assertTrue(len(SYSTEM_PROMPT) > 0)

    def test_agent_name_value(self):
        """Test AGENT_NAME has correct value."""
        from topsailai.ai_base.agent_types.react import AGENT_NAME
        
        self.assertEqual(AGENT_NAME, "AgentReAct")


class TestStep4ReAct(unittest.TestCase):
    """Test cases for Step4ReAct class."""

    def test_format_action_result_dict_to_json(self):
        """Test dict result is converted to JSON string."""
        from topsailai.ai_base.agent_types.react import Step4ReAct

        instance = Step4ReAct()
        result = {"key": "value", "num": 1}
        formatted = instance._Step4ReAct__format_action_result(result)
        self.assertEqual(formatted["step_name"], "observation")
        self.assertIsInstance(formatted["raw_text"], str)
        self.assertIn('"key": "value"', formatted["raw_text"])

    def test_format_action_result_list_to_json(self):
        """Test list result is converted to JSON string."""
        from topsailai.ai_base.agent_types.react import Step4ReAct

        instance = Step4ReAct()
        result = [1, 2, 3]
        formatted = instance._Step4ReAct__format_action_result(result)
        self.assertEqual(formatted["step_name"], "observation")
        self.assertIsInstance(formatted["raw_text"], str)
        self.assertIn("1", formatted["raw_text"])

    def test_format_action_result_string_unchanged(self):
        """Test string result is preserved unchanged."""
        from topsailai.ai_base.agent_types.react import Step4ReAct

        instance = Step4ReAct()
        result = "plain text result"
        formatted = instance._Step4ReAct__format_action_result(result)
        self.assertEqual(formatted["step_name"], "observation")
        self.assertEqual(formatted["raw_text"], "plain text result")

    def test_inherits_from_step_call_tool(self):
        """Test Step4ReAct inherits from StepCallTool."""
        from topsailai.ai_base.agent_types.react import Step4ReAct
        from topsailai.ai_base.agent_types.tool import StepCallTool
        
        self.assertTrue(issubclass(Step4ReAct, StepCallTool))

    def test_can_be_instantiated(self):
        """Test Step4ReAct can be instantiated."""
        from topsailai.ai_base.agent_types.react import Step4ReAct
        
        instance = Step4ReAct()
        self.assertIsNotNone(instance)

    def test_execute_handles_final_step(self):
        """Test _execute handles 'final' step_name."""
        from topsailai.ai_base.agent_types.react import Step4ReAct
        
        instance = Step4ReAct()
        step = {"step_name": "final_answer", "raw_text": "Done"}
        
        # Should not raise
        instance._execute(step=step, tools={}, response=[step], index=0)

    def test_execute_handles_inquiry_step(self):
        """Test _execute handles 'inquiry' step_name."""
        from topsailai.ai_base.agent_types.react import Step4ReAct
        
        instance = Step4ReAct()
        step = {"step_name": "inquiry", "raw_text": "Need more info"}
        
        # Should not raise
        instance._execute(step=step, tools={}, response=[step], index=0)

    def test_execute_handles_action_step(self):
        """Test _execute handles 'action' step_name."""
        from topsailai.ai_base.agent_types.react import Step4ReAct
        
        instance = Step4ReAct()
        step = {"step_name": "action", "raw_text": "Take action"}
        
        # Should not raise
        instance._execute(step=step, tools={}, response=[step], index=0)

    def test_execute_handles_thought_step(self):
        """Test _execute handles 'thought' step_name."""
        from topsailai.ai_base.agent_types.react import Step4ReAct
        
        instance = Step4ReAct()
        step = {"step_name": "thought", "raw_text": "Thinking..."}
        
        # Should not raise
        instance._execute(step=step, tools={}, response=[step], index=0)

    def test_execute_handles_observation_step(self):
        """Test _execute handles 'observation' step_name."""
        from topsailai.ai_base.agent_types.react import Step4ReAct
        
        instance = Step4ReAct()
        step = {"step_name": "observation", "raw_text": "Result"}
        
        # Should not raise
        instance._execute(step=step, tools={}, response=[step], index=0)

    def test_execute_handles_unknown_step(self):
        """Test _execute handles unknown step_name."""
        from topsailai.ai_base.agent_types.react import Step4ReAct
        
        instance = Step4ReAct()
        step = {"step_name": "unknown", "raw_text": "Unknown step"}
        
        # Should not raise
        instance._execute(step=step, tools={}, response=[step], index=0)


class TestReActExports(unittest.TestCase):
    """Test cases for react module exports."""

    def test_all_exports_defined(self):
        """Test all items in __all__ are defined."""
        from topsailai.ai_base.agent_types.react import __all__
        
        self.assertIn("SYSTEM_PROMPT", __all__)
        self.assertIn("AGENT_NAME", __all__)
        self.assertIn("AgentStepCall", __all__)

    def test_agent_step_call_alias(self):
        """Test AgentStepCall is an alias for Step4ReAct."""
        from topsailai.ai_base.agent_types.react import AgentStepCall, Step4ReAct
        
        self.assertIs(AgentStepCall, Step4ReAct)


if __name__ == "__main__":
    unittest.main()
