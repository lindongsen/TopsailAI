"""
Integration tests for ACS login session key expiry.

These tests verify the behavior documented in docs/cases/TestCase_integration_session_expiry.md:
- session keys expire after ACS_LOGIN_SESSION_EXPIRY_SECONDS
- new sessions replace old ones
- expired sessions are rejected by protected endpoints
- expires_at_ms reflects the configured expiry
- role-based restrictions on session creation
- password change invalidates the current session

A secondary ACS server is started with a very short session expiry (2 seconds)
so that expiry scenarios complete quickly.

NOTE: The current ACS API returns raw objects for some endpoints
(GET /accounts/me, POST /accounts) instead of the documented
{data, error, trace_id} envelope. Helpers in this file handle both shapes.
See: issues/issue-api-response-envelope-inconsistency.md
"""

import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = "/TopsailAI/src/topsailai_server/agent_community"
SERVER_BIN = os.path.join(PROJECT_ROOT, "bin", "acs-server")
AGENT_CMD_DIR = os.path.join(PROJECT_ROOT, "scripts", "topsailai_agent_cmd")

SECONDARY_HOST = "127.1.0.5"
TEST_PORT = 7370


def _read_token_file(file_name: str) -> str | None:
    """Read a generated API key token from the project root."""
    token_path = os.path.join(PROJECT_ROOT, file_name)
    if os.path.exists(token_path):
        with open(token_path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    return None


def _wait_for_server(base_url: str, timeout: int = 60) -> bool:
    """Poll /healthz until the server responds or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/healthz", timeout=2)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def _check_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _start_secondary_server() -> subprocess.Popen:
    """Start a secondary ACS server with a short session expiry."""
    if not os.path.exists(SERVER_BIN):
        pytest.skip(f"ACS server binary not found: {SERVER_BIN}")

    pg_host = os.environ.get("ACS_DB_HOST", "localhost")
    pg_port = int(os.environ.get("ACS_DB_PORT", "5432"))
    nats_url = os.environ.get("ACS_NATS_SERVERS", "nats://127.0.0.1:4222")
    nats_host_port = nats_url.split("://")[-1].split(",")[0]
    if ":" in nats_host_port:
        nats_host, nats_port_str = nats_host_port.rsplit(":", 1)
        nats_port = int(nats_port_str)
    else:
        nats_host = nats_host_port
        nats_port = 4222

    if not _check_tcp(pg_host, pg_port):
        pytest.skip(f"PostgreSQL is not reachable at {pg_host}:{pg_port}")
    if not _check_tcp(nats_host, nats_port):
        pytest.skip(f"NATS is not reachable at {nats_host}:{nats_port}")

    admin_key = os.environ.get("ACS_ACCOUNT_ADMIN_API_KEY") or _read_token_file(
        "ACS_ACCOUNT_ADMIN_API_KEY.acs"
    )
    manager_key = os.environ.get("ACS_ACCOUNT_MANAGER_API_KEY") or _read_token_file(
        "ACS_ACCOUNT_MANAGER_API_KEY.acs"
    )

    env = os.environ.copy()
    env["PATH"] = f"{AGENT_CMD_DIR}:{env.get('PATH', '')}"
    env["ACS_HTTP_HOST"] = SECONDARY_HOST
    env["ACS_HTTP_PORT"] = str(TEST_PORT)
    env["ACS_LOG_OUTPUT"] = "stdout"
    env["ACS_LOG_LEVEL"] = "info"
    # Short session expiry so tests can observe expiration quickly.
    env["ACS_LOGIN_SESSION_EXPIRY_SECONDS"] = "2"

    if admin_key:
        env["ACS_ACCOUNT_ADMIN_API_KEY"] = admin_key
    if manager_key:
        env["ACS_ACCOUNT_MANAGER_API_KEY"] = manager_key

    log_dir = os.path.join(PROJECT_ROOT, "tests", "integration", ".tmp")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(log_dir, f"acs-server-{SECONDARY_HOST}-{TEST_PORT}-session-expiry.log")

    with open(log_file, "a", encoding="utf-8") as out:
        process = subprocess.Popen(
            [SERVER_BIN],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )

    base_url = f"http://{SECONDARY_HOST}:{TEST_PORT}"
    if not _wait_for_server(base_url, timeout=60):
        _stop_server(process)
        pytest.fail(f"Secondary server did not become ready at {base_url}; see {log_file}")

    time.sleep(1)
    return process


def _stop_server(process: subprocess.Popen | None) -> None:
    """Gracefully stop a server process and wait for it to exit."""
    if process is None:
        return
    try:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    except ProcessLookupError:
        pass


@pytest.fixture(scope="module")
def session_expiry_server():
    """Start the secondary ACS server and yield its base URL."""
    process = _start_secondary_server()
    try:
        yield f"http://{SECONDARY_HOST}:{TEST_PORT}"
    finally:
        _stop_server(process)


@pytest.fixture(scope="function")
def admin_session(session_expiry_server: str) -> requests.Session:
    """Return an admin-authenticated session for the secondary server."""
    admin_key = os.environ.get("ACS_ACCOUNT_ADMIN_API_KEY") or _read_token_file(
        "ACS_ACCOUNT_ADMIN_API_KEY.acs"
    )
    if not admin_key:
        pytest.skip("Admin API key not available")

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.headers.update({"Authorization": f"Bearer {admin_key}"})
    yield session
    session.close()


@pytest.fixture(scope="function")
def manager_session(session_expiry_server: str) -> requests.Session | None:
    """Return a manager-authenticated session for the secondary server."""
    manager_key = os.environ.get("ACS_ACCOUNT_MANAGER_API_KEY") or _read_token_file(
        "ACS_ACCOUNT_MANAGER_API_KEY.acs"
    )
    if not manager_key:
        yield None
        return

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.headers.update({"Authorization": f"Bearer {manager_key}"})
    yield session
    session.close()


def _resp_data(response: requests.Response) -> dict:
    """Return the response payload, handling both wrapped and flat JSON shapes."""
    body = response.json()
    if isinstance(body, dict) and "data" in body and "trace_id" in body:
        return body["data"]
    return body


def _create_user_account(
    admin_session: requests.Session, server_url: str, unique_id: str, suffix: str
) -> dict:
    """Create a temporary user account on the secondary server."""
    account_data = {
        "account_name": f"SESS User {suffix} {unique_id}",
        "role": "user",
        "login_name": f"sess_user_{suffix}_{unique_id}",
        "login_password": "SessUser123!",
    }
    response = admin_session.post(f"{server_url}/api/v1/accounts", json=account_data)
    assert response.status_code == 201, f"Failed to create user account: {response.text}"
    return _resp_data(response)


def _create_admin_account(
    admin_session: requests.Session, server_url: str, unique_id: str, suffix: str
) -> dict:
    """Create a temporary admin account on the secondary server."""
    account_data = {
        "account_name": f"SESS Admin {suffix} {unique_id}",
        "role": "admin",
        "login_name": f"sess_admin_{suffix}_{unique_id}",
        "login_password": "SessAdmin123!",
    }
    response = admin_session.post(f"{server_url}/api/v1/accounts", json=account_data)
    assert response.status_code == 201, f"Failed to create admin account: {response.text}"
    return _resp_data(response)


def _api_key_client(
    admin_session: requests.Session, server_url: str, account_id: str
) -> tuple[requests.Session, str]:
    """Create an API key for an account and return a session using it."""
    key_data = {"api_key_name": "sess-test-key", "role": "user"}
    response = admin_session.post(
        f"{server_url}/api/v1/accounts/{account_id}/api-keys", json=key_data
    )
    assert response.status_code == 201, f"Failed to create API key: {response.text}"
    token = _resp_data(response)["token"]

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session, token


def _session_client(session_key: str) -> requests.Session:
    """Return a requests session authenticated only by a session key."""
    session = requests.Session()
    session.headers.update({"X-Session-Key": session_key})
    return session


def _create_session(
    client: requests.Session, server_url: str, account_id: str
) -> dict:
    """Create a login session and return its payload."""
    response = client.post(f"{server_url}/api/v1/accounts/{account_id}/session")
    assert response.status_code == 200, f"Failed to create session: {response.text}"
    return _resp_data(response)


class TestSessionExpiry:
    """Tests for session key expiration behavior."""

    def test_session_valid_before_expiry(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-001: A freshly created session key is valid."""
        account = _create_user_account(admin_session, session_expiry_server, unique_id, "before_expiry")
        try:
            session = _create_session(admin_session, session_expiry_server, account["account_id"])
            client = _session_client(session["session_key"])
            response = client.get(f"{session_expiry_server}/api/v1/accounts/me")
            assert response.status_code == 200
            assert _resp_data(response)["account_id"] == account["account_id"]
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")

    def test_session_expires_after_configured_duration(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-002: A session key becomes invalid after expiry."""
        account = _create_user_account(admin_session, session_expiry_server, unique_id, "after_expiry")
        try:
            session = _create_session(admin_session, session_expiry_server, account["account_id"])
            client = _session_client(session["session_key"])

            # Verify the session works immediately.
            response = client.get(f"{session_expiry_server}/api/v1/accounts/me")
            assert response.status_code == 200

            # Wait longer than the 2-second expiry configured on the server.
            time.sleep(3)

            response = client.get(f"{session_expiry_server}/api/v1/accounts/me")
            assert response.status_code == 401, (
                f"Expected 401 after expiry, got {response.status_code}: {response.text}"
            )
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")

    def test_expired_session_rejected_by_protected_endpoints(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-003: Expired session keys are rejected by protected endpoints."""
        account = _create_user_account(admin_session, session_expiry_server, unique_id, "expired")
        try:
            session = _create_session(admin_session, session_expiry_server, account["account_id"])
            client = _session_client(session["session_key"])

            time.sleep(3)

            # Try several protected endpoints; all should reject the expired key.
            for path in [
                "/api/v1/accounts/me",
                "/api/v1/groups",
                "/api/v1/accounts",
            ]:
                response = client.get(f"{session_expiry_server}{path}")
                assert response.status_code == 401, (
                    f"Expected 401 for {path}, got {response.status_code}: {response.text}"
                )
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")

    def test_expires_at_ms_reflects_configured_expiry(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-004: expires_at_ms is approximately now + configured expiry."""
        account = _create_user_account(admin_session, session_expiry_server, unique_id, "expiry_ms")
        try:
            before_ms = int(time.time() * 1000)
            session = _create_session(admin_session, session_expiry_server, account["account_id"])
            after_ms = int(time.time() * 1000)

            expected_ms = before_ms + 2000
            assert session["expires_at_ms"] >= expected_ms - 500, (
                f"expires_at_ms {session['expires_at_ms']} is too early (expected ~{expected_ms})"
            )
            assert session["expires_at_ms"] <= after_ms + 2000 + 500, (
                f"expires_at_ms {session['expires_at_ms']} is too late"
            )
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")


class TestSessionReplacement:
    """Tests for session key replacement semantics."""

    def test_new_session_invalidates_previous_session(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-005: Creating a new session invalidates the previous one."""
        account = _create_user_account(admin_session, session_expiry_server, unique_id, "replace")
        try:
            session_a = _create_session(admin_session, session_expiry_server, account["account_id"])
            client_a = _session_client(session_a["session_key"])

            # Create a second session for the same account.
            session_b = _create_session(admin_session, session_expiry_server, account["account_id"])
            client_b = _session_client(session_b["session_key"])

            response = client_b.get(f"{session_expiry_server}/api/v1/accounts/me")
            assert response.status_code == 200

            response = client_a.get(f"{session_expiry_server}/api/v1/accounts/me")
            assert response.status_code == 401, (
                f"Expected previous session to be invalidated, got {response.status_code}: {response.text}"
            )
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")

    def test_login_creates_new_session_and_invalidates_old(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-006: Password login creates a new session and invalidates the old one."""
        account = _create_user_account(admin_session, session_expiry_server, unique_id, "login_replace")
        try:
            session_a = _create_session(admin_session, session_expiry_server, account["account_id"])
            client_a = _session_client(session_a["session_key"])

            login_client = requests.Session()
            login_client.headers.update({"Content-Type": "application/json"})
            response = login_client.post(
                f"{session_expiry_server}/api/v1/accounts/login",
                json={
                    "login_name": account["login_name"],
                    "login_password": "SessUser123!",
                },
            )
            assert response.status_code == 200
            session_b = _resp_data(response)
            assert session_b["account_id"] == account["account_id"]
            assert "session_key" in session_b
            assert "expires_at_ms" in session_b

            client_b = _session_client(session_b["session_key"])
            response = client_b.get(f"{session_expiry_server}/api/v1/accounts/me")
            assert response.status_code == 200

            response = client_a.get(f"{session_expiry_server}/api/v1/accounts/me")
            assert response.status_code == 401, (
                f"Expected old session invalidated after login, got {response.status_code}: {response.text}"
            )
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")


class TestSessionCreationRBAC:
    """Tests for role-based restrictions on session creation."""

    def test_manager_can_create_session_for_user(
        self,
        session_expiry_server: str,
        admin_session: requests.Session,
        manager_session: requests.Session | None,
        unique_id: str,
    ):
        """INT-SESS-007: Manager can create a session for a user account."""
        if manager_session is None:
            pytest.skip("Manager token not available")

        account = _create_user_account(admin_session, session_expiry_server, unique_id, "mgr_user")
        try:
            response = manager_session.post(
                f"{session_expiry_server}/api/v1/accounts/{account['account_id']}/session"
            )
            assert response.status_code == 200
            data = _resp_data(response)
            assert "session_key" in data
            assert "expires_at_ms" in data
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")

    def test_manager_cannot_create_session_for_admin(
        self,
        session_expiry_server: str,
        admin_session: requests.Session,
        manager_session: requests.Session | None,
        unique_id: str,
    ):
        """INT-SESS-008: Manager cannot create a session for an admin account."""
        if manager_session is None:
            pytest.skip("Manager token not available")

        account = _create_admin_account(admin_session, session_expiry_server, unique_id, "mgr_admin")
        try:
            response = manager_session.post(
                f"{session_expiry_server}/api/v1/accounts/{account['account_id']}/session"
            )
            assert response.status_code == 403
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")

    def test_user_can_create_own_session(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-009: User can create a session for their own account."""
        account = _create_user_account(admin_session, session_expiry_server, unique_id, "own_session")
        user_client, _ = _api_key_client(admin_session, session_expiry_server, account["account_id"])
        try:
            response = user_client.post(
                f"{session_expiry_server}/api/v1/accounts/{account['account_id']}/session"
            )
            assert response.status_code == 200
            data = _resp_data(response)
            assert "session_key" in data
        finally:
            user_client.close()
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")

    def test_user_cannot_create_session_for_other_account(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-010: User cannot create a session for another account."""
        account_a = _create_user_account(admin_session, session_expiry_server, unique_id, "other_a")
        account_b = _create_user_account(admin_session, session_expiry_server, unique_id, "other_b")
        user_client_a, _ = _api_key_client(
            admin_session, session_expiry_server, account_a["account_id"]
        )
        try:
            response = user_client_a.post(
                f"{session_expiry_server}/api/v1/accounts/{account_b['account_id']}/session"
            )
            assert response.status_code == 403
        finally:
            user_client_a.close()
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account_a['account_id']}")
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account_b['account_id']}")


class TestSessionPasswordInvalidation:
    """Tests for session invalidation on password change."""

    def test_password_change_invalidates_session(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-011: Changing the password invalidates the current session."""
        account = _create_user_account(admin_session, session_expiry_server, unique_id, "pwd_change")
        try:
            session = _create_session(admin_session, session_expiry_server, account["account_id"])
            client = _session_client(session["session_key"])

            response = client.get(f"{session_expiry_server}/api/v1/accounts/me")
            assert response.status_code == 200

            response = admin_session.post(
                f"{session_expiry_server}/api/v1/accounts/{account['account_id']}/password",
                json={"new_password": "NewSessPass123!"},
            )
            assert response.status_code == 200

            response = client.get(f"{session_expiry_server}/api/v1/accounts/me")
            assert response.status_code == 401, (
                f"Expected session invalidated after password change, got {response.status_code}: {response.text}"
            )
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")

    def test_login_with_new_password_after_change_succeeds(
        self, session_expiry_server: str, admin_session: requests.Session, unique_id: str
    ):
        """INT-SESS-012: Login with the new password succeeds after a password change."""
        account = _create_user_account(admin_session, session_expiry_server, unique_id, "pwd_login")
        try:
            new_password = "NewSessPass123!"
            response = admin_session.post(
                f"{session_expiry_server}/api/v1/accounts/{account['account_id']}/password",
                json={"new_password": new_password},
            )
            assert response.status_code == 200

            login_client = requests.Session()
            login_client.headers.update({"Content-Type": "application/json"})
            response = login_client.post(
                f"{session_expiry_server}/api/v1/accounts/login",
                json={
                    "login_name": account["login_name"],
                    "login_password": new_password,
                },
            )
            assert response.status_code == 200
            data = _resp_data(response)
            assert data["account_id"] == account["account_id"]
            assert "session_key" in data
        finally:
            admin_session.delete(f"{session_expiry_server}/api/v1/accounts/{account['account_id']}")
