'''
Test for clean_messages function in ChatHistorySQLAlchemy
'''
import os
import sys
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, workspace_root + "/src")

from topsailai.context.chat_history_manager.sql import ChatHistorySQLAlchemy, Message, SessionMessage, Base
from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData


class TestCleanMessages:
    """Test cases for clean_messages function"""

    def setup_method(self):
        """Setup test database and instance"""
        # Use SQLite in-memory database for testing
        self.engine = create_engine('sqlite:///:memory:')
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        # Create tables
        Base.metadata.create_all(bind=self.engine)

        # Create ChatHistorySQLAlchemy instance with the same engine
        self.chat_history = ChatHistorySQLAlchemy('sqlite:///:memory:')
        # Replace the engine with our shared engine to ensure they use the same database
        self.chat_history.engine = self.engine
        self.chat_history.SessionLocal = self.SessionLocal

    def teardown_method(self):
        """Clean up after tests"""
        self.engine.dispose()

    def test_clean_messages_basic_functionality(self):
        """Test that clean_messages deletes old messages correctly"""
        # Create test messages using the ChatHistorySQLAlchemy instance
        current_time = datetime.now()

        # Message accessed 1 hour ago (should be deleted if before_seconds=30 minutes)
        msg1 = ChatHistoryMessageData(
            message="Message 1",
            msg_id="msg1",
            session_id="session1"
        )
        # Manually set access_time to 1 hour ago
        session = self.SessionLocal()
        try:
            message1 = Message(
                msg_id="msg1",
                message="Message 1",
                msg_size=10,
                access_time=current_time - timedelta(hours=1),
                access_count=1
            )
            session.add(message1)
            session_mapping1 = SessionMessage(msg_id="msg1", session_id="session1")
            session.add(session_mapping1)
            session.commit()
        finally:
            session.close()

        # Message accessed 10 minutes ago (should be kept)
        msg2 = ChatHistoryMessageData(
            message="Message 2",
            msg_id="msg2",
            session_id="session1"
        )
        session = self.SessionLocal()
        try:
            message2 = Message(
                msg_id="msg2",
                message="Message 2",
                msg_size=10,
                access_time=current_time - timedelta(minutes=10),
                access_count=1
            )
            session.add(message2)
            session_mapping2 = SessionMessage(msg_id="msg2", session_id="session1")
            session.add(session_mapping2)
            session.commit()
        finally:
            session.close()

        # Message with no access time (should be kept)
        msg3 = ChatHistoryMessageData(
            message="Message 3",
            msg_id="msg3",
            session_id="session1"
        )
        self.chat_history.add_message(msg3)

        # Clean messages older than 30 minutes
        deleted_count = self.chat_history.clean_messages(before_seconds=30 * 60)  # 30 minutes

        # Verify that only msg1 was deleted
        assert deleted_count == 1

        # Verify remaining messages using the chat_history instance
        messages = self.chat_history.get_messages_by_session("session1")
        assert len(messages) == 2
        remaining_msg_ids = {msg.msg_id for msg in messages}
        assert "msg2" in remaining_msg_ids
        assert "msg3" in remaining_msg_ids
        assert "msg1" not in remaining_msg_ids

    def test_clean_messages_no_messages_to_delete(self):
        """Test clean_messages when no messages match the criteria"""
        session = self.SessionLocal()

        # Create a recent message
        msg = Message(
            msg_id="msg1",
            message="Message 1",
            msg_size=10,
            access_time=datetime.now() - timedelta(minutes=10),  # 10 minutes ago
            access_count=1
        )

        session.add(msg)
        session_mapping = SessionMessage(msg_id="msg1", session_id="session1")
        session.add(session_mapping)
        session.commit()

        # Clean messages older than 1 hour (should not delete anything)
        deleted_count = self.chat_history.clean_messages(before_seconds=60 * 60)  # 1 hour

        assert deleted_count == 0

        # Verify message still exists
        remaining_message = session.query(Message).first()
        assert remaining_message is not None
        assert remaining_message.msg_id == "msg1"

    def test_clean_messages_all_messages_old(self):
        """Test clean_messages when all messages should be deleted"""
        session = self.SessionLocal()

        # Create old messages
        old_time = datetime.now() - timedelta(days=1)  # 1 day ago

        msg1 = Message(
            msg_id="msg1",
            message="Message 1",
            msg_size=10,
            access_time=old_time,
            access_count=1
        )

        msg2 = Message(
            msg_id="msg2",
            message="Message 2",
            msg_size=10,
            access_time=old_time,
            access_count=1
        )

        session.add_all([msg1, msg2])

        # Add session mappings
        session_mapping1 = SessionMessage(msg_id="msg1", session_id="session1")
        session_mapping2 = SessionMessage(msg_id="msg2", session_id="session1")
        session.add_all([session_mapping1, session_mapping2])
        session.commit()

        # Clean messages older than 1 hour (should delete all)
        deleted_count = self.chat_history.clean_messages(before_seconds=60 * 60)  # 1 hour

        assert deleted_count == 2

        # Verify no messages remain
        remaining_messages = session.query(Message).all()
        assert len(remaining_messages) == 0

        # Verify no session mappings remain
        remaining_mappings = session.query(SessionMessage).all()
        assert len(remaining_mappings) == 0

    def test_clean_messages_mixed_ages(self):
        """Test clean_messages with messages of various ages"""
        session = self.SessionLocal()

        current_time = datetime.now()

        # Messages with different ages
        messages = [
            Message(msg_id="msg1", message="1 day old", msg_size=10,
                   access_time=current_time - timedelta(days=1), access_count=1),
            Message(msg_id="msg2", message="2 hours old", msg_size=10,
                   access_time=current_time - timedelta(hours=2), access_count=1),
            Message(msg_id="msg3", message="30 minutes old", msg_size=10,
                   access_time=current_time - timedelta(minutes=30), access_count=1),
            Message(msg_id="msg4", message="10 minutes old", msg_size=10,
                   access_time=current_time - timedelta(minutes=10), access_count=1),
            Message(msg_id="msg5", message="No access time", msg_size=10,
                   access_time=None, access_count=0),
        ]

        session.add_all(messages)

        # Add session mappings
        for i in range(1, 6):
            session.add(SessionMessage(msg_id=f"msg{i}", session_id="session1"))

        session.commit()

        # Clean messages older than 1 hour
        deleted_count = self.chat_history.clean_messages(before_seconds=60 * 60)  # 1 hour

        # Should delete msg1 (1 day old) and msg2 (2 hours old)
        assert deleted_count == 2

        # Verify remaining messages
        remaining_messages = session.query(Message).all()
        assert len(remaining_messages) == 3

        remaining_msg_ids = {msg.msg_id for msg in remaining_messages}
        assert "msg3" in remaining_msg_ids  # 30 minutes old (kept)
        assert "msg4" in remaining_msg_ids  # 10 minutes old (kept)
        assert "msg5" in remaining_msg_ids  # No access time (kept)
        assert "msg1" not in remaining_msg_ids  # 1 day old (deleted)
        assert "msg2" not in remaining_msg_ids  # 2 hours old (deleted)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
