"""
Integration tests for ACS account management endpoints.

These tests verify account CRUD, authentication, sessions, and role-based
access control against a running ACS server.
"""

import pytest
import requests


class TestAccountAuthentication:
    """Test authentication requirements for account endpoints."""

    def test_unauthenticated_request_rejected(self, api_client: requests.Session, server_url: str):
        """Protected endpoints must reject requests without credentials."""
        response = api_client.get(f"{server_url}/api/v1/accounts")
        assert response.status_code == 401
        data = response.json()
        assert "error" in data

    def test_admin_token_can_list_accounts(self, admin_client: requests.Session, server_url: str):
        """An admin API key should be able to list accounts."""
        response = admin_client.get(f"{server_url}/api/v1/accounts")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_get_current_account(self, admin_client: requests.Session, server_url: str, admin_token: str):
        """GET /api/v1/accounts/me should return the authenticated account."""
        response = admin_client.get(f"{server_url}/api/v1/accounts/me")
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "admin"
        assert "login_password" not in data
        assert "login_session_key" not in data


class TestAccountCRUD:
    """Test account lifecycle operations."""

    def test_create_user_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin should be able to create a user account."""
        account_data = {
            "account_name": f"Create Test {unique_id}",
            "role": "user",
            "login_name": f"create_test_{unique_id}",
            "login_password": "CreatePass123!",
        }

        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        data = response.json()
        assert data["account_name"] == account_data["account_name"]
        assert data["role"] == "user"
        assert data["status"] == "active"
        assert data["login_name"] == account_data["login_name"]
        assert "account_id" in data

        # Cleanup
        admin_client.delete(f"{server_url}/api/v1/accounts/{data['account_id']}")

    def test_create_manager_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin should be able to create a manager account."""
        account_data = {
            "account_name": f"Manager Test {unique_id}",
            "role": "manager",
            "login_name": f"manager_test_{unique_id}",
            "login_password": "ManagerPass123!",
        }

        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "manager"

        # Cleanup
        admin_client.delete(f"{server_url}/api/v1/accounts/{data['account_id']}")

    def test_create_account_duplicate_login_name(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Creating an account with a duplicate login_name should fail."""
        login_name = f"dup_test_{unique_id}"
        account_data = {
            "account_name": f"Dup Test {unique_id}",
            "role": "user",
            "login_name": login_name,
            "login_password": "DupPass123!",
        }

        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        created = response.json()

        # Second attempt with same login_name should conflict.
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 409

        # Cleanup
        admin_client.delete(f"{server_url}/api/v1/accounts/{created['account_id']}")

    def test_get_account_by_id(self, admin_client: requests.Session, server_url: str, test_account: dict):
        """Admin should be able to retrieve an account by ID."""
        response = admin_client.get(f"{server_url}/api/v1/accounts/{test_account['account_id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == test_account["account_id"]
        assert data["login_name"] == test_account["login_name"]
        assert "login_password" not in data

    def test_update_account(self, admin_client: requests.Session, server_url: str, test_account: dict):
        """Admin should be able to update an account."""
        update_data = {
            "account_name": f"Updated {test_account['account_name']}",
            "account_description": "Updated description",
        }

        response = admin_client.put(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}",
            json=update_data,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["account_name"] == update_data["account_name"]
        assert data["account_description"] == update_data["account_description"]

    def test_soft_delete_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Deleting an account should mark it as deleted."""
        account_data = {
            "account_name": f"Delete Test {unique_id}",
            "role": "user",
            "login_name": f"delete_test_{unique_id}",
            "login_password": "DeletePass123!",
        }

        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        account = response.json()

        response = admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")
        assert response.status_code == 200

        # Verify the account is marked deleted.
        response = admin_client.get(f"{server_url}/api/v1/accounts/{account['account_id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["delete_at_ms"] > 0


class TestAccountLoginAndSession:
    """Test password login and session key authentication."""

    def test_login_by_password(self, admin_client: requests.Session, api_client: requests.Session, server_url: str, test_account: dict):
        """A user should be able to log in with login_name and password."""
        login_data = {
            "login_name": test_account["login_name"],
            "password": "TestPass123!",
        }

        response = api_client.post(f"{server_url}/api/v1/accounts/login", json=login_data)
        assert response.status_code == 200
        data = response.json()
        assert "session_key" in data
        assert "account_id" in data
        assert "expires_at_ms" in data
        assert data["account_id"] == test_account["account_id"]

    def test_login_with_wrong_password_fails(self, api_client: requests.Session, server_url: str, test_account: dict):
        """Login with an incorrect password should fail."""
        login_data = {
            "login_name": test_account["login_name"],
            "password": "WrongPassword!",
        }

        response = api_client.post(f"{server_url}/api/v1/accounts/login", json=login_data)
        assert response.status_code == 401

    def test_session_key_authentication(self, admin_client: requests.Session, api_client: requests.Session, server_url: str, test_account: dict):
        """A session key should authenticate requests."""
        # Create a session via the admin API.
        response = admin_client.post(f"{server_url}/api/v1/accounts/{test_account['account_id']}/session")
        assert response.status_code == 200
        session = response.json()

        # Use the session key to fetch the current account.
        headers = {"X-Session-Key": session["session_key"]}
        response = api_client.get(f"{server_url}/api/v1/accounts/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == test_account["account_id"]

    def test_change_password(self, admin_client: requests.Session, api_client: requests.Session, server_url: str, test_account: dict):
        """A user should be able to change their password."""
        new_password = "NewPass123!"
        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/password",
            json={"new_password": new_password},
        )
        assert response.status_code == 200

        # Login with the new password should succeed.
        login_data = {
            "login_name": test_account["login_name"],
            "password": new_password,
        }
        response = api_client.post(f"{server_url}/api/v1/accounts/login", json=login_data)
        assert response.status_code == 200

        # Login with the old password should fail.
        login_data["password"] = "TestPass123!"
        response = api_client.post(f"{server_url}/api/v1/accounts/login", json=login_data)
        assert response.status_code == 401


class TestManagerAccountLimitations:
    """Test manager role restrictions."""

    def test_manager_can_create_user_account(self, manager_client: requests.Session | None, server_url: str, unique_id: str):
        """A manager should be able to create user accounts."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        account_data = {
            "account_name": f"Manager Created {unique_id}",
            "role": "user",
            "login_name": f"manager_created_{unique_id}",
            "login_password": "ManagerCreated123!",
        }

        response = manager_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "user"

        # Cleanup
        # Manager cannot delete accounts, so we cannot clean up here directly.
        # The test leaves the account; in a real CI setup an admin cleanup step
        # or a dedicated admin client should be used.

    def test_manager_cannot_create_admin_account(self, manager_client: requests.Session | None, server_url: str, unique_id: str):
        """A manager should not be able to create admin accounts."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        account_data = {
            "account_name": f"Manager Admin Attempt {unique_id}",
            "role": "admin",
            "login_name": f"manager_admin_attempt_{unique_id}",
            "login_password": "ManagerAdmin123!",
        }

        response = manager_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 403

    def test_manager_cannot_create_api_key(self, manager_client: requests.Session | None, server_url: str, manager_token: str | None):
        """A manager should not be able to create API keys."""
        if manager_client is None or not manager_token:
            pytest.skip("Manager token not available")

        # We need the manager account ID. Resolve it via /accounts/me.
        response = manager_client.get(f"{server_url}/api/v1/accounts/me")
        assert response.status_code == 200
        manager_account = response.json()

        key_data = {"api_key_name": "manager-key-attempt", "role": "manager"}
        response = manager_client.post(
            f"{server_url}/api/v1/accounts/{manager_account['account_id']}/api-keys",
            json=key_data,
        )
        assert response.status_code == 403


class TestAccountAuditLogs:
    """Test that account lifecycle actions generate audit logs."""

    def test_account_create_writes_audit_log(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Creating an account should produce an audit log entry."""
        account_data = {
            "account_name": f"Audit Test {unique_id}",
            "role": "user",
            "login_name": f"audit_test_{unique_id}",
            "login_password": "AuditPass123!",
        }

        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        account = response.json()

        # Query audit logs for the account creation action.
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={
                "action": "account.create",
                "resource_type": "account",
                "resource_id": account["account_id"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any(
            log["resource_id"] == account["account_id"] and log["action"] == "account.create"
            for log in data["items"]
        )

        # Cleanup
        admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")
