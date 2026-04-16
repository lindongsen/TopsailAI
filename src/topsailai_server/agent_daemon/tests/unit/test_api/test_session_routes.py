'''
  Author: Dawsonlin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose: Unit tests for Session API routes and Health Check
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


class TestHealthCheck(unittest.TestCase):
    """Test cases for Health Check endpoint"""
    
    def setUp(self):
        """Set up test fixtures"""
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
        self.app = create_app(
            self.storage.session,
            self.storage.message,
            self.worker_manager,
            MockScheduler()
        )
        
        # Create test client
        self.client = TestClient(self.app)
    
    def tearDown(self):
        # Clean up temp database
        self.engine.dispose()
        try:
            os.remove('/tmp/test_topsailai_agent_daemon.db')
        except FileNotFoundError:
            pass
    
    def test_health_check(self):
        """Test health check endpoint"""
        response = self.client.get('/health')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        self.assertIn('data', data)


class TestGetSession(unittest.TestCase):
    """Test cases for GetSession API endpoint"""
    
    def setUp(self):
        """Set up test fixtures"""
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
        self.app = create_app(
            self.storage.session,
            self.storage.message,
            self.worker_manager,
            MockScheduler()
        )
        
        # Create test client
        self.client = TestClient(self.app)
        
        # Create a test session
        self.test_session_id = 'test-session-001'
        self.test_session = SessionData(
            session_id=self.test_session_id,
            session_name='Test Session',
            task='Test task',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(self.test_session)
    
    def tearDown(self):
        # Clean up temp database
        self.engine.dispose()
        try:
            os.remove('/tmp/test_topsailai_agent_daemon.db')
        except FileNotFoundError:
            pass
    
    def test_get_session_success_idle(self):
        """Test retrieving an existing session with idle status"""
        response = self.client.get(f'/api/v1/session/{self.test_session_id}')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check response structure
        self.assertEqual(data['code'], 0)
        self.assertIn('data', data)
        
        session_data = data['data']
        
        # Check all required fields
        self.assertEqual(session_data['session_id'], self.test_session_id)
        self.assertEqual(session_data['session_name'], 'Test Session')
        self.assertEqual(session_data['task'], 'Test task')
        self.assertIn('create_time', session_data)
        self.assertIn('update_time', session_data)
        self.assertIn('processed_msg_id', session_data)
        
        # Check status field is present and valid
        self.assertIn('status', session_data)
        self.assertIn(session_data['status'], ['idle', 'processing'])
    
    def test_get_session_success_processing(self):
        """Test retrieving an existing session with processing status"""
        # Set processed_msg_id to simulate a session being processed
        self.storage.session.update_processed_msg_id(
            self.test_session_id,
            'msg-001'
        )
        
        response = self.client.get(f'/api/v1/session/{self.test_session_id}')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check response structure
        self.assertEqual(data['code'], 0)
        self.assertIn('data', data)
        
        session_data = data['data']
        
        # Check all required fields
        self.assertEqual(session_data['session_id'], self.test_session_id)
        self.assertIn('status', session_data)
        self.assertIn(session_data['status'], ['idle', 'processing'])
    
    def test_get_session_invalid_id(self):
        """Test invalid session_id format returns error"""
        invalid_session_id = 'invalid@session#id!'
        
        response = self.client.get(f'/api/v1/session/{invalid_session_id}')
        
        # The endpoint should return 200 with error code for invalid format
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Should have an error message
        self.assertIn('code', data)
        self.assertIn('message', data)
        self.assertNotEqual(data['code'], 0)
    
    def test_get_session_not_found(self):
        """Test non-existent session returns 404"""
        non_existent_id = 'non-existent-session-999'
        
        response = self.client.get(f'/api/v1/session/{non_existent_id}')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check error response
        self.assertEqual(data['code'], 404)
        self.assertIn('message', data)
        self.assertIn('not found', data['message'].lower())
    
    def test_get_session_with_all_fields(self):
        """Test that all session fields are returned correctly"""
        # Update session with all fields
        self.storage.session.update_processed_msg_id(
            self.test_session_id,
            'msg-processed-001'
        )
        
        # Update task via SessionData
        updated_session = SessionData(
            session_id=self.test_session_id,
            session_name='Test Session',
            task='Complete task info',
            create_time=self.test_session.create_time,
            update_time=datetime.now(),
            processed_msg_id='msg-processed-001'
        )
        self.storage.session.update(updated_session)
        
        response = self.client.get(f'/api/v1/session/{self.test_session_id}')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        session_data = data['data']
        
        # Verify all fields
        self.assertEqual(session_data['session_id'], self.test_session_id)
        self.assertEqual(session_data['session_name'], 'Test Session')
        self.assertEqual(session_data['task'], 'Complete task info')
        self.assertEqual(session_data['processed_msg_id'], 'msg-processed-001')
        self.assertIn('status', session_data)
        self.assertIn('create_time', session_data)
        self.assertIn('update_time', session_data)


if __name__ == '__main__':
    unittest.main()
