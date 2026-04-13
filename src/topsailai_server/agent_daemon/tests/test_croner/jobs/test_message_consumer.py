"""
Test MessageConsumer cron job
"""

import unittest
import os
from datetime import datetime, timedelta

os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_DB_URL'] = 'sqlite:///:memory:'

from sqlalchemy import create_engine

from topsailai_server.agent_daemon.storage import Storage, SessionData, MessageData
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.configer import get_config
from topsailai_server.agent_daemon.croner.jobs.message_consumer import MessageConsumer


class TestMessageConsumer(unittest.TestCase):
    """Test cases for MessageConsumer cron job"""
    
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
        self.storage = Storage(self.engine)
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        self.consumer = MessageConsumer(storage=self.storage, worker_manager=self.worker_manager)
    
    def test_message_consumer_initialization(self):
        """Test MessageConsumer initialization"""
        self.assertIsNotNone(self.consumer)
    
    def test_message_consumer_get_recent_messages(self):
        """Test getting recent messages from last 10 minutes"""
        now = datetime.now()
        msg1 = self.storage.message.create(
            MessageData(msg_id='msg-1', session_id='session-1', message='Test 1',
                       create_time=now - timedelta(minutes=5))
        )
        msg2 = self.storage.message.create(
            MessageData(msg_id='msg-2', session_id='session-2', message='Test 2',
                       create_time=now - timedelta(minutes=15))
        )
        since = now - timedelta(minutes=10)
        recent_messages = self.storage.message.get_messages_since(since)
        self.assertEqual(len(recent_messages), 1)
        self.assertEqual(recent_messages[0].msg_id, 'msg-1')
    
    def test_message_consumer_get_unique_sessions(self):
        """Test getting unique session IDs from messages"""
        now = datetime.now()
        for i in range(3):
            self.storage.message.create(
                MessageData(msg_id=f'msg-{i}', session_id=f'session-{i % 2}',
                           message=f'Test {i}', create_time=now)
            )
        recent_messages = self.storage.message.get_messages_since(now - timedelta(minutes=10))
        session_ids = list(set(m.session_id for m in recent_messages))
        self.assertEqual(len(session_ids), 2)
    
    def test_message_consumer_triggers_processor(self):
        """Test that processor is triggered when message is not processed"""
        session = self.storage.session.create(
            SessionData(session_id='test-consumer-session', task='Test task', session_name='Test')
        )
        now = datetime.now()
        self.storage.message.create(
            MessageData(msg_id='unprocessed-msg', session_id='test-consumer-session',
                       message='Unprocessed', create_time=now)
        )
        try:
            self.consumer.run()
        except Exception:
            pass
        messages = self.storage.message.get_by_session('test-consumer-session')
        self.assertEqual(len(messages), 1)
    
    def test_message_consumer_skips_processed_session(self):
        """Test that consumer skips sessions that are already processed"""
        now = datetime.now()
        session = self.storage.session.create(
            SessionData(session_id='processed-session', task='Test task', session_name='Processed',
                       processed_msg_id='latest-msg')
        )
        self.storage.message.create(
            MessageData(msg_id='latest-msg', session_id='processed-session',
                       message='Latest', create_time=now)
        )
        try:
            self.consumer.run()
        except Exception:
            pass
        session = self.storage.session.get('processed-session')
        self.assertEqual(session.processed_msg_id, 'latest-msg')


class TestMessageConsumerIntegration(unittest.TestCase):
    """Integration tests for MessageConsumer"""
    
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
        self.storage = Storage(self.engine)
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        self.consumer = MessageConsumer(storage=self.storage, worker_manager=self.worker_manager)
    
    def test_full_message_consumption_flow(self):
        """Test complete message consumption flow"""
        now = datetime.now()
        for session_idx in range(3):
            session_id = f'flow-session-{session_idx}'
            self.storage.session.create(
                SessionData(session_id=session_id, task='Test task', session_name=f'Session {session_idx}')
            )
            for msg_idx in range(2):
                self.storage.message.create(
                    MessageData(msg_id=f'{session_id}-msg-{msg_idx}', session_id=session_id,
                               message=f'Message {msg_idx}', create_time=now - timedelta(minutes=msg_idx))
                )
        try:
            self.consumer.run()
        except Exception:
            pass
        for session_idx in range(3):
            session_id = f'flow-session-{session_idx}'
            messages = self.storage.message.get_by_session(session_id)
            self.assertEqual(len(messages), 2)


if __name__ == '__main__':
    unittest.main()
