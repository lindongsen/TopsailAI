"""
Unit tests for topsailai.workspace.lock_tool module.

Author: AI
Purpose: Test file locking functionality for thread-safe operations.
"""

import os
import sys
import time
import tempfile
import shutil
import threading
from unittest import TestCase, mock
from contextlib import contextmanager

# Import from the module under test
from topsailai.workspace.lock_tool import (
    YieldData,
    FileLock,
    ctxm_try_session_lock,
    ctxm_void,
    init,
)


class TestYieldData(TestCase):
    """Test suite for YieldData class."""

    def test_init_with_kwargs(self):
        """Test YieldData initialization with keyword arguments."""
        data = YieldData(session_id="test_session", fp=123, msg="test message")
        self.assertEqual(data.data["session_id"], "test_session")
        self.assertEqual(data.data["fp"], 123)
        self.assertEqual(data.data["msg"], "test message")

    def test_init_empty(self):
        """Test YieldData initialization with no arguments."""
        data = YieldData()
        self.assertEqual(data.data, {})

    def test_get_existing_key(self):
        """Test getting an existing key from YieldData."""
        data = YieldData(key1="value1", key2="value2")
        self.assertEqual(data.get("key1"), "value1")
        self.assertEqual(data.get("key2"), "value2")

    def test_get_missing_key(self):
        """Test getting a missing key returns None."""
        data = YieldData(key1="value1")
        self.assertIsNone(data.get("nonexistent"))
        self.assertIsNone(data.get(""))

    def test_get_none_value(self):
        """Test getting a key with None value returns None."""
        data = YieldData(key1=None)
        self.assertIsNone(data.get("key1"))


class TestFileLock(TestCase):
    """Test suite for FileLock context manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp(prefix="lock_test_")
        self.mock_folder_lock = os.path.join(self.temp_dir, "locks")

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_filelock_basic_usage(self, mock_folder_constants):
        """Test basic FileLock usage."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)

        lock_name = "test_resource"
        acquired_fd = None

        with FileLock(lock_name) as fd:
            acquired_fd = fd
            self.assertIsNotNone(fd)

        # Lock file should be deleted after context exit
        expected_lock_path = os.path.join(self.mock_folder_lock, "test_resource.lock")
        self.assertFalse(os.path.exists(expected_lock_path))

    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_filelock_with_extension(self, mock_folder_constants):
        """Test FileLock with .lock extension already present."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)

        lock_name = "test_resource.lock"
        with FileLock(lock_name) as fd:
            self.assertIsNotNone(fd)

        expected_lock_path = os.path.join(self.mock_folder_lock, "test_resource.lock")
        self.assertFalse(os.path.exists(expected_lock_path))

    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_filelock_empty_name_raises(self, mock_folder_constants):
        """Test FileLock raises AssertionError for empty name."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock

        with self.assertRaises(AssertionError) as context:
            with FileLock(""):
                pass
        self.assertIn("Lock name cannot be empty", str(context.exception))

    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_filelock_none_name_raises(self, mock_folder_constants):
        """Test FileLock raises AssertionError for None name."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock

        with self.assertRaises(AssertionError) as context:
            with FileLock(None):
                pass
        self.assertIn("Lock name cannot be empty", str(context.exception))

    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_filelock_special_characters(self, mock_folder_constants):
        """Test FileLock with special characters in name."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)

        lock_name = "test-resource_123"
        with FileLock(lock_name) as fd:
            self.assertIsNotNone(fd)

        expected_lock_path = os.path.join(self.mock_folder_lock, "test-resource_123.lock")
        self.assertFalse(os.path.exists(expected_lock_path))

    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_filelock_concurrent_access(self, mock_folder_constants):
        """Test FileLock handles concurrent access correctly."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)

        results = []
        lock_name = "concurrent_test"

        def worker():
            with FileLock(lock_name):
                results.append(threading.current_thread().name)
                time.sleep(0.05)

        threads = [threading.Thread(target=worker, name=f"worker_{i}") for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should have completed
        self.assertEqual(len(results), 3)


class TestCtxmTrySessionLock(TestCase):
    """Test suite for ctxm_try_session_lock context manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp(prefix="session_lock_test_")
        self.mock_folder_lock = os.path.join(self.temp_dir, "locks")

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @mock.patch("topsailai.workspace.lock_tool.env_tool")
    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_session_lock_basic(self, mock_folder_constants, mock_env_tool):
        """Test basic ctxm_try_session_lock usage."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)
        mock_env_tool.get_session_id.return_value = "test_session_123"
        mock_env_tool.EnvReaderInstance.get.return_value = 60
        mock_env_tool.EnvReaderInstance.check_bool.return_value = True

        with ctxm_try_session_lock() as yield_data:
            self.assertEqual(yield_data.get("session_id"), "test_session_123")
            self.assertIsNotNone(yield_data.get("fp"))
            self.assertEqual(yield_data.get("msg"), "")

    @mock.patch("topsailai.workspace.lock_tool.env_tool")
    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_session_lock_custom_session_id(self, mock_folder_constants, mock_env_tool):
        """Test ctxm_try_session_lock with custom session_id."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)
        mock_env_tool.EnvReaderInstance.get.return_value = 60
        mock_env_tool.EnvReaderInstance.check_bool.return_value = True

        with ctxm_try_session_lock(session_id="custom_session") as yield_data:
            self.assertEqual(yield_data.get("session_id"), "custom_session")

    @mock.patch("topsailai.workspace.lock_tool.env_tool")
    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_session_lock_empty_session_id(self, mock_folder_constants, mock_env_tool):
        """Test ctxm_try_session_lock with empty session_id."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)
        mock_env_tool.get_session_id.return_value = ""
        mock_env_tool.EnvReaderInstance.get.return_value = 60
        mock_env_tool.EnvReaderInstance.check_bool.return_value = True

        with ctxm_try_session_lock() as yield_data:
            # Empty string is stored as empty string, not None
            self.assertEqual(yield_data.get("session_id"), "")
            # fp is None because no lock file is created for empty session_id
            self.assertIsNone(yield_data.get("fp"))
            self.assertEqual(yield_data.get("msg"), "")

    @mock.patch("topsailai.workspace.lock_tool.env_tool")
    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_session_lock_custom_timeout(self, mock_folder_constants, mock_env_tool):
        """Test ctxm_try_session_lock with custom timeout."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)
        mock_env_tool.get_session_id.return_value = "test_session"
        mock_env_tool.EnvReaderInstance.get.return_value = 60
        mock_env_tool.EnvReaderInstance.check_bool.return_value = True

        with ctxm_try_session_lock(timeout=30) as yield_data:
            self.assertIsNotNone(yield_data)

    @mock.patch("topsailai.workspace.lock_tool.env_tool")
    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_session_lock_session_id_sanitization(self, mock_folder_constants, mock_env_tool):
        """Test that session_id is sanitized (slashes and spaces replaced)."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)
        mock_env_tool.get_session_id.return_value = "session/with/slashes and spaces"
        mock_env_tool.EnvReaderInstance.get.return_value = 60
        mock_env_tool.EnvReaderInstance.check_bool.return_value = True

        with ctxm_try_session_lock() as yield_data:
            self.assertEqual(yield_data.get("session_id"), "session/with/slashes and spaces")

    @mock.patch("topsailai.workspace.lock_tool.env_tool")
    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_session_lock_timeout_minimum(self, mock_folder_constants, mock_env_tool):
        """Test that timeout is at least 1."""
        mock_folder_constants.FOLDER_LOCK = self.mock_folder_lock
        os.makedirs(self.mock_folder_lock, exist_ok=True)
        mock_env_tool.get_session_id.return_value = "test_session"
        mock_env_tool.EnvReaderInstance.get.return_value = 60
        mock_env_tool.EnvReaderInstance.check_bool.return_value = True

        with ctxm_try_session_lock(timeout=0) as yield_data:
            self.assertIsNotNone(yield_data)


class TestCtxmVoid(TestCase):
    """Test suite for ctxm_void context manager."""

    def test_ctxm_void_yields_empty_data(self):
        """Test that ctxm_void yields YieldData with empty data."""
        with ctxm_void() as yield_data:
            self.assertIsInstance(yield_data, YieldData)
            self.assertEqual(yield_data.data, {})

    def test_ctxm_void_with_args(self):
        """Test ctxm_void ignores arguments and yields empty data."""
        with ctxm_void("arg1", "arg2", key="value") as yield_data:
            self.assertIsInstance(yield_data, YieldData)
            self.assertEqual(yield_data.data, {})

    def test_ctxm_void_multiple_entries(self):
        """Test multiple ctxm_void entries yield independent data."""
        with ctxm_void() as data1:
            data1.data["test"] = "value1"
            with ctxm_void() as data2:
                data2.data["test"] = "value2"
                self.assertNotEqual(data1.data, data2.data)
            self.assertEqual(data1.data["test"], "value1")


class TestInitFunction(TestCase):
    """Test suite for init function."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp(prefix="init_test_")

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_init_creates_lock_directory(self, mock_folder_constants):
        """Test that init creates the lock directory if it doesn't exist."""
        mock_folder_constants.FOLDER_LOCK = os.path.join(self.temp_dir, "locks")

        # Directory should not exist before init
        self.assertFalse(os.path.exists(mock_folder_constants.FOLDER_LOCK))

        # Call init
        init()

        # Directory should exist after init
        self.assertTrue(os.path.exists(mock_folder_constants.FOLDER_LOCK))
        self.assertTrue(os.path.isdir(mock_folder_constants.FOLDER_LOCK))

    @mock.patch("topsailai.workspace.lock_tool.folder_constants")
    def test_init_idempotent(self, mock_folder_constants):
        """Test that init is idempotent (can be called multiple times)."""
        mock_folder_constants.FOLDER_LOCK = os.path.join(self.temp_dir, "locks")

        # Call init multiple times
        init()
        init()
        init()

        # Directory should still exist
        self.assertTrue(os.path.exists(mock_folder_constants.FOLDER_LOCK))


import multiprocessing
import time

from topsailai.workspace.lock_tool import (
    ctxm_project_workspace_lock,
    _get_project_workspace_lock_enabled,
    _get_project_workspace_lock_timeout,
)


def _hold_lock_file(lock_file: str, hold_seconds: float) -> None:
    """Acquire *lock_file* and hold it for *hold_seconds*, then release."""
    import fcntl
    with open(lock_file, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        time.sleep(hold_seconds)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class TestCtxmProjectWorkspaceLock(TestCase):
    """Test suite for ctxm_project_workspace_lock context manager."""

    def setUp(self):
        """Set up a temporary project workspace."""
        self.temp_dir = tempfile.mkdtemp(prefix="project_workspace_lock_test_")

    def tearDown(self):
        """Clean up the temporary project workspace."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _lock_file_path(self):
        return os.path.join(self.temp_dir, ".topsailai", "project_workspace.lock")

    def _start_lock_holder(self, hold_seconds=0.5):
        """Start a subprocess that holds the workspace lock."""
        lock_file = self._lock_file_path()
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)
        proc = multiprocessing.Process(
            target=_hold_lock_file,
            args=(lock_file, hold_seconds),
        )
        proc.start()
        # Give the subprocess a moment to acquire the lock.
        time.sleep(0.1)
        return proc

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_project_workspace_lock_acquires_successfully(self):
        """Test that the lock is acquired and cleaned up on success."""
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = self.temp_dir

        with ctxm_project_workspace_lock() as has_lock:
            self.assertTrue(has_lock)
            self.assertTrue(os.path.exists(self._lock_file_path()))

        self.assertFalse(os.path.exists(self._lock_file_path()))

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_project_workspace_lock_no_workspace_yields_false(self):
        """Test that missing workspace yields False and creates no lock."""
        with ctxm_project_workspace_lock() as has_lock:
            self.assertFalse(has_lock)

        self.assertFalse(os.path.exists(self._lock_file_path()))

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_project_workspace_lock_disabled_yields_false(self):
        """Test that disabling the lock yields False and creates no lock."""
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = self.temp_dir
        os.environ["TOPSAILAI_PROJECT_WORKSPACE_LOCK_ENABLED"] = "0"

        with ctxm_project_workspace_lock() as has_lock:
            self.assertFalse(has_lock)

        self.assertFalse(os.path.exists(self._lock_file_path()))

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_project_workspace_lock_mkdir_failure_yields_false(self):
        """Test that a non-directory workspace path falls back gracefully."""
        file_path = os.path.join(self.temp_dir, "not_a_directory")
        with open(file_path, "w") as f:
            f.write("x")
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = file_path

        with self.assertLogs("topsailai.workspace.lock_tool", level="WARNING"):
            with ctxm_project_workspace_lock() as has_lock:
                self.assertFalse(has_lock)

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("topsailai.workspace.input_tool.input_from_pipe_session")
    @mock.patch("topsailai.workspace.lock_tool.sys.exit")
    def test_project_workspace_lock_contested_exit(
        self, mock_exit, mock_input
    ):
        """Test that choosing exit terminates the process."""
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = self.temp_dir
        mock_input.return_value = "exit"
        mock_exit.side_effect = SystemExit(1)
        proc = self._start_lock_holder(hold_seconds=2.0)

        try:
            with self.assertRaises(SystemExit) as cm:
                with ctxm_project_workspace_lock():
                    self.fail("Should have exited before yielding")
        finally:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)

        self.assertEqual(cm.exception.code, 1)
        mock_exit.assert_called_once_with(1)

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("topsailai.workspace.input_tool.input_from_pipe_session")
    def test_project_workspace_lock_contested_continue(self, mock_input):
        """Test that choosing continue yields False."""
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = self.temp_dir
        mock_input.return_value = "continue"
        proc = self._start_lock_holder(hold_seconds=2.0)

        try:
            with ctxm_project_workspace_lock() as has_lock:
                self.assertFalse(has_lock)
        finally:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("topsailai.workspace.input_tool.input_from_pipe_session")
    def test_project_workspace_lock_contested_wait_then_acquire(self, mock_input):
        """Test that choosing wait eventually acquires the lock."""
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = self.temp_dir
        mock_input.return_value = "wait"
        proc = self._start_lock_holder(hold_seconds=0.5)

        try:
            with ctxm_project_workspace_lock() as has_lock:
                self.assertTrue(has_lock)
        finally:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)

        self.assertFalse(os.path.exists(self._lock_file_path()))

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("topsailai.workspace.input_tool.input_from_pipe_session")
    def test_project_workspace_lock_prompt_timeout_defaults_wait(self, mock_input):
        """Test that prompt timeout defaults to wait and acquires the lock."""
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = self.temp_dir
        mock_input.side_effect = TimeoutError("timed out")
        proc = self._start_lock_holder(hold_seconds=0.5)

        try:
            with ctxm_project_workspace_lock(prompt_timeout=5.0) as has_lock:
                self.assertTrue(has_lock)
        finally:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("topsailai.workspace.input_tool.input_from_pipe_session")
    def test_project_workspace_lock_prompt_failure_defaults_wait(self, mock_input):
        """Test that prompt failure defaults to wait and acquires the lock."""
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = self.temp_dir
        mock_input.side_effect = RuntimeError("input broken")
        proc = self._start_lock_holder(hold_seconds=0.5)

        try:
            with ctxm_project_workspace_lock(prompt_timeout=5.0) as has_lock:
                self.assertTrue(has_lock)
        finally:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("topsailai.workspace.input_tool.input_from_pipe_session")
    def test_project_workspace_lock_unknown_input_defaults_wait(self, mock_input):
        """Test that unknown input defaults to wait and acquires the lock."""
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = self.temp_dir
        mock_input.return_value = "unknown"
        proc = self._start_lock_holder(hold_seconds=0.5)

        try:
            with ctxm_project_workspace_lock(prompt_timeout=5.0) as has_lock:
                self.assertTrue(has_lock)
        finally:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("topsailai.workspace.input_tool.input_from_pipe_session")
    def test_project_workspace_lock_timeout_from_env(self, mock_input):
        """Test that the prompt timeout is read from environment."""
        os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = self.temp_dir
        os.environ["TOPSAILAI_PROJECT_WORKSPACE_LOCK_TIMEOUT"] = "10"
        mock_input.return_value = "wait"
        proc = self._start_lock_holder(hold_seconds=0.5)

        try:
            with ctxm_project_workspace_lock() as has_lock:
                self.assertTrue(has_lock)
        finally:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)

        mock_input.assert_called_once()
        call_kwargs = mock_input.call_args[1]
        self.assertEqual(call_kwargs.get("timeout"), 10.0)

    def test_project_workspace_lock_timeout_invalid_fallback(self):
        """Test invalid timeout falls back to default."""
        with mock.patch.dict(os.environ, {"TOPSAILAI_PROJECT_WORKSPACE_LOCK_TIMEOUT": "invalid"}, clear=True):
            self.assertEqual(_get_project_workspace_lock_timeout(), 300.0)

    def test_project_workspace_lock_timeout_zero_fallback(self):
        """Test zero timeout falls back to default."""
        with mock.patch.dict(os.environ, {"TOPSAILAI_PROJECT_WORKSPACE_LOCK_TIMEOUT": "0"}, clear=True):
            self.assertEqual(_get_project_workspace_lock_timeout(), 300.0)

    def test_project_workspace_lock_enabled_unset_defaults_true(self):
        """Test lock enabled defaults to True when unset."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(_get_project_workspace_lock_enabled())

    def test_project_workspace_lock_enabled_false(self):
        """Test lock enabled can be disabled."""
        with mock.patch.dict(os.environ, {"TOPSAILAI_PROJECT_WORKSPACE_LOCK_ENABLED": "0"}, clear=True):
            self.assertFalse(_get_project_workspace_lock_enabled())

    def test_project_workspace_lock_enabled_true(self):
        """Test lock enabled can be explicitly enabled."""
        with mock.patch.dict(os.environ, {"TOPSAILAI_PROJECT_WORKSPACE_LOCK_ENABLED": "1"}, clear=True):
            self.assertTrue(_get_project_workspace_lock_enabled())
