'''
  Author: km2
  Email: lin_dongsen@126.com
  Created: 2026-05-04
  Purpose: Integration tests for auth in session/message/task routes.
'''

import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# Set test environment variables BEFORE any imports
os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_DB_URL'] = 'sqlite:////tmp/test_auth_integration.db'
os.environ['TOPSAILAI_AGENT_DAEMON_API_KEY_ENABLED'] = 'true'

from fastapi import FastAPI
from fastapi.testclient import TestClient

from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData
from topsailai_server.agent_daemon.api.middleware import auth as auth_module
from topsailai_server.agent_daemon.api.routes import session as session_module
from topsailai_server.agent_daemon.api.routes import message as message_module
from topsailai_server.agent_daemon.api.routes import task as task_module


class TestAuthIntegration(unittest.TestCase):
    """Test auth integration in session, message, and task routes."""

    def setUp(self):
        """Set up test fixtures with mocked storage and routes."""
        # Create mock storage
        self.mock_api_key_storage = MagicMock()
        self.mock_session_storage = MagicMock()
        self.mock_message_storage = MagicMock()
        self.mock_worker_manager = MagicMock()

        # Default: unknown API key returns None
        self.mock_api_key_storage.get_api_key_by_value.return_value = None

        # Set up mock engine
        self.mock_engine = MagicMock()
        self.mock_session_storage.engine = self.mock_engine
        self.mock_message_storage.engine = self.mock_engine

        # Create mock storage facade
        self.mock_storage = MagicMock()
        self.mock_storage.session = self.mock_session_storage
        self.mock_storage.message = self.mock_message_storage
        self.mock_storage.api_key = self.mock_api_key_storage

        # Patch Storage constructor
        self.storage_patch = patch(
            'topsailai_server.agent_daemon.api.routes.session.Storage',
            return_value=self.mock_storage
        )
        self.storage_patch.start()

        self.msg_storage_patch = patch(
            'topsailai_server.agent_daemon.api.routes.message.Storage',
            return_value=self.mock_storage
        )
        self.msg_storage_patch.start()

        self.task_storage_patch = patch(
            'topsailai_server.agent_daemon.api.routes.task.Storage',
            return_value=self.mock_storage
        )
        self.task_storage_patch.start()

        # Set auth module storage
        auth_module._api_key_storage = self.mock_api_key_storage

        # Set route module dependencies
        session_module.set_dependencies(
            self.mock_session_storage,
            self.mock_message_storage,
            self.mock_worker_manager
        )
        message_module.set_dependencies(
            self.mock_session_storage,
            self.mock_message_storage,
            self.mock_worker_manager
        )
        task_module.set_dependencies(
            self.mock_session_storage,
            self.mock_message_storage,
            self.mock_worker_manager
        )

        # Create FastAPI app with routes
        self.app = FastAPI()
        self.app.include_router(session_module.router)
        self.app.include_router(message_module.router)
        self.app.include_router(task_module.router)

        self.client = TestClient(self.app)

        # Create test API keys
        self.admin_key = ApiKeyData(
            api_key_id='admin-key-001',
            api_key='admin-secret-key',
            name='Admin Key',
            role='admin',
            rate_limit=0,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now()
        )
        self.user_key = ApiKeyData(
            api_key_id='user-key-001',
            api_key='user-secret-key',
            name='User Key',
            role='user',
            rate_limit=10,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now()
        )
        self.user_key_unbound = ApiKeyData(
            api_key_id='user-key-002',
            api_key='user-secret-key-unbound',
            name='User Key Unbound',
            role='user',
            rate_limit=10,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now()
        )

    def tearDown(self):
        """Clean up patches and global state."""
        self.storage_patch.stop()
        self.msg_storage_patch.stop()
        self.task_storage_patch.stop()
        auth_module._api_key_storage = None

    def _make_mock_session(self, session_id='test-session', session_name='Test Session',
                           task=None, processed_msg_id=None):
        """Create a properly configured mock session object."""
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.session_name = session_name
        mock_session.task = task
        mock_session.create_time = datetime.now()
        mock_session.update_time = datetime.now()
        mock_session.processed_msg_id = processed_msg_id
        return mock_session

    # ------------------------------------------------------------------
    # Session Routes Auth Tests
    # ------------------------------------------------------------------

    def test_get_session_requires_auth(self):
        """GET /api/v1/session/{session_id} without auth returns 401."""
        response = self.client.get('/api/v1/session/test-session')
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn('Missing API key', data['detail'])

    def test_get_session_admin_can_access_any_session(self):
        """Admin API key can access any session."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        mock_session = self._make_mock_session('test-session', 'Test Session')
        self.mock_session_storage.get.return_value = mock_session

        self.mock_worker_manager.check_session_state.return_value = 'idle'

        response = self.client.get(
            '/api/v1/session/test-session',
            headers={'X-API-Key': 'admin-secret-key'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        self.assertEqual(data['data']['session_id'], 'test-session')

    def test_get_session_user_with_bound_session_can_access(self):
        """User API key with bound session can access that session."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_api_key_storage.is_session_bound.return_value = True

        mock_session = self._make_mock_session('bound-session', 'Bound Session')
        self.mock_session_storage.get.return_value = mock_session

        self.mock_worker_manager.check_session_state.return_value = 'idle'

        response = self.client.get(
            '/api/v1/session/bound-session',
            headers={'X-API-Key': 'user-secret-key'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)

    def test_get_session_user_without_bound_session_gets_403(self):
        """User API key without bound session gets 403."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key_unbound
        self.mock_api_key_storage.is_session_bound.return_value = False

        response = self.client.get(
            '/api/v1/session/unbound-session',
            headers={'X-API-Key': 'user-secret-key-unbound'}
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn('Access denied', data['detail'])

    def test_process_session_requires_auth(self):
        """POST /api/v1/session/process without auth returns 401."""
        response = self.client.post('/api/v1/session/process', json={
            'session_id': 'test-session'
        })
        self.assertEqual(response.status_code, 401)

    def test_process_session_admin_can_process_any_session(self):
        """Admin API key can process any session."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        mock_session = MagicMock()
        mock_session.processed_msg_id = 'msg-001'
        self.mock_session_storage.get.return_value = mock_session

        # Mock messages - no unprocessed messages
        self.mock_message_storage.get_messages.return_value = []

        with patch('topsailai_server.agent_daemon.api.routes.session.check_and_process_messages') as mock_check:
            mock_check.return_value = None
            response = self.client.post(
                '/api/v1/session/process',
                json={'session_id': 'test-session'},
                headers={'X-API-Key': 'admin-secret-key'}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)

    def test_process_session_user_without_bound_session_gets_403(self):
        """User API key without bound session gets 403 on process."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key_unbound
        self.mock_api_key_storage.is_session_bound.return_value = False

        response = self.client.post(
            '/api/v1/session/process',
            json={'session_id': 'unbound-session'},
            headers={'X-API-Key': 'user-secret-key-unbound'}
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn('Access denied', data['detail'])

    # ------------------------------------------------------------------
    # Message Routes Auth + Rate Limit Tests
    # ------------------------------------------------------------------

    def test_receive_message_requires_auth(self):
        """POST /api/v1/message without auth returns 401."""
        response = self.client.post('/api/v1/message', json={
            'message': 'Hello',
            'session_id': 'test-session'
        })
        self.assertEqual(response.status_code, 401)

    def test_receive_message_admin_can_send_to_any_session(self):
        """Admin API key can send messages to any session."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        self.mock_session_storage.get.return_value = None

        with patch('topsailai_server.agent_daemon.api.routes.message.check_and_process_messages'):
            response = self.client.post(
                '/api/v1/message',
                json={
                    'message': 'Hello from admin',
                    'session_id': 'any-session'
                },
                headers={'X-API-Key': 'admin-secret-key'}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)

    def test_receive_message_user_with_bound_session_can_send(self):
        """User API key with bound session can send messages."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_api_key_storage.is_session_bound.return_value = True
        self.mock_api_key_storage.count_rate_limit.return_value = 0

        self.mock_session_storage.get.return_value = None

        with patch('topsailai_server.agent_daemon.api.routes.message.check_and_process_messages'):
            response = self.client.post(
                '/api/v1/message',
                json={
                    'message': 'Hello from user',
                    'session_id': 'bound-session'
                },
                headers={'X-API-Key': 'user-secret-key'}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)

    def test_receive_message_user_without_bound_session_gets_403(self):
        """User API key without bound session gets 403 on message send."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key_unbound
        self.mock_api_key_storage.is_session_bound.return_value = False

        response = self.client.post(
            '/api/v1/message',
            json={
                'message': 'Hello',
                'session_id': 'unbound-session'
            },
            headers={'X-API-Key': 'user-secret-key-unbound'}
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn('Access denied', data['detail'])

    def test_receive_message_rate_limit_exceeded_returns_429(self):
        """Rate limit exceeded returns 429 for user key."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_api_key_storage.is_session_bound.return_value = True
        self.mock_api_key_storage.count_rate_limit.return_value = 10  # At limit

        response = self.client.post(
            '/api/v1/message',
            json={
                'message': 'Hello',
                'session_id': 'bound-session'
            },
            headers={'X-API-Key': 'user-secret-key'}
        )
        self.assertEqual(response.status_code, 429)
        data = response.json()
        self.assertIn('Rate limit exceeded', data['detail'])

    def test_receive_message_admin_not_rate_limited(self):
        """Admin API key is not subject to rate limiting."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        self.mock_session_storage.get.return_value = None

        with patch('topsailai_server.agent_daemon.api.routes.message.check_and_process_messages'):
            response = self.client.post(
                '/api/v1/message',
                json={
                    'message': 'Hello from admin',
                    'session_id': 'any-session'
                },
                headers={'X-API-Key': 'admin-secret-key'}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)
            # Admin should not trigger rate limit check
            self.mock_api_key_storage.count_rate_limit.assert_not_called()

    def test_retrieve_messages_requires_auth(self):
        """GET /api/v1/message requires auth header."""
        response = self.client.get('/api/v1/message?session_id=test-session')
        self.assertEqual(response.status_code, 401)

    def test_retrieve_messages_user_without_bound_session_gets_403(self):
        """User API key without bound session gets 403 on retrieve messages."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key_unbound
        self.mock_api_key_storage.is_session_bound.return_value = False

        response = self.client.get(
            '/api/v1/message?session_id=unbound-session',
            headers={'X-API-Key': 'user-secret-key-unbound'}
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn('Access denied', data['detail'])

    # ------------------------------------------------------------------
    # Task Routes Auth Tests
    # ------------------------------------------------------------------

    def test_set_task_result_requires_auth(self):
        """POST /api/v1/task without auth returns 401."""
        response = self.client.post('/api/v1/task', json={
            'session_id': 'test-session',
            'processed_msg_id': 'msg-001',
            'task_id': 'task-001',
            'task_result': 'Done'
        })
        self.assertEqual(response.status_code, 401)

    def test_set_task_result_admin_can_set_for_any_session(self):
        """Admin API key can set task results for any session."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        mock_message = MagicMock()
        mock_message.task_id = 'task-001'
        self.mock_message_storage.update_task_info.return_value = mock_message

        with patch('topsailai_server.agent_daemon.api.routes.task.check_and_process_messages'):
            response = self.client.post(
                '/api/v1/task',
                json={
                    'session_id': 'any-session',
                    'processed_msg_id': 'msg-001',
                    'task_id': 'task-001',
                    'task_result': 'Done'
                },
                headers={'X-API-Key': 'admin-secret-key'}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)

    def test_set_task_result_user_with_bound_session_can_set(self):
        """User API key with bound session can set task results."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_api_key_storage.is_session_bound.return_value = True

        mock_message = MagicMock()
        mock_message.task_id = 'task-001'
        self.mock_message_storage.update_task_info.return_value = mock_message

        with patch('topsailai_server.agent_daemon.api.routes.task.check_and_process_messages'):
            response = self.client.post(
                '/api/v1/task',
                json={
                    'session_id': 'bound-session',
                    'processed_msg_id': 'msg-001',
                    'task_id': 'task-001',
                    'task_result': 'Done'
                },
                headers={'X-API-Key': 'user-secret-key'}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['code'], 0)

    def test_set_task_result_user_without_bound_session_gets_403(self):
        """User API key without bound session gets 403 on set task result."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key_unbound
        self.mock_api_key_storage.is_session_bound.return_value = False

        response = self.client.post(
            '/api/v1/task',
            json={
                'session_id': 'unbound-session',
                'processed_msg_id': 'msg-001',
                'task_id': 'task-001',
                'task_result': 'Done'
            },
            headers={'X-API-Key': 'user-secret-key-unbound'}
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn('Access denied', data['detail'])

    def test_retrieve_tasks_requires_auth(self):
        """GET /api/v1/task requires auth header."""
        response = self.client.get('/api/v1/task?session_id=test-session')
        self.assertEqual(response.status_code, 401)

    def test_retrieve_tasks_user_without_bound_session_gets_403(self):
        """User API key without bound session gets 403 on retrieve tasks."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key_unbound
        self.mock_api_key_storage.is_session_bound.return_value = False

        response = self.client.get(
            '/api/v1/task?session_id=unbound-session',
            headers={'X-API-Key': 'user-secret-key-unbound'}
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn('Access denied', data['detail'])

    # ------------------------------------------------------------------
    # List Sessions Auth Tests
    # ------------------------------------------------------------------

    def test_list_sessions_requires_auth(self):
        """GET /api/v1/session without auth returns 401."""
        response = self.client.get('/api/v1/session')
        self.assertEqual(response.status_code, 401)

    def test_list_sessions_admin_lists_all(self):
        """Admin API key can list all sessions."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_session_storage.list_sessions.return_value = []

        response = self.client.get(
            '/api/v1/session',
            headers={'X-API-Key': 'admin-secret-key'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        self.assertEqual(data['data'], [])

    def test_list_sessions_user_lists_only_bound(self):
        """User API key can only list bound sessions."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_api_key_storage.list_bound_sessions.return_value = ['session-1', 'session-2']

        mock_session1 = self._make_mock_session('session-1', 'Session 1')

        self.mock_session_storage.list_sessions.return_value = [mock_session1]

        response = self.client.get(
            '/api/v1/session',
            headers={'X-API-Key': 'user-secret-key'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        # Verify list_sessions was called with bound session IDs
        call_kwargs = self.mock_session_storage.list_sessions.call_args[1]
        self.assertEqual(call_kwargs['session_ids'], ['session-1', 'session-2'])

    def test_list_sessions_user_with_no_bound_sessions_returns_empty(self):
        """User API key with no bound sessions returns empty list."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_api_key_storage.list_bound_sessions.return_value = []

        response = self.client.get(
            '/api/v1/session',
            headers={'X-API-Key': 'user-secret-key'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        self.assertEqual(data['data'], [])

    # ------------------------------------------------------------------
    # Delete Sessions Auth Tests
    # ------------------------------------------------------------------

    def test_delete_sessions_requires_admin(self):
        """DELETE /api/v1/session requires admin role."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.delete(
            '/api/v1/session?session_ids=test-session',
            headers={'X-API-Key': 'user-secret-key'}
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn('Admin access required', data['detail'])

    def test_delete_sessions_admin_can_delete(self):
        """Admin API key can delete sessions."""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        response = self.client.delete(
            '/api/v1/session?session_ids=test-session',
            headers={'X-API-Key': 'admin-secret-key'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)


if __name__ == '__main__':
    unittest.main()
