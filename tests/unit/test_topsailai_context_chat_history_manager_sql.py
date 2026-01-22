#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Unit tests for chat_history_manager sql
'''

import pytest
import sys
import os
workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
    sys.path.insert(0, workspace_root + "/src")
from topsailai.context.chat_history_manager.sql import ChatHistorySQLAlchemy, ChatHistoryMessageData

class TestChatHistorySQLAlchemy:
    @pytest.fixture
    def db_conn(self):
        return "sqlite:///:memory:"

    @pytest.fixture
    def manager(self, db_conn):
        return ChatHistorySQLAlchemy(db_conn)

    def test_add_message_new_message(self, manager):
        msg = ChatHistoryMessageData("Hello world", None, "session1")
        manager.add_message(msg)
        assert msg.msg_id is not None
        retrieved = manager.get_message(msg.msg_id)
        assert retrieved.message == "Hello world"
        assert retrieved.session_id is None  # get_message doesn't set session_id
        assert retrieved.msg_size == 11

    def test_add_message_existing_message_new_session(self, manager):
        msg1 = ChatHistoryMessageData("Hello world", None, "session1")
        manager.add_message(msg1)
        msg2 = ChatHistoryMessageData("Hello world", None, "session2")  # Same message, different session
        manager.add_message(msg2)
        assert msg1.msg_id == msg2.msg_id  # Same msg_id

        messages_session1 = manager.get_messages_by_session("session1")
        messages_session2 = manager.get_messages_by_session("session2")
        assert len(messages_session1) == 1
        assert len(messages_session2) == 1
        assert messages_session1[0].msg_id == messages_session2[0].msg_id

    def test_get_message_updates_stats(self, manager):
        msg = ChatHistoryMessageData("Test message", None, "session1")
        manager.add_message(msg)
        retrieved1 = manager.get_message(msg.msg_id)
        assert retrieved1.access_count == 1
        retrieved2 = manager.get_message(msg.msg_id)
        assert retrieved2.access_count == 2

    def test_get_message_not_found(self, manager):
        retrieved = manager.get_message("nonexistent")
        assert retrieved is None

    def test_get_messages_by_session(self, manager):
        msg1 = ChatHistoryMessageData("Message 1", None, "session1")
        msg2 = ChatHistoryMessageData("Message 2", None, "session1")
        manager.add_message(msg1)
        manager.add_message(msg2)
        messages = manager.get_messages_by_session("session1")
        assert len(messages) == 2
        message_texts = [m.message for m in messages]
        assert "Message 1" in message_texts
        assert "Message 2" in message_texts

    def test_get_messages_by_session_empty(self, manager):
        messages = manager.get_messages_by_session("empty_session")
        assert messages == []

    def test_del_messages_by_msg_id(self, manager):
        msg1 = ChatHistoryMessageData("Message 1", None, "session1")
        msg2 = ChatHistoryMessageData("Message 2", None, "session1")
        manager.add_message(msg1)
        manager.add_message(msg2)
        manager.del_messages(msg_id=msg1.msg_id)
        messages = manager.get_messages_by_session("session1")
        assert len(messages) == 1
        assert messages[0].message == "Message 2"
        assert manager.get_message(msg1.msg_id) is None

    def test_del_messages_by_session_id(self, manager):
        msg1 = ChatHistoryMessageData("Message 1", None, "session1")
        msg2 = ChatHistoryMessageData("Message 2", None, "session2")
        manager.add_message(msg1)
        manager.add_message(msg2)
        manager.del_messages(session_id="session1")
        messages_session1 = manager.get_messages_by_session("session1")
        messages_session2 = manager.get_messages_by_session("session2")
        assert len(messages_session1) == 0
        assert len(messages_session2) == 1
        # Message 1 should still exist if it was in another session, but in this case it's not
        assert manager.get_message(msg1.msg_id) is None

    def test_del_messages_by_session_id_shared_message(self, manager):
        msg1 = ChatHistoryMessageData("Shared message", None, "session1")
        manager.add_message(msg1)
        msg2 = ChatHistoryMessageData("Shared message", msg1.msg_id, "session2")  # Same message in another session
        manager.add_message(msg2)
        # Del from session1, message should remain because it's still in session2
        manager.del_messages(session_id="session1")
        messages_session2 = manager.get_messages_by_session("session2")
        assert len(messages_session2) == 1
        assert manager.get_message(msg1.msg_id) is not None
