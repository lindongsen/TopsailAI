"""
Integration tests for ACS audit log endpoints.

These tests verify that security-relevant actions are recorded and that
the audit log API can be queried, filtered, and paginated by admin callers.
"""

import time

import pytest
import requests


def _resp_data(response: requests.Response) -> dict:
    """Unwrap the API response envelope and return the data payload."""
    return response.json()["data"]


class TestAuditLogAuthentication:
    """Test authentication and authorization for audit log endpoints."""

    def test_list_audit_logs_requires_admin(self, admin_client: requests.Session, server_url: str):
        """Admin should be able to list audit logs."""
        response = admin_client.get(f"{server_url}/api/v1/audit-logs")
        assert response.status_code == 200
        data = _resp_data(response)
        assert "items" in data
        assert "total" in data

    def test_list_audit_logs_denied_for_user(
        self,
        admin_client: requests.Session,
        server_url: str,
        test_account_with_api_key: tuple[dict, str],
    ):
        """User should receive 403 when listing audit logs."""
        _, token = test_account_with_api_key
        user_client = requests.Session()
        user_client.headers.update({"Content-Type": "application/json"})
        headers = {"Authorization": f"Bearer {token}"}
        response = user_client.get(f"{server_url}/api/v1/audit-logs", headers=headers)
        assert response.status_code == 403
        assert "error" in response.json()

    def test_list_audit_logs_denied_for_manager(
        self, manager_client: requests.Session | None, server_url: str
    ):
        """Manager should receive 403 when listing audit logs."""
        if manager_client is None:
            pytest.skip("Manager token not available")
        response = manager_client.get(f"{server_url}/api/v1/audit-logs")
        assert response.status_code == 403
        assert "error" in response.json()

    def test_get_audit_log_requires_admin(
        self,
        admin_client: requests.Session,
        server_url: str,
        test_account: dict,
    ):
        """Admin should be able to get a single audit log by ID."""
        # Find an audit log for the test account creation.
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        audit_log_id = data["items"][0]["audit_log_id"]

        response = admin_client.get(f"{server_url}/api/v1/audit-logs/{audit_log_id}")
        assert response.status_code == 200
        log = response.json()
        assert log["audit_log_id"] == audit_log_id

    def test_get_audit_log_denied_for_user(
        self,
        admin_client: requests.Session,
        server_url: str,
        test_account_with_api_key: tuple[dict, str],
    ):
        """User should receive 403 when getting an audit log by ID."""
        _, token = test_account_with_api_key
        # Find any audit log.
        response = admin_client.get(f"{server_url}/api/v1/audit-logs", params={"limit": 1})
        assert response.status_code == 200
        data = _resp_data(response)
        if data["total"] == 0:
            pytest.skip("No audit logs available")
        audit_log_id = data["items"][0]["audit_log_id"]

        user_client = requests.Session()
        user_client.headers.update({"Content-Type": "application/json"})
        headers = {"Authorization": f"Bearer {token}"}
        response = user_client.get(
            f"{server_url}/api/v1/audit-logs/{audit_log_id}", headers=headers
        )
        assert response.status_code == 403

    def test_get_nonexistent_audit_log_returns_404(self, admin_client: requests.Session, server_url: str):
        """Requesting an unknown audit log ID returns 404."""
        response = admin_client.get(f"{server_url}/api/v1/audit-logs/al-does-not-exist")
        assert response.status_code == 404
        assert "error" in response.json()


class TestAuditLogFields:
    """Test the structure and contents of audit log records."""

    def test_audit_log_has_expected_fields(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Audit log records contain the expected fields."""
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        log = data["items"][0]

        expected_fields = {
            "audit_log_id",
            "account_id",
            "action",
            "resource_type",
            "resource_id",
            "resource_name",
            "detail",
            "client_ip",
            "create_at_ms",
        }
        for field in expected_fields:
            assert field in log, f"Missing field: {field}"

    def test_audit_log_does_not_leak_sensitive_fields(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Audit log records do not contain sensitive fields."""
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        log = data["items"][0]

        forbidden_fields = {"login_password", "login_session_key", "api_key_hash"}
        for field in forbidden_fields:
            assert field not in log, f"Sensitive field leaked: {field}"

    def test_audit_log_includes_client_ip(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Audit log records include the client IP address."""
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        log = data["items"][0]
        assert "client_ip" in log
        assert log["client_ip"] not in ("", None)

    def test_audit_log_resource_name_captured(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Audit log records capture the resource name."""
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        log = data["items"][0]
        assert "resource_name" in log
        assert log["resource_name"] not in ("", None)

    def test_audit_log_detail_is_meaningful(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Audit log detail field contains a meaningful description."""
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        log = data["items"][0]
        assert "detail" in log
        assert isinstance(log["detail"], str)


class TestAuditLogFiltering:
    """Test filtering, pagination, and sorting of audit logs."""

    def test_filter_by_action(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Filter audit logs by action."""
        # Discover the action name used for account creation.
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        action = data["items"][0]["action"]

        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs", params={"action": action}
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        for log in data["items"]:
            assert log["action"] == action

    def test_filter_by_resource_type_and_id(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Filter audit logs by resource_type and resource_id."""
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        for log in data["items"]:
            assert log["resource_type"] == "account"
            assert log["resource_id"] == test_account["account_id"]

    def test_filter_by_account_id(
        self, admin_client: requests.Session, server_url: str, admin_token: str
    ):
        """Filter audit logs by acting account_id."""
        # Resolve the admin account ID.
        response = admin_client.get(f"{server_url}/api/v1/accounts/me")
        assert response.status_code == 200
        admin_account = response.json()

        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs", params={"account_id": admin_account["account_id"]}
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        for log in data["items"]:
            assert log["account_id"] == admin_account["account_id"]

    def test_filter_by_api_key_id(
        self, admin_client: requests.Session, server_url: str, admin_token: str
    ):
        """Filter audit logs by api_key_id."""
        api_key_id = admin_token.split(".")[0]
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs", params={"api_key_id": api_key_id}
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["total"] >= 1
        for log in data["items"]:
            assert log["api_key_id"] == api_key_id

    def test_pagination(
        self, admin_client: requests.Session, server_url: str
    ):
        """Pagination parameters offset and limit are respected."""
        response = admin_client.get(f"{server_url}/api/v1/audit-logs", params={"limit": 1})
        assert response.status_code == 200
        first_page = _resp_data(response)
        if first_page["total"] < 2:
            pytest.skip("Not enough audit logs to test pagination")

        assert len(first_page["items"]) == 1
        first_id = first_page["items"][0]["audit_log_id"]

        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs", params={"offset": 1, "limit": 1}
        )
        assert response.status_code == 200
        second_page = _resp_data(response)
        assert len(second_page["items"]) == 1
        second_id = second_page["items"][0]["audit_log_id"]
        assert first_id != second_id
        assert first_page["total"] == second_page["total"]

    def test_time_range_filter(
        self, admin_client: requests.Session, server_url: str, unique_id: str
    ):
        """Time range filter create_at_ms={start}-{end} works."""
        before_ms = int(time.time() * 1000)
        account_data = {
            "account_name": f"Time Range Test {unique_id}",
            "role": "user",
            "login_name": f"time_range_test_{unique_id}",
            "login_password": "TimeRangePass123!",
        }
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        account = response.json()
        after_ms = int(time.time() * 1000)

        try:
            response = admin_client.get(
                f"{server_url}/api/v1/audit-logs",
                params={
                    "resource_type": "account",
                    "resource_id": account["account_id"],
                    "create_at_ms": f"{before_ms}-{after_ms}",
                },
            )
            assert response.status_code == 200
            data = _resp_data(response)
            assert data["total"] >= 1
            for log in data["items"]:
                assert before_ms <= log["create_at_ms"] <= after_ms
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")

    def test_sorting_by_create_at_ms(
        self, admin_client: requests.Session, server_url: str
    ):
        """Sorting by create_at_ms asc and desc works."""
        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"sort_key": "create_at_ms", "order_by": "desc", "limit": 100},
        )
        assert response.status_code == 200
        desc_data = _resp_data(response)
        if desc_data["total"] < 2:
            pytest.skip("Not enough audit logs to test sorting")

        timestamps = [log["create_at_ms"] for log in desc_data["items"]]
        assert timestamps == sorted(timestamps, reverse=True)

        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"sort_key": "create_at_ms", "order_by": "asc", "limit": 100},
        )
        assert response.status_code == 200
        asc_data = _resp_data(response)
        timestamps = [log["create_at_ms"] for log in asc_data["items"]]
        assert timestamps == sorted(timestamps)


class TestAuditLogLifecycleEvents:
    """Test that security-relevant lifecycle events generate audit logs."""

    def test_account_create_writes_audit_log(
        self, admin_client: requests.Session, server_url: str, unique_id: str
    ):
        """Creating an account generates an audit log."""
        account_data = {
            "account_name": f"Lifecycle Create {unique_id}",
            "role": "user",
            "login_name": f"lifecycle_create_{unique_id}",
            "login_password": "LifecyclePass123!",
        }
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        account = response.json()

        try:
            response = admin_client.get(
                f"{server_url}/api/v1/audit-logs",
                params={"resource_type": "account", "resource_id": account["account_id"]},
            )
            assert response.status_code == 200
            data = _resp_data(response)
            assert data["total"] >= 1
            assert any(log["resource_id"] == account["account_id"] for log in data["items"])
        finally:
            admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")

    def test_api_key_create_writes_audit_log(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Creating an API key generates an audit log."""
        key_data = {"api_key_name": "audit-lifecycle-key", "role": "user"}
        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
            json=key_data,
        )
        assert response.status_code == 201
        api_key = response.json()

        try:
            response = admin_client.get(
                f"{server_url}/api/v1/audit-logs",
                params={"resource_type": "api_key", "resource_id": api_key["api_key_id"]},
            )
            assert response.status_code == 200
            data = _resp_data(response)
            assert data["total"] >= 1
            assert any(log["resource_id"] == api_key["api_key_id"] for log in data["items"])
        finally:
            admin_client.delete(
                f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys/{api_key['api_key_id']}"
            )

    def test_login_attempts_write_audit_log(
        self,
        admin_client: requests.Session,
        unauthenticated_client: requests.Session,
        server_url: str,
        test_account: dict,
    ):
        """Successful and failed login attempts generate audit logs."""
        # Failed login attempt.
        response = unauthenticated_client.post(
            f"{server_url}/api/v1/accounts/login",
            json={
                "login_name": test_account["login_name"],
                "login_password": "WrongPassword123!",
            },
        )
        assert response.status_code == 401

        # Successful login attempt.
        response = unauthenticated_client.post(
            f"{server_url}/api/v1/accounts/login",
            json={
                "login_name": test_account["login_name"],
                "login_password": "TestPass123!",
            },
        )
        assert response.status_code == 200

        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        login_logs = [log for log in data["items"] if "login" in log["action"]]
        assert len(login_logs) >= 2

    def test_password_change_writes_audit_log(
        self, admin_client: requests.Session, server_url: str, test_account: dict
    ):
        """Changing a password generates an audit log."""
        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{test_account['account_id']}/password",
            json={"new_password": "ChangedPass123!"},
        )
        assert response.status_code == 200

        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": test_account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        password_logs = [log for log in data["items"] if "password" in log["action"]]
        assert len(password_logs) >= 1

    def test_account_delete_writes_audit_log(
        self, admin_client: requests.Session, server_url: str, unique_id: str
    ):
        """Soft-deleting an account generates an audit log."""
        account_data = {
            "account_name": f"Lifecycle Delete {unique_id}",
            "role": "user",
            "login_name": f"lifecycle_delete_{unique_id}",
            "login_password": "LifecycleDelete123!",
        }
        response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
        assert response.status_code == 201
        account = response.json()

        response = admin_client.delete(
            f"{server_url}/api/v1/accounts/{account['account_id']}"
        )
        assert response.status_code == 200

        response = admin_client.get(
            f"{server_url}/api/v1/audit-logs",
            params={"resource_type": "account", "resource_id": account["account_id"]},
        )
        assert response.status_code == 200
        data = _resp_data(response)
        delete_logs = [log for log in data["items"] if "delete" in log["action"]]
        assert len(delete_logs) >= 1

    def test_group_create_writes_audit_log(
        self, admin_client: requests.Session, server_url: str, unique_id: str
    ):
        """Creating a group generates an audit log."""
        group_data = {
            "group_name": f"Audit Group {unique_id}",
            "group_context": "Group for audit log test",
            "group_key": "",
        }
        response = admin_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201
        group = response.json()

        try:
            response = admin_client.get(
                f"{server_url}/api/v1/audit-logs",
                params={"resource_type": "group", "resource_id": group["group_id"]},
            )
            assert response.status_code == 200
            data = _resp_data(response)
            assert data["total"] >= 1
            assert any(log["resource_id"] == group["group_id"] for log in data["items"])
        finally:
            admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")
