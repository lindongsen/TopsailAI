'''
  Author: Dawsonlin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose: Unit tests for Task API routes
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

    def test_set_task_result_updates_processed_msg_id(self):
        """Verify that SetTaskResult uses update_processed_msg_id instead of manual session update (Bug 4 fix)"""
        from unittest.mock import patch
        
        # First create a message to get a valid msg_id
        msg_response = self.client.post('/api/v1/message', json={
            'message': 'Test message for processed_msg_id',
            'session_id': 'test-session-bug4',
            'role': 'user'
        })
        msg_id = msg_response.json()['data']['msg_id']
        
        # Patch at the class level since the route creates a new Storage instance via Depends(get_storage)
        with patch.object(SessionSQLAlchemy, 'update_processed_msg_id') as mock_update:
            # Set task result
            response = self.client.post('/api/v1/task', json={
                'session_id': 'test-session-bug4',
                'processed_msg_id': msg_id,
                'task_id': 'task-bug4',
                'task_result': 'Bug 4 fix verification'
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)
            
            # Verify update_processed_msg_id was called with correct arguments (Bug 4 fix)
            mock_update.assert_called_once_with('test-session-bug4', msg_id)
    
    def test_set_task_result_triggers_processing_check(self):
        """Verify that SetTaskResult calls check_and_process_messages after setting the task result"""
        from unittest.mock import patch
        
        # First create a message to get a valid msg_id
        msg_response = self.client.post('/api/v1/message', json={
            'message': 'Test message for processing check',
            'session_id': 'test-session-proc-check',
            'role': 'user'
        })
        msg_id = msg_response.json()['data']['msg_id']
        
        with patch('topsailai_server.agent_daemon.api.routes.task.check_and_process_messages') as mock_check:
            # Set task result
            response = self.client.post('/api/v1/task', json={
                'session_id': 'test-session-proc-check',
                'processed_msg_id': msg_id,
                'task_id': 'task-proc-check',
                'task_result': 'Processing check verification'
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)
            
            # Verify check_and_process_messages was called after setting task result
            mock_check.assert_called_once()
            call_args = mock_check.call_args
            self.assertEqual(call_args[0][0], 'test-session-proc-check')  # session_id


if __name__ == '__main__':
    unittest.main()


    def test_set_task_result_with_processed_msg_id(self):
        """Test SetTaskResult with processed_msg_id updates session's processed_msg_id"""
        from unittest.mock import patch

        # First create a session and message
        self.client.post('/api/v1/message', json={
            'message': 'Initial message for task',
            'session_id': 'test-session-task-proc-1',
            'role': 'user'
        })

        # Get the message ID from the response
        msg_response = self.client.post('/api/v1/message', json={
            'message': 'Task request message',
            'session_id': 'test-session-task-proc-1',
            'role': 'user'
        })
        msg_id = msg_response.json()['data']['msg_id']

        with patch('topsailai_server.agent_daemon.api.routes.task.check_and_process_messages') as mock_check:
            # Call SetTaskResult with processed_msg_id
            response = self.client.post('/api/v1/task', json={
                'session_id': 'test-session-task-proc-1',
                'processed_msg_id': msg_id,
                'task_id': 'task_proc_001',
                'task_result': 'Task completed successfully'
            })

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)

            # Verify the session's processed_msg_id was updated
            session = self.storage.session.get('test-session-task-proc-1')
            self.assertEqual(session.processed_msg_id, msg_id)

            # Verify check_and_process_messages was called
            mock_check.assert_called_once()
