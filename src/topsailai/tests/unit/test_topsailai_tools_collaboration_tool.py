"""
Unit tests for tools/collaboration_tool module.

Test coverage:
- TOOLS constant (empty dict as per source code)
- await_or_transfer_task function

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock


class TestToolsConstant(unittest.TestCase):
    """Test cases for TOOLS constant."""

    def test_tools_is_dict(self):
        """Test TOOLS is a dictionary."""
        from topsailai.tools.collaboration_tool import TOOLS
        self.assertIsInstance(TOOLS, dict)

    def test_tools_empty(self):
        """Test TOOLS is empty as per source code."""
        from topsailai.tools.collaboration_tool import TOOLS
        self.assertEqual(len(TOOLS), 0)

    def test_tools_no_await_or_transfer_task(self):
        """Test await_or_transfer_task is not in TOOLS (empty dict)."""
        from topsailai.tools.collaboration_tool import TOOLS
        self.assertNotIn('await_or_transfer_task', TOOLS)


class TestAwaitOrTransferTask(unittest.TestCase):
    """Test cases for await_or_transfer_task function."""

    def test_await_or_transfer_task_exists(self):
        """Test await_or_transfer_task function exists."""
        from topsailai.tools.collaboration_tool import await_or_transfer_task
        self.assertTrue(callable(await_or_transfer_task))

    def test_await_or_transfer_task_raises_agent_final_answer(self):
        """Test await_or_transfer_task raises AgentFinalAnswer exception."""
        from topsailai.tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        with self.assertRaises(AgentFinalAnswer) as context:
            await_or_transfer_task(task="test task")
        
        self.assertEqual(str(context.exception), "test task")

    def test_await_or_transfer_task_exception_message(self):
        """Test await_or_transfer_task exception contains task content."""
        from topsailai.tools.collaboration_tool import await_or_transfer_task
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        test_task = "complete the analysis"
        
        with self.assertRaises(AgentFinalAnswer) as context:
            await_or_transfer_task(task=test_task)
        
        self.assertIn(test_task, str(context.exception))


if __name__ == "__main__":
    unittest.main()
