'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Unit tests for Session Manager
'''

import unittest
import os
import tempfile
from datetime import datetime, timedelta

# Set test environment variables before imports
os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'

from sqlalchemy import create_engine

from topsailai_server.agent_daemon.storage.session_manager.sql import SessionSQLAlchemy
from topsailai_server.agent_daemon.storage.session_manager.__base import SessionData


class TestSessionManager(unittest.TestCase):
    """Test cases for Session Manager"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.engine = create_engine('sqlite:///:memory:')
        cls.session_manager = SessionSQLAlchemy(cls.engine)
    
    def setUp(self):
        """Set up each test"""
        pass
    
    def test_create_session(self):
        """Test creating a new session"""
        session_data = SessionData(
            session_id='test-session-1',
            session_name='Test Session',
            task='Test task',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        
        result = self.session_manager.create(session_data)
        self.assertTrue(result)
        
        # Verify session was created
        retrieved = self.session_manager.get('test-session-1')
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.session_id, 'test-session-1')
        self.assertEqual(retrieved.session_name, 'Test Session')
    
    def test_get_session(self):
        """Test retrieving a session"""
        session_data = SessionData(
            session_id='test-session-2',
            session_name='Test Session 2',
            task='Test task 2',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        
        self.session_manager.create(session_data)
        retrieved = self.session_manager.get('test-session-2')
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.session_id, 'test-session-2')
    
    def test_update_session(self):
        """Test updating a session"""
        session_data = SessionData(
            session_id='test-session-3',
            session_name='Original Name',
            task='Original task',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        
        self.session_manager.create(session_data)
        
        # Update session
        session_data.session_name = 'Updated Name'
        session_data.task = 'Updated task'
        result = self.session_manager.update(session_data)
        
        self.assertTrue(result)
        
        # Verify update
        retrieved = self.session_manager.get('test-session-3')
        self.assertEqual(retrieved.session_name, 'Updated Name')
        self.assertEqual(retrieved.task, 'Updated task')
    
    def test_update_processed_msg_id(self):
        """Test updating processed_msg_id"""
        session_data = SessionData(
            session_id='test-session-4',
            session_name='Test Session 4',
            task='Test task 4',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        
        self.session_manager.create(session_data)
        
        # Update processed_msg_id
        result = self.session_manager.update_processed_msg_id('test-session-4', 'msg-123')
        
        self.assertTrue(result)
        
        # Verify update
        retrieved = self.session_manager.get('test-session-4')
        self.assertEqual(retrieved.processed_msg_id, 'msg-123')
    
    def test_delete_session(self):
        """Test deleting a session"""
        session_data = SessionData(
            session_id='test-session-5',
            session_name='Test Session 5',
            task='Test task 5',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        
        self.session_manager.create(session_data)
        
        # Delete session
        result = self.session_manager.delete('test-session-5')
        self.assertTrue(result)
        
        # Verify deletion
        retrieved = self.session_manager.get('test-session-5')
        self.assertIsNone(retrieved)
    
    def test_get_or_create(self):
        """Test get_or_create method"""
        # Create new session
        session = self.session_manager.get_or_create('test-session-6', 'New Session', 'New task')
        
        self.assertEqual(session.session_id, 'test-session-6')
        self.assertEqual(session.session_name, 'New Session')
        
        # Get existing session
        existing = self.session_manager.get_or_create('test-session-6', 'Different Name', 'Different task')
        
        self.assertEqual(existing.session_id, 'test-session-6')
        self.assertEqual(existing.session_name, 'New Session')  # Should not change
    
    def test_get_sessions_older_than(self):
        """Test getting sessions older than a date"""
        # Create old session
        old_time = datetime.now() - timedelta(days=400)
        session_data = SessionData(
            session_id='old-session',
            session_name='Old Session',
            task='Old task',
            create_time=old_time,
            update_time=old_time,
            processed_msg_id=None
        )
        self.session_manager.create(session_data)
        
        # Create recent session
        recent_session = SessionData(
            session_id='recent-session',
            session_name='Recent Session',
            task='Recent task',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.session_manager.create(recent_session)
        
        # Get sessions older than 1 year
        cutoff = datetime.now() - timedelta(days=365)
        old_sessions = self.session_manager.get_sessions_older_than(cutoff)
        
        session_ids = [s.session_id for s in old_sessions]
        self.assertIn('old-session', session_ids)
        self.assertNotIn('recent-session', session_ids)


if __name__ == '__main__':
    unittest.main()
