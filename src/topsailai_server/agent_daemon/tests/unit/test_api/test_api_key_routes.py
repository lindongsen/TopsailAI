"""
  Author: km2
  Email: lin_dongsen@126.com
  Created: 2026-05-04
  Purpose: Unit tests for API Key management routes
"""

import unittest
import os
from datetime import datetime
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Need to set env vars before importing routes
from topsailai_server.agent_daemon.storage.api_key_environ_manager.base import ApiKeyEnvironData
os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_API_KEY_ENABLED'] = 'true'

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
    def test_create_api_key_success(self):
        """Test admin can create API key"""
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

    def test_create_api_key_with_sessions(self):
        """Test creating API key with session bindings"""
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

    def test_create_api_key_non_admin_rejected(self):
        """Test non-admin cannot create API key"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.post(
            "/api/v1/apikey",
            json={"name": "Test Key", "role": "user"},
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    def test_create_api_key_invalid_role(self):
        """Test creating API key with invalid role returns error"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        response = self.client.post(
            "/api/v1/apikey",
            json={"name": "Test Key", "role": "invalid"},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    def test_create_api_key_missing_name(self):
        """Test creating API key without name returns validation error"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key

        response = self.client.post(
            "/api/v1/apikey",
            json={"role": "user"},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 422)

    # Tests for ListApiKeys
    def test_list_api_keys_success(self):
        """Test admin can list all API keys"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.list_api_keys_with_details.return_value = [
            {"api_key": self.admin_key, "session_ids": [], "environs": []},
            {"api_key": self.user_key, "session_ids": ["session_1"], "environs": []}
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
        # Verify sessions and environs are included in response
        self.assertIn("sessions", data["data"]["api_keys"][0])
        self.assertIn("environs", data["data"]["api_keys"][0])

    def test_list_api_keys_pagination(self):
        """Test listing API keys with pagination"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.list_api_keys_with_details.return_value = [
            {"api_key": self.user_key, "session_ids": ["session_1"], "environs": []}
        ]

        response = self.client.get(
            "/api/v1/apikey?offset=1&limit=1",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(len(data["data"]["api_keys"]), 1)
        self.assertEqual(data["data"]["total"], 1)

    def test_list_api_keys_non_admin_rejected(self):
        """Test non-admin cannot list API keys"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.get(
            "/api/v1/apikey",
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    # Tests for DeleteApiKey
    def test_delete_api_key_success(self):
        """Test admin can delete API key"""
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

    def test_delete_api_key_non_admin_rejected(self):
        """Test non-admin cannot delete API key"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.delete(
            "/api/v1/apikey/ak_admin_001",
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    def test_delete_nonexistent_api_key(self):
        """Test deleting non-existent API key returns error"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = None

        response = self.client.delete(
            "/api/v1/apikey/nonexistent",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    def test_delete_last_admin_key_rejected(self):
        """Test deleting last admin key is rejected"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.admin_key
        self.mock_api_key_storage.count_admin_api_keys.return_value = 1

        response = self.client.delete(
            "/api/v1/apikey/ak_admin_001",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    # Tests for BindSessions
    def test_bind_sessions_success(self):
        """Test admin can bind sessions to API key"""
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

    def test_bind_sessions_non_admin_rejected(self):
        """Test non-admin cannot bind sessions"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.post(
            "/api/v1/apikey/ak_user_001/sessions",
            json={"session_ids": ["session_1"]},
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    def test_bind_sessions_nonexistent_key(self):
        """Test binding sessions to non-existent API key returns 404"""
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

    def test_bind_sessions_to_admin_key_rejected(self):
        """Test binding sessions to admin API key is rejected"""
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
    def test_unbind_sessions_success(self):
        """Test admin can unbind sessions from API key"""
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

    def test_unbind_sessions_non_admin_rejected(self):
        """Test non-admin cannot unbind sessions"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.request(
            "DELETE",
            "/api/v1/apikey/ak_user_001/sessions",
            json={"session_ids": ["session_1"]},
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    def test_unbind_sessions_nonexistent_key(self):
        """Test unbinding sessions from non-existent API key returns 404"""
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

    # Tests for SetEnviron
    def test_set_api_key_environ_success(self):
        """Test admin can set environment variable for API key"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.admin_key
        environ_data = ApiKeyEnvironData(
            api_key_id="ak_admin_001",
            key="TEST_VAR",
            value="test_value",
            create_time=datetime.now(),
            update_time=datetime.now()
        )
        self.mock_api_key_storage.create_api_key_environ.return_value = environ_data

        response = self.client.post(
            "/api/v1/apikey/ak_admin_001/environs",
            json={"key": "TEST_VAR", "value": "test_value"},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["key"], "TEST_VAR")
        self.assertEqual(data["data"]["value"], "test_value")
        self.mock_api_key_storage.create_api_key_environ.assert_called_once_with(
            api_key_id="ak_admin_001",
            key="TEST_VAR",
            value="test_value"
        )

    def test_set_api_key_environ_non_admin(self):
        """Test non-admin cannot set environment variable"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.post(
            "/api/v1/apikey/ak_user_001/environs",
            json={"key": "TEST_VAR", "value": "test_value"},
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    def test_set_api_key_environ_key_not_found(self):
        """Test setting environ for non-existent API key returns error"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = None

        response = self.client.post(
            "/api/v1/apikey/nonexistent/environs",
            json={"key": "TEST_VAR", "value": "test_value"},
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    # Tests for ListEnvirons
    def test_list_api_key_environs_success(self):
        """Test admin can list environment variables for API key"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.admin_key
        now = datetime.now()
        environs = [
            ApiKeyEnvironData(
                api_key_id="ak_admin_001",
                key="VAR_1",
                value="value_1",
                create_time=now,
                update_time=now
            ),
            ApiKeyEnvironData(
                api_key_id="ak_admin_001",
                key="VAR_2",
                value="value_2",
                create_time=now,
                update_time=now
            )
        ]
        self.mock_api_key_storage.get_api_key_environs_by_api_key_id.return_value = environs

        response = self.client.get(
            "/api/v1/apikey/ak_admin_001/environs",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(len(data["data"]["environs"]), 2)
        self.assertEqual(data["data"]["total"], 2)

    def test_list_api_key_environs_empty(self):
        """Test listing environs returns empty list when none exist"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_environs_by_api_key_id.return_value = []

        response = self.client.get(
            "/api/v1/apikey/ak_admin_001/environs",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["environs"], [])
        self.assertEqual(data["data"]["total"], 0)

    # Tests for DeleteEnviron
    def test_delete_api_key_environ_success(self):
        """Test admin can delete environment variable"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.admin_key
        self.mock_api_key_storage.delete_api_key_environ.return_value = True

        response = self.client.delete(
            "/api/v1/apikey/ak_admin_001/environs/TEST_VAR",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.mock_api_key_storage.delete_api_key_environ.assert_called_once_with(
            "ak_admin_001", "TEST_VAR"
        )

    def test_delete_api_key_environ_not_found(self):
        """Test deleting non-existent environ returns error"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.admin_key
        self.mock_api_key_storage.get_api_key_by_id.return_value = self.admin_key
        self.mock_api_key_storage.delete_api_key_environ.return_value = False

        response = self.client.delete(
            "/api/v1/apikey/ak_admin_001/environs/NONEXISTENT",
            headers=self._auth_header("admin_secret_key_123")
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["code"], 0)

    def test_delete_api_key_environ_non_admin(self):
        """Test non-admin cannot delete environment variable"""
        self.mock_api_key_storage.get_api_key_by_value.return_value = self.user_key

        response = self.client.delete(
            "/api/v1/apikey/ak_user_001/environs/TEST_VAR",
            headers=self._auth_header("user_secret_key_123")
        )

        self.assertEqual(response.status_code, 403)

    # Tests for missing auth header on environ endpoints
    def test_set_api_key_environ_missing_auth(self):
        """Test setting environ without auth header"""
        response = self.client.post(
            "/api/v1/apikey/ak_admin_001/environs",
            json={"key": "TEST_VAR", "value": "test_value"}
        )

        self.assertEqual(response.status_code, 401)

    def test_list_api_key_environs_missing_auth(self):
        """Test listing environs without auth header"""
        response = self.client.get("/api/v1/apikey/ak_admin_001/environs")

        self.assertEqual(response.status_code, 401)

    def test_delete_api_key_environ_missing_auth(self):
        """Test deleting environ without auth header"""
        response = self.client.delete("/api/v1/apikey/ak_admin_001/environs/TEST_VAR")

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
