"""
Unit tests for context/ctx_manager.py module.

This module tests the context management functions including:
- get_managers_by_env: Get chat history managers from environment
- get_session_manager: Get session manager with fallback logic
- get_messages_by_session: Retrieve messages for a session
- exists_session: Check if session exists
- create_session: Create a new session
- add_session_message: Add a message to a session
- del_session_messages: Delete messages from a session
- cut_messages: Cut messages based on head_tail_offset

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock
import os


class TestGetManagersByEnv(unittest.TestCase):
    """Test cases for get_managers_by_env function."""

    def test_get_managers_by_env_no_env_var(self):
        """Test get_managers_by_env when CONTEXT_HISTORY_MANAGERS is not set."""
        from topsailai.context.ctx_manager import get_managers_by_env

        with patch.dict(os.environ, {}, clear=True):
            result = get_managers_by_env()
            self.assertIsNone(result)

    def test_get_managers_by_env_empty_env_var(self):
        """Test get_managers_by_env when CONTEXT_HISTORY_MANAGERS is empty."""
        from topsailai.context.ctx_manager import get_managers_by_env

        with patch.dict(os.environ, {"CONTEXT_HISTORY_MANAGERS": ""}):
            result = get_managers_by_env()
            # Empty string evaluates to False, so function returns None
            self.assertIsNone(result)

    def test_get_managers_by_env_invalid_manager(self):
        """Test get_managers_by_env with invalid manager name."""
        from topsailai.context.ctx_manager import get_managers_by_env

        with patch.dict(os.environ, {"CONTEXT_HISTORY_MANAGERS": "invalid_manager"}):
            result = get_managers_by_env()
            self.assertEqual(result, [])

    def test_get_managers_by_env_missing_params(self):
        """Test get_managers_by_env with manager name but no parameters."""
        from topsailai.context.ctx_manager import get_managers_by_env

        with patch.dict(os.environ, {"CONTEXT_HISTORY_MANAGERS": "sql"}):
            result = get_managers_by_env()
            self.assertEqual(result, [])

    def test_get_managers_by_env_valid_manager(self):
        """Test get_managers_by_env with valid manager and parameters."""
        from topsailai.context.ctx_manager import get_managers_by_env

        mock_manager_class = MagicMock()
        mock_manager_instance = MagicMock()
        mock_manager_class.return_value = mock_manager_instance

        with patch.dict(os.environ, {"CONTEXT_HISTORY_MANAGERS": "sql conn=sqlite://memory.db"}):
            with patch.dict('topsailai.context.ctx_manager.ALL_MANAGERS', {"sql": mock_manager_class}):
                result = get_managers_by_env()

                self.assertEqual(len(result), 1)
                mock_manager_class.assert_called_once_with(conn="sqlite://memory.db")

    def test_get_managers_by_env_multiple_managers(self):
        """Test get_managers_by_env with multiple managers separated by semicolon."""
        from topsailai.context.ctx_manager import get_managers_by_env

        mock_manager_class = MagicMock()
        mock_manager_instance = MagicMock()
        mock_manager_class.return_value = mock_manager_instance

        with patch.dict(os.environ, {"CONTEXT_HISTORY_MANAGERS": "sql conn=sqlite://memory.db; sql conn=sqlite://test.db"}):
            with patch.dict('topsailai.context.ctx_manager.ALL_MANAGERS', {"sql": mock_manager_class}):
                result = get_managers_by_env()

                self.assertEqual(len(result), 2)

    def test_get_managers_by_env_with_positional_args(self):
        """Test get_managers_by_env with positional arguments."""
        from topsailai.context.ctx_manager import get_managers_by_env

        mock_manager_class = MagicMock()
        mock_manager_instance = MagicMock()
        mock_manager_class.return_value = mock_manager_instance

        with patch.dict(os.environ, {"CONTEXT_HISTORY_MANAGERS": "sql arg1 arg2"}):
            with patch.dict('topsailai.context.ctx_manager.ALL_MANAGERS', {"sql": mock_manager_class}):
                result = get_managers_by_env()

                self.assertEqual(len(result), 1)
                mock_manager_class.assert_called_once_with("arg1", "arg2")

    def test_get_managers_by_env_count_limit(self):
        """Test get_managers_by_env respects count parameter."""
        from topsailai.context.ctx_manager import get_managers_by_env

        mock_manager_class = MagicMock()
        mock_manager_instance = MagicMock()
        mock_manager_class.return_value = mock_manager_instance

        with patch.dict(os.environ, {"CONTEXT_HISTORY_MANAGERS": "sql conn=sqlite://memory.db; sql conn=sqlite://test.db"}):
            with patch.dict('topsailai.context.ctx_manager.ALL_MANAGERS', {"sql": mock_manager_class}):
                result = get_managers_by_env(count=1)

                self.assertEqual(len(result), 1)


class TestGetSessionManager(unittest.TestCase):
    """Test cases for get_session_manager function."""

    def test_get_session_manager_with_conn(self):
        """Test get_session_manager with explicit connection."""
        from topsailai.context.ctx_manager import get_session_manager

        with patch('topsailai.context.ctx_manager.SessionSQLAlchemy') as mock_session_class:
            mock_instance = MagicMock()
            mock_session_class.return_value = mock_instance

            result = get_session_manager(conn="sqlite://explicit.db")

            mock_session_class.assert_called_once_with("sqlite://explicit.db")
            self.assertEqual(result, mock_instance)

    def test_get_session_manager_with_env_manager(self):
        """Test get_session_manager falls back to env manager."""
        from topsailai.context.ctx_manager import get_session_manager

        mock_history_mgr = MagicMock()
        mock_history_mgr.conn = "sqlite://env.db"

        with patch('topsailai.context.ctx_manager.get_managers_by_env') as mock_get_managers:
            with patch('topsailai.context.ctx_manager.SessionSQLAlchemy') as mock_session_class:
                mock_session_instance = MagicMock()
                mock_session_class.return_value = mock_session_instance
                mock_get_managers.return_value = [mock_history_mgr]

                result = get_session_manager()

                mock_session_class.assert_called_once_with("sqlite://env.db")
                self.assertEqual(result, mock_session_instance)

    def test_get_session_manager_with_default_conn(self):
        """Test get_session_manager falls back to default connection."""
        from topsailai.context.ctx_manager import get_session_manager

        with patch('topsailai.context.ctx_manager.get_managers_by_env') as mock_get_managers:
            with patch('topsailai.context.ctx_manager.SessionSQLAlchemy') as mock_session_class:
                mock_session_instance = MagicMock()
                mock_session_class.return_value = mock_session_instance
                mock_get_managers.return_value = []

                result = get_session_manager(default_conn="sqlite://default.db")

                mock_session_class.assert_called_once_with("sqlite://default.db")
                self.assertEqual(result, mock_session_instance)

    def test_get_session_manager_no_valid_manager_raises(self):
        """Test get_session_manager raises exception when no valid manager."""
        from topsailai.context.ctx_manager import get_session_manager

        with patch('topsailai.context.ctx_manager.get_managers_by_env') as mock_get_managers:
            mock_get_managers.return_value = []

            with self.assertRaises(Exception) as context:
                get_session_manager(conn=None, default_conn=None)

            self.assertIn("fail to get session manager", str(context.exception))


class TestGetMessagesBySession(unittest.TestCase):
    """Test cases for get_messages_by_session function."""

    def test_get_messages_by_session_no_session_id(self):
        """Test get_messages_by_session returns empty list when no session_id."""
        from topsailai.context.ctx_manager import get_messages_by_session

        with patch('topsailai.context.ctx_manager.env_tool.get_session_id', return_value=None):
            result = get_messages_by_session(session_id="", session_mgr=None)

            self.assertEqual(result, [])

    def test_get_messages_by_session_with_session_id(self):
        """Test get_messages_by_session retrieves messages for valid session."""
        from topsailai.context.ctx_manager import get_messages_by_session

        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = True
        mock_session_mgr.retrieve_messages.return_value = [{"role": "user", "content": "hello"}]

        result = get_messages_by_session(session_id="test_session", session_mgr=mock_session_mgr)

        mock_session_mgr.exists_session.assert_called_once_with("test_session")
        mock_session_mgr.retrieve_messages.assert_called_once_with("test_session")
        self.assertEqual(result, [{"role": "user", "content": "hello"}])

    def test_get_messages_by_session_for_raw(self):
        """Test get_messages_by_session with for_raw=True."""
        from topsailai.context.ctx_manager import get_messages_by_session

        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = True
        mock_session_mgr.get_messages_by_session.return_value = ["raw_message_1", "raw_message_2"]

        result = get_messages_by_session(session_id="test_session", session_mgr=mock_session_mgr, for_raw=True)

        mock_session_mgr.get_messages_by_session.assert_called_once_with("test_session")
        self.assertEqual(result, ["raw_message_1", "raw_message_2"])

    def test_get_messages_by_session_session_not_exists(self):
        """Test get_messages_by_session returns empty list when session doesn't exist."""
        from topsailai.context.ctx_manager import get_messages_by_session

        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = False

        result = get_messages_by_session(session_id="nonexistent_session", session_mgr=mock_session_mgr)

        self.assertEqual(result, [])

    def test_get_messages_by_session_uses_env_session_id(self):
        """Test get_messages_by_session uses SESSION_ID from environment."""
        from topsailai.context.ctx_manager import get_messages_by_session

        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = True
        mock_session_mgr.retrieve_messages.return_value = []

        with patch('topsailai.context.ctx_manager.env_tool.get_session_id', return_value="env_session"):
            result = get_messages_by_session(session_id="", session_mgr=mock_session_mgr)

            mock_session_mgr.exists_session.assert_called_once_with("env_session")


class TestExistsSession(unittest.TestCase):
    """Test cases for exists_session function."""

    def test_exists_session_empty_session_id(self):
        """Test exists_session returns False for empty session_id."""
        from topsailai.context.ctx_manager import exists_session

        result = exists_session(session_id="")

        self.assertFalse(result)

    def test_exists_session_true(self):
        """Test exists_session returns True when session exists."""
        from topsailai.context.ctx_manager import exists_session

        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = True

        result = exists_session(session_id="existing_session", session_mgr=mock_session_mgr)

        self.assertTrue(result)
        mock_session_mgr.exists_session.assert_called_once_with("existing_session")

    def test_exists_session_false(self):
        """Test exists_session returns False when session doesn't exist."""
        from topsailai.context.ctx_manager import exists_session

        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = False

        result = exists_session(session_id="nonexistent_session", session_mgr=mock_session_mgr)

        self.assertFalse(result)


class TestCreateSession(unittest.TestCase):
    """Test cases for create_session function."""

    def test_create_session_empty_session_id(self):
        """Test create_session returns False for empty session_id."""
        from topsailai.context.ctx_manager import create_session

        result = create_session(session_id="", task="test task")

        self.assertFalse(result)

    def test_create_session_empty_task(self):
        """Test create_session returns False for empty task."""
        from topsailai.context.ctx_manager import create_session

        result = create_session(session_id="test_session", task="")

        self.assertFalse(result)

    def test_create_session_success(self):
        """Test create_session successfully creates a session."""
        from topsailai.context.ctx_manager import create_session
        from topsailai.context.session_manager.__base import SessionData

        mock_session_mgr = MagicMock()

        result = create_session(session_id="test_session", task="test task", session_mgr=mock_session_mgr)

        self.assertTrue(result)
        mock_session_mgr.create_session.assert_called_once()
        call_args = mock_session_mgr.create_session.call_args[0][0]
        self.assertIsInstance(call_args, SessionData)
        self.assertEqual(call_args.session_id, "test_session")
        self.assertEqual(call_args.task, "test task")


class TestAddSessionMessage(unittest.TestCase):
    """Test cases for add_session_message function."""

    def test_add_session_message_no_managers(self):
        """Test add_session_message returns False when no managers configured."""
        from topsailai.context.ctx_manager import add_session_message

        with patch('topsailai.context.ctx_manager.get_managers_by_env', return_value=None):
            result = add_session_message(session_id="test_session", message={"role": "user"})

            self.assertFalse(result)

    def test_add_session_message_success(self):
        """Test add_session_message successfully adds message to all managers."""
        from topsailai.context.ctx_manager import add_session_message

        mock_mgr1 = MagicMock()
        mock_mgr2 = MagicMock()

        with patch('topsailai.context.ctx_manager.get_managers_by_env', return_value=[mock_mgr1, mock_mgr2]):
            result = add_session_message(session_id="test_session", message={"role": "user", "content": "hello"})

            self.assertTrue(result)
            mock_mgr1.add_session_message.assert_called_once()
            mock_mgr2.add_session_message.assert_called_once()


class TestDelSessionMessages(unittest.TestCase):
    """Test cases for del_session_messages function."""

    def test_del_session_messages_no_managers(self):
        """Test del_session_messages returns False when no managers configured."""
        from topsailai.context.ctx_manager import del_session_messages

        with patch('topsailai.context.ctx_manager.get_managers_by_env', return_value=None):
            result = del_session_messages(session_id="test_session", message_ids=["msg1"])

            self.assertFalse(result)

    def test_del_session_messages_empty_message_ids(self):
        """Test del_session_messages returns False for empty message_ids."""
        from topsailai.context.ctx_manager import del_session_messages

        result = del_session_messages(session_id="test_session", message_ids=[])

        self.assertFalse(result)

    def test_del_session_messages_success(self):
        """Test del_session_messages successfully deletes messages from all managers."""
        from topsailai.context.ctx_manager import del_session_messages

        mock_mgr1 = MagicMock()
        mock_mgr2 = MagicMock()

        with patch('topsailai.context.ctx_manager.get_managers_by_env', return_value=[mock_mgr1, mock_mgr2]):
            result = del_session_messages(session_id="test_session", message_ids=["msg1", "msg2"])

            self.assertTrue(result)
            # Each manager should have del_messages called for each message_id
            self.assertEqual(mock_mgr1.del_messages.call_count, 2)
            self.assertEqual(mock_mgr2.del_messages.call_count, 2)

    def test_del_session_messages_single_id_as_string(self):
        """Test del_session_messages handles single message_id as string."""
        from topsailai.context.ctx_manager import del_session_messages

        mock_mgr = MagicMock()

        with patch('topsailai.context.ctx_manager.get_managers_by_env', return_value=[mock_mgr]):
            result = del_session_messages(session_id="test_session", message_ids="msg1")

            self.assertTrue(result)
            mock_mgr.del_messages.assert_called_once_with("msg1", "test_session")


class TestCutMessages(unittest.TestCase):
    """Test cases for cut_messages function."""

    def test_cut_messages_empty_list(self):
        """Test cut_messages returns empty list as-is."""
        from topsailai.context.ctx_manager import cut_messages

        result = cut_messages(messages=[])

        self.assertEqual(result, [])

    def test_cut_messages_none(self):
        """Test cut_messages returns None as-is."""
        from topsailai.context.ctx_manager import cut_messages

        result = cut_messages(messages=None)

        self.assertIsNone(result)

    def test_cut_messages_small_list(self):
        """Test cut_messages returns small list as-is (not exceeding threshold)."""
        from topsailai.context.ctx_manager import cut_messages

        messages = [{"role": "user"}, {"role": "assistant"}]

        result = cut_messages(messages=messages, head_tail_offset=7)

        self.assertEqual(result, messages)

    def test_cut_messages_large_list(self):
        """Test cut_messages cuts large list to head and tail."""
        from topsailai.context.ctx_manager import cut_messages

        messages = [f"msg_{i}" for i in range(20)]

        result = cut_messages(messages=messages, head_tail_offset=5)

        expected = messages[:5] + messages[-5:]
        self.assertEqual(result, expected)
        self.assertEqual(len(result), 10)

    def test_cut_messages_zero_offset(self):
        """Test cut_messages with zero offset returns original list."""
        from topsailai.context.ctx_manager import cut_messages

        messages = [f"msg_{i}" for i in range(20)]

        result = cut_messages(messages=messages, head_tail_offset=0)

        self.assertEqual(result, messages)

    def test_cut_messages_negative_offset(self):
        """Test cut_messages with negative offset returns original list."""
        from topsailai.context.ctx_manager import cut_messages

        messages = [f"msg_{i}" for i in range(20)]

        result = cut_messages(messages=messages, head_tail_offset=-1)

        self.assertEqual(result, messages)

    def test_cut_messages_string_offset(self):
        """Test cut_messages handles string offset parameter."""
        from topsailai.context.ctx_manager import cut_messages

        messages = [f"msg_{i}" for i in range(20)]

        result = cut_messages(messages=messages, head_tail_offset="5")

        expected = messages[:5] + messages[-5:]
        self.assertEqual(result, expected)

    def test_cut_messages_exactly_threshold(self):
        """Test cut_messages returns list as-is when exactly at threshold."""
        from topsailai.context.ctx_manager import cut_messages

        # With offset=5, threshold is 10 (5*2), so 10 messages should not be cut
        messages = [f"msg_{i}" for i in range(10)]

        result = cut_messages(messages=messages, head_tail_offset=5)

        self.assertEqual(result, messages)


if __name__ == '__main__':
    unittest.main()
