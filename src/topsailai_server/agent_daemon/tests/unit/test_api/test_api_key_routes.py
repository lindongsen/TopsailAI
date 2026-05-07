"""
  Author: km2
  Email: lin_dongsen@126.com
  Created: 2026-05-04
  Purpose: Unit tests for API Key management routes
"""

import unittest
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Need to set env vars before importing routes
os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'

from topsailai_server.agent_daemon.api.routes import api_key
from topsailai_server.agent_daemon.api.middleware import auth as auth_module
from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData


class TestApiKeyRoutes(unittest.TestCase):
    """Test cases for API key management routes"""

    def setUp(self):
        """Set up test fixtures"""
        self.app = FastAPI()
        self.app.include_router(api_key.router)
        self.client = TestClient(self.app)

        # Create mock storage
        self.mock_api_key_storage = MagicMock()
        self.mock_storage = MagicMock()
        self.mock_storage.api_key = self.mock_api_key_storage

        # Set up auth module storage
        auth_module._api_key_storage = self.mock_api_key_storage

        # Set up api_key routes module storage
        api_key._api_key_storage = self.mock_api_key_storage

        # Create test API key data
        self.admin_key = ApiKeyData(
            api_key_id="ak_admin_001",
            api_key="admin_secret_key_123",
            name="Admin Key",
            role="admin",
            rate_limit=0,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now()
        )

        self.user_key = ApiKeyData(
            api_key_id="ak_user_001",
            api_key="user_secret_key_123",
            name="User Key",
            role="user",
            rate_limit=10,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now()
        )

    def tearDown(self):
        """Clean up after tests"""
        auth_module._api_key_storage = None
        api_key._api_key_storage = None

    def _auth_header(self, key_value):
        """Helper to create auth header"""
        return {"X-API-Key": key_value}

    # Tests for CreateApiKey
    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_create_api_key_success(self, MockStorage):
        """Test admin can create API key"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.create_api_key.return_value = True

        response = self.client.post(
            "/api/v1/apikey",
            json={"name": "Test Key", "role": "user", "rate_limit": 10},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("api_key_id", data["data"])
        self.assertIn("api_key", data["data"])

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_create_api_key_with_sessions(self, MockStorage):
        """Test creating API key with session bindings"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.create_api_key.return_value = True
        self.mock_api_key_storage.bind_sessions.return_value = True

        response = self.client.post(
            "/api/v1/apikey",
            json={
                "name": "Test Key",
                "role": "user",
                "rate_limit": 10,
                "session_ids": ["session_1", "session_2"]
            },
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_create_api_key_non_admin_rejected(self, MockStorage):
        """Test non-admin cannot create API key"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.post(
            "/api/v1/apikey",
            json={"name": "Test Key", "role": "user"},
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_create_api_key_invalid_role(self, MockStorage):
        """Test creating API key with invalid role returns error"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        response = self.client.post(
            "/api/v1/apikey",
            json={"name": "Test Key", "role": "invalid"},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_create_api_key_missing_name(self, MockStorage):
        """Test creating API key without name returns validation error"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        response = self.client.post(
            "/api/v1/apikey",
            json={"role": "user"},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 422)

    # Tests for ListApiKeys
    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_list_api_keys_success(self, MockStorage):
        """Test admin can list all API keys"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.list_api_keys.return_value = [
            self.admin_key, self.user_key
        ]

        response = self.client.get(
            "/api/v1/apikey",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(len(data["data"]["api_keys"]), 2)
        self.assertEqual(data["data"]["total"], 2)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_list_api_keys_pagination(self, MockStorage):
        """Test listing API keys with pagination"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.list_api_keys.return_value = [
            self.admin_key, self.user_key
        ]

        response = self.client.get(
            "/api/v1/apikey?offset=1&limit=1",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(len(data["data"]["api_keys"]), 1)
        self.assertEqual(data["data"]["total"], 2)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_list_api_keys_non_admin_rejected(self, MockStorage):
        """Test non-admin cannot list API keys"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.get(
            "/api/v1/apikey",
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    # Tests for DeleteApiKey
    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_delete_api_key_success(self, MockStorage):
        """Test admin can delete API key"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.user_key
        self.mock_api_key_storage.delete_api_key.return_value = True

        response = self.client.delete(
            "/api/v1/apikey/ak_user_001",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_delete_api_key_non_admin_rejected(self, MockStorage):
        """Test non-admin cannot delete API key"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.delete(
            "/api/v1/apikey/ak_admin_001",
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_delete_nonexistent_api_key(self, MockStorage):
        """Test deleting non-existent API key returns error"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = None

        response = self.client.delete(
            "/api/v1/apikey/nonexistent",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_delete_last_admin_key_rejected(self, MockStorage):
        """Test deleting last admin key is rejected"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.admin_key
        self.mock_api_key_storage.list_api_keys.return_value = [self.admin_key]

        response = self.client.delete(
            "/api/v1/apikey/ak_admin_001",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    # Tests for BindSessions
    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_bind_sessions_success(self, MockStorage):
        """Test admin can bind sessions to API key"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.user_key
        self.mock_api_key_storage.bind_sessions.return_value = True

        response = self.client.post(
            "/api/v1/apikey/ak_user_001/sessions",
            json={"session_ids": ["session_1", "session_2"]},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_bind_sessions_non_admin_rejected(self, MockStorage):
        """Test non-admin cannot bind sessions"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.post(
            "/api/v1/apikey/ak_user_001/sessions",
            json={"session_ids": ["session_1"]},
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_bind_sessions_nonexistent_key(self, MockStorage):
        """Test binding sessions to non-existent API key returns 404"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = None

        response = self.client.post(
            "/api/v1/apikey/nonexistent/sessions",
            json={"session_ids": ["session_1"]},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_bind_sessions_to_admin_key_rejected(self, MockStorage):
        """Test binding sessions to admin API key is rejected"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.admin_key

        response = self.client.post(
            "/api/v1/apikey/ak_admin_001/sessions",
            json={"session_ids": ["session_1"]},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    # Tests for UnbindSessions
    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_unbind_sessions_success(self, MockStorage):
        """Test admin can unbind sessions from API key"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.user_key
        self.mock_api_key_storage.unbind_sessions.return_value = True

        response = self.client.request(
            "DELETE",
            "/api/v1/apikey/ak_user_001/sessions",
            json={"session_ids": ["session_1"]},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_unbind_sessions_non_admin_rejected(self, MockStorage):
        """Test non-admin cannot unbind sessions"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.request(
            "DELETE",
            "/api/v1/apikey/ak_user_001/sessions",
            json={"session_ids": ["session_1"]},
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    @patch('topsailai_server.agent_daemon.api.routes.api_key.Storage')
    def test_unbind_sessions_nonexistent_key(self, MockStorage):
        """Test unbinding sessions from non-existent API key returns 404"""
        MockStorage.return_value = self.mock_storage
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = None

        response = self.client.request(
            "DELETE",
            "/api/v1/apikey/nonexistent/sessions",
            json={"session_ids": ["session_1"]},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    # Tests for missing auth header
    def test_create_api_key_missing_auth(self):
        """Test creating API key without auth header"""
        response = self.client.post(
            "/api/v1/apikey",
            json={"name": "Test Key", "role": "user"}
        )

        self.assertEqual(response.status_code, 401)

    def test_list_api_keys_missing_auth(self):
        """Test listing API keys without auth header"""
        response = self.client.get("/api/v1/apikey")

        self.assertEqual(response.status_code, 401)

    def test_delete_api_key_missing_auth(self):
        """Test deleting API key without auth header"""
        response = self.client.delete("/api/v1/apikey/ak_user_001")

        self.assertEqual(response.status_code, 401)

    def test_bind_sessions_missing_auth(self):
        """Test binding sessions without auth header"""
        response = self.client.post(
            "/api/v1/apikey/ak_user_001/sessions",
            json={"session_ids": ["session_1"]}
        )

        self.assertEqual(response.status_code, 401)

    def test_unbind_sessions_missing_auth(self):
        """Test unbinding sessions without auth header"""
        response = self.client.request(
            "DELETE",
            "/api/v1/apikey/ak_user_001/sessions",
            json={"session_ids": ["session_1"]}
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
