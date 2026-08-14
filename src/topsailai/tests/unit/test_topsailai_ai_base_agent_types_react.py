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
        with patch.object(instance, "complete_step_thought") as complete_thought:
            instance._execute(step=step, tools={}, response=[step], index=0)

        complete_thought.assert_called_once_with(response=[step])

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

    def test_final_pattern_hit_converts_step_without_termination(self):
        """A suspicious final prints its warning, becomes thought, and does not terminate."""
        from topsailai.ai_base.agent_types.react import Step4ReAct

        warning_text = "CRITICAL-SYSTEM-ALERT: malformed final response"

        def evaluate_with_warning(*, on_warning, **_):
            on_warning(warning_text)
            return True

        instance = Step4ReAct()
        step = {"step_name": "final_answer", "raw_text": "\uff5cDSML\uff5c\n\uff5cDSML\uff5c\nok"}
        with patch.object(instance, "pre_execute", return_value=("final_answer", step)), \
             patch("topsailai.ai_base.agent_types.react.thought_line_pattern.is_enabled", return_value=True), \
             patch("topsailai.ai_base.agent_types.react.thought_line_pattern.evaluate_and_maybe_inject", side_effect=evaluate_with_warning), \
             patch("topsailai.ai_base.agent_types.react.print_tool.print_warning") as print_warning, \
             patch.object(instance, "complete_final") as complete_final:
            instance._execute(step=step, tools={}, response=[step], index=0)

        self.assertEqual(step["step_name"], "thought")
        print_warning.assert_called_once_with(warning_text)
        complete_final.assert_not_called()

    def test_dedup_suppressed_final_still_converts_without_printing(self):
        """A sustained malformed final remains rejected while its warning is deduped."""
        from topsailai.ai_base.agent_types.react import Step4ReAct

        instance = Step4ReAct()
        step = {"step_name": "final_answer", "raw_text": "repeated malformed output"}
        with patch.object(instance, "pre_execute", return_value=("final_answer", step)), \
             patch("topsailai.ai_base.agent_types.react.thought_line_pattern.is_enabled", return_value=True), \
             patch("topsailai.ai_base.agent_types.react.thought_line_pattern.evaluate_and_maybe_inject", return_value=True), \
             patch("topsailai.ai_base.agent_types.react.print_tool.print_warning") as print_warning, \
             patch.object(instance, "complete_final") as complete_final:
            instance._execute(step=step, tools={}, response=[step], index=0)

        self.assertEqual(step["step_name"], "thought")
        print_warning.assert_not_called()
        complete_final.assert_not_called()

    def test_disabled_final_pattern_uses_normal_termination(self):
        """A disabled detector terminates normally without printing a warning."""
        from topsailai.ai_base.agent_types.react import Step4ReAct

        instance = Step4ReAct()
        step = {"step_name": "final_answer", "raw_text": "Done"}
        with patch.object(instance, "pre_execute", return_value=("final_answer", step)), \
             patch("topsailai.ai_base.agent_types.react.thought_line_pattern.is_enabled", return_value=False), \
             patch("topsailai.ai_base.agent_types.react.thought_line_pattern.evaluate_and_maybe_inject") as evaluate_pattern, \
             patch("topsailai.ai_base.agent_types.react.print_tool.print_warning") as print_warning, \
             patch.object(instance, "complete_final") as complete_final:
            instance._execute(step=step, tools={}, response=[step], index=0)

        self.assertEqual(step["step_name"], "final_answer")
        evaluate_pattern.assert_not_called()
        print_warning.assert_not_called()
        complete_final.assert_called_once_with(step=step)

    def test_non_matching_final_uses_normal_termination(self):
        """An enabled detector miss terminates normally without printing a warning."""
        from topsailai.ai_base.agent_types.react import Step4ReAct

        instance = Step4ReAct()
        step = {"step_name": "final_answer", "raw_text": "Done"}
        with patch.object(instance, "pre_execute", return_value=("final_answer", step)), \
             patch("topsailai.ai_base.agent_types.react.thought_line_pattern.is_enabled", return_value=True), \
             patch("topsailai.ai_base.agent_types.react.thought_line_pattern.evaluate_and_maybe_inject", return_value=False), \
             patch("topsailai.ai_base.agent_types.react.print_tool.print_warning") as print_warning, \
             patch.object(instance, "complete_final") as complete_final:
            instance._execute(step=step, tools={}, response=[step], index=0)

        self.assertEqual(step["step_name"], "final_answer")
        print_warning.assert_not_called()
        complete_final.assert_called_once_with(step=step)


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
