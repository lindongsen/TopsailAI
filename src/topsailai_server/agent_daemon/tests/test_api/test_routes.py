'''
  Author: Dawsonlin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Integration tests for API routes
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

from topsailai_server.agent_daemon.storage import Storage, SessionData, MessageData
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


class TestTaskAPI(unittest.TestCase):
    """Test cases for Task API routes"""
    
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
    
    def test_set_task_result_success(self):
        """Test setting task result"""
        # First create a message
        msg_response = self.client.post('/api/v1/message', json={
            'message': 'Test message',
            'session_id': 'test-session-task',
            'role': 'user'
        })
        msg_id = msg_response.json()['data']['msg_id']
        
        # Set task result
        response = self.client.post('/api/v1/task', json={
            'session_id': 'test-session-task',
            'processed_msg_id': msg_id,
            'task_id': 'task-123',
            'task_result': 'Task completed successfully'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
    
    def test_set_task_result_missing_fields(self):
        """Test setting task result with missing required fields"""
        response = self.client.post('/api/v1/task', json={
            'session_id': 'test-session-task'
        })
        
        self.assertEqual(response.status_code, 422)
    
    def test_retrieve_tasks(self):
        """Test retrieving tasks"""
        # First create a message and set task result
        msg_response = self.client.post('/api/v1/message', json={
            'message': 'Test message',
            'session_id': 'test-session-task-2',
            'role': 'user'
        })
        msg_id = msg_response.json()['data']['msg_id']
        
        self.client.post('/api/v1/task', json={
            'session_id': 'test-session-task-2',
            'processed_msg_id': msg_id,
            'task_id': 'task-456',
            'task_result': 'Result here'
        })
        
        # Retrieve tasks
        response = self.client.get('/api/v1/task?session_id=test-session-task-2')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data['data'], list)


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


if __name__ == '__main__':
    unittest.main()
