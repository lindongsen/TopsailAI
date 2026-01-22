import unittest
import threading
from unittest.mock import patch
from src.topsailai.utils.thread_local_tool import (
    set_thread_var, get_thread_var, unset_thread_var, rid_all_thread_vars,
    incr_agent_deep, decr_agent_deep, ctxm_give_agent_name, get_agent_name,
    get_session_id, ctxm_set_agent, get_agent_object, KEY_AGENT_NAME,
    KEY_SESSION_ID, KEY_AGENT_OBJECT, KEY_AGENT_DEEP, MAX_AGENT_DEEP
)


class TestThreadLocalTool(unittest.TestCase):
    """Test cases for thread_local_tool module."""

    def setUp(self):
        """Clear thread-local storage before each test."""
        rid_all_thread_vars()

    def tearDown(self):
        """Clear thread-local storage after each test."""
        rid_all_thread_vars()

    def test_set_get_thread_var_basic(self):
        """Test basic set and get functionality."""
        set_thread_var("test_key", "test_value")
        self.assertEqual(get_thread_var("test_key"), "test_value")

    def test_get_thread_var_default_value(self):
        """Test getting a non-existent variable returns default."""
        self.assertEqual(get_thread_var("nonexistent", "default"), "default")
        self.assertIsNone(get_thread_var("nonexistent"))

    def test_unset_thread_var(self):
        """Test removing a specific variable."""
        set_thread_var("test_key", "test_value")
        unset_thread_var("test_key")
        self.assertIsNone(get_thread_var("test_key"))

    def test_unset_nonexistent_thread_var(self):
        """Test removing a non-existent variable (should not raise error)."""
        unset_thread_var("nonexistent")
        # Should not raise any exception

    def test_rid_all_thread_vars(self):
        """Test clearing all thread-local variables."""
        set_thread_var("key1", "value1")
        set_thread_var("key2", "value2")
        rid_all_thread_vars()
        self.assertIsNone(get_thread_var("key1"))
        self.assertIsNone(get_thread_var("key2"))

    def test_incr_decr_agent_deep(self):
        """Test agent depth increment and decrement."""
        self.assertEqual(get_thread_var(KEY_AGENT_DEEP, 0), 0)
        
        incr_agent_deep()
        self.assertEqual(get_thread_var(KEY_AGENT_DEEP), 1)
        
        incr_agent_deep()
        self.assertEqual(get_thread_var(KEY_AGENT_DEEP), 2)
        
        decr_agent_deep()
        self.assertEqual(get_thread_var(KEY_AGENT_DEEP), 1)
        
        decr_agent_deep()
        self.assertEqual(get_thread_var(KEY_AGENT_DEEP), 0)

    def test_decr_agent_deep_below_zero(self):
        """Test decrementing depth when already at zero."""
        self.assertEqual(get_thread_var(KEY_AGENT_DEEP, 0), 0)
        decr_agent_deep()  # Should not go below zero
        self.assertEqual(get_thread_var(KEY_AGENT_DEEP, 0), 0)

    def test_ctxm_give_agent_name(self):
        """Test context manager for agent name."""
        set_thread_var(KEY_AGENT_NAME, "original_agent")
        
        with ctxm_give_agent_name("temp_agent"):
            self.assertEqual(get_agent_name(), "temp_agent")
        
        self.assertEqual(get_agent_name(), "original_agent")

    def test_ctxm_give_agent_name_no_previous(self):
        """Test context manager when no previous agent name exists."""
        self.assertIsNone(get_agent_name())
        
        with ctxm_give_agent_name("temp_agent"):
            self.assertEqual(get_agent_name(), "temp_agent")
        
        self.assertIsNone(get_agent_name())

    def test_get_agent_name(self):
        """Test getting agent name."""
        set_thread_var(KEY_AGENT_NAME, "test_agent")
        self.assertEqual(get_agent_name(), "test_agent")

    def test_get_session_id(self):
        """Test getting session ID as string."""
        set_thread_var(KEY_SESSION_ID, 12345)
        self.assertEqual(get_session_id(), "12345")
        
        set_thread_var(KEY_SESSION_ID, "session_123")
        self.assertEqual(get_session_id(), "session_123")

    def test_get_session_id_none(self):
        """Test getting session ID when not set."""
        self.assertEqual(get_session_id(), "None")

    def test_ctxm_set_agent_basic(self):
        """Test context manager for agent object."""
        mock_agent = object()
        set_thread_var(KEY_AGENT_OBJECT, "original_agent")
        
        with ctxm_set_agent(mock_agent):
            self.assertEqual(get_agent_object(), mock_agent)
            self.assertEqual(get_thread_var(KEY_AGENT_DEEP), 1)
        
        self.assertEqual(get_agent_object(), "original_agent")
        self.assertEqual(get_thread_var(KEY_AGENT_DEEP, 0), 0)

    def test_ctxm_set_agent_no_previous(self):
        """Test context manager when no previous agent object exists."""
        mock_agent = object()
        
        with ctxm_set_agent(mock_agent):
            self.assertEqual(get_agent_object(), mock_agent)
            self.assertEqual(get_thread_var(KEY_AGENT_DEEP), 1)
        
        self.assertIsNone(get_agent_object())
        self.assertEqual(get_thread_var(KEY_AGENT_DEEP, 0), 0)

    def test_ctxm_set_agent_max_depth_exceeded(self):
        """Test that max depth constraint is enforced."""
        mock_agent = object()
        
        # Set depth to max allowed
        set_thread_var(KEY_AGENT_DEEP, MAX_AGENT_DEEP)
        
        with self.assertRaises(AssertionError) as cm:
            with ctxm_set_agent(mock_agent):
                pass
        
        self.assertIn(f"Reach the maximum depth: {MAX_AGENT_DEEP}", str(cm.exception))

    def test_get_agent_object(self):
        """Test getting agent object."""
        mock_agent = object()
        set_thread_var(KEY_AGENT_OBJECT, mock_agent)
        self.assertEqual(get_agent_object(), mock_agent)

    def test_thread_isolation(self):
        """Test that thread-local storage is isolated between threads."""
        results = {}
        
        def thread_func(thread_id):
            set_thread_var("thread_specific", f"value_{thread_id}")
            results[thread_id] = get_thread_var("thread_specific")
        
        # Set value in main thread
        set_thread_var("thread_specific", "main_thread_value")
        
        # Create and run other threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=thread_func, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Check main thread value is preserved
        self.assertEqual(get_thread_var("thread_specific"), "main_thread_value")
        
        # Check other threads had their own values
        self.assertEqual(results[0], "value_0")
        self.assertEqual(results[1], "value_1")
        self.assertEqual(results[2], "value_2")


if __name__ == "__main__":
    unittest.main()
