"""
Integration tests for ACS role-based access control (RBAC).

These tests verify the role hierarchy (admin > manager > user) across
accounts, API keys, groups, members, and messages.
"""

import pytest
import requests


def _create_user_account(admin_client: requests.Session, server_url: str, unique_id: str, suffix: str) -> dict:
    """Helper to create a user account for RBAC tests."""
    account_data = {
        "account_name": f"RBAC User {suffix} {unique_id}",
        "role": "user",
        "login_name": f"rbac_user_{suffix}_{unique_id}",
        "login_password": "RbacUser123!",
    }
    response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
    assert response.status_code == 201, f"Failed to create user account: {response.text}"
    return response.json()


def _api_key_client(admin_client: requests.Session, server_url: str, account_id: str) -> tuple[requests.Session, str]:
    """Create an API key for an account and return a session using it."""
    key_data = {"api_key_name": "rbac-test-key", "role": "user"}
    response = admin_client.post(f"{server_url}/api/v1/accounts/{account_id}/api-keys", json=key_data)
    assert response.status_code == 201, f"Failed to create API key: {response.text}"
    key = response.json()
    token = key["token"]

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session, token



def get_response_data(response):
    """Return the response payload, handling both wrapped and flat JSON formats.

    Wrapped ACS responses have the shape {"data": ..., "error": ..., "trace_id": ...}.
    Flat responses return the resource object directly.
    """
    body = response.json()
    if isinstance(body, dict) and "data" in body and "trace_id" in body:
        return body["data"]
    return body

class TestAccountCreationRBAC:
    """Role-based account creation restrictions."""

    def test_admin_can_create_admin_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can create an admin account."""
        account_data = {
            "account_name": f"RBAC Admin {unique_id}",
            "role": "admin",
            "login_name": f"rbac_admin_{unique_id}",
            "login_password": "RbacAdmin123!",
        }
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        account = response.json()
        assert account["role"] == "admin"
        admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")

    def test_admin_can_create_manager_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can create a manager account."""
        account_data = {
            "account_name": f"RBAC Manager {unique_id}",
            "role": "manager",
            "login_name": f"rbac_manager_{unique_id}",
            "login_password": "RbacManager123!",
        }
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        account = response.json()
        assert account["role"] == "manager"
        admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")

    def test_admin_can_create_user_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can create a user account."""
        account = _create_user_account(admin_client, server_url, unique_id, "admin_user")
        assert account["role"] == "user"
        admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")

    def test_manager_can_create_user_account(self, manager_client: requests.Session | None, server_url: str, unique_id: str):
        """Manager can create accounts with role=user."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        account_data = {
            "account_name": f"RBAC Manager-Created User {unique_id}",
            "role": "user",
            "login_name": f"rbac_mgr_user_{unique_id}",
            "login_password": "RbacUser123!",
        }
        response = manager_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        account = response.json()
        assert account["role"] == "user"
        # Cleanup requires admin client; use server_url with admin auth if available.

    def test_manager_cannot_create_manager_account(self, manager_client: requests.Session | None, server_url: str, unique_id: str):
        """Manager cannot create accounts with role=manager."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        account_data = {
            "account_name": f"RBAC Manager Attempt {unique_id}",
            "role": "manager",
            "login_name": f"rbac_mgr_attempt_{unique_id}",
            "login_password": "RbacManager123!",
        }
        response = manager_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 403

    def test_manager_cannot_create_admin_account(self, manager_client: requests.Session | None, server_url: str, unique_id: str):
        """Manager cannot create accounts with role=admin."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        account_data = {
            "account_name": f"RBAC Admin Attempt {unique_id}",
            "role": "admin",
            "login_name": f"rbac_admin_attempt_{unique_id}",
            "login_password": "RbacAdmin123!",
        }
        response = manager_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 403

    def test_user_cannot_create_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User cannot create any account."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "create_attempt")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            account_data = {
                "account_name": f"RBAC User Create Attempt {unique_id}",
                "role": "user",
                "login_name": f"rbac_user_create_attempt_{unique_id}",
                "login_password": "RbacUserCreate123!",
            }
            response = user_client.post(f"{server_url}/api/v1/accounts", json=account_data)
            assert response.status_code == 403
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")


class TestAPIKeyRBAC:
    """Role-based API key restrictions."""

    def test_admin_can_create_api_key_for_any_role(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can create API keys for any account; key role is capped by owner role."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "admin_key")
        admin_account_data = {
            "account_name": f"RBAC Key Admin {unique_id}",
            "role": "admin",
            "login_name": f"rbac_key_admin_{unique_id}",
            "login_password": "RbacKeyAdmin123!",
        }
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=admin_account_data)
        assert response.status_code == 201
        admin_account = response.json()

        try:
            # Admin can create a user-level key for a user account.
            key_data = {"api_key_name": f"rbac-admin-key-user-{unique_id}", "role": "user"}
            response = admin_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/api-keys",
                json=key_data,
            )
            assert response.status_code == 201, f"Failed to create user key: {response.text}"
            user_key_id = response.json()["api_key_id"]

            # Admin can create admin/manager keys only for an admin account.
            for role in ["manager", "admin"]:
                key_data = {"api_key_name": f"rbac-admin-key-{role}-{unique_id}", "role": role}
                response = admin_client.post(
                    f"{server_url}/api/v1/accounts/{admin_account['account_id']}/api-keys",
                    json=key_data,
                )
                assert response.status_code == 201, f"Failed to create {role} key: {response.text}"
                api_key_id = response.json()["api_key_id"]
                admin_client.delete(
                    f"{server_url}/api/v1/accounts/{admin_account['account_id']}/api-keys/{api_key_id}"
                )

            admin_client.delete(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/api-keys/{user_key_id}"
            )
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{admin_account['account_id']}")

    def test_user_can_create_own_api_key(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can create an API key for their own account with role=user."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "own_key")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            key_data = {"api_key_name": f"rbac-user-own-key-{unique_id}", "role": "user"}
            response = user_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/api-keys",
                json=key_data,
            )
            assert response.status_code == 201
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_cannot_create_api_key_for_other_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User cannot create an API key for another account."""
        user_a = _create_user_account(admin_client, server_url, unique_id, "key_a")
        user_b = _create_user_account(admin_client, server_url, unique_id, "key_b")
        user_client_a, _ = _api_key_client(admin_client, server_url, user_a["account_id"])

        try:
            key_data = {"api_key_name": f"rbac-cross-account-key-{unique_id}", "role": "user"}
            response = user_client_a.post(
                f"{server_url}/api/v1/accounts/{user_b['account_id']}/api-keys",
                json=key_data,
            )
            assert response.status_code == 403
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_a['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_b['account_id']}")

    def test_manager_cannot_create_api_key(self, manager_client: requests.Session | None, server_url: str):
        """Manager cannot create API keys, even for their own account."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        response = manager_client.get(f"{server_url}/api/v1/accounts/me")
        assert response.status_code == 200
        manager_account = get_response_data(response)

        key_data = {"api_key_name": "rbac-manager-key-attempt", "role": "manager"}
        response = manager_client.post(
            f"{server_url}/api/v1/accounts/{manager_account['account_id']}/api-keys",
            json=key_data,
        )
        assert response.status_code == 403

    def test_api_key_role_cannot_exceed_owner_role(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """API key role cannot exceed the owner account's role."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "role_cap")

        try:
            key_data = {"api_key_name": f"rbac-key-over-role-{unique_id}", "role": "manager"}
            response = admin_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/api-keys",
                json=key_data,
            )
            assert response.status_code == 403
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_admin_can_delete_any_api_key(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can delete API keys belonging to any account."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "key_delete")

        try:
            key_data = {"api_key_name": f"rbac-key-delete-{unique_id}", "role": "user"}
            response = admin_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/api-keys",
                json=key_data,
            )
            assert response.status_code == 201
            api_key_id = response.json()["api_key_id"]

            response = admin_client.delete(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/api-keys/{api_key_id}"
            )
            assert response.status_code == 200
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_can_delete_own_api_key(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can delete their own API keys."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "own_key_delete")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            key_data = {"api_key_name": f"rbac-user-key-delete-{unique_id}", "role": "user"}
            response = user_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/api-keys",
                json=key_data,
            )
            assert response.status_code == 201
            api_key_id = response.json()["api_key_id"]

            response = user_client.delete(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/api-keys/{api_key_id}"
            )
            assert response.status_code == 200
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")


class TestAccountAccessRBAC:
    """Role-based account access restrictions."""

    def test_admin_can_list_all_accounts(self, admin_client: requests.Session, server_url: str):
        """Admin can list all accounts."""
        response = admin_client.get(f"{server_url}/api/v1/accounts")
        assert response.status_code == 200
        data = get_response_data(response)
        assert "items" in data
        assert "total" in data

    def test_manager_can_list_accounts_with_limited_fields(self, manager_client: requests.Session | None, server_url: str):
        """Manager can list accounts but sensitive fields are omitted."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        response = manager_client.get(f"{server_url}/api/v1/accounts")
        assert response.status_code == 200
        data = get_response_data(response)
        assert "items" in data
        for account in data["items"]:
            assert "login_password" not in account
            assert "login_session_key" not in account

    def test_user_cannot_list_all_accounts(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User cannot list all accounts."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "list_attempt")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            response = user_client.get(f"{server_url}/api/v1/accounts")
            assert response.status_code == 403
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_admin_can_access_any_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can access any account by ID."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "admin_access")

        try:
            response = admin_client.get(f"{server_url}/api/v1/accounts/{user_account['account_id']}")
            assert response.status_code == 200
            assert get_response_data(response)["account_id"] == user_account["account_id"]
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_manager_can_query_account_by_id_with_limited_fields(self, manager_client: requests.Session | None, admin_client: requests.Session, server_url: str, unique_id: str):
        """Manager can query accounts by id with limited fields."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        user_account = _create_user_account(admin_client, server_url, unique_id, "mgr_query")

        try:
            response = manager_client.get(f"{server_url}/api/v1/accounts/{user_account['account_id']}")
            assert response.status_code == 200
            account = get_response_data(response)
            assert account["account_id"] == user_account["account_id"]
            assert "login_password" not in account
            assert "login_session_key" not in account
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_manager_can_query_account_by_external_id(self, manager_client: requests.Session | None, admin_client: requests.Session, server_url: str, unique_id: str):
        """Manager can query accounts by external_id."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        account_data = {
            "account_name": f"RBAC External {unique_id}",
            "role": "user",
            "login_name": f"rbac_external_{unique_id}",
            "login_password": "RbacExternal123!",
            "external_id": f"ext-rbac-{unique_id}",
        }
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        user_account = response.json()

        try:
            response = manager_client.get(
                f"{server_url}/api/v1/accounts", params={"external_id": user_account["external_id"]}
            )
            assert response.status_code == 200
            items = get_response_data(response)["items"]
            assert len(items) == 1
            assert items[0]["external_id"] == user_account["external_id"]
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_can_only_access_own_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can only access their own account."""
        user_a = _create_user_account(admin_client, server_url, unique_id, "own_a")
        user_b = _create_user_account(admin_client, server_url, unique_id, "own_b")
        user_client_a, _ = _api_key_client(admin_client, server_url, user_a["account_id"])

        try:
            response = user_client_a.get(f"{server_url}/api/v1/accounts/{user_a['account_id']}")
            assert response.status_code == 200

            response = user_client_a.get(f"{server_url}/api/v1/accounts/{user_b['account_id']}")
            assert response.status_code == 403
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_a['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_b['account_id']}")

    def test_admin_can_update_any_account_role_and_status(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can update any account including role and status."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "admin_update")

        try:
            update_data = {"role": "manager", "status": "inactive"}
            response = admin_client.put(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}",
                json=update_data,
            )
            assert response.status_code == 200
            updated = get_response_data(response)
            assert updated["role"] == "manager"
            assert updated["status"] == "inactive"
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_cannot_change_own_role_or_status(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User cannot change their own role or status."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "self_update")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            update_data = {"role": "admin", "status": "inactive"}
            response = user_client.put(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}",
                json=update_data,
            )
            assert response.status_code == 403
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_admin_can_delete_any_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can delete any account."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "admin_delete")

        response = admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")
        assert response.status_code == 200

    def test_manager_cannot_delete_account(self, manager_client: requests.Session | None, admin_client: requests.Session, server_url: str, unique_id: str):
        """Manager cannot delete accounts."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        user_account = _create_user_account(admin_client, server_url, unique_id, "manager_delete")

        try:
            response = manager_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")
            assert response.status_code == 403
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_cannot_delete_account(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User cannot delete accounts."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "user_delete")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            response = user_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")
            assert response.status_code == 403
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_admin_can_change_any_password(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can change any account password."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "admin_pwd")

        try:
            response = admin_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/password",
                json={"new_password": "NewPassword123!"},
            )
            assert response.status_code == 200
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_can_change_own_password(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can change their own password."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "user_pwd")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            response = user_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/password",
                json={"new_password": "NewPassword123!"},
            )
            assert response.status_code == 200
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_manager_can_create_session_for_user(self, manager_client: requests.Session | None, admin_client: requests.Session, server_url: str, unique_id: str):
        """Manager can create a login session for a user account."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        user_account = _create_user_account(admin_client, server_url, unique_id, "mgr_session")

        try:
            response = manager_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/session"
            )
            assert response.status_code == 200
            data = get_response_data(response)
            assert "session_key" in data
            assert "expires_at_ms" in data
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_manager_cannot_create_session_for_admin(self, manager_client: requests.Session | None, admin_client: requests.Session, server_url: str, unique_id: str):
        """Manager cannot create a login session for an admin account."""
        if manager_client is None:
            pytest.skip("Manager token not available")

        account_data = {
            "account_name": f"RBAC Session Admin {unique_id}",
            "role": "admin",
            "login_name": f"rbac_session_admin_{unique_id}",
            "login_password": "RbacSessionAdmin123!",
        }
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        admin_account = response.json()

        try:
            response = manager_client.post(
                f"{server_url}/api/v1/accounts/{admin_account['account_id']}/session"
            )
            assert response.status_code == 403
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{admin_account['account_id']}")

    def test_user_can_create_own_session(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can create a session for their own account."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "user_session")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            response = user_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/session"
            )
            assert response.status_code == 200
            data = get_response_data(response)
            assert "session_key" in data
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")


class TestGroupRBAC:
    """Role-based group access restrictions."""

    def test_admin_can_access_any_group(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can access any group regardless of membership."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "group_owner")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            group_data = {"group_name": f"RBAC Group {unique_id}", "group_context": "RBAC test group"}
            response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            response = admin_client.get(f"{server_url}/api/v1/groups/{group['group_id']}")
            assert response.status_code == 200
            assert get_response_data(response)["group_id"] == group["group_id"]

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_can_only_access_member_groups(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can only access groups they are a member of."""
        user_a = _create_user_account(admin_client, server_url, unique_id, "group_a")
        user_b = _create_user_account(admin_client, server_url, unique_id, "group_b")
        user_client_a, _ = _api_key_client(admin_client, server_url, user_a["account_id"])
        user_client_b, _ = _api_key_client(admin_client, server_url, user_b["account_id"])

        try:
            group_data = {"group_name": f"RBAC Private Group {unique_id}", "group_context": "Private"}
            response = user_client_a.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            response = user_client_b.get(f"{server_url}/api/v1/groups/{group['group_id']}")
            assert response.status_code == 403

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_a['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_b['account_id']}")

    def test_group_owner_can_update_and_delete_own_group(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Group owner can update and delete their own group."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "group_owner_ops")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            group_data = {"group_name": f"RBAC Owner Group {unique_id}", "group_context": "Owner test"}
            response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            update_data = {"group_name": f"RBAC Owner Group Updated {unique_id}"}
            response = user_client.put(
                f"{server_url}/api/v1/groups/{group['group_id']}",
                json=update_data,
            )
            assert response.status_code == 200

            response = user_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
            assert response.status_code == 204
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_non_owner_user_cannot_delete_others_group(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Non-owner user cannot delete another user's group."""
        owner = _create_user_account(admin_client, server_url, unique_id, "group_owner_other")
        other = _create_user_account(admin_client, server_url, unique_id, "group_other")
        owner_client, _ = _api_key_client(admin_client, server_url, owner["account_id"])
        other_client, _ = _api_key_client(admin_client, server_url, other["account_id"])

        try:
            group_data = {"group_name": f"RBAC Other Group {unique_id}", "group_context": "Other"}
            response = owner_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            response = other_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
            assert response.status_code == 403

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{owner['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{other['account_id']}")


class TestGroupMemberRBAC:
    """Role-based group member restrictions."""

    def test_admin_can_manage_any_group_members(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Admin can add members to any group."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "member_group_owner")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            group_data = {"group_name": f"RBAC Member Group {unique_id}", "group_context": "Member test"}
            response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            member_data = {
                "member_id": f"rbac-member-{unique_id}",
                "member_name": f"RBAC_Member_{unique_id}",
                "member_type": "user",
            }
            response = admin_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/members",
                json=member_data,
            )
            assert response.status_code == 201

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_group_owner_can_add_members(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Group owner can add members to their group."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "owner_add_member")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            group_data = {"group_name": f"RBAC Owner Member Group {unique_id}", "group_context": "Owner member"}
            response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            member_data = {
                "member_id": f"rbac-owner-member-{unique_id}",
                "member_name": f"RBAC_Owner_Member_{unique_id}",
                "member_type": "user",
            }
            response = user_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/members",
                json=member_data,
            )
            assert response.status_code == 201

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_non_member_user_cannot_list_members(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Non-member user cannot list members of a private group."""
        owner = _create_user_account(admin_client, server_url, unique_id, "member_owner")
        other = _create_user_account(admin_client, server_url, unique_id, "member_other")
        owner_client, _ = _api_key_client(admin_client, server_url, owner["account_id"])
        other_client, _ = _api_key_client(admin_client, server_url, other["account_id"])

        try:
            group_data = {"group_name": f"RBAC Member Private {unique_id}", "group_context": "Private"}
            response = owner_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            response = other_client.get(f"{server_url}/api/v1/groups/{group['group_id']}/members")
            assert response.status_code == 403

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{owner['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{other['account_id']}")

    def test_user_can_update_own_member_record(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can update their own member record in a group."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "own_member")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            group_data = {"group_name": f"RBAC Own Member Group {unique_id}", "group_context": "Own member"}
            response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            update_data = {"member_name": f"Updated_Member_{unique_id}"}
            response = user_client.put(
                f"{server_url}/api/v1/groups/{group['group_id']}/members/{user_account['account_id']}",
                json=update_data,
            )
            assert response.status_code == 200

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_cannot_update_others_member_record(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User cannot update another member's record."""
        owner = _create_user_account(admin_client, server_url, unique_id, "member_update_owner")
        other = _create_user_account(admin_client, server_url, unique_id, "member_update_other")
        owner_client, _ = _api_key_client(admin_client, server_url, owner["account_id"])
        other_client, _ = _api_key_client(admin_client, server_url, other["account_id"])

        try:
            group_data = {"group_name": f"RBAC Member Update {unique_id}", "group_context": "Update"}
            response = owner_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            member_data = {
                "member_id": other["account_id"],
                "member_name": f"RBAC_Other_Member_{unique_id}",
                "member_type": "user",
            }
            response = owner_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/members",
                json=member_data,
            )
            assert response.status_code == 201

            update_data = {"member_name": f"Hacked Member {unique_id}"}
            response = other_client.put(
                f"{server_url}/api/v1/groups/{group['group_id']}/members/{owner['account_id']}",
                json=update_data,
            )
            assert response.status_code == 403

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{owner['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{other['account_id']}")

    def test_user_can_delete_own_member_record(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can delete (leave) their own member record."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "own_leave")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            group_data = {"group_name": f"RBAC Leave Group {unique_id}", "group_context": "Leave"}
            response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            response = user_client.delete(
                f"{server_url}/api/v1/groups/{group['group_id']}/members/{user_account['account_id']}"
            )
            assert response.status_code == 204

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")


class TestMessageRBAC:
    """Role-based message restrictions."""

    def test_user_can_send_message_to_member_group(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can send messages to groups they are a member of."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "msg_sender")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            group_data = {"group_name": f"RBAC Message Group {unique_id}", "group_context": "Messages"}
            response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            message_data = {"message_text": f"Hello from user {unique_id}"}
            response = user_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 201

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_non_member_user_cannot_send_messages(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """Non-member user cannot send messages to a group."""
        owner = _create_user_account(admin_client, server_url, unique_id, "msg_owner")
        other = _create_user_account(admin_client, server_url, unique_id, "msg_other")
        owner_client, _ = _api_key_client(admin_client, server_url, owner["account_id"])
        other_client, _ = _api_key_client(admin_client, server_url, other["account_id"])

        try:
            group_data = {"group_name": f"RBAC Message Private {unique_id}", "group_context": "Private"}
            response = owner_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            message_data = {"message_text": "Unauthorized message"}
            response = other_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 403

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{owner['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{other['account_id']}")

    def test_user_can_update_own_message(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can update their own messages."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "msg_update")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            group_data = {"group_name": f"RBAC Update Group {unique_id}", "group_context": "Update"}
            response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            message_data = {"message_text": "Original message"}
            response = user_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 201
            message = get_response_data(response)

            update_data = {"message_text": "Updated message"}
            response = user_client.put(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages/{message['message_id']}",
                json=update_data,
            )
            assert response.status_code == 200

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_cannot_update_others_message(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User cannot update another user's messages."""
        owner = _create_user_account(admin_client, server_url, unique_id, "msg_update_owner")
        other = _create_user_account(admin_client, server_url, unique_id, "msg_update_other")
        owner_client, _ = _api_key_client(admin_client, server_url, owner["account_id"])
        other_client, _ = _api_key_client(admin_client, server_url, other["account_id"])

        try:
            group_data = {"group_name": f"RBAC Message Update {unique_id}", "group_context": "Update"}
            response = owner_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            member_data = {
                "member_id": other["account_id"],
                "member_name": f"RBAC_Other_{unique_id}",
                "member_type": "user",
            }
            response = owner_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/members",
                json=member_data,
            )
            assert response.status_code == 201

            message_data = {"message_text": "Owner's message"}
            response = owner_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 201
            message = get_response_data(response)

            update_data = {"message_text": "Hacked message"}
            response = other_client.put(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages/{message['message_id']}",
                json=update_data,
            )
            assert response.status_code == 403

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{owner['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{other['account_id']}")

    def test_user_can_delete_own_message(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User can delete their own messages."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "msg_delete")
        user_client, _ = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            group_data = {"group_name": f"RBAC Delete Group {unique_id}", "group_context": "Delete"}
            response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            message_data = {"message_text": "Message to delete"}
            response = user_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 201
            message = get_response_data(response)

            response = user_client.delete(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages/{message['message_id']}"
            )
            assert response.status_code == 204

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_user_cannot_delete_others_message(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """User cannot delete another user's messages."""
        owner = _create_user_account(admin_client, server_url, unique_id, "msg_delete_owner")
        other = _create_user_account(admin_client, server_url, unique_id, "msg_delete_other")
        owner_client, _ = _api_key_client(admin_client, server_url, owner["account_id"])
        other_client, _ = _api_key_client(admin_client, server_url, other["account_id"])

        try:
            group_data = {"group_name": f"RBAC Message Delete {unique_id}", "group_context": "Delete"}
            response = owner_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group = get_response_data(response)

            member_data = {
                "member_id": other["account_id"],
                "member_name": f"RBAC_Other_{unique_id}",
                "member_type": "user",
            }
            response = owner_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/members",
                json=member_data,
            )
            assert response.status_code == 201

            message_data = {"message_text": "Owner's message"}
            response = owner_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 201
            message = get_response_data(response)

            response = other_client.delete(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages/{message['message_id']}"
            )
            assert response.status_code == 403

            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{owner['account_id']}")
            admin_client.delete(f"{server_url}/api/v1/accounts/{other['account_id']}")


class TestAuthenticationPriority:
    """Authentication priority: login_name_password > session_key > api_key."""

    def test_session_key_takes_priority_over_api_key(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """When both session key and API key are present, session key identity is used."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "auth_priority")
        user_client, token = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            response = user_client.post(
                f"{server_url}/api/v1/accounts/{user_account['account_id']}/session"
            )
            assert response.status_code == 200
            session_key = get_response_data(response)["session_key"]

            # Use a session from a different account while API key is for user_account.
            other_account = _create_user_account(admin_client, server_url, unique_id, "auth_other")
            try:
                other_client, _ = _api_key_client(admin_client, server_url, other_account["account_id"])
                response = other_client.post(
                    f"{server_url}/api/v1/accounts/{other_account['account_id']}/session"
                )
                assert response.status_code == 200
                other_session = get_response_data(response)["session_key"]

                mixed_client = requests.Session()
                mixed_client.headers.update({
                    "Authorization": f"Bearer {token}",
                    "X-Session-Key": other_session,
                })
                response = mixed_client.get(f"{server_url}/api/v1/accounts/me")
                assert response.status_code == 200
                assert get_response_data(response)["account_id"] == other_account["account_id"]
            finally:
                admin_client.delete(f"{server_url}/api/v1/accounts/{other_account['account_id']}")
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")

    def test_api_key_used_when_session_key_invalid(self, admin_client: requests.Session, server_url: str, unique_id: str):
        """When session key is invalid, API key is used."""
        user_account = _create_user_account(admin_client, server_url, unique_id, "api_fallback")
        user_client, token = _api_key_client(admin_client, server_url, user_account["account_id"])

        try:
            fallback_client = requests.Session()
            fallback_client.headers.update({
                "Authorization": f"Bearer {token}",
                "X-Session-Key": "invalid-session-key",
            })
            response = fallback_client.get(f"{server_url}/api/v1/accounts/me")
            assert response.status_code == 200
            assert get_response_data(response)["account_id"] == user_account["account_id"]
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{user_account['account_id']}")


class TestUnauthenticated:
    """Unauthenticated requests are rejected."""

    def test_unauthenticated_request_rejected(self, server_url: str):
        """Requests without valid credentials are rejected."""
        client = requests.Session()
        response = client.get(f"{server_url}/api/v1/accounts/me")
        assert response.status_code == 401
