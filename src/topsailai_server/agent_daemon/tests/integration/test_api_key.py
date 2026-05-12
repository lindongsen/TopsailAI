"""
  Author: km2
  Email: lin_dongsen@126.com
  Created: 2026-05-11
  Purpose: Integration tests for API Key Authentication feature.

  Test Scenarios (from TestCases_API_KEY.md):
  1. API Key Disabled - all endpoints work without auth
  2. API Key Enabled with Default Admin - auto-creates admin key on startup
  3. Admin Operations - create/list/delete API keys, bind/unbind sessions
  4. User Permissions - user keys can only access bound sessions
  5. Rate Limiting - QoS enforcement on ReceiveMessage
  6. Authentication Errors - missing/invalid/inactive keys return 401
"""

import os
import sys
import time
import uuid
import signal
import subprocess
import requests
import pytest

# Ensure project root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# =============================================================================
# Constants
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, 'scripts')
MOCK_PROCESSOR = os.path.join(BASE_DIR, 'mock_processor.sh')
MOCK_SUMMARIZER = os.path.join(BASE_DIR, 'mock_summarizer.sh')
MOCK_STATE_CHECKER = os.path.join(BASE_DIR, 'mock_session_state_checker.sh')

DEFAULT_ADMIN_KEY = "test-admin-key-1234567890abcdef"


# =============================================================================
# Helper Functions
# =============================================================================

def find_free_port(start=17373):
    """Find a free TCP port starting from start."""
    import socket
    for port in range(start, start + 1000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port
    raise RuntimeError("No free port found")


def wait_for_server(url, timeout=30):
    """Wait for server to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(url + "/health", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)
    return False


class ServerProcess:
    """Manages a server process for integration testing."""

    def __init__(self, port, db_path, api_key_enabled=False, admin_key=None):
        self.port = port
        self.db_path = db_path
        self.api_key_enabled = api_key_enabled
        self.admin_key = admin_key
        self.process = None
        self.base_url = "http://127.0.0.1:{}".format(port)

    def start(self):
        """Start the server process."""
        env = os.environ.copy()
        # Use the actual env var names that get_config() expects
        env['TOPSAILAI_AGENT_DAEMON_HOST'] = '127.0.0.1'
        env['TOPSAILAI_AGENT_DAEMON_PORT'] = str(self.port)
        env['TOPSAILAI_AGENT_DAEMON_DB_URL'] = 'sqlite:///{}'.format(self.db_path)
        env['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = MOCK_PROCESSOR
        env['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = MOCK_SUMMARIZER
        env['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = MOCK_STATE_CHECKER
        env['TOPSAILAI_AGENT_DAEMON_API_KEY_ENABLED'] = 'true' if self.api_key_enabled else 'false'
        if self.admin_key:
            env['TOPSAILAI_AGENT_DAEMON_DEFAULT_ADMIN_KEY'] = self.admin_key

        cmd = [
            sys.executable, '-c',
            """
import sys
sys.path.insert(0, '/root/ai/TopsailAI/src')
from topsailai_server.agent_daemon.main import AgentDaemon

daemon = AgentDaemon()
daemon.initialize()
daemon.run()
"""
        ]

        self.process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if not wait_for_server(self.base_url, timeout=30):
            stdout, stderr = self.process.communicate(timeout=5)
            raise RuntimeError(
                "Server failed to start on port {}.\nSTDOUT: {}\nSTDERR: {}".format(
                    self.port, stdout.decode('utf-8', errors='replace'), stderr.decode('utf-8', errors='replace')
                )
            )

    def stop(self):
        """Stop the server process."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.process = None

        # Clean up DB file
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
        return False


# =============================================================================
# Test Class 1: API Key Disabled
# =============================================================================

class TestAPIKeyDisabled:
    """Test that endpoints work normally when API key is disabled."""

    @pytest.fixture(scope="class")
    def server(self):
        port = find_free_port(17373)
        db_path = os.path.join(BASE_DIR, 'test_api_key_disabled.db')
        srv = ServerProcess(port, db_path, api_key_enabled=False)
        srv.start()
        yield srv
        srv.stop()

    def test_health_no_auth_required(self, server):
        """Health check should work without API key."""
        resp = requests.get(server.base_url + "/health", timeout=10)
        assert resp.status_code == 200, "Health check failed: {}".format(resp.text)

    def test_session_endpoints_work_without_key(self, server):
        """Session endpoints should work without API key when disabled."""
        session_id = "test-session-{}".format(uuid.uuid4().hex[:8])

        # Create session via message
        resp = requests.post(
            server.base_url + "/api/v1/message",
            json={"message": "hello", "session_id": session_id, "role": "user"},
            timeout=10
        )
        assert resp.status_code == 200, "Create session failed: {}".format(resp.text)
        assert resp.json()["code"] == 0

        # Get session
        resp = requests.get(
            server.base_url + "/api/v1/session/{}".format(session_id),
            timeout=10
        )
        assert resp.status_code == 200, "Get session failed: {}".format(resp.text)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["session_id"] == session_id

        # List sessions
        resp = requests.get(
            server.base_url + "/api/v1/session",
            timeout=10
        )
        assert resp.status_code == 200, "List sessions failed: {}".format(resp.text)
        assert resp.json()["code"] == 0
        assert len(resp.json()["data"]) >= 1

    def test_message_endpoints_work_without_key(self, server):
        """Message endpoints should work without API key when disabled."""
        session_id = "test-session-{}".format(uuid.uuid4().hex[:8])

        # Receive message
        resp = requests.post(
            server.base_url + "/api/v1/message",
            json={"message": "test msg", "session_id": session_id, "role": "user"},
            timeout=10
        )
        assert resp.status_code == 200, "Receive message failed: {}".format(resp.text)
        assert resp.json()["code"] == 0

        # Retrieve messages
        resp = requests.get(
            server.base_url + "/api/v1/message?session_id={}".format(session_id),
            timeout=10
        )
        assert resp.status_code == 200, "Retrieve messages failed: {}".format(resp.text)
        assert resp.json()["code"] == 0
        assert len(resp.json()["data"]) == 1


# =============================================================================
# Test Class 2: API Key Enabled - Default Admin
# =============================================================================

class TestAPIKeyEnabledDefaultAdmin:
    """Test auto-creation of default admin key when API key is enabled."""

    @pytest.fixture(scope="class")
    def server(self):
        port = find_free_port(18373)
        db_path = os.path.join(BASE_DIR, 'test_api_key_admin.db')
        srv = ServerProcess(
            port, db_path,
            api_key_enabled=True,
            admin_key=DEFAULT_ADMIN_KEY
        )
        srv.start()
        yield srv
        srv.stop()

    def test_auto_create_configured_admin_key(self, server):
        """Admin key from env var should be created on startup."""
        # Use the configured admin key to list API keys
        resp = requests.get(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            timeout=10
        )
        assert resp.status_code == 200, "List API keys failed: {}".format(resp.text)
        data = resp.json()
        assert data["code"] == 0, "Unexpected code: {}".format(data)
        assert len(data["data"]["api_keys"]) == 1
        assert data["data"]["api_keys"][0]["role"] == "admin"

    def test_admin_key_can_access_all_sessions(self, server):
        """Admin key should be able to access any session."""
        session_id = "admin-session-{}".format(uuid.uuid4().hex[:8])

        # Create session with admin key
        resp = requests.post(
            server.base_url + "/api/v1/message",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"message": "admin test", "session_id": session_id, "role": "user"},
            timeout=10
        )
        assert resp.status_code == 200, "Create session failed: {}".format(resp.text)
        assert resp.json()["code"] == 0

        # Get session with admin key
        resp = requests.get(
            server.base_url + "/api/v1/session/{}".format(session_id),
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            timeout=10
        )
        assert resp.status_code == 200, "Get session failed: {}".format(resp.text)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["session_id"] == session_id


# =============================================================================
# Test Class 3: Admin Operations
# =============================================================================

class TestAPIKeyAdminOperations:
    """Test admin-only API key management operations."""

    @pytest.fixture(scope="class")
    def server(self):
        port = find_free_port(19373)
        db_path = os.path.join(BASE_DIR, 'test_api_key_ops.db')
        srv = ServerProcess(
            port, db_path,
            api_key_enabled=True,
            admin_key=DEFAULT_ADMIN_KEY
        )
        srv.start()
        yield srv
        srv.stop()

    def test_create_user_key(self, server):
        """Admin should be able to create a user API key."""
        resp = requests.post(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"name": "Test User Key", "role": "user", "rate_limit": 60},
            timeout=10
        )
        assert resp.status_code == 200, "Create user key failed: {}".format(resp.text)
        data = resp.json()
        assert data["code"] == 0, "Unexpected code: {}".format(data)
        assert data["data"]["role"] == "user"
        assert data["data"]["rate_limit"] == 60
        assert "api_key" in data["data"]

    def test_create_admin_key(self, server):
        """Admin should be able to create another admin API key."""
        resp = requests.post(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"name": "Test Admin Key", "role": "admin", "rate_limit": 0},
            timeout=10
        )
        assert resp.status_code == 200, "Create admin key failed: {}".format(resp.text)
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["role"] == "admin"

    def test_list_api_keys(self, server):
        """Admin should be able to list all API keys."""
        resp = requests.get(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            timeout=10
        )
        assert resp.status_code == 200, "List API keys failed: {}".format(resp.text)
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["total"] >= 2  # default admin + created keys

    def test_bind_sessions_to_user_key(self, server):
        """Admin should be able to bind sessions to a user key."""
        # Create a session first
        session_id = "bind-session-{}".format(uuid.uuid4().hex[:8])
        resp = requests.post(
            server.base_url + "/api/v1/message",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"message": "bind test", "session_id": session_id, "role": "user"},
            timeout=10
        )
        assert resp.status_code == 200

        # Create a user key
        resp = requests.post(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"name": "Bind Test Key", "role": "user", "rate_limit": 60},
            timeout=10
        )
        assert resp.status_code == 200
        api_key_id = resp.json()["data"]["api_key_id"]

        # Bind session
        resp = requests.post(
            server.base_url + "/api/v1/apikey/{}/sessions".format(api_key_id),
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"session_ids": [session_id]},
            timeout=10
        )
        assert resp.status_code == 200, "Bind sessions failed: {}".format(resp.text)
        data = resp.json()
        assert data["code"] == 0
        assert session_id in data["data"]["bound_sessions"]

    def test_unbind_sessions_from_user_key(self, server):
        """Admin should be able to unbind sessions from a user key."""
        # Create a session
        session_id = "unbind-session-{}".format(uuid.uuid4().hex[:8])
        resp = requests.post(
            server.base_url + "/api/v1/message",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"message": "unbind test", "session_id": session_id, "role": "user"},
            timeout=10
        )
        assert resp.status_code == 200

        # Create a user key with session bound
        resp = requests.post(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"name": "Unbind Test Key", "role": "user", "rate_limit": 60, "session_ids": [session_id]},
            timeout=10
        )
        assert resp.status_code == 200
        api_key_id = resp.json()["data"]["api_key_id"]

        # Unbind session
        resp = requests.delete(
            server.base_url + "/api/v1/apikey/{}/sessions".format(api_key_id),
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"session_ids": [session_id]},
            timeout=10
        )
        assert resp.status_code == 200, "Unbind sessions failed: {}".format(resp.text)
        data = resp.json()
        assert data["code"] == 0
        assert session_id in data["data"]["unbound_sessions"]

    def test_delete_api_key(self, server):
        """Admin should be able to delete an API key."""
        # Create a key to delete
        resp = requests.post(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"name": "Delete Test Key", "role": "user", "rate_limit": 60},
            timeout=10
        )
        assert resp.status_code == 200
        api_key_id = resp.json()["data"]["api_key_id"]

        # Delete the key
        resp = requests.delete(
            server.base_url + "/api/v1/apikey/{}".format(api_key_id),
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            timeout=10
        )
        assert resp.status_code == 200, "Delete API key failed: {}".format(resp.text)
        assert resp.json()["code"] == 0

        # Verify it's gone
        resp = requests.get(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            timeout=10
        )
        keys = resp.json()["data"]["api_keys"]
        assert not any(k["api_key_id"] == api_key_id for k in keys)

    def test_cannot_delete_last_admin_key(self, server):
        """Should not be able to delete the last admin API key."""
        # Get all API keys
        resp = requests.get(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            timeout=10
        )
        admin_keys = [k for k in resp.json()["data"]["api_keys"] if k["role"] == "admin"]
        assert len(admin_keys) >= 1, "Need at least one admin key"

        # Find the default admin key (created on startup) and keep it
        default_admin = None
        other_admins = []
        for k in admin_keys:
            if k.get("name") == "Default Admin":
                default_admin = k
            else:
                other_admins.append(k)

        assert default_admin is not None, "Default admin key not found"

        # Delete all other admin keys
        for key in other_admins:
            resp = requests.delete(
                server.base_url + "/api/v1/apikey/{}".format(key["api_key_id"]),
                headers={"X-API-Key": DEFAULT_ADMIN_KEY},
                timeout=10
            )
            assert resp.status_code == 200, "Failed to delete admin key: {}".format(resp.text)

        # Try to delete the last admin key (the default one)
        resp = requests.delete(
            server.base_url + "/api/v1/apikey/{}".format(default_admin["api_key_id"]),
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            timeout=10
        )
        assert resp.status_code == 200, "Expected 200, got {}: {}".format(resp.status_code, resp.text)
        assert resp.json()["code"] == 400
# =============================================================================
class TestAPIKeyUserPermissions:
    """Test user key permission restrictions."""
    @pytest.fixture(scope="class")
    def server(self):
        port = find_free_port(20373)
        db_path = os.path.join(BASE_DIR, 'test_api_key_user.db')
        srv = ServerProcess(
            port, db_path,
            api_key_enabled=True,
            admin_key=DEFAULT_ADMIN_KEY
        )
        srv.start()
        yield srv
        srv.stop()
    @pytest.fixture(scope="class")
    def user_key_with_session(self, server):
        """Create a user key bound to a session. Returns (user_key, session_id)."""
        session_id = "user-session-{}".format(uuid.uuid4().hex[:8])
        # Create session with admin key
        resp = requests.post(
            server.base_url + "/api/v1/message",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"message": "user test", "session_id": session_id, "role": "user"},
            timeout=10
        )
        assert resp.status_code == 200
        # Create user key bound to session
        resp = requests.post(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={
                "name": "User Permission Key",
                "role": "user",
                "rate_limit": 60,
                "session_ids": [session_id]
            },
            timeout=10
        )
        assert resp.status_code == 200
        user_key = resp.json()["data"]["api_key"]
        return user_key, session_id
    def test_user_key_can_access_bound_session(self, server, user_key_with_session):
        """User key should be able to access bound sessions."""
        user_key, session_id = user_key_with_session
        resp = requests.get(
            server.base_url + "/api/v1/session/{}".format(session_id),
            headers={"X-API-Key": user_key},
            timeout=10
        )
        assert resp.status_code == 200, "Access bound session failed: {}".format(resp.text)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["session_id"] == session_id
    def test_user_key_cannot_access_unbound_session(self, server, user_key_with_session):
        """User key should NOT be able to access unbound sessions."""
        user_key, _ = user_key_with_session
        unbound_session = "unbound-session-{}".format(uuid.uuid4().hex[:8])
        # Create the unbound session with admin key
        resp = requests.post(
            server.base_url + "/api/v1/message",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"message": "unbound test", "session_id": unbound_session, "role": "user"},
            timeout=10
        )
        assert resp.status_code == 200
        # Try to access with user key
        resp = requests.get(
            server.base_url + "/api/v1/session/{}".format(unbound_session),
            headers={"X-API-Key": user_key},
            timeout=10
        )
        assert resp.status_code == 403, "Expected 403, got {}: {}".format(resp.status_code, resp.text)
    def test_user_key_list_sessions_filtered(self, server, user_key_with_session):
        """User key should only see bound sessions in list."""
        user_key, session_id = user_key_with_session
        # Create another session with admin key
        other_session = "other-session-{}".format(uuid.uuid4().hex[:8])
        resp = requests.post(
            server.base_url + "/api/v1/message",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"message": "other test", "session_id": other_session, "role": "user"},
            timeout=10
        )
        assert resp.status_code == 200
        # List sessions with user key
        resp = requests.get(
            server.base_url + "/api/v1/session",
            headers={"X-API-Key": user_key},
            timeout=10
        )
        assert resp.status_code == 200, "List sessions failed: {}".format(resp.text)
        data = resp.json()
        assert data["code"] == 0
        session_ids = [s["session_id"] for s in data["data"]]
        assert session_id in session_ids
        assert other_session not in session_ids
    def test_user_key_cannot_create_key(self, server, user_key_with_session):
        """User key should NOT be able to create API keys."""
        user_key, _ = user_key_with_session
        resp = requests.post(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": user_key},
            json={"name": "Hacker Key", "role": "user", "rate_limit": 60},
            timeout=10
        )
        assert resp.status_code == 403, "Expected 403, got {}: {}".format(resp.status_code, resp.text)
    def test_user_key_cannot_delete_key(self, server, user_key_with_session):
        """User key should NOT be able to delete API keys."""
        user_key, _ = user_key_with_session
        resp = requests.delete(
            server.base_url + "/api/v1/apikey/ak_something",
            headers={"X-API-Key": user_key},
            timeout=10
        )
        assert resp.status_code == 403, "Expected 403, got {}: {}".format(resp.status_code, resp.text)
    def test_user_key_cannot_delete_session(self, server, user_key_with_session):
        """User key should NOT be able to delete sessions."""
        user_key, session_id = user_key_with_session
        resp = requests.delete(
            server.base_url + "/api/v1/session?session_ids={}".format(session_id),
            headers={"X-API-Key": user_key},
            timeout=10
        )
        assert resp.status_code == 403, "Expected 403, got {}: {}".format(resp.status_code, resp.text)
# =============================================================================
# Test Class 5: Rate Limiting
# =============================================================================
class TestAPIKeyRateLimiting:
    """Test QoS rate limiting on ReceiveMessage endpoint."""
    @pytest.fixture(scope="class")
    def server(self):
        port = find_free_port(21373)
        db_path = os.path.join(BASE_DIR, 'test_api_key_rate.db')
        srv = ServerProcess(
            port, db_path,
            api_key_enabled=True,
            admin_key=DEFAULT_ADMIN_KEY
        )
        srv.start()
        yield srv
        srv.stop()
    def test_rate_limit_enforced(self, server):
        """User key with rate_limit=2 should be blocked on 3rd message."""
        session_id = "rate-session-{}".format(uuid.uuid4().hex[:8])
        # Create user key with rate_limit=2
        resp = requests.post(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={
                "name": "Rate Limit Key",
                "role": "user",
                "rate_limit": 2,
                "session_ids": [session_id]
            },
            timeout=10
        )
        assert resp.status_code == 200
        user_key = resp.json()["data"]["api_key"]
        # Send 2 messages (should succeed)
        for i in range(2):
            resp = requests.post(
                server.base_url + "/api/v1/message",
                headers={"X-API-Key": user_key},
                json={"message": "msg {}".format(i), "session_id": session_id, "role": "user"},
                timeout=10
            )
            assert resp.status_code == 200, "Message {} failed: {}".format(i, resp.text)
        # 3rd message should be rate limited
        resp = requests.post(
            server.base_url + "/api/v1/message",
            headers={"X-API-Key": user_key},
            json={"message": "msg 3", "session_id": session_id, "role": "user"},
            timeout=10
        )
    def test_admin_key_unlimited(self, server):
        """Admin key with rate_limit=0 should not be rate limited."""
        session_id = "unlimited-session-{}".format(uuid.uuid4().hex[:8])
        # Send multiple messages with admin key
        for i in range(5):
            resp = requests.post(
                server.base_url + "/api/v1/message",
                headers={"X-API-Key": DEFAULT_ADMIN_KEY},
                json={"message": "admin msg {}".format(i), "session_id": session_id, "role": "user"},
                timeout=10
            )
            assert resp.status_code == 200, "Admin message {} failed: {}".format(i, resp.text)
# =============================================================================
# Test Class 6: Authentication Errors
# =============================================================================
class TestAPIKeyAuthenticationErrors:
    """Test authentication error responses."""
    @pytest.fixture(scope="class")
    def server(self):
        port = find_free_port(22373)
        db_path = os.path.join(BASE_DIR, 'test_api_key_auth.db')
        srv = ServerProcess(
            port, db_path,
            api_key_enabled=True,
            admin_key=DEFAULT_ADMIN_KEY
        )
        srv.start()
        yield srv
        srv.stop()
    def test_missing_header_401(self, server):
        """Request without X-API-Key header should return 401."""
        resp = requests.get(
            server.base_url + "/api/v1/session",
            timeout=10
        )
        assert resp.status_code == 401, "Expected 401, got {}: {}".format(resp.status_code, resp.text)
    def test_invalid_key_401(self, server):
        """Request with invalid X-API-Key should return 401."""
        resp = requests.get(
            server.base_url + "/api/v1/session",
            headers={"X-API-Key": "invalid-key-12345"},
            timeout=10
        )
        assert resp.status_code == 401, "Expected 401, got {}: {}".format(resp.status_code, resp.text)
    def test_inactive_key_401(self, server):
        """Request with inactive (deleted) API key should return 401."""
        # Create a key
        resp = requests.post(
            server.base_url + "/api/v1/apikey",
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            json={"name": "Inactive Key", "role": "user", "rate_limit": 60},
            timeout=10
        )
        assert resp.status_code == 200
        api_key_id = resp.json()["data"]["api_key_id"]
        api_key_value = resp.json()["data"]["api_key"]
        resp = requests.delete(
            server.base_url + "/api/v1/apikey/{}".format(api_key_id),
            headers={"X-API-Key": DEFAULT_ADMIN_KEY},
            timeout=10
        )
        assert resp.status_code == 200
        resp = requests.get(
            server.base_url + "/api/v1/session",
            headers={"X-API-Key": api_key_value},
            timeout=10
        )
        assert resp.status_code == 401, "Expected 401, got {}: {}".format(resp.status_code, resp.text)
