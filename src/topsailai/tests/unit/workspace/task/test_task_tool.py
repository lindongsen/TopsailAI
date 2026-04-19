"""
Unit tests for workspace/task/task_tool module.

Test coverage:
- TaskData class initialization and properties
- TaskUtil class methods (load, dump, lock/unlock)
- ctxm_process_task context manager
- Edge cases and exception handling

Author: mm-m25
"""

import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch, mock_open


class TestImports(unittest.TestCase):
    """Test cases for module imports."""

    def test_import_task_data(self):
        """Test TaskData can be imported."""
        from topsailai.workspace.task.task_tool import TaskData
        self.assertTrue(callable(TaskData))

    def test_import_task_util(self):
        """Test TaskUtil can be imported."""
        from topsailai.workspace.task.task_tool import TaskUtil
        self.assertTrue(callable(TaskUtil))

    def test_import_generate_task_id(self):
        """Test generate_task_id can be imported."""
        from topsailai.workspace.task.task_tool import generate_task_id
        self.assertTrue(callable(generate_task_id))

    def test_import_ctxm_process_task(self):
        """Test ctxm_process_task can be imported."""
        from topsailai.workspace.task.task_tool import ctxm_process_task
        self.assertTrue(callable(ctxm_process_task))


class TestGenerateTaskId(unittest.TestCase):
    """Test cases for generate_task_id function."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_generate_task_id_with_session(self):
        """Test generate_task_id returns expected format with session ID."""
        from topsailai.workspace.task.task_tool import generate_task_id
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = "test_session_123"
                mock_time.get_current_date.return_value = "2026-04-19"
                
                result = generate_task_id()
                
                self.assertEqual(result, "test_session_123.2026-04-19")
                mock_env.get_session_id.assert_called_once()
                mock_time.get_current_date.assert_called_once_with(True)

    def test_generate_task_id_without_session(self):
        """Test generate_task_id uses default prefix when no session ID."""
        from topsailai.workspace.task.task_tool import generate_task_id
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19"
                
                result = generate_task_id()
                
                self.assertEqual(result, "topsailai.2026-04-19")

    def test_generate_task_id_format(self):
        """Test generate_task_id returns string in correct format."""
        from topsailai.workspace.task.task_tool import generate_task_id
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = "session"
                mock_time.get_current_date.return_value = "2026-04-19"
                
                result = generate_task_id()
                
                self.assertIsInstance(result, str)
                self.assertIn(".", result)
                parts = result.split(".")
                self.assertEqual(len(parts), 2)


class TestTaskDataInit(unittest.TestCase):
    """Test cases for TaskData initialization."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_init_with_task_id(self):
        """Test TaskData initialization with valid task_id."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = "test_session"
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_001")
                
                self.assertEqual(task.task_id, "task_001")
                self.assertTrue(task.task_file.endswith("/task_001.task"))
                self.assertIsNone(task.task_content)
                self.assertEqual(task.session_id, "test_session")
                self.assertEqual(task.session_messages, [])
                self.assertEqual(task.status, TaskData.TASK_STATUS_INITING)
                self.assertIsNone(task.result)

    def test_init_status_constants(self):
        """Test TaskData status constants are defined correctly."""
        from topsailai.workspace.task.task_tool import TaskData
        self.assertEqual(TaskData.TASK_STATUS_INITING, "initializing")
        self.assertEqual(TaskData.TASK_STATUS_WORKING, "working")
        self.assertEqual(TaskData.TASK_STATUS_DONE, "done")

    def test_init_without_session(self):
        """Test TaskData initialization when no session ID is available."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_002")
                
                self.assertEqual(task.session_id, "")


class TestTaskDataManifest(unittest.TestCase):
    """Test cases for TaskData.manifest property."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_manifest_format(self):
        """Test manifest returns valid YAML format."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_003")
                manifest = task.manifest
                
                self.assertIn("---", manifest)
                self.assertIn("task_id: task_003", manifest)
                self.assertIn("status: initializing", manifest)

    def test_manifest_updates_with_status(self):
        """Test manifest reflects current status."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_004")
                task.status = TaskData.TASK_STATUS_WORKING
                manifest = task.manifest
                
                self.assertIn("status: working", manifest)


class TestTaskDataMethods(unittest.TestCase):
    """Test cases for TaskData conversion methods."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_to_dict(self):
        """Test to_dict returns correct dictionary structure."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = "session_abc"
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_005")
                task.task_content = "Test content"
                task.session_messages = [{"role": "user", "content": "hello"}]
                
                result = task.to_dict()
                
                self.assertEqual(result["task_id"], "task_005")
                self.assertEqual(result["task_content"], "Test content")
                self.assertEqual(result["session_id"], "session_abc")
                self.assertEqual(result["session_messages"], [{"role": "user", "content": "hello"}])
                self.assertEqual(result["create_time"], "2026-04-19T10:00:00")

    def test_to_json(self):
        """Test to_json returns valid JSON string."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = "session_abc"
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_006")
                task.task_content = "Test content"
                
                result = task.to_json()
                
                self.assertIsInstance(result, str)
                parsed = json.loads(result)
                self.assertEqual(parsed["task_id"], "task_006")
                self.assertEqual(parsed["task_content"], "Test content")

    def test_to_json_empty_content(self):
        """Test to_json handles None task_content."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = "session_abc"
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_007")
                
                result = task.to_json()
                parsed = json.loads(result)
                
                self.assertIsNone(parsed["task_content"])


class TestTaskUtilLoad(unittest.TestCase):
    """Test cases for TaskUtil.load method."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_load_success(self):
        """Test load successfully loads task data from file."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_008")
                task.task_file = "/tmp/test_task_008.task"
                
                json_content = json.dumps({
                    "task_content": "Loaded content",
                    "session_id": "loaded_session",
                    "session_messages": [{"role": "assistant", "content": "hi"}],
                    "create_time": "2026-04-19T09:00:00"
                })
                
                with patch('builtins.open', mock_open(read_data=json_content)):
                    with patch('topsailai.workspace.task.task_tool.json_tool') as mock_json:
                        mock_json.safe_json_load.return_value = {
                            "task_content": "Loaded content",
                            "session_id": "loaded_session",
                            "session_messages": [{"role": "assistant", "content": "hi"}],
                            "create_time": "2026-04-19T09:00:00"
                        }
                        
                        result = task.load()
                        
                        self.assertTrue(result)
                        self.assertEqual(task.task_content, "Loaded content")
                        self.assertEqual(task.session_id, "loaded_session")
                        self.assertEqual(task.session_messages, [{"role": "assistant", "content": "hi"}])

    def test_load_empty_file(self):
        """Test load returns False for empty file."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_009")
                task.task_file = "/tmp/test_task_009.task"
                
                with patch('builtins.open', mock_open(read_data="")):
                    result = task.load()
                    
                    self.assertFalse(result)

    def test_load_invalid_json(self):
        """Test load returns False for invalid JSON."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_010")
                task.task_file = "/tmp/test_task_010.task"
                
                with patch('builtins.open', mock_open(read_data="invalid json")):
                    with patch('topsailai.workspace.task.task_tool.json_tool') as mock_json:
                        mock_json.safe_json_load.return_value = None
                        
                        result = task.load()
                        
                        self.assertFalse(result)


class TestTaskUtilDump(unittest.TestCase):
    """Test cases for TaskUtil.dump method."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_dump_with_file_pointer(self):
        """Test dump writes to provided file pointer."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_011")
                task.task_content = "Dump content"
                
                mock_fp = MagicMock()
                result = task.dump(mock_fp)
                
                self.assertTrue(result)
                mock_fp.write.assert_called_once()
                mock_fp.flush.assert_called_once()

    def test_dump_creates_new_file(self):
        """Test dump creates new file when no file pointer provided."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_012")
                task.task_content = "New file content"
                task.task_file = "/tmp/test_task_012.task"
                
                with patch('os.path.exists', return_value=False):
                    with patch('builtins.open', mock_open()) as mock_file:
                        result = task.dump(None)
                        
                        self.assertTrue(result)
                        mock_file.assert_called_once()

    def test_dump_file_exists_raises(self):
        """Test dump raises assertion when file already exists."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_013")
                task.task_file = "/tmp/test_task_013.task"
                
                with patch('os.path.exists', return_value=True):
                    with self.assertRaises(AssertionError) as context:
                        task.dump(None)
                    
                    self.assertIn("The task file exists", str(context.exception))


class TestTaskUtilLockMethods(unittest.TestCase):
    """Test cases for TaskUtil lock-related methods."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_pre_lock_creates_file(self):
        """Test pre_lock creates file if it doesn't exist."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_014")
                task.task_file = "/tmp/test_task_014.task"
                
                with patch('os.path.exists', return_value=False):
                    with patch('topsailai.workspace.task.task_tool.write_text') as mock_write:
                        task.pre_lock()
                        
                        mock_write.assert_called_once_with("/tmp/test_task_014.task", "")

    def test_pre_lock_file_exists(self):
        """Test pre_lock does nothing if file already exists."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_015")
                task.task_file = "/tmp/test_task_015.task"
                
                with patch('os.path.exists', return_value=True):
                    with patch('topsailai.workspace.task.task_tool.write_text') as mock_write:
                        task.pre_lock()
                        
                        mock_write.assert_not_called()

    def test_post_lock_with_content(self):
        """Test post_lock dumps content when task_content exists."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_016")
                task.task_content = "Content to dump"
                
                mock_fp = MagicMock()
                task.post_lock(mock_fp)
                
                self.assertEqual(task.status, TaskUtil.TASK_STATUS_WORKING)
                mock_fp.write.assert_called_once()

    def test_post_lock_without_content(self):
        """Test post_lock loads data when no task_content."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_017")
                task.task_file = "/tmp/test_task_017.task"
                
                mock_fp = MagicMock()
                with patch.object(task, 'load', return_value=True) as mock_load:
                    task.post_lock(mock_fp)
                    
                    mock_load.assert_called_once()

    def test_pre_unlock_with_result(self):
        """Test pre_unlock sets status to done when result exists."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_018")
                task.result = "Task completed successfully"
                
                mock_fp = MagicMock()
                task.pre_unlock(mock_fp)
                
                self.assertEqual(task.status, TaskUtil.TASK_STATUS_DONE)

    def test_pre_unlock_without_result(self):
        """Test pre_unlock keeps current status when no result."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_019")
                task.status = TaskUtil.TASK_STATUS_WORKING
                
                mock_fp = MagicMock()
                task.pre_unlock(mock_fp)
                
                self.assertEqual(task.status, TaskUtil.TASK_STATUS_WORKING)

    def test_post_unlock_deletes_file_when_done(self):
        """Test post_unlock deletes file when status is done."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_020")
                task.status = TaskUtil.TASK_STATUS_DONE
                
                with patch('topsailai.workspace.task.task_tool.delete_file') as mock_delete:
                    task.post_unlock()
                    
                    mock_delete.assert_called_once()

    def test_post_unlock_keeps_file_when_not_done(self):
        """Test post_unlock does not delete file when status is not done."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_021")
                task.status = TaskUtil.TASK_STATUS_WORKING
                
                with patch('topsailai.workspace.task.task_tool.delete_file') as mock_delete:
                    task.post_unlock()
                    
                    mock_delete.assert_not_called()


class TestCtxmProcessTask(unittest.TestCase):
    """Test cases for ctxm_process_task context manager."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_context_manager_with_none_task(self):
        """Test ctxm_process_task handles None task gracefully."""
        from topsailai.workspace.task.task_tool import ctxm_process_task
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                with ctxm_process_task(None) as fp:
                    self.assertIsNone(fp)

    def test_context_manager_lock_failure(self):
        """Test ctxm_process_task handles lock failure."""
        from topsailai.workspace.task.task_tool import ctxm_process_task, TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_023")
                task.task_file = "/tmp/test_task_023.task"
                
                with patch.object(task, 'pre_lock'):
                    with patch('topsailai.workspace.task.task_tool.ctxm_try_file_lock') as mock_lock:
                        mock_lock.return_value.__enter__ = MagicMock(return_value=None)
                        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
                        
                        with self.assertRaises(AssertionError) as context:
                            with ctxm_process_task(task):
                                pass
                        
                        self.assertIn("lock task file failed", str(context.exception))


class TestEdgeCases(unittest.TestCase):
    """Edge case tests."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_empty_task_id(self):
        """Test TaskData with empty task_id."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("")
                
                self.assertEqual(task.task_id, "")
                self.assertIn(".task", task.task_file)

    def test_special_characters_in_task_id(self):
        """Test TaskData with special characters in task_id."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task.with.dots.and_underscores")
                
                self.assertEqual(task.task_id, "task.with.dots.and_underscores")

    def test_unicode_content(self):
        """Test TaskData handles unicode content."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_unicode")
                task.task_content = "Hello 世界 🌍"
                
                result = task.to_dict()
                self.assertIn("Hello 世界 🌍", result["task_content"])

    def test_large_session_messages(self):
        """Test TaskData handles large session messages list."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_large")
                task.session_messages = [{"role": f"role_{i}", "content": f"msg_{i}"} for i in range(100)]
                
                result = task.to_dict()
                self.assertEqual(len(result["session_messages"]), 100)


class TestExceptionHandling(unittest.TestCase):
    """Exception handling tests."""

    def setUp(self):
        """Set up test environment."""
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def test_to_json_with_complex_object(self):
        """Test to_json handles complex objects gracefully."""
        from topsailai.workspace.task.task_tool import TaskData
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskData("task_complex")
                task.task_content = {"nested": {"data": [1, 2, 3]}}
                
                result = task.to_json()
                parsed = json.loads(result)
                
                self.assertEqual(parsed["task_content"]["nested"]["data"], [1, 2, 3])

    def test_load_with_complete_data(self):
        """Test load handles complete JSON data correctly."""
        from topsailai.workspace.task.task_tool import TaskUtil
        with patch('topsailai.workspace.task.task_tool.env_tool') as mock_env:
            with patch('topsailai.workspace.task.task_tool.time_tool') as mock_time:
                mock_env.get_session_id.return_value = None
                mock_time.get_current_date.return_value = "2026-04-19T10:00:00"
                
                task = TaskUtil("task_complete")
                task.task_file = "/tmp/test_task_complete.task"
                
                complete_json = json.dumps({
                    "task_content": "content only",
                    "session_id": "session_123",
                    "session_messages": [],
                    "create_time": "2026-04-19T09:00:00"
                })
                
                with patch('builtins.open', mock_open(read_data=complete_json)):
                    with patch('topsailai.workspace.task.task_tool.json_tool') as mock_json:
                        mock_json.safe_json_load.return_value = {
                            "task_content": "content only",
                            "session_id": "session_123",
                            "session_messages": [],
                            "create_time": "2026-04-19T09:00:00"
                        }
                        
                        result = task.load()
                        
                        self.assertTrue(result)
                        self.assertEqual(task.task_content, "content only")
                        self.assertEqual(task.session_id, "session_123")


if __name__ == '__main__':
    unittest.main()
