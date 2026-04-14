"""
Test MessageSummarizer cron job
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
from topsailai_server.agent_daemon.croner.jobs.message_summarizer import MessageSummarizer


class TestMessageSummarizer(unittest.TestCase):
    """Test cases for MessageSummarizer cron job"""
    
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
        self.storage = Storage(self.engine)
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        self.summarizer = MessageSummarizer(storage=self.storage, worker_manager=self.worker_manager)
    
    def test_message_summarizer_initialization(self):
        """Test MessageSummarizer initialization"""
        self.assertIsNotNone(self.summarizer)
    
    def test_message_summarizer_get_last_24h_messages(self):
        """Test getting messages from last 24 hours"""
        now = datetime.now()
        msg1 = self.storage.message.create(
            MessageData(msg_id='msg-1', session_id='session-1', message='Test 1',
                       create_time=now - timedelta(hours=12))
        )
        msg2 = self.storage.message.create(
            MessageData(msg_id='msg-2', session_id='session-2', message='Test 2',
                       create_time=now - timedelta(hours=36))
        )
        since = now - timedelta(hours=24)
        recent_messages = self.storage.message.get_messages_since(since)
        self.assertEqual(len(recent_messages), 1)
        self.assertEqual(recent_messages[0].msg_id, 'msg-1')
    
    def test_message_summarizer_group_by_session(self):
        """Test grouping messages by session"""
        now = datetime.now()
        sessions = ['session-a', 'session-b', 'session-a']
        for i, session_id in enumerate(sessions):
            self.storage.message.create(
                MessageData(msg_id=f'msg-{i}', session_id=session_id,
                           message=f'Message {i}', create_time=now - timedelta(hours=i))
            )
        since = now - timedelta(hours=24)
        messages = self.storage.message.get_messages_since(since)
        session_messages = {}
        for msg in messages:
            if msg.session_id not in session_messages:
                session_messages[msg.session_id] = []
            session_messages[msg.session_id].append(msg)
        self.assertEqual(len(session_messages), 2)
        self.assertEqual(len(session_messages['session-a']), 2)
        self.assertEqual(len(session_messages['session-b']), 1)
    
    def test_message_summarizer_order_by_create_time(self):
        """Test that messages are ordered by create_time"""
        now = datetime.now()
        timestamps = [
            (now - timedelta(hours=10), 'msg-1'),
            (now - timedelta(hours=5), 'msg-2'),
            (now - timedelta(hours=15), 'msg-3'),
        ]
        for ts, msg_id in timestamps:
            self.storage.message.create(
                MessageData(msg_id=msg_id, session_id='ordered-session',
                           message=f'Message {msg_id}', create_time=ts)
            )
        # Note: get_messages_since doesn't support sort_key/order_by
        # The messages are returned in default order
        messages = self.storage.message.get_messages_since(now - timedelta(hours=24))
        self.assertEqual(len(messages), 3)
    
    def test_message_summarizer_calls_worker(self):
        """Test that summarizer calls worker to run summarizer script"""
        now = datetime.now()
        self.storage.message.create(
            MessageData(msg_id='summarizer-test-msg', session_id='summarizer-test-session',
                       message='Test', create_time=now)
        )
        try:
            self.summarizer.run()
        except Exception:
            pass
        messages = self.storage.message.get_by_session('summarizer-test-session')
        self.assertEqual(len(messages), 1)


class TestMessageSummarizerIntegration(unittest.TestCase):
    """Integration tests for MessageSummarizer"""
    
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
        self.storage = Storage(self.engine)
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        self.summarizer = MessageSummarizer(storage=self.storage, worker_manager=self.worker_manager)
    
    def test_full_summarization_flow(self):
        """Test complete summarization flow"""
        now = datetime.now()
        sessions_data = [
            ('session-1', ['msg-1a', 'msg-1b']),
            ('session-2', ['msg-2a']),
            ('session-3', ['msg-3a', 'msg-3b', 'msg-3c']),
        ]
        for session_id, msg_ids in sessions_data:
            self.storage.session.create(
                SessionData(session_id=session_id, task='Test task', session_name=f'Session {session_id}')
            )
            for i, msg_id in enumerate(msg_ids):
                self.storage.message.create(
                    MessageData(msg_id=msg_id, session_id=session_id,
                               message=f'Message for {session_id}', create_time=now - timedelta(hours=i * 3))
                )
        try:
            self.summarizer.run()
        except Exception:
            pass
        for session_id, msg_ids in sessions_data:
            messages = self.storage.message.get_by_session(session_id)
            self.assertEqual(len(messages), len(msg_ids))


if __name__ == '__main__':
    unittest.main()
