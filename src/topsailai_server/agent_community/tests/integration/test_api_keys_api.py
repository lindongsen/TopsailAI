"""
Integration tests for ACS API key management endpoints.

These tests verify API key creation, listing, usage, deletion, and
constraint enforcement against a running ACS server.
"""

import pytest
import requests
from .conftest import get_response_data


class TestAPIKeyCRUD:
    """Test API key lifecycle operations."""

    def test_create_api_key_for_account(self, admin_client: requests.Session, server_url: str, test_account: dict):
        """Admin should be able to create an API key for another account."""
        key_data = {
            "api_key_name": "test-key",
            "role": "user",
        }

        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
            json=key_data,
        )
        assert response.status_code == 201
        data = get_response_data(response)
        assert data["api_key_name"] == key_data["api_key_name"]
        assert data["role"] == "user"
        assert data["owner_id"] == test_account["account_id"]
        assert "token" in data
        assert "api_key_id" in data
        assert data["token"].startswith(data["api_key_id"] + ".")

    def test_list_api_keys(self, admin_client: requests.Session, server_url: str, test_account: dict):
        """Admin should be able to list API keys for an account."""
        # Create a key first.
        key_data = {"api_key_name": "list-test-key", "role": "user"}
        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
            json=key_data,
        )
        assert response.status_code == 201

        response = admin_client.get(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys"
        )
        assert response.status_code == 200
        data = get_response_data(response)
        assert data["total"] >= 1
        assert any(key["api_key_name"] == key_data["api_key_name"] for key in data["items"])

    def test_use_api_key_to_access_protected_endpoint(
        self,
        admin_client: requests.Session,
        api_client: requests.Session,
        server_url: str,
        test_account_with_api_key: tuple[dict, str],
    ):
        """An API key token should authenticate requests to protected endpoints."""
        account, token = test_account_with_api_key

        headers = {"Authorization": f"Bearer {token}"}
        response = api_client.get(f"{server_url}/api/v1/accounts/me", headers=headers)
        assert response.status_code == 200
        data = get_response_data(response)
        assert data["account_id"] == account["account_id"]

    def test_deleted_api_key_cannot_authenticate(
        self,
        admin_client: requests.Session,
        api_client: requests.Session,
        server_url: str,
        test_account_with_api_key: tuple[dict, str],
    ):
        """After deleting an API key, it should no longer authenticate requests."""
        account, token = test_account_with_api_key

        # Resolve the api_key_id from the token.
        api_key_id = token.split(".")[0]

        # Delete the key.
        response = admin_client.delete(
            f"{server_url}/api/v1/accounts/{account['account_id']}/api-keys/{api_key_id}"
        )
        assert response.status_code == 200

        # The token should now be rejected.
        headers = {"Authorization": f"Bearer {token}"}
        response = api_client.get(f"{server_url}/api/v1/accounts/me", headers=headers)
        assert response.status_code == 401


class TestAPIKeyConstraints:
    """Test API key role and limit constraints."""

    def test_api_key_role_cannot_exceed_owner_role(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """An API key role must not exceed the owner account role."""
        key_data = {
            "api_key_name": "admin-role-attempt",
            "role": "admin",
        }

        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
            json=key_data,
        )
        assert response.status_code == 403
        data = get_response_data(response)
        assert "role" in data["error"].lower() or "api key role" in data["error"].lower()

    def test_user_can_create_own_api_key(
        self,
        admin_client: requests.Session,
        server_url: str,
        test_account: dict,
    ):
        """A user should be able to create an API key for themselves."""
        # Create a session for the test account.
        response = admin_client.post(f"{server_url}/api/v1/accounts/{test_account['account_id']}/session")
        assert response.status_code == 200
        session_key = get_response_data(response)["session_key"]
        # Use a fresh session so the X-Session-Key header is the only credential.
        session_client = requests.Session()
        session_client.headers.update({"Content-Type": "application/json"})
        headers = {"X-Session-Key": session_key}
        key_data = {"api_key_name": "user-own-key", "role": "user"}
        response = session_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
            headers=headers,
            json=key_data,
        )
        assert response.status_code == 201
        data = get_response_data(response)
        assert data["role"] == "user"
        assert "token" in data

    def test_user_cannot_create_api_key_for_other_account(
        self,
        admin_client: requests.Session,
        server_url: str,
        test_account: dict,
        unique_id: str,
    ):
        """A user should not be able to create an API key for another account."""
        # Create a second user account.
        other_account_data = {
            "account_name": f"Other User {unique_id}",
            "role": "user",
            "login_name": f"other_user_{unique_id}",
            "login_password": "OtherPass123!",
        }
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=other_account_data)
        assert response.status_code == 201
        other_account = get_response_data(response)

        # Create a session for the first test account.
        response = admin_client.post(f"{server_url}/api/v1/accounts/{test_account['account_id']}/session")
        # Create a session for the first test account.
        response = admin_client.post(f"{server_url}/api/v1/accounts/{test_account['account_id']}/session")
        assert response.status_code == 200
        session_key = get_response_data(response)["session_key"]
        # so the X-Session-Key header is the only credential.
        session_client = requests.Session()
        session_client.headers.update({"Content-Type": "application/json"})
        headers = {"X-Session-Key": session_key}
        key_data = {"api_key_name": "cross-account-key", "role": "user"}
        response = session_client.post(
            f"{server_url}/api/v1/accounts/{other_account['account_id']}/api-keys",
            headers=headers,
            json=key_data,
        )
        assert response.status_code == 403

        # Cleanup
        admin_client.delete(f"{server_url}/api/v1/accounts/{other_account['account_id']}")

    def test_per_owner_api_key_limit(
        self,
        admin_client: requests.Session,
        server_url: str,
        test_account: dict,
    ):
        """Creating more API keys than the per-owner limit should fail."""
        # Determine the configured limit. The default is 10 and the test account
        # may already have keys from other fixtures, so we attempt to create keys
        # until the limit is reached.
        limit_response = admin_client.get(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys"
        )
        assert limit_response.status_code == 200
        existing_count = get_response_data(limit_response)["total"]

        created_keys = []
        try:
            for i in range(existing_count, 20):
                key_data = {"api_key_name": f"limit-key-{i}", "role": "user"}
                response = admin_client.post(
                    f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
                    json=key_data,
                )
                if response.status_code == 201:
                    created_keys.append(get_response_data(response)["api_key_id"])
                elif response.status_code == 409:
                    # Limit reached.
                    break
                else:
                    pytest.fail(f"Unexpected status code {response.status_code}: {response.text}")
            else:
                pytest.fail("Expected API key limit to be reached before 20 keys")
        finally:
            # Clean up keys created by this test.
            for api_key_id in created_keys:
                admin_client.delete(
                    f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys/{api_key_id}"
                )


class TestAPIKeyAuditLogs:
    """Test that API key lifecycle actions generate audit logs."""

    def test_api_key_create_writes_audit_log(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Creating an API key should produce an audit log entry."""
        key_data = {"api_key_name": "audit-key", "role": "user"}
        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
            json=key_data,
        )
        assert response.status_code == 201
        api_key = get_response_data(response)

        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={
                "action": "api_key.create",
                "resource_type": "api_key",
                "resource_id": api_key["api_key_id"],
            },
        )
        assert response.status_code == 200
        data = get_response_data(response)
        assert data["total"] >= 1
        assert any(
            log["resource_id"] == api_key["api_key_id"] and log["action"] == "api_key.create"
            for log in data["items"]
        )

        # Cleanup
        admin_client.delete(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys/{api_key['api_key_id']}"
        )
