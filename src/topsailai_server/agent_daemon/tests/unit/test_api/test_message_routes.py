'''
  Author: Dawsonlin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose: Unit tests for Message API routes
'''

import unittest
import os

# Set test environment variables before imports
os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_DB_URL'] = 'sqlite:////tmp/test_topsailai_agent_daemon.db'

from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from topsailai_server.agent_daemon.storage import Storage, SessionData, MessageData, SessionSQLAlchemy
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.configer import get_config


class TestMessageAPI(unittest.TestCase):
    """Test cases for Message API routes"""
    
    def setUp(self):
        # Create temp database file
        self.db_path = '/tmp/test_topsailai_agent_daemon.db'
        # Remove any existing db file
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        
        self.engine = create_engine(f'sqlite:///{self.db_path}', connect_args={'check_same_thread': False})
        
        # Initialize storage
        self.storage = Storage(self.engine)
        self.storage.init_db()
        
        # Initialize worker manager
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        
        # Create mock scheduler
        class MockScheduler:
            def start(self): pass
            def stop(self): pass
        
        # Create FastAPI app
        from topsailai_server.agent_daemon.api.app import create_app
        self.scheduler = MockScheduler()
        self.app = create_app(self.storage.session, self.storage.message, self.worker_manager, self.scheduler)
        self.client = TestClient(self.app)

    def tearDown(self):
        # Clean up temp database
        self.engine.dispose()
        try:
            os.remove('/tmp/test_topsailai_agent_daemon.db')
        except FileNotFoundError:
            pass

    def test_receive_message_success(self):
        """Test receiving a valid message"""
        response = self.client.post('/api/v1/message', json={
            'message': 'Hello, world!',
            'session_id': 'test-session-1',
            'role': 'user'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        self.assertIn('msg_id', data['data'])
    
    def test_receive_message_missing_message(self):
        """Test receiving message without message content"""
        response = self.client.post('/api/v1/message', json={
            'session_id': 'test-session-2'
        })
        
        self.assertEqual(response.status_code, 422)  # FastAPI returns 422 for validation errors
        data = response.json()
        self.assertIn('detail', data)
    
    def test_receive_message_missing_session_id(self):
        """Test receiving message without session_id"""
        response = self.client.post('/api/v1/message', json={
            'message': 'Hello!'
        })
        
        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertIn('detail', data)
    
    def test_retrieve_messages(self):
        """Test retrieving messages for a session"""
        # First create a message
        self.client.post('/api/v1/message', json={
            'message': 'Test message',
            'session_id': 'test-session-3',
            'role': 'user'
        })
        
        # Retrieve messages
        response = self.client.get('/api/v1/message?session_id=test-session-3')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data['data'], list)
    
    def test_retrieve_messages_missing_session_id(self):
        """Test retrieving messages without session_id"""
        response = self.client.get('/api/v1/message')
        
        self.assertEqual(response.status_code, 422)  # FastAPI returns 422 for missing required params

    def test_receive_message_with_processed_msg_id_triggers_processing(self):
        """Test that check_and_process_messages is called even when processed_msg_id is provided (Bug 3 fix)"""
        from unittest.mock import patch
        
        with patch('topsailai_server.agent_daemon.api.routes.message.check_and_process_messages') as mock_check:
            response = self.client.post('/api/v1/message', json={
                'message': 'Hello with processed_msg_id!',
                'session_id': 'test-session-proc-1',
                'role': 'user',
                'processed_msg_id': 'some-previous-msg-id'
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)
            # Verify check_and_process_messages was called (Bug 3 fix: always check for more unprocessed messages)
            mock_check.assert_called_once()
            call_args = mock_check.call_args
            self.assertEqual(call_args[0][0], 'test-session-proc-1')  # session_id
    
    def test_receive_message_with_processed_msg_id_updates_session(self):
        """Test that session's processed_msg_id is updated when processed_msg_id is provided"""
        from unittest.mock import patch
        
        with patch('topsailai_server.agent_daemon.api.routes.message.check_and_process_messages') as mock_check:
            # First create a session by sending a message
            self.client.post('/api/v1/message', json={
                'message': 'Initial message',
                'session_id': 'test-session-proc-2',
                'role': 'user'
            })
            
            # Now send a message with processed_msg_id
            response = self.client.post('/api/v1/message', json={
                'message': 'Follow-up message',
                'session_id': 'test-session-proc-2',
                'role': 'user',
                'processed_msg_id': 'updated-msg-id-123'
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)
            
            # Verify the session's processed_msg_id was updated
            session = self.storage.session.get('test-session-proc-2')
            self.assertEqual(session.processed_msg_id, 'updated-msg-id-123')


if __name__ == '__main__':
    unittest.main()
