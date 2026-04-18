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
