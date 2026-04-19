"""
Unit tests for tools/collaboration_tool.py module.

Tests verify collaboration workflow functions including task delegation,
message passing, and error handling for collaboration scenarios.
"""

import unittest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class TestAwaitOrTransferTaskFunction(unittest.TestCase):
    """Test await_or_transfer_task function behavior."""

    def test_raises_agent_final_answer_with_task(self):
        """Verify await_or_transfer_task raises AgentFinalAnswer with task content."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        task_content = "Complete the analysis report"
        try:
            await_or_transfer_task(task_content)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer as e:
            self.assertEqual(str(e), task_content)

    def test_raises_agent_final_answer_with_empty_string(self):
        """Verify await_or_transfer_task handles empty task string."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        try:
            await_or_transfer_task("")
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer as e:
            self.assertEqual(str(e), "")

    def test_raises_agent_final_answer_with_unicode(self):
        """Verify await_or_transfer_task handles unicode task content."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        unicode_task = "任务内容：分析数据 📊"
        try:
            await_or_transfer_task(unicode_task)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer as e:
            self.assertEqual(str(e), unicode_task)

    def test_raises_agent_final_answer_with_multiline(self):
        """Verify await_or_transfer_task handles multiline task content."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        multiline_task = "Step 1: Analyze\nStep 2: Implement\nStep 3: Test"
        try:
            await_or_transfer_task(multiline_task)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer as e:
            self.assertEqual(str(e), multiline_task)

    def test_raises_agent_final_answer_with_special_chars(self):
        """Verify await_or_transfer_task handles special characters."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        special_task = "Task with <xml> & \"quotes\" and 'apostrophes'"
        try:
            await_or_transfer_task(special_task)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer as e:
            self.assertEqual(str(e), special_task)

    def test_raises_agent_final_answer_with_long_task(self):
        """Verify await_or_transfer_task handles long task content."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        long_task = "A" * 10000
        try:
            await_or_transfer_task(long_task)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer as e:
            self.assertEqual(str(e), long_task)


class TestFinishTaskFunction(unittest.TestCase):
    """Test finish_task function behavior."""

    def test_raises_bug_exception(self):
        """Verify finish_task raises BUG exception indicating improper usage."""
        from tools.collaboration_tool import finish_task
        
        try:
            finish_task("Final answer content")
            self.fail("Expected exception to be raised")
        except Exception as e:
            self.assertEqual(str(e), "BUG: no need execute the tool")

    def test_raises_bug_exception_with_empty_string(self):
        """Verify finish_task handles empty final answer."""
        from tools.collaboration_tool import finish_task
        
        try:
            finish_task("")
            self.fail("Expected exception to be raised")
        except Exception as e:
            self.assertEqual(str(e), "BUG: no need execute the tool")

    def test_raises_bug_exception_with_unicode(self):
        """Verify finish_task handles unicode final answer."""
        from tools.collaboration_tool import finish_task
        
        try:
            finish_task("最终答案：完成 ✅")
            self.fail("Expected exception to be raised")
        except Exception as e:
            self.assertEqual(str(e), "BUG: no need execute the tool")

    def test_bug_exception_message_is_static(self):
        """Verify bug exception message is consistent."""
        from tools.collaboration_tool import finish_task
        
        messages = ["answer1", "answer2", "answer3"]
        for msg in messages:
            try:
                finish_task(msg)
                self.fail("Expected exception to be raised")
            except Exception as e:
                self.assertEqual(str(e), "BUG: no need execute the tool")


class TestToolsConstant(unittest.TestCase):
    """Test TOOLS constant definition."""

    def test_tools_is_dict(self):
        """Verify TOOLS is a dictionary."""
        from tools.collaboration_tool import TOOLS
        self.assertIsInstance(TOOLS, dict)

    def test_tools_contains_await_or_transfer_task(self):
        """Verify TOOLS contains await_or_transfer_task key."""
        from tools.collaboration_tool import TOOLS
        self.assertIn("await_or_transfer_task", TOOLS)

    def test_tools_value_is_callable(self):
        """Verify TOOLS value is a callable function."""
        from tools.collaboration_tool import TOOLS
        self.assertTrue(callable(TOOLS.get("await_or_transfer_task")))

    def test_tools_single_entry(self):
        """Verify TOOLS contains exactly one entry."""
        from tools.collaboration_tool import TOOLS
        self.assertEqual(len(TOOLS), 1)


class TestFlagToolEnabled(unittest.TestCase):
    """Test FLAG_TOOL_ENABLED constant."""

    def test_flag_tool_enabled_is_boolean(self):
        """Verify FLAG_TOOL_ENABLED is a boolean."""
        from tools.collaboration_tool import FLAG_TOOL_ENABLED
        self.assertIsInstance(FLAG_TOOL_ENABLED, bool)

    def test_flag_tool_enabled_is_false_by_default(self):
        """Verify FLAG_TOOL_ENABLED defaults to False."""
        from tools.collaboration_tool import FLAG_TOOL_ENABLED
        self.assertFalse(FLAG_TOOL_ENABLED)


class TestPromptConstant(unittest.TestCase):
    """Test PROMPT constant."""

    def test_prompt_is_string(self):
        """Verify PROMPT is a string."""
        from tools.collaboration_tool import PROMPT
        self.assertIsInstance(PROMPT, str)

    def test_prompt_is_not_empty(self):
        """Verify PROMPT is not empty."""
        from tools.collaboration_tool import PROMPT
        self.assertTrue(len(PROMPT) > 0)

    def test_prompt_contains_collaboration_keywords(self):
        """Verify PROMPT contains collaboration-related content."""
        from tools.collaboration_tool import PROMPT
        # Check for common collaboration-related keywords
        keywords = ["collaboration", "team", "agent", "task"]
        prompt_lower = PROMPT.lower()
        found_keywords = [kw for kw in keywords if kw in prompt_lower]
        self.assertTrue(len(found_keywords) > 0,
                       f"PROMPT should contain collaboration keywords, found: {found_keywords}")


class TestModuleExports(unittest.TestCase):
    """Test module exports and accessibility."""

    def test_await_or_transfer_task_importable(self):
        """Verify await_or_transfer_task can be imported directly."""
        from tools.collaboration_tool import await_or_transfer_task
        self.assertTrue(callable(await_or_transfer_task))

    def test_finish_task_importable(self):
        """Verify finish_task can be imported directly."""
        from tools.collaboration_tool import finish_task
        self.assertTrue(callable(finish_task))

    def test_action_finish_task_defined(self):
        """Verify ACTION_FINISH_TASK constant is defined."""
        from tools.collaboration_tool import ACTION_FINISH_TASK
        self.assertEqual(ACTION_FINISH_TASK, "await_or_transfer_task")


class TestCollaborationWorkflow(unittest.TestCase):
    """Test collaboration workflow scenarios."""

    def test_task_delegation_scenario(self):
        """Test typical task delegation workflow."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        # Simulate task delegation
        task = "awaiting something from x; execute the next step by x;"
        try:
            await_or_transfer_task(task)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer as e:
            self.assertIsInstance(str(e), str)

    def test_stage_completion_scenario(self):
        """Test stage/step completion scenario."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        # Simulate stage completion
        task = "Step 1 completed, proceeding to Step 2"
        try:
            await_or_transfer_task(task)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer as e:
            self.assertIn("Step 1", str(e))

    def test_handoff_scenario(self):
        """Test agent handoff scenario."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        # Simulate agent handoff
        task = "Transferring to @AIMember.km-k25 for review"
        try:
            await_or_transfer_task(task)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer as e:
            self.assertIn("km-k25", str(e))


class TestErrorHandling(unittest.TestCase):
    """Test error handling scenarios."""

    def test_invalid_task_type_none(self):
        """Test handling of None task (should still raise)."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        try:
            await_or_transfer_task(None)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer:
            pass  # Expected

    def test_invalid_task_type_int(self):
        """Test handling of integer task (should still raise)."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        try:
            await_or_transfer_task(123)
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer:
            pass  # Expected

    def test_invalid_task_type_list(self):
        """Test handling of list task (should still raise)."""
        from tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        try:
            await_or_transfer_task(["task1", "task2"])
            self.fail("Expected AgentFinalAnswer to be raised")
        except AgentFinalAnswer:
            pass  # Expected


if __name__ == '__main__':
    unittest.main()
