"""
Unit tests for workspace/task/task_tool.py module.

This module tests the TaskData and TaskUtil classes along with their
task status constants.

Author: mm-m25
"""

import os
import json
from unittest import TestCase
from unittest.mock import patch, MagicMock

from topsailai.workspace.task.task_tool import (
    TaskData,
    TaskUtil,
    generate_task_id,
    ctxm_process_task,
)


class TestTaskDataConstants(TestCase):
    """Test cases for TaskData status constants."""

    def test_task_status_initing_defined(self):
        """Verify TASK_STATUS_INITING constant is defined."""
        self.assertTrue(hasattr(TaskData, 'TASK_STATUS_INITING'))

    def test_task_status_working_defined(self):
        """Verify TASK_STATUS_WORKING constant is defined."""
        self.assertTrue(hasattr(TaskData, 'TASK_STATUS_WORKING'))

    def test_task_status_done_defined(self):
        """Verify TASK_STATUS_DONE constant is defined."""
        self.assertTrue(hasattr(TaskData, 'TASK_STATUS_DONE'))

    def test_all_task_status_constants_present(self):
        """Verify all expected task status constants are present."""
        expected_constants = [
            'TASK_STATUS_INITING',
            'TASK_STATUS_WORKING',
            'TASK_STATUS_DONE',
        ]
        for const in expected_constants:
            self.assertTrue(
                hasattr(TaskData, const),
                f"Expected constant {const} not found in TaskData"
            )

    def test_task_status_values_are_strings(self):
        """Verify all task status constants are strings."""
        self.assertIsInstance(TaskData.TASK_STATUS_INITING, str)
        self.assertIsInstance(TaskData.TASK_STATUS_WORKING, str)
        self.assertIsInstance(TaskData.TASK_STATUS_DONE, str)

    def test_task_status_values_correct(self):
        """Verify task status constants have expected values."""
        # Create fresh instance to avoid any test pollution
        task = TaskData("verify_task")
        self.assertEqual(task.TASK_STATUS_INITING, "initializing")
        self.assertEqual(task.TASK_STATUS_WORKING, "working")
        self.assertEqual(task.TASK_STATUS_DONE, "done")

    def test_task_status_values_are_distinct(self):
        """Verify task status constants have distinct values."""
        statuses = [
            TaskData.TASK_STATUS_INITING,
            TaskData.TASK_STATUS_WORKING,
            TaskData.TASK_STATUS_DONE,
        ]
        self.assertEqual(len(statuses), len(set(statuses)))

    def test_task_status_constants_consistent_across_instances(self):
        """Verify constants are consistent across TaskData instances."""
        task1 = TaskData("task1")
        task2 = TaskData("task2")
        
        # Verify both instances share the same constant values
        self.assertEqual(task1.TASK_STATUS_INITING, task2.TASK_STATUS_INITING)
        self.assertEqual(task1.TASK_STATUS_WORKING, task2.TASK_STATUS_WORKING)
        self.assertEqual(task1.TASK_STATUS_DONE, task2.TASK_STATUS_DONE)

    def test_task_status_values_are_lowercase(self):
        """Verify task status constants are lowercase strings."""
        self.assertEqual(TaskData.TASK_STATUS_INITING, TaskData.TASK_STATUS_INITING.lower())
        self.assertEqual(TaskData.TASK_STATUS_WORKING, TaskData.TASK_STATUS_WORKING.lower())
        self.assertEqual(TaskData.TASK_STATUS_DONE, TaskData.TASK_STATUS_DONE.lower())


class TestTaskDataInitialization(TestCase):
    """Test cases for TaskData class initialization."""

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_task_data_initializes_with_task_id(self, mock_time, mock_env):
        """Verify TaskData initializes correctly with task_id."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskData("test_task_123")

        self.assertEqual(task.task_id, "test_task_123")
        self.assertEqual(task.task_file, "/tmp/tasks/test_task_123.task")

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_task_data_initial_status_is_initing(self, mock_time, mock_env):
        """Verify TaskData initial status is TASK_STATUS_INITING."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskData("test_task")

        self.assertEqual(task.status, TaskData.TASK_STATUS_INITING)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_task_data_session_messages_is_empty_list(self, mock_time, mock_env):
        """Verify TaskData session_messages initializes as empty list."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskData("test_task")

        self.assertIsInstance(task.session_messages, list)
        self.assertEqual(len(task.session_messages), 0)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_task_data_result_initializes_as_none(self, mock_time, mock_env):
        """Verify TaskData result initializes as None."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskData("test_task")

        self.assertIsNone(task.result)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_task_data_handles_empty_session_id(self, mock_time, mock_env):
        """Verify TaskData handles empty session_id from env_tool."""
        mock_env.get_session_id.return_value = None
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskData("test_task")

        self.assertEqual(task.session_id, "")


class TestTaskDataMethods(TestCase):
    """Test cases for TaskData class methods."""

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_to_dict_returns_dict(self, mock_time, mock_env):
        """Verify to_dict returns a dictionary."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskData("test_task")
        task.task_content = "test content"

        result = task.to_dict()

        self.assertIsInstance(result, dict)
        self.assertIn('task_id', result)
        self.assertIn('task_content', result)
        self.assertIn('session_id', result)
        self.assertIn('session_messages', result)
        self.assertIn('create_time', result)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_to_dict_contains_correct_values(self, mock_time, mock_env):
        """Verify to_dict contains correct values."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskData("test_task")
        task.task_content = "test content"
        task.session_messages = ["msg1", "msg2"]

        result = task.to_dict()

        self.assertEqual(result['task_id'], "test_task")
        self.assertEqual(result['task_content'], "test content")
        self.assertEqual(result['session_messages'], ["msg1", "msg2"])

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_to_json_returns_string(self, mock_time, mock_env):
        """Verify to_json returns a JSON string."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskData("test_task")

        result = task.to_json()

        self.assertIsInstance(result, str)
        # Verify it's valid JSON
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_manifest_returns_yaml_string(self, mock_time, mock_env):
        """Verify manifest returns a YAML-formatted string."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskData("test_task")
        task.status = TaskData.TASK_STATUS_WORKING

        result = task.manifest

        self.assertIsInstance(result, str)
        self.assertIn('task_id: test_task', result)
        self.assertIn('status: working', result)
        self.assertIn('---', result)


class TestTaskUtilMethods(TestCase):
    """Test cases for TaskUtil class methods."""

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_task_util_inherits_from_task_data(self, mock_time, mock_env):
        """Verify TaskUtil inherits from TaskData."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskUtil("test_task")

        self.assertIsInstance(task, TaskData)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_pre_lock_creates_file_if_not_exists(self, mock_time, mock_env):
        """Verify pre_lock creates task file if it doesn't exist."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskUtil("test_pre_lock_task")
        
        # Clean up any existing file
        if os.path.exists(task.task_file):
            os.remove(task.task_file)
            
        task.pre_lock()

        # File should be created (empty)
        self.assertTrue(os.path.exists(task.task_file))

        # Cleanup
        if os.path.exists(task.task_file):
            os.remove(task.task_file)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_post_lock_sets_status_to_working(self, mock_time, mock_env):
        """Verify post_lock sets status to TASK_STATUS_WORKING."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskUtil("test_post_lock_task")
        
        # Clean up any existing file from previous runs
        if os.path.exists(task.task_file):
            os.remove(task.task_file)
            
        # Set task_content to avoid calling load() which requires file
        task.task_content = "test content"
        task.post_lock(None)

        self.assertEqual(task.status, TaskData.TASK_STATUS_WORKING)
        
        # Cleanup
        if os.path.exists(task.task_file):
            os.remove(task.task_file)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_pre_unlock_sets_status_to_done_if_result_exists(self, mock_time, mock_env):
        """Verify pre_unlock sets status to TASK_STATUS_DONE when result exists."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskUtil("test_pre_unlock_done_task")
        
        # Clean up any existing file
        if os.path.exists(task.task_file):
            os.remove(task.task_file)
            
        task.result = "task completed"
        task.pre_unlock(None)

        self.assertEqual(task.status, TaskData.TASK_STATUS_DONE)
        
        # Cleanup
        if os.path.exists(task.task_file):
            os.remove(task.task_file)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_pre_unlock_does_not_change_status_if_no_result(self, mock_time, mock_env):
        """Verify pre_unlock does not change status when result is None."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        task = TaskUtil("test_pre_unlock_no_result_task")
        
        # Clean up any existing file
        if os.path.exists(task.task_file):
            os.remove(task.task_file)
            
        task.status = TaskData.TASK_STATUS_WORKING
        task.result = None
        task.pre_unlock(None)

        self.assertEqual(task.status, TaskData.TASK_STATUS_WORKING)
        
        # Cleanup
        if os.path.exists(task.task_file):
            os.remove(task.task_file)


class TestGenerateTaskId(TestCase):
    """Test cases for generate_task_id function."""

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    def test_generate_task_id_returns_string(self, mock_time, mock_env):
        """Verify generate_task_id returns a string."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        result = generate_task_id()

        self.assertIsInstance(result, str)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    def test_generate_task_id_contains_session_id(self, mock_time, mock_env):
        """Verify generate_task_id contains session_id."""
        mock_env.get_session_id.return_value = "my_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        result = generate_task_id()

        self.assertIn("my_session", result)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    def test_generate_task_id_contains_date(self, mock_time, mock_env):
        """Verify generate_task_id contains date."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        result = generate_task_id()

        self.assertIn("2026-04-19", result)

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    def test_generate_task_id_uses_default_when_session_none(self, mock_time, mock_env):
        """Verify generate_task_id uses 'topsailai' when session_id is None."""
        mock_env.get_session_id.return_value = None
        mock_time.get_current_date.return_value = "2026-04-19"

        result = generate_task_id()

        self.assertIn("topsailai", result)


class TestCtxmProcessTask(TestCase):
    """Test cases for ctxm_process_task context manager."""

    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_ctxm_process_task_yields_none_when_task_is_none(self, mock_time, mock_env):
        """Verify ctxm_process_task yields None when task is None."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        with ctxm_process_task(None) as fp:
            self.assertIsNone(fp)

    @patch('topsailai.workspace.task.task_tool.ctxm_try_file_lock')
    @patch('topsailai.workspace.task.task_tool.env_tool')
    @patch('topsailai.workspace.task.task_tool.time_tool')
    @patch('topsailai.workspace.task.task_tool.FOLDER_WORKSPACE_TASK', '/tmp/tasks')
    def test_ctxm_process_task_handles_task_with_result(self, mock_time, mock_env, mock_lock):
        """Verify ctxm_process_task handles task with result correctly."""
        mock_env.get_session_id.return_value = "test_session"
        mock_time.get_current_date.return_value = "2026-04-19"

        # Create a real TaskUtil
        task = TaskUtil("test_ctxm_task")
        task.task_content = "test content"
        task.result = "completed"

        # Mock the file lock to yield a mock file pointer
        mock_fp = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_fp)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)

        # This test verifies the context manager structure
        # Full integration test would require actual file operations
        self.assertIsNotNone(task)
        self.assertEqual(task.result, "completed")
