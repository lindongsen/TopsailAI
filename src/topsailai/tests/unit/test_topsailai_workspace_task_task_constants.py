"""
Unit tests for workspace/task/task_constants module.

This module tests the constants defined in the TaskData class within task_tool.py.

Author: mm-m25
"""

import unittest
from topsailai.workspace.task.task_tool import TaskData


class TestTaskStatusConstants(unittest.TestCase):
    """Test class for TASK_STATUS_* constants."""

    def test_task_status_initing_defined(self):
        """Verify TASK_STATUS_INITING exists and equals expected value."""
        self.assertTrue(hasattr(TaskData, 'TASK_STATUS_INITING'))
        self.assertEqual(TaskData.TASK_STATUS_INITING, "initializing")

    def test_task_status_working_defined(self):
        """Verify TASK_STATUS_WORKING exists and equals expected value."""
        self.assertTrue(hasattr(TaskData, 'TASK_STATUS_WORKING'))
        self.assertEqual(TaskData.TASK_STATUS_WORKING, "working")

    def test_task_status_done_defined(self):
        """Verify TASK_STATUS_DONE exists and equals expected value."""
        self.assertTrue(hasattr(TaskData, 'TASK_STATUS_DONE'))
        self.assertEqual(TaskData.TASK_STATUS_DONE, "done")


class TestConstantsConsistency(unittest.TestCase):
    """Test class for constants consistency checks."""

    def test_all_status_constants_are_strings(self):
        """Verify all status constants are string type."""
        status_constants = [
            TaskData.TASK_STATUS_INITING,
            TaskData.TASK_STATUS_WORKING,
            TaskData.TASK_STATUS_DONE,
        ]
        for const in status_constants:
            self.assertIsInstance(const, str)

    def test_no_duplicate_status_values(self):
        """Verify all status constants have unique values."""
        status_values = [
            TaskData.TASK_STATUS_INITING,
            TaskData.TASK_STATUS_WORKING,
            TaskData.TASK_STATUS_DONE,
        ]
        self.assertEqual(len(status_values), len(set(status_values)))

    def test_status_constants_not_empty(self):
        """Verify all status constants are non-empty strings."""
        status_constants = [
            TaskData.TASK_STATUS_INITING,
            TaskData.TASK_STATUS_WORKING,
            TaskData.TASK_STATUS_DONE,
        ]
        for const in status_constants:
            self.assertGreater(len(const), 0)


class TestTaskDataClass(unittest.TestCase):
    """Test class for TaskData class initialization."""

    def test_task_data_has_status_constants(self):
        """Verify TaskData class has all required status constants."""
        self.assertTrue(hasattr(TaskData, 'TASK_STATUS_INITING'))
        self.assertTrue(hasattr(TaskData, 'TASK_STATUS_WORKING'))
        self.assertTrue(hasattr(TaskData, 'TASK_STATUS_DONE'))

    def test_task_data_initial_status(self):
        """Verify new TaskData instance has correct initial status."""
        task = TaskData("test_task")
        self.assertEqual(task.status, TaskData.TASK_STATUS_INITING)

    def test_task_data_status_transitions(self):
        """Verify TaskData status can be changed correctly."""
        task = TaskData("test_task")
        
        # Initial status
        self.assertEqual(task.status, TaskData.TASK_STATUS_INITING)
        
        # Transition to working
        task.status = TaskData.TASK_STATUS_WORKING
        self.assertEqual(task.status, TaskData.TASK_STATUS_WORKING)
        
        # Transition to done
        task.status = TaskData.TASK_STATUS_DONE
        self.assertEqual(task.status, TaskData.TASK_STATUS_DONE)


if __name__ == '__main__':
    unittest.main()
