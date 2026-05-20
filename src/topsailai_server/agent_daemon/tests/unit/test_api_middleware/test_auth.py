"""
Unit tests for api/middleware/auth.py.

This module tests the authentication and authorization middleware including:
    - API key validation via X-API-Key header
    - Admin role verification
    - Session permission checking
    - Rate limiting (QoS) enforcement

Test Coverage:
    - get_current_api_key dependency
    - require_admin dependency
    - check_session_permission dependency
    - check_rate_limit dependency
    - verify_session_permission helper
    - verify_rate_limit helper
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient


# Create a test FastAPI app with routes using auth dependencies
def _create_test_app(mock_storage):
    """Create a test FastAPI app with auth-protected routes."""
    from topsailai_server.agent_daemon.api.middleware import auth as auth_module
    from topsailai_server.agent_daemon.api.middleware.auth import (
        get_current_api_key,
        require_admin,
        check_session_permission,
        check_rate_limit,
    )

    # Set the storage dependency directly using the correct variable name
    auth_module._api_key_storage = mock_storage

    # Mock get_config to return api_key_enabled=True for tests
    mock_cfg = MagicMock()
    mock_cfg.api_key_enabled = True
    auth_module.get_config = lambda: mock_cfg

    app = FastAPI()

    @app.get("/test-auth")
    def test_auth(current_key=Depends(get_current_api_key)):
        return {"api_key_id": current_key.api_key_id, "role": current_key.role}

    @app.get("/test-admin")
    def test_admin(admin_key=Depends(require_admin)):
        return {"api_key_id": admin_key.api_key_id}

    @app.get("/test-permission")
    def test_permission(
        session_id: str = None,
        _=Depends(check_session_permission),
    ):
        return {"session_id": session_id}

    @app.post("/test-rate-limit")
    def test_rate_limit(
        session_id: str = None,
        _=Depends(check_rate_limit),
    ):
        return {"session_id": session_id}

    return app


class TestGetCurrentApiKey:
    """Tests for get_current_api_key dependency."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked storage."""
        self.mock_storage = MagicMock()
        self.admin_key = MagicMock()
        self.admin_key.api_key_id = "admin-001"
        self.admin_key.api_key = "admin-secret-key"
        self.admin_key.name = "Admin Key"
        self.admin_key.role = "admin"
        self.admin_key.rate_limit = 0
        self.admin_key.is_active = True

        app = _create_test_app(self.mock_storage)
        yield TestClient(app)

    def test_get_current_api_key_success(self, client):
        """Test valid API key returns key data."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.get("/test-auth", headers={"X-API-Key": "admin-secret-key"})

        assert response.status_code == 200
        data = response.json()
        assert data["api_key_id"] == "admin-001"
        assert data["role"] == "admin"

    def test_get_current_api_key_missing_header(self, client):
        """Test missing X-API-Key header returns 401."""
        response = client.get("/test-auth")

        assert response.status_code == 401
        assert "Missing API key" in response.json()["detail"]

    def test_get_current_api_key_empty_header(self, client):
        """Test empty X-API-Key header returns 401."""
        response = client.get("/test-auth", headers={"X-API-Key": ""})

        assert response.status_code == 401
        assert "Missing API key" in response.json()["detail"]

    def test_get_current_api_key_invalid_key(self, client):
        """Test invalid API key returns 401."""
        self.mock_storage.get_api_key_by_value.return_value = None

        response = client.get("/test-auth", headers={"X-API-Key": "invalid-key"})

        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]

    def test_get_current_api_key_inactive_key(self, client):
        """Test inactive API key returns 401.

        The storage layer filters inactive keys, so get_api_key_by_value
        returns None for inactive keys.
        """
        self.mock_storage.get_api_key_by_value.return_value = None

        response = client.get("/test-auth", headers={"X-API-Key": "inactive-key"})

        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]
    def test_get_current_api_key_storage_not_initialized(self, client):
        """Test storage not initialized returns 500."""
        from topsailai_server.agent_daemon.api.middleware import auth as auth_module
        auth_module._api_key_storage = None

        response = client.get("/test-auth", headers={"X-API-Key": "admin-secret-key"})

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]


class TestRequireAdmin:
    """Tests for require_admin dependency."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked storage."""
        self.mock_storage = MagicMock()
        self.admin_key = MagicMock()
        self.admin_key.api_key_id = "admin-001"
        self.admin_key.role = "admin"
        self.admin_key.is_active = True

        self.user_key = MagicMock()
        self.user_key.api_key_id = "user-001"
        self.user_key.role = "user"
        self.user_key.is_active = True

        app = _create_test_app(self.mock_storage)
        yield TestClient(app)

    def test_require_admin_success(self, client):
        """Test admin key passes admin check."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.get("/test-admin", headers={"X-API-Key": "admin-secret-key"})

        assert response.status_code == 200
        assert response.json()["api_key_id"] == "admin-001"

    def test_require_admin_non_admin_rejected(self, client):
        """Test non-admin key is rejected with 403."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key

        response = client.get("/test-admin", headers={"X-API-Key": "user-secret-key"})

        assert response.status_code == 403
        assert "Admin access required" in response.json()["detail"]


class TestCheckSessionPermission:
    """Tests for check_session_permission dependency."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked storage."""
        self.mock_storage = MagicMock()
        self.admin_key = MagicMock()
        self.admin_key.api_key_id = "admin-001"
        self.admin_key.role = "admin"
        self.admin_key.is_active = True

        self.user_key = MagicMock()
        self.user_key.api_key_id = "user-001"
        self.user_key.role = "user"
        self.user_key.is_active = True

        app = _create_test_app(self.mock_storage)
        yield TestClient(app)

    def test_admin_has_access_to_all_sessions(self, client):
        """Test admin can access any session without binding."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.get(
            "/test-permission",
            headers={"X-API-Key": "admin-secret-key"},
            params={"session_id": "any-session"},
        )

        assert response.status_code == 200

    def test_user_with_bound_session_has_access(self, client):
        """Test user can access bound session."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.is_session_bound.return_value = True

        response = client.get(
            "/test-permission",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": "bound-session"},
        )

        assert response.status_code == 200
        self.mock_storage.is_session_bound.assert_called_once_with("user-001", "bound-session")

    def test_user_without_bound_session_rejected(self, client):
        """Test user is rejected for unbound session."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.is_session_bound.return_value = False

        response = client.get(
            "/test-permission",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": "unbound-session"},
        )

        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    def test_no_session_id_skips_check(self, client):
        """Test permission check is skipped when no session_id provided."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key

        response = client.get(
            "/test-permission",
            headers={"X-API-Key": "user-secret-key"},
        )

        assert response.status_code == 200
        self.mock_storage.is_session_bound.assert_not_called()

    def test_session_id_from_query_params(self, client):
        """Test session_id is read from query parameters."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.is_session_bound.return_value = True

        response = client.get(
            "/test-permission",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": "query-session"},
        )

        assert response.status_code == 200
        self.mock_storage.is_session_bound.assert_called_once_with("user-001", "query-session")

    def test_storage_not_initialized_raises_500(self, client):
        """Test storage not initialized returns 500."""
        from topsailai_server.agent_daemon.api.middleware import auth as auth_module
        auth_module._api_key_storage = None

        response = client.get(
            "/test-permission",
            headers={"X-API-Key": "admin-secret-key"},
            params={"session_id": "any-session"},
        )

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]


class TestCheckRateLimit:
    """Tests for check_rate_limit dependency."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked storage."""
        self.mock_storage = MagicMock()
        self.admin_key = MagicMock()
        self.admin_key.api_key_id = "admin-001"
        self.admin_key.role = "admin"
        self.admin_key.rate_limit = 0
        self.admin_key.is_active = True

        self.user_key = MagicMock()
        self.user_key.api_key_id = "user-001"
        self.user_key.role = "user"
        self.user_key.rate_limit = 5
        self.user_key.is_active = True

        app = _create_test_app(self.mock_storage)
        yield TestClient(app)

    def test_within_limit_allowed(self, client):
        """Test request within rate limit is allowed."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.count_rate_limit.return_value = 3

        response = client.post(
            "/test-rate-limit",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": "session-001"},
        )

        assert response.status_code == 200
        self.mock_storage.log_rate_limit.assert_called_once()

    def test_exceeding_rate_limit_rejected(self, client):
        """Test request exceeding rate limit returns 429."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.count_rate_limit.return_value = 5

        response = client.post(
            "/test-rate-limit",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": "session-001"},
        )

        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["detail"]
        self.mock_storage.log_rate_limit.assert_not_called()

    def test_rate_limit_just_under_boundary(self, client):
        """Test request at limit-1 is allowed."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.count_rate_limit.return_value = 4

        response = client.post(
            "/test-rate-limit",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": "session-001"},
        )

        assert response.status_code == 200

    def test_rate_limit_boundary(self, client):
        """Test request at exact limit is rejected."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.count_rate_limit.return_value = 5

        response = client.post(
            "/test-rate-limit",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": "session-001"},
        )

        assert response.status_code == 429

    def test_admin_unlimited_rate(self, client):
        """Test admin key has unlimited rate."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.post(
            "/test-rate-limit",
            headers={"X-API-Key": "admin-secret-key"},
            params={"session_id": "session-001"},
        )

        assert response.status_code == 200
        self.mock_storage.count_rate_limit.assert_not_called()
        self.mock_storage.log_rate_limit.assert_not_called()

    def test_no_session_id_skips_rate_limit(self, client):
        """Test rate limit check is skipped when no session_id provided."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key

        response = client.post(
            "/test-rate-limit",
            headers={"X-API-Key": "user-secret-key"},
        )

        assert response.status_code == 200
        self.mock_storage.count_rate_limit.assert_not_called()
        self.mock_storage.log_rate_limit.assert_not_called()


class TestVerifySessionPermission:
    """Tests for verify_session_permission helper function."""

    def test_verify_admin_has_access(self):
        """Test admin can access any session via helper."""
        from topsailai_server.agent_daemon.api.middleware.auth import verify_session_permission
        from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData

        admin_key = ApiKeyData(
            api_key_id="admin-001",
            api_key="admin-key",
            name="Admin",
            role="admin",
            rate_limit=0,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )

        # Should not raise for admin
        verify_session_permission(admin_key, "any-session")

    def test_verify_user_with_bound_session(self):
        """Test user can access bound session via helper."""
        from topsailai_server.agent_daemon.api.middleware.auth import verify_session_permission
        from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData

        user_key = ApiKeyData(
            api_key_id="user-001",
            api_key="user-key",
            name="User",
            role="user",
            rate_limit=5,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )

        mock_storage = MagicMock()
        mock_storage.is_session_bound.return_value = True

        from topsailai_server.agent_daemon.api.middleware import auth as auth_module
        auth_module._api_key_storage = mock_storage

        verify_session_permission(user_key, "bound-session")

        mock_storage.is_session_bound.assert_called_once_with("user-001", "bound-session")

    def test_verify_user_without_bound_session(self):
        """Test user is rejected for unbound session via helper."""
        from topsailai_server.agent_daemon.api.middleware.auth import verify_session_permission
        from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData
        from fastapi import HTTPException

        user_key = ApiKeyData(
            api_key_id="user-001",
            api_key="user-key",
            name="User",
            role="user",
            rate_limit=5,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )

        mock_storage = MagicMock()
        mock_storage.is_session_bound.return_value = False

        from topsailai_server.agent_daemon.api.middleware import auth as auth_module
        auth_module._api_key_storage = mock_storage

        with pytest.raises(HTTPException) as exc_info:
            verify_session_permission(user_key, "unbound-session")

        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.detail

    def test_verify_storage_not_initialized(self):
        """Test storage not initialized raises 500 via helper."""
        from topsailai_server.agent_daemon.api.middleware.auth import verify_session_permission
        from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData
        from fastapi import HTTPException

        user_key = ApiKeyData(
            api_key_id="user-001",
            api_key="user-key",
            name="User",
            role="user",
            rate_limit=5,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )

        from topsailai_server.agent_daemon.api.middleware import auth as auth_module
        auth_module._api_key_storage = None

        with pytest.raises(HTTPException) as exc_info:
            verify_session_permission(user_key, "any-session")

        assert exc_info.value.status_code == 500
        assert "Internal server error" in exc_info.value.detail


class TestVerifyRateLimit:
    """Tests for verify_rate_limit helper function."""

    def test_verify_rate_limit_within_limit(self):
        """Test request within rate limit via helper is allowed."""
        from topsailai_server.agent_daemon.api.middleware.auth import verify_rate_limit
        from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData

        user_key = ApiKeyData(
            api_key_id="user-001",
            api_key="user-key",
            name="User",
            role="user",
            rate_limit=5,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )

        mock_storage = MagicMock()
        mock_storage.count_rate_limit.return_value = 2

        from topsailai_server.agent_daemon.api.middleware import auth as auth_module
        auth_module._api_key_storage = mock_storage

        verify_rate_limit(user_key, "session-001")

        mock_storage.log_rate_limit.assert_called_once()

    def test_verify_rate_limit_exceeded(self):
        """Test request exceeding rate limit via helper returns 429."""
        from topsailai_server.agent_daemon.api.middleware.auth import verify_rate_limit
        from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData
        from fastapi import HTTPException

        user_key = ApiKeyData(
            api_key_id="user-001",
            api_key="user-key",
            name="User",
            role="user",
            rate_limit=5,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )

        mock_storage = MagicMock()
        mock_storage.count_rate_limit.return_value = 5

        from topsailai_server.agent_daemon.api.middleware import auth as auth_module
        auth_module._api_key_storage = mock_storage

        with pytest.raises(HTTPException) as exc_info:
            verify_rate_limit(user_key, "session-001")

        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in exc_info.value.detail
        mock_storage.log_rate_limit.assert_not_called()

    def test_verify_rate_limit_admin_unlimited(self):
        """Test admin has unlimited rate via helper."""
        from topsailai_server.agent_daemon.api.middleware.auth import verify_rate_limit
        from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData

        admin_key = ApiKeyData(
            api_key_id="admin-001",
            api_key="admin-key",
            name="Admin",
            role="admin",
            rate_limit=0,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )

        mock_storage = MagicMock()

        from topsailai_server.agent_daemon.api.middleware import auth as auth_module
        auth_module._api_key_storage = mock_storage

        verify_rate_limit(admin_key, "session-001")

        mock_storage.count_rate_limit.assert_not_called()
        mock_storage.log_rate_limit.assert_not_called()

    def test_verify_rate_limit_zero_means_unlimited(self):
        """Test rate limit of 0 means unlimited for user."""
        from topsailai_server.agent_daemon.api.middleware.auth import verify_rate_limit
        from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData

        user_key = ApiKeyData(
            api_key_id="user-001",
            api_key="user-key",
            name="User",
            role="user",
            rate_limit=0,
            is_active=True,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )

        mock_storage = MagicMock()

        from topsailai_server.agent_daemon.api.middleware import auth as auth_module
        auth_module._api_key_storage = mock_storage

        verify_rate_limit(user_key, "session-001")

        mock_storage.count_rate_limit.assert_not_called()
        mock_storage.log_rate_limit.assert_not_called()


class TestAuthEdgeCases:
    """Tests for edge cases in auth middleware."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked storage."""
        self.mock_storage = MagicMock()
        self.user_key = MagicMock()
        self.user_key.api_key_id = "user-001"
        self.user_key.role = "user"
        self.user_key.rate_limit = 5
        self.user_key.is_active = True

        app = _create_test_app(self.mock_storage)
        yield TestClient(app)

    def test_rate_limit_with_zero_limit(self, client):
        """Test rate limit of 0 means unlimited for user."""
        self.user_key.rate_limit = 0
        self.mock_storage.get_api_key_by_value.return_value = self.user_key

        response = client.post(
            "/test-rate-limit",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": "session-001"},
        )

        assert response.status_code == 200
        self.mock_storage.count_rate_limit.assert_not_called()

    def test_rate_limit_with_very_high_count(self, client):
        """Test rate limit with very high request count."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.count_rate_limit.return_value = 999999

        response = client.post(
            "/test-rate-limit",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": "session-001"},
        )

        assert response.status_code == 429

    def test_permission_check_with_empty_session_id(self, client):
        """Test permission check with empty session_id string."""
        self.mock_storage.get_api_key_by_value.return_value = self.user_key

        response = client.get(
            "/test-permission",
            headers={"X-API-Key": "user-secret-key"},
            params={"session_id": ""},
        )

        # Empty string is falsy, so check is skipped
        assert response.status_code == 200
        self.mock_storage.is_session_bound.assert_not_called()


class TestBearerTokenAuth:
    """Tests for Bearer Token authentication via Authorization header."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked storage."""
        self.mock_storage = MagicMock()
        self.admin_key = MagicMock()
        self.admin_key.api_key_id = "admin-001"
        self.admin_key.api_key = "admin-secret-key"
        self.admin_key.name = "Admin Key"
        self.admin_key.role = "admin"
        self.admin_key.rate_limit = 0
        self.admin_key.is_active = True

        app = _create_test_app(self.mock_storage)
        yield TestClient(app)

    def test_bearer_token_success(self, client):
        """Test valid Bearer token returns key data."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.get(
            "/test-auth",
            headers={"Authorization": "Bearer admin-secret-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["api_key_id"] == "admin-001"
        assert data["role"] == "admin"

    def test_bearer_token_lowercase_bearer(self, client):
        """Test lowercase 'bearer' scheme is accepted."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.get(
            "/test-auth",
            headers={"Authorization": "bearer admin-secret-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["api_key_id"] == "admin-001"

    def test_bearer_token_uppercase_bearer(self, client):
        """Test uppercase 'BEARER' scheme is accepted."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.get(
            "/test-auth",
            headers={"Authorization": "BEARER admin-secret-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["api_key_id"] == "admin-001"

    def test_bearer_token_missing_auth_header(self, client):
        """Test missing Authorization header returns 401."""
        response = client.get("/test-auth")

        assert response.status_code == 401
        assert "Missing API key" in response.json()["detail"]

    def test_bearer_token_empty_bearer_token(self, client):
        """Test empty Bearer token returns 401."""
        response = client.get(
            "/test-auth",
            headers={"Authorization": "Bearer "},
        )

        assert response.status_code == 401
        assert "Missing API key" in response.json()["detail"]

    def test_bearer_token_wrong_scheme(self, client):
        """Test wrong Authorization scheme (Basic) returns 401."""
        response = client.get(
            "/test-auth",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )

        assert response.status_code == 401
        assert "Missing API key" in response.json()["detail"]

    def test_bearer_token_invalid_key(self, client):
        """Test invalid Bearer token returns 401."""
        self.mock_storage.get_api_key_by_value.return_value = None

        response = client.get(
            "/test-auth",
            headers={"Authorization": "Bearer invalid-key"},
        )

        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]

    def test_x_api_key_takes_precedence_over_bearer(self, client):
        """Test X-API-Key header takes precedence over Authorization: Bearer."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.get(
            "/test-auth",
            headers={
                "X-API-Key": "admin-secret-key",
                "Authorization": "Bearer some-other-token",
            },
        )

        assert response.status_code == 200
        # Verify the X-API-Key value was used (get_api_key_by_value called with it)
        self.mock_storage.get_api_key_by_value.assert_called_once_with("admin-secret-key")

    def test_x_api_key_invalid_bearer_valid_uses_x_api_key(self, client):
        """Test invalid X-API-Key takes precedence even if Bearer is valid."""
        self.mock_storage.get_api_key_by_value.return_value = None

        response = client.get(
            "/test-auth",
            headers={
                "X-API-Key": "invalid-key",
                "Authorization": "Bearer admin-secret-key",
            },
        )

        assert response.status_code == 401
        # Verify the X-API-Key value was checked first
        self.mock_storage.get_api_key_by_value.assert_called_once_with("invalid-key")

    def test_bearer_token_with_extra_whitespace(self, client):
        """Test Bearer token with extra whitespace is parsed correctly."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.get(
            "/test-auth",
            headers={"Authorization": "Bearer   admin-secret-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["api_key_id"] == "admin-001"

    def test_bearer_token_with_rate_limit(self, client):
        """Test Bearer token works with rate limiting."""
        self.user_key = MagicMock()
        self.user_key.api_key_id = "user-001"
        self.user_key.role = "user"
        self.user_key.rate_limit = 5
        self.user_key.is_active = True
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.count_rate_limit.return_value = 3

        response = client.post(
            "/test-rate-limit",
            headers={"Authorization": "Bearer user-secret-key"},
            params={"session_id": "session-001"},
        )

        assert response.status_code == 200
        self.mock_storage.log_rate_limit.assert_called_once()

    def test_bearer_token_with_session_permission(self, client):
        """Test Bearer token works with session permission checks."""
        self.user_key = MagicMock()
        self.user_key.api_key_id = "user-001"
        self.user_key.role = "user"
        self.user_key.rate_limit = 5
        self.user_key.is_active = True
        self.mock_storage.get_api_key_by_value.return_value = self.user_key
        self.mock_storage.is_session_bound.return_value = True

        response = client.get(
            "/test-permission",
            headers={"Authorization": "Bearer user-secret-key"},
            params={"session_id": "bound-session"},
        )

        assert response.status_code == 200
        self.mock_storage.is_session_bound.assert_called_once_with("user-001", "bound-session")

    def test_bearer_token_with_admin_check(self, client):
        """Test Bearer token works with admin role check."""
        self.mock_storage.get_api_key_by_value.return_value = self.admin_key

        response = client.get(
            "/test-admin",
            headers={"Authorization": "Bearer admin-secret-key"},
        )

        assert response.status_code == 200
        assert response.json()["api_key_id"] == "admin-001"
