"""
Test SessionCleaner cron job
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
from topsailai_server.agent_daemon.croner.jobs.session_cleaner import SessionCleaner


class TestSessionCleaner(unittest.TestCase):
    """Test cases for SessionCleaner cron job"""
    
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
        self.storage = Storage(self.engine)
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        self.cleaner = SessionCleaner(storage=self.storage, worker_manager=self.worker_manager)
    
    def test_session_cleaner_initialization(self):
        """Test SessionCleaner initialization"""
        self.assertIsNotNone(self.cleaner)
        self.assertIsNotNone(self.cleaner.storage)
        self.assertIsNotNone(self.cleaner.worker_manager)
    
    def test_session_cleaner_finds_old_sessions(self):
        """Test finding sessions older than 1 year"""
        now = datetime.now()
        old_session = self.storage.session.create(
            SessionData(session_id='old-session', task='Test task', session_name='Old',
                       update_time=now - timedelta(days=400))
        )
        new_session = self.storage.session.create(
            SessionData(session_id='new-session', task='Test task', session_name='New',
                       update_time=now - timedelta(days=30))
        )
        one_year_ago = now - timedelta(days=365)
        sessions = self.storage.session.get_sessions_older_than(one_year_ago)
        session_ids = [s.session_id for s in sessions]
        self.assertIn('old-session', session_ids)
        self.assertNotIn('new-session', session_ids)
    
    def test_session_cleaner_deletes_session_messages(self):
        """Test that deleting a session also deletes its messages"""
        now = datetime.now()
        session = self.storage.session.create(
            SessionData(session_id='to-delete-session', task='Test task', session_name='Delete',
                       update_time=now - timedelta(days=400))
        )
        for i in range(3):
            self.storage.message.create(
                MessageData(msg_id=f'msg-to-delete-{i}', session_id='to-delete-session',
                           message=f'Message {i}', create_time=now - timedelta(days=400))
            )
        messages = self.storage.message.get_by_session('to-delete-session')
        self.assertEqual(len(messages), 3)
        deleted_count = self.storage.message.delete_messages_by_session('to-delete-session')
        self.assertEqual(deleted_count, 3)
        messages = self.storage.message.get_by_session('to-delete-session')
        self.assertEqual(len(messages), 0)
    
    def test_session_cleaner_deletes_session(self):
        """Test deleting a session"""
        now = datetime.now()
        session = self.storage.session.create(
            SessionData(session_id='delete-me', task='Test task', session_name='Delete Me',
                       update_time=now - timedelta(days=400))
        )
        session = self.storage.session.get('delete-me')
        self.assertIsNotNone(session)
        result = self.storage.session.delete('delete-me')
        session = self.storage.session.get('delete-me')
        self.assertIsNone(session)
    
    def test_session_cleaner_full_cleanup_flow(self):
        """Test complete cleanup flow"""
        now = datetime.now()
        old_sessions = ['old-1', 'old-2', 'old-3']
        for session_id in old_sessions:
            self.storage.session.create(
                SessionData(session_id=session_id, task='Test task', session_name=f'Old {session_id}',
                           update_time=now - timedelta(days=400))
            )
            for i in range(2):
                self.storage.message.create(
                    MessageData(msg_id=f'{session_id}-msg-{i}', session_id=session_id,
                               message=f'Message {i}', create_time=now - timedelta(days=400))
                )
        new_sessions = ['new-1', 'new-2']
        for session_id in new_sessions:
            self.storage.session.create(
                SessionData(session_id=session_id, task='Test task', session_name=f'New {session_id}',
                           update_time=now - timedelta(days=30))
            )
            for i in range(2):
                self.storage.message.create(
                    MessageData(msg_id=f'{session_id}-msg-{i}', session_id=session_id,
                               message=f'Message {i}', create_time=now - timedelta(days=30))
                )
        self.cleaner.run()
        for session_id in old_sessions:
            session = self.storage.session.get(session_id)
            self.assertIsNone(session)
        for session_id in new_sessions:
            session = self.storage.session.get(session_id)
            self.assertIsNotNone(session)
    
    def test_session_cleaner_preserves_recent_sessions(self):
        """Test that recent sessions are not deleted"""
        now = datetime.now()
        session = self.storage.session.create(
            SessionData(session_id='recent-session', task='Test task', session_name='Recent',
                       update_time=now - timedelta(days=180))
        )
        one_year_ago = now - timedelta(days=365)
        sessions = self.storage.session.get_sessions_older_than(one_year_ago)
        session_ids = [s.session_id for s in sessions]
        self.assertNotIn('recent-session', session_ids)
    
    def test_session_cleaner_handles_empty_database(self):
        """Test that cleaner handles empty database gracefully"""
        try:
            self.cleaner.run()
        except Exception as e:
            self.fail(f"Cleaner failed on empty database: {e}")
    
    def test_session_cleaner_handles_session_without_messages(self):
        """Test that cleaner handles sessions without messages"""
        now = datetime.now()
        session = self.storage.session.create(
            SessionData(session_id='no-messages-session', task='Test task', session_name='No Messages',
                       update_time=now - timedelta(days=400))
        )
        self.cleaner.run()
        session = self.storage.session.get('no-messages-session')
        self.assertIsNone(session)


class TestSessionCleanerIntegration(unittest.TestCase):
    """Integration tests for SessionCleaner"""
    
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
        self.storage = Storage(self.engine)
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        self.cleaner = SessionCleaner(storage=self.storage, worker_manager=self.worker_manager)
    
    def test_multiple_old_sessions_cleanup(self):
        """Test cleaning up multiple old sessions"""
        now = datetime.now()
        for i in range(10):
            session_id = f'old-session-{i}'
            self.storage.session.create(
                SessionData(session_id=session_id, task='Test task', session_name=f'Old {i}',
                           update_time=now - timedelta(days=400 + i))
            )
            for j in range(3):
                self.storage.message.create(
                    MessageData(msg_id=f'{session_id}-msg-{j}', session_id=session_id,
                               message=f'Message {j}', create_time=now - timedelta(days=400 + i))
                )
        self.cleaner.run()
        for i in range(10):
            session_id = f'old-session-{i}'
            session = self.storage.session.get(session_id)
            self.assertIsNone(session)


if __name__ == '__main__':
    unittest.main()
