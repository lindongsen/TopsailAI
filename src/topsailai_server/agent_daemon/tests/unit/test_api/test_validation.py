'''
  Author: Dawsonlin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose: Unit tests for validation functions and edge cases
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


class TestValidationFunctions(unittest.TestCase):
    """Test cases for validation functions"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.db_path = '/tmp/test_validation.db'
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        
        self.engine = create_engine(f'sqlite:///{self.db_path}', connect_args={'check_same_thread': False})
        self.storage = Storage(self.engine)
        self.storage.init_db()
        
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        
        class MockScheduler:
            def start(self): pass
            def stop(self): pass
        
        from topsailai_server.agent_daemon.api.app import create_app
        self.app = create_app(
            self.storage.session,
            self.storage.message,
            self.worker_manager,
            MockScheduler()
        )
        self.client = TestClient(self.app)
    
    def tearDown(self):
        self.engine.dispose()
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass
    
    def test_validate_session_id_valid_uuid(self):
        """Test _validate_session_id with valid UUID"""
        valid_uuid = '550e8400-e29b-41d4-a716-446655440000'
        
        response = self.client.post('/api/v1/message', json={
            'message': 'Test',
            'session_id': valid_uuid,
            'role': 'user'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
    
    def test_validate_session_id_valid_alphanumeric(self):
        """Test _validate_session_id with valid alphanumeric"""
        valid_ids = [
            'session123',
            'test_session_456',
            'Session789',
            'abc123def456',
        ]
        
        for session_id in valid_ids:
            response = self.client.post('/api/v1/message', json={
                'message': 'Test',
                'session_id': session_id,
                'role': 'user'
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0, f"Failed for session_id: {session_id}")
    
    def test_validate_session_id_invalid(self):
        """Test _validate_session_id with invalid inputs"""
        invalid_ids = [
            '',
            'session@domain.com',
            'session#hash',
            'session space',
            'session!exclamation',
        ]
        
        for session_id in invalid_ids:
            response = self.client.post('/api/v1/message', json={
                'message': 'Test',
                'session_id': session_id,
                'role': 'user'
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertNotEqual(data['code'], 0, f"Should fail for session_id: {session_id}")
    
    def test_validate_message_content_whitespace(self):
        """Test _validate_message_content with whitespace-only content"""
        whitespace_messages = [
            '   ',
            '\t\n\r',
            '  \t  ',
        ]
        
        for msg in whitespace_messages:
            response = self.client.post('/api/v1/message', json={
                'message': msg,
                'session_id': 'test-session',
                'role': 'user'
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertNotEqual(data['code'], 0)
    
    def test_validate_role_case_sensitive(self):
        """Test _validate_role is case sensitive"""
        case_variants = [
            'User',
            'USER',
            'Assistant',
            'ASSISTANT',
            'user ',  # trailing space
            ' assistant',  # leading space
        ]
        
        for role in case_variants:
            response = self.client.post('/api/v1/message', json={
                'message': 'Test',
                'session_id': 'test-session',
                'role': role
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertNotEqual(data['code'], 0, f"Should fail for role: {role}")
    
    def test_error_response_format_validation(self):
        """Test error response format for validation failures"""
        response = self.client.post('/api/v1/message', json={
            'message': '',
            'session_id': 'invalid@id',
            'role': 'invalid_role'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify error response format
        self.assertIn('code', data)
        self.assertIn('message', data)
        self.assertNotEqual(data['code'], 0)
        self.assertIsInstance(data['message'], str)
        self.assertTrue(len(data['message']) > 0)


class TestMalformedInput(unittest.TestCase):
    """Test cases for malformed input data"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.db_path = '/tmp/test_malformed.db'
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        
        self.engine = create_engine(f'sqlite:///{self.db_path}', connect_args={'check_same_thread': False})
        self.storage = Storage(self.engine)
        self.storage.init_db()
        
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        
        class MockScheduler:
            def start(self): pass
            def stop(self): pass
        
        from topsailai_server.agent_daemon.api.app import create_app
        self.app = create_app(
            self.storage.session,
            self.storage.message,
            self.worker_manager,
            MockScheduler()
        )
        self.client = TestClient(self.app)
    
    def tearDown(self):
        self.engine.dispose()
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass
    
    def test_invalid_session_id_special_characters(self):
        """Test invalid session_id with special characters"""
        invalid_session_ids = [
            'session<script>alert(1)</script>',
            'session;drop table session;--',
            'session../../../etc/passwd',
            'session\x00nullbyte',
            'session\nnewline',
            'session\ttab',
        ]
        
        for session_id in invalid_session_ids:
            response = self.client.post('/api/v1/message', json={
                'message': 'Test message',
                'session_id': session_id,
                'role': 'user'
            })
            
            # Should return validation error
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertNotEqual(data['code'], 0)
    
    def test_invalid_session_id_empty_string(self):
        """Test invalid session_id with empty string"""
        response = self.client.post('/api/v1/message', json={
            'message': 'Test message',
            'session_id': '',
            'role': 'user'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data['code'], 0)
    
    def test_invalid_message_content_none(self):
        """Test invalid message content with None"""
        response = self.client.post('/api/v1/message', json={
            'message': None,
            'session_id': 'test-session',
            'role': 'user'
        })
        
        self.assertEqual(response.status_code, 422)  # FastAPI validation
    
    def test_invalid_message_content_empty(self):
        """Test invalid message content with empty string"""
        response = self.client.post('/api/v1/message', json={
            'message': '',
            'session_id': 'test-session',
            'role': 'user'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data['code'], 0)
    
    def test_invalid_message_content_too_long(self):
        """Test invalid message content that is too long"""
        long_message = 'x' * 100000  # 100KB message
        
        response = self.client.post('/api/v1/message', json={
            'message': long_message,
            'session_id': 'test-session',
            'role': 'user'
        })
        
        # Should either succeed or return validation error
        self.assertIn(response.status_code, [200, 422, 413])
    
    def test_invalid_role_values(self):
        """Test invalid role values (not 'user' or 'assistant')"""
        invalid_roles = [
            'admin',
            'system',
            'bot',
            '123',
            '',
            None,
            'USER',  # case sensitive
            'Assistant',
        ]
        
        for role in invalid_roles:
            json_data = {
                'message': 'Test message',
                'session_id': 'test-session',
                'role': role
            }
            if role is None:
                del json_data['role']  # FastAPI will use default
            
            response = self.client.post('/api/v1/message', json=json_data)
            
            if role is None:
                # Should use default 'user'
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data['code'], 0)
            else:
                # Should return validation error
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertNotEqual(data['code'], 0)
    
    def test_invalid_task_id_format(self):
        """Test invalid task_id formats"""
        # First create a valid message
        msg_response = self.client.post('/api/v1/message', json={
            'message': 'Task message',
            'session_id': 'task-format-session',
            'role': 'user'
        })
        msg_id = msg_response.json()['data']['msg_id']
        
        invalid_task_ids = [
            '',
            'task<script>',
            'task;drop table;--',
            'task\x00',
        ]
        
        for task_id in invalid_task_ids:
            response = self.client.post('/api/v1/task', json={
                'session_id': 'task-format-session',
                'processed_msg_id': msg_id,
                'task_id': task_id,
                'task_result': 'Result'
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertNotEqual(data['code'], 0)
    
    def test_invalid_msg_id_format(self):
        """Test invalid msg_id formats"""
        invalid_msg_ids = [
            '',
            'msg<script>',
            'msg;drop table;--',
            'msg\x00',
        ]
        
        for msg_id in invalid_msg_ids:
            response = self.client.post('/api/v1/task', json={
                'session_id': 'msg-format-session',
                'processed_msg_id': msg_id,
                'task_id': 'task-123',
                'task_result': 'Result'
            })
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertNotEqual(data['code'], 0)


class TestSequentialProcessing(unittest.TestCase):
    """Test cases for sequential message processing (SQLite safe)"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.db_path = '/tmp/test_sequential.db'
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        
        self.engine = create_engine(f'sqlite:///{self.db_path}', connect_args={'check_same_thread': False})
        self.storage = Storage(self.engine)
        self.storage.init_db()
        
        self.config = get_config()
        self.worker_manager = WorkerManager(self.config)
        
        class MockScheduler:
            def start(self): pass
            def stop(self): pass
        
        from topsailai_server.agent_daemon.api.app import create_app
        self.app = create_app(
            self.storage.session,
            self.storage.message,
            self.worker_manager,
            MockScheduler()
        )
        self.client = TestClient(self.app)
    
    def tearDown(self):
        self.engine.dispose()
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass
    
    def test_sequential_message_submissions_same_session(self):
        """Test sequential message submissions to same session"""
        session_id = 'sequential-session-1'
        
        # Send 5 messages sequentially
        for i in range(5):
            response = self.client.post('/api/v1/message', json={
                'message': f'Sequential message {i}',
                'session_id': session_id,
                'role': 'user'
            })
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)
        
        # Verify all messages were stored
        session_messages = self.storage.message.get_by_session(session_id)
        self.assertEqual(len(session_messages), 5)
    
    def test_race_condition_processed_msg_id(self):
        """Test processed_msg_id updates work correctly"""
        session_id = 'race-condition-session'
        
        # Create initial message
        response1 = self.client.post('/api/v1/message', json={
            'message': 'First message',
            'session_id': session_id,
            'role': 'user'
        })
        msg_id_1 = response1.json()['data']['msg_id']
        
        # Create second message
        response2 = self.client.post('/api/v1/message', json={
            'message': 'Second message',
            'session_id': session_id,
            'role': 'user'
        })
        msg_id_2 = response2.json()['data']['msg_id']
        
        # Update with first msg_id
        response3 = self.client.post('/api/v1/message', json={
            'message': 'Third message',
            'session_id': session_id,
            'role': 'user',
            'processed_msg_id': msg_id_1
        })
        self.assertEqual(response3.status_code, 200)
        
        # Update with second msg_id (should overwrite)
        response4 = self.client.post('/api/v1/message', json={
            'message': 'Fourth message',
            'session_id': session_id,
            'role': 'user',
            'processed_msg_id': msg_id_2
        })
        self.assertEqual(response4.status_code, 200)
        
        # Verify final state
        session = self.storage.session.get(session_id)
        self.assertEqual(session.processed_msg_id, msg_id_2)
    
    def test_sequential_task_result_setting(self):
        """Test sequential task result setting"""
        session_id = 'sequential-task-session'
        
        # Create initial message
        msg_response = self.client.post('/api/v1/message', json={
            'message': 'Task message',
            'session_id': session_id,
            'role': 'user'
        })
        msg_id = msg_response.json()['data']['msg_id']
        
        # Set 3 task results sequentially
        for i in range(3):
            response = self.client.post('/api/v1/task', json={
                'session_id': session_id,
                'processed_msg_id': msg_id,
                'task_id': f'task-{i}',
                'task_result': f'Result {i}'
            })
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)


if __name__ == '__main__':
    unittest.main()
