"""
Environment-variable driven behavior tests that do not require a server restart.

Full validation of environment variables such as ACS_HTTP_PORT,
ACS_NATS_PENDING_MESSAGE_NO_ACK, or ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT
requires starting the server with specific values. Those cases remain
manual-only and are documented in the conversion report.
"""

import pytest

from .conftest import get_response_data


class TestApiKeyMaxPerAccount:
    """Verify ACS_API_KEY_MAX_PER_ACCOUNT enforcement."""

    def test_create_api_keys_up_to_limit(
        self,
        admin_client,
        server_url: str,
        test_account: dict,
    ):
        """CLI-ENV-002: account cannot exceed max API keys."""
        # The default limit is 10. Create keys until the limit is reached.
        max_keys = 10
        created = 0

        for i in range(max_keys):
            response = admin_client.post(
                f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
                json={"api_key_name": f"limit-key-{i}", "role": "user"},
            )
            if response.status_code == 409:
                # Limit already configured lower than default.
                break
            assert response.status_code == 201, response.text
            created += 1

        # The next creation should fail.
        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
            json={"api_key_name": "over-limit-key", "role": "user"},
        )
        assert response.status_code == 409
        payload = response.json()
        assert "error" in payload
        assert "limit" in payload.get("error", "").lower() or "max" in payload.get("error", "").lower()


class TestHttpServerReachability:
    """Verify the HTTP server is reachable on the configured base URL."""

    def test_healthz_returns_alive(self, unauthenticated_client, server_url: str):
        """CLI-ENV-001: server responds on configured host/port."""
        response = unauthenticated_client.get(f"{server_url}/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "alive"


class TestSessionExpirySeconds:
    """Verify login session expiry respects ACS_LOGIN_SESSION_EXPIRY_SECONDS."""

    def test_session_has_expires_at(self, admin_client, server_url: str, test_account: dict):
        """CLI-ENV-003: created session includes expires_at_ms."""
        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/session"
        )
        assert response.status_code == 200
        data = get_response_data(response)
        assert "session_key" in data
        assert "expires_at_ms" in data
        assert data["expires_at_ms"] > 0