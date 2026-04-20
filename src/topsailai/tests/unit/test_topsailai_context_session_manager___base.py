"""
Unit tests for context/session_manager/__base.py module.

This module contains tests for SessionData and SessionStorageBase classes
which provide session management functionality for the AI engineering framework.

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock
from topsailai.context.session_manager.__base import SessionData, SessionStorageBase


class TestSessionData(unittest.TestCase):
    """Test cases for SessionData class."""

    def test_init_with_all_params(self):
        """Test SessionData initialization with required parameters."""
        session_id = "test_session_123"
        task = "test_task_description"
        
        session = SessionData(session_id=session_id, task=task)
        
        self.assertEqual(session.session_id, session_id)
        self.assertEqual(session.task, task)

    def test_init_session_name_defaults_to_none(self):
        """Test that session_name defaults to None."""
        session = SessionData(session_id="s1", task="t1")
        
        self.assertIsNone(session.session_name)

    def test_init_create_time_defaults_to_none(self):
        """Test that create_time defaults to None."""
        session = SessionData(session_id="s1", task="t1")
        
        self.assertIsNone(session.create_time)

    def test_attributes_are_writable(self):
        """Test that session attributes can be set after initialization."""
        session = SessionData(session_id="s1", task="t1")
        
        # Set additional attributes
        session.session_name = "My Session"
        session.create_time = "2025-01-01T00:00:00"
        
        self.assertEqual(session.session_name, "My Session")
        self.assertEqual(session.create_time, "2025-01-01T00:00:00")

    def test_str_representation(self):
        """Test string representation of SessionData."""
        session = SessionData(session_id="s1", task="test task")
        
        str_repr = str(session)
        
        self.assertIn("s1", str_repr)
        self.assertIn("test task", str_repr)

    def test_multiple_sessions_independent(self):
        """Test that multiple SessionData instances are independent."""
        session1 = SessionData(session_id="s1", task="task1")
        session2 = SessionData(session_id="s2", task="task2")
        
        session1.session_name = "Session 1"
        session2.session_name = "Session 2"
        
        self.assertNotEqual(session1.session_name, session2.session_name)
        self.assertEqual(session1.session_name, "Session 1")
        self.assertEqual(session2.session_name, "Session 2")


class TestSessionStorageBase(unittest.TestCase):
    """Test cases for SessionStorageBase abstract class."""

    def test_exists_session_raises_not_implemented(self):
        """Test that exists_session raises NotImplementedError."""
        storage = SessionStorageBase()
        
        with self.assertRaises(NotImplementedError):
            storage.exists_session("test_session_id")

    def test_create_session_raises_not_implemented(self):
        """Test that create_session raises NotImplementedError."""
        storage = SessionStorageBase()
        session_data = SessionData(session_id="s1", task="t1")
        
        with self.assertRaises(NotImplementedError):
            storage.create_session(session_data)

    def test_list_sessions_raises_not_implemented(self):
        """Test that list_sessions raises NotImplementedError."""
        storage = SessionStorageBase()
        
        with self.assertRaises(NotImplementedError):
            storage.list_sessions()

    def test_delete_session_raises_not_implemented(self):
        """Test that delete_session raises NotImplementedError."""
        storage = SessionStorageBase()
        
        with self.assertRaises(NotImplementedError):
            storage.delete_session("test_session_id")

    def test_retrieve_messages_raises_not_implemented(self):
        """Test that retrieve_messages raises NotImplementedError."""
        storage = SessionStorageBase()
        
        with self.assertRaises(NotImplementedError):
            storage.retrieve_messages("test_session_id")

    def test_clean_sessions_raises_not_implemented(self):
        """Test that clean_sessions raises NotImplementedError."""
        storage = SessionStorageBase()
        
        with self.assertRaises(NotImplementedError):
            storage.clean_sessions(3600)

    def test_get_messages_by_session_raises_not_implemented(self):
        """Test that get_messages_by_session raises NotImplementedError."""
        storage = SessionStorageBase()
        
        with self.assertRaises(NotImplementedError):
            storage.get_messages_by_session("test_session_id")

    def test_tb_session_attribute(self):
        """Test that tb_session class attribute is set correctly."""
        self.assertEqual(SessionStorageBase.tb_session, "session")

    def test_chat_history_initialized_to_none(self):
        """Test that chat_history is initialized to None."""
        storage = SessionStorageBase()
        
        self.assertIsNone(storage.chat_history)

    def test_chat_history_can_be_set(self):
        """Test that chat_history can be assigned after initialization."""
        storage = SessionStorageBase()
        mock_chat_history = MagicMock()
        
        storage.chat_history = mock_chat_history
        
        self.assertIs(storage.chat_history, mock_chat_history)


if __name__ == "__main__":
    unittest.main()
