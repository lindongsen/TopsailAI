'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Unit tests for Message Manager
'''

import unittest
import os
import uuid
from datetime import datetime, timedelta

# Set test environment variables before imports
os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'

from sqlalchemy import create_engine

from topsailai_server.agent_daemon.storage.message_manager.sql import MessageSQLAlchemy
from topsailai_server.agent_daemon.storage.message_manager.base import MessageData
from topsailai_server.agent_daemon.storage.session_manager.sql import SessionSQLAlchemy
from topsailai_server.agent_daemon.storage.session_manager.base import SessionData


class TestMessageManager(unittest.TestCase):
    """Test cases for Message Manager"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.engine = create_engine('sqlite:///:memory:')

        # Create session table first (for foreign key)
        from topsailai_server.agent_daemon.storage.session_manager.sql import Base as SessionBase
        SessionBase.metadata.create_all(cls.engine)

        # Create message table
        from topsailai_server.agent_daemon.storage.message_manager.sql import Base as MessageBase
        MessageBase.metadata.create_all(cls.engine)

        cls.message_manager = MessageSQLAlchemy(cls.engine)
        cls.session_manager = SessionSQLAlchemy(cls.engine)

    def setUp(self):
        """Set up each test with unique session ID"""
        # Use unique session ID for each test to avoid conflicts
        self.test_session_id = f'test-session-{uuid.uuid4().hex[:8]}'

        # Create a test session
        session_data = SessionData(
            session_id=self.test_session_id,
            session_name='Test Session',
            task='Test task',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.session_manager.create(session_data)

    def test_create_message(self):
        """Test creating a new message"""
        message_data = MessageData(
            msg_id='msg-001',
            session_id=self.test_session_id,
            message='Hello, world!',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )

        result = self.message_manager.create(message_data)
        self.assertTrue(result)

        # Verify message was created
        retrieved = self.message_manager.get('msg-001', self.test_session_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.msg_id, 'msg-001')
        self.assertEqual(retrieved.message, 'Hello, world!')

    def test_get_message(self):
        """Test retrieving a message"""
        message_data = MessageData(
            msg_id='msg-002',
            session_id=self.test_session_id,
            message='Test message',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )

        self.message_manager.create(message_data)
        retrieved = self.message_manager.get('msg-002', self.test_session_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.msg_id, 'msg-002')

    def test_update_message(self):
        """Test updating a message"""
        message_data = MessageData(
            msg_id='msg-003',
            session_id=self.test_session_id,
            message='Original message',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )

        self.message_manager.create(message_data)

        # Update message
        message_data.message = 'Updated message'
        result = self.message_manager.update(message_data)

        self.assertTrue(result)

        # Verify update
        retrieved = self.message_manager.get('msg-003', self.test_session_id)
        self.assertEqual(retrieved.message, 'Updated message')

    def test_delete_message(self):
        """Test deleting a message"""
        message_data = MessageData(
            msg_id='msg-004',
            session_id=self.test_session_id,
            message='Message to delete',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )

        self.message_manager.create(message_data)

        # Delete message
        result = self.message_manager.delete('msg-004', self.test_session_id)
        self.assertTrue(result)

        # Verify deletion
        retrieved = self.message_manager.get('msg-004', self.test_session_id)
        self.assertIsNone(retrieved)

    def test_get_by_session(self):
        """Test getting messages by session"""
        # Create multiple messages
        for i in range(5):
            message_data = MessageData(
                msg_id=f'msg-session-{i:03d}',
                session_id=self.test_session_id,
                message=f'Message {i}',
                role='user',
                create_time=datetime.now() - timedelta(minutes=5-i),
                update_time=datetime.now(),
                task_id=None,
                task_result=None
            )
            self.message_manager.create(message_data)

        messages = self.message_manager.get_by_session(self.test_session_id)

        self.assertEqual(len(messages), 5)

    def test_get_latest_message(self):
        """Test getting the latest message"""
        # Create messages at different times
        for i in range(3):
            message_data = MessageData(
                msg_id=f'msg-latest-{i}',
                session_id=self.test_session_id,
                message=f'Message {i}',
                role='user',
                create_time=datetime.now() - timedelta(minutes=3-i),
                update_time=datetime.now(),
                task_id=None,
                task_result=None
            )
            self.message_manager.create(message_data)

        latest = self.message_manager.get_latest_message(self.test_session_id)

        self.assertIsNotNone(latest)
        self.assertEqual(latest.msg_id, 'msg-latest-2')

    def test_get_unprocessed_messages(self):
        """Test getting unprocessed messages"""
        # Create messages
        for i in range(3):
            message_data = MessageData(
                msg_id=f'msg-unproc-{i}',
                session_id=self.test_session_id,
                message=f'Message {i}',
                role='user',
                create_time=datetime.now() - timedelta(minutes=3-i),
                update_time=datetime.now(),
                task_id=None,
                task_result=None
            )
            self.message_manager.create(message_data)

        # Get unprocessed messages after msg-unproc-0
        unprocessed = self.message_manager.get_unprocessed_messages(self.test_session_id, 'msg-unproc-0')

        self.assertEqual(len(unprocessed), 2)
        self.assertEqual(unprocessed[0].msg_id, 'msg-unproc-1')

    def test_get_unprocessed_messages_includes_assistant_messages(self):
        """Test that assistant messages are included in get_unprocessed_messages"""
        # Create a user message as the processed message
        user_msg = MessageData(
            msg_id='msg-assistant-user-0',
            session_id=self.test_session_id,
            message='User message',
            role='user',
            create_time=datetime.now() - timedelta(minutes=3),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.message_manager.create(user_msg)

        # Create an assistant message after the user message
        assistant_msg = MessageData(
            msg_id='msg-assistant-1',
            session_id=self.test_session_id,
            message='Assistant response',
            role='assistant',
            create_time=datetime.now() - timedelta(minutes=2),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.message_manager.create(assistant_msg)

        # Create another user message after the assistant message
        user_msg2 = MessageData(
            msg_id='msg-assistant-user-2',
            session_id=self.test_session_id,
            message='Another user message',
            role='user',
            create_time=datetime.now() - timedelta(minutes=1),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.message_manager.create(user_msg2)

        # Get unprocessed messages after the first user message
        unprocessed = self.message_manager.get_unprocessed_messages(
            self.test_session_id, 'msg-assistant-user-0'
        )

        # Both the assistant message and the second user message should be returned
        self.assertEqual(len(unprocessed), 2)
        msg_ids = [m.msg_id for m in unprocessed]
        self.assertIn('msg-assistant-1', msg_ids)
        self.assertIn('msg-assistant-user-2', msg_ids)

        # Verify the assistant message role is preserved
        assistant_result = [m for m in unprocessed if m.msg_id == 'msg-assistant-1'][0]
        self.assertEqual(assistant_result.role, 'assistant')

    def test_get_unprocessed_messages_includes_messages_with_task_id(self):
        """Test that messages with task_id and task_result are included"""
        # Create a processed message
        processed_msg = MessageData(
            msg_id='msg-task-proc-0',
            session_id=self.test_session_id,
            message='Processed message',
            role='user',
            create_time=datetime.now() - timedelta(minutes=3),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.message_manager.create(processed_msg)

        # Create a message with task_id and task_result
        task_msg = MessageData(
            msg_id='msg-task-1',
            session_id=self.test_session_id,
            message='Message with task info',
            role='assistant',
            create_time=datetime.now() - timedelta(minutes=2),
            update_time=datetime.now(),
            task_id='task-abc-123',
            task_result='Task completed successfully'
        )
        self.message_manager.create(task_msg)

        # Create another message without task info
        plain_msg = MessageData(
            msg_id='msg-task-plain-2',
            session_id=self.test_session_id,
            message='Plain message',
            role='user',
            create_time=datetime.now() - timedelta(minutes=1),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.message_manager.create(plain_msg)

        # Get unprocessed messages after the processed message
        unprocessed = self.message_manager.get_unprocessed_messages(
            self.test_session_id, 'msg-task-proc-0'
        )

        # Both messages should be returned
        self.assertEqual(len(unprocessed), 2)
        msg_ids = [m.msg_id for m in unprocessed]
        self.assertIn('msg-task-1', msg_ids)
        self.assertIn('msg-task-plain-2', msg_ids)

        # Verify task info is preserved
        task_result = [m for m in unprocessed if m.msg_id == 'msg-task-1'][0]
        self.assertEqual(task_result.task_id, 'task-abc-123')
        self.assertEqual(task_result.task_result, 'Task completed successfully')

    def test_get_unprocessed_messages_with_none_processed_msg_id(self):
        """Test that when processed_msg_id is None, all messages for the session are returned"""
        # Create multiple messages with different roles
        for i in range(3):
            message_data = MessageData(
                msg_id=f'msg-none-proc-{i}',
                session_id=self.test_session_id,
                message=f'Message {i}',
                role='user' if i % 2 == 0 else 'assistant',
                create_time=datetime.now() - timedelta(minutes=3-i),
                update_time=datetime.now(),
                task_id=None,
                task_result=None
            )
            self.message_manager.create(message_data)

        # Get unprocessed messages with None processed_msg_id
        unprocessed = self.message_manager.get_unprocessed_messages(
            self.test_session_id, None
        )

        # All messages should be returned
        self.assertEqual(len(unprocessed), 3)
        msg_ids = [m.msg_id for m in unprocessed]
        self.assertIn('msg-none-proc-0', msg_ids)
        self.assertIn('msg-none-proc-1', msg_ids)
        self.assertIn('msg-none-proc-2', msg_ids)

    def test_get_unprocessed_messages_with_empty_processed_msg_id(self):
        """Test that when processed_msg_id is empty string, all messages for the session are returned"""
        # Create multiple messages with different roles
        for i in range(3):
            message_data = MessageData(
                msg_id=f'msg-empty-proc-{i}',
                session_id=self.test_session_id,
                message=f'Message {i}',
                role='user' if i % 2 == 0 else 'assistant',
                create_time=datetime.now() - timedelta(minutes=3-i),
                update_time=datetime.now(),
                task_id=None,
                task_result=None
            )
            self.message_manager.create(message_data)

        # Get unprocessed messages with empty string processed_msg_id
        unprocessed = self.message_manager.get_unprocessed_messages(
            self.test_session_id, ''
        )

        # All messages should be returned
        self.assertEqual(len(unprocessed), 3)
        msg_ids = [m.msg_id for m in unprocessed]
        self.assertIn('msg-empty-proc-0', msg_ids)
        self.assertIn('msg-empty-proc-1', msg_ids)
        self.assertIn('msg-empty-proc-2', msg_ids)

    def test_update_task_info(self):
        """Test updating task info"""
        message_data = MessageData(
            msg_id='msg-task-001',
            session_id=self.test_session_id,
            message='Message with task',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )

        self.message_manager.create(message_data)

        # Update task info
        result = self.message_manager.update_task_info(
            'msg-task-001', self.test_session_id, 'task-123', 'Task result'
        )

        self.assertTrue(result)

        # Verify update
        retrieved = self.message_manager.get('msg-task-001', self.test_session_id)
        self.assertEqual(retrieved.task_id, 'task-123')
        self.assertEqual(retrieved.task_result, 'Task result')

    def test_get_recent_messages(self):
        """Test getting recent messages"""
        # Create old message
        old_message = MessageData(
            msg_id='msg-old',
            session_id=self.test_session_id,
            message='Old message',
            role='user',
            create_time=datetime.now() - timedelta(days=2),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.message_manager.create(old_message)

        # Create recent message
        recent_message = MessageData(
            msg_id='msg-recent',
            session_id=self.test_session_id,
            message='Recent message',
            role='user',
            create_time=datetime.now() - timedelta(minutes=5),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.message_manager.create(recent_message)

        # Get recent messages for this session (last 10 minutes)
        cutoff = datetime.now() - timedelta(minutes=10)
        recent = self.message_manager.get_recent_messages(cutoff)

        # Filter by session_id since other tests also create messages
        recent = [m for m in recent if m.session_id == self.test_session_id]

        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].msg_id, 'msg-recent')

    def test_delete_by_session(self):
        """Test deleting all messages for a session"""
        # Create messages
        for i in range(3):
            message_data = MessageData(
                msg_id=f'msg-del-{i}',
                session_id=self.test_session_id,
                message=f'Message {i}',
                role='user',
                create_time=datetime.now(),
                update_time=datetime.now(),
                task_id=None,
                task_result=None
            )
            self.message_manager.create(message_data)

        # Delete all messages for session
        result = self.message_manager.delete_by_session(self.test_session_id)

        self.assertTrue(result)

        # Verify deletion
        messages = self.message_manager.get_by_session(self.test_session_id)
        self.assertEqual(len(messages), 0)


if __name__ == '__main__':
    unittest.main()
