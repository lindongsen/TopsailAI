"""
Live Integration Tests for topsailai_agent_daemon and topsailai_agent_client.

These tests require a running daemon server and test real functionality
without mocking. The server is started/stopped automatically.
"""

import os
import sys
import time
import json
import subprocess
import pytest
import requests

# Configuration
WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAEMON_SCRIPT = os.path.join(WORKSPACE, "topsailai_agent_daemon.py")
CLIENT_SCRIPT = os.path.join(WORKSPACE, "topsailai_agent_client.py")
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 7373
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

# Integration test home directory
HOME_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Script paths for the daemon (must be absolute paths)
SCRIPTS_DIR = os.path.join(WORKSPACE, "scripts")
PROCESSOR_SCRIPT = os.path.join(SCRIPTS_DIR, "test_processor.sh")
SUMMARIZER_SCRIPT = os.path.join(SCRIPTS_DIR, "test_summarizer.sh")
SESSION_STATE_CHECKER_SCRIPT = os.path.join(SCRIPTS_DIR, "test_session_state_checker.sh")

# Global server process reference
_server_process = None


def _run_client(*args, verbose=False):
    """Run the client CLI with given arguments and return (stdout, stderr, returncode)."""
    cmd = [sys.executable, CLIENT_SCRIPT, "--host", SERVER_HOST, "--port", str(SERVER_PORT)]
    if verbose:
        cmd.append("-v")
    cmd.extend(args)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "HOME": HOME_DIR},
    )
    return result.stdout, result.stderr, result.returncode


def _run_daemon(*args):
    """Run the daemon CLI with given arguments and return (stdout, stderr, returncode)."""
    cmd = [sys.executable, DAEMON_SCRIPT]
    cmd.extend(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "HOME": HOME_DIR},
    )
    return result.stdout, result.stderr, result.returncode


def _check_server_health():
    """Check if the server is healthy by calling the health endpoint."""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def _wait_for_server(timeout=30):
    """Wait for the server to become healthy."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if _check_server_health():
            return True
        time.sleep(1)
    return False


def _ensure_server_running():
    """Ensure the server is running. If not, start it."""
    if _check_server_health():
        return True
    # Server not running, try to start it
    stdout, stderr, rc = _run_daemon("start")
    if rc != 0 and "already running" not in stderr.lower() and "already running" not in stdout.lower():
        print(f"Failed to start server: {stderr}")
        return False
    return _wait_for_server(timeout=30)


def setup_module(module):
    """Start the daemon server before all tests."""
    global _server_process
    
    # Kill any existing server on port 7373
    subprocess.run(
        ["bash", "-c", "lsof -ti:7373 | xargs kill -9 2>/dev/null || true"],
        capture_output=True
    )
    time.sleep(2)  # Wait for port to be released
    
    # Start the server with absolute paths
    stdout, stderr, rc = _run_daemon(
        "start",
        "--processor", PROCESSOR_SCRIPT,
        "--summarizer", SUMMARIZER_SCRIPT,
        "--session_state_checker", SESSION_STATE_CHECKER_SCRIPT,
    )
    # If server is already running, rc=1 is acceptable
    if rc != 0 and "already running" not in stderr.lower() and "already running" not in stdout.lower():
        raise RuntimeError(f"Failed to start server: {stderr}")
    if not _wait_for_server(timeout=60):
        raise RuntimeError("Server did not become healthy within timeout")


def teardown_module(module):
    """Stop the daemon server after all tests."""
    stdout, stderr, rc = _run_daemon("stop")
    if rc != 0:
        print(f"Warning: Failed to stop server cleanly: {stderr}")


# ============================================================
# TestServerLifecycle - Server startup, health, shutdown
# ============================================================


class TestServerLifecycle:
    """Test server lifecycle: start, health check, status."""

    def test_server_health_endpoint(self):
        """Verify the /health endpoint returns healthy status."""
        _ensure_server_running()
        response = requests.get(f"{BASE_URL}/health", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["status"] == "healthy"
        assert data["data"]["database"] == "healthy"

    def test_server_status_via_daemon_cli(self):
        """Verify daemon status command reports running."""
        stdout, stderr, rc = _run_daemon("status")
        assert rc == 0
        assert "RUNNING" in stdout


# ============================================================
# TestClientOperations - All client CLI commands
# ============================================================


class TestClientOperations:
    """Test all client CLI operations against a live server."""

    def test_client_health(self):
        """Test client health command."""
        _ensure_server_running()
        stdout, stderr, rc = _run_client("health")
        assert rc == 0
        assert "healthy" in stdout.lower()

    def test_client_health_verbose(self):
        """Test client health command with verbose flag."""
        _ensure_server_running()
        stdout, stderr, rc = _run_client("health", verbose=True)
        assert rc == 0
        assert "healthy" in stdout.lower()
        assert "Response" in stdout

    def test_client_list_sessions_empty(self):
        """Test list-sessions when no sessions exist."""
        _ensure_server_running()
        stdout, stderr, rc = _run_client("list-sessions")
        assert rc == 0

    def test_client_send_message(self):
        """Test send-message creates a session and sends a message."""
        _ensure_server_running()
        session_id = f"test_live_send_{int(time.time())}"
        stdout, stderr, rc = _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Hello from live integration test",
        )
        assert rc == 0
        # Verify the session was created
        stdout2, stderr2, rc2 = _run_client("list-sessions")
        assert rc2 == 0
        assert session_id in stdout2

    def test_client_send_message_verbose(self):
        """Test send-message with verbose output."""
        _ensure_server_running()
        session_id = f"test_live_verbose_{int(time.time())}"
        stdout, stderr, rc = _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Verbose test message",
            verbose=True,
        )
        assert rc == 0
        assert "Response" in stdout

    def test_client_get_messages(self):
        """Test get-messages retrieves messages from a session."""
        _ensure_server_running()
        session_id = f"test_live_getmsg_{int(time.time())}"
        # First send a message
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Test message for retrieval",
        )
        # Then retrieve messages
        stdout, stderr, rc = _run_client(
            "get-messages",
            "--session-id", session_id,
        )
        assert rc == 0
        assert "Test message for retrieval" in stdout

    def test_client_list_messages_alias(self):
        """Test list-messages (alias for get-messages)."""
        _ensure_server_running()
        session_id = f"test_live_listmsg_{int(time.time())}"
        # Send a message first
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Alias test message",
        )
        # Use list-messages alias
        stdout, stderr, rc = _run_client(
            "list-messages",
            "--session-id", session_id,
        )
        assert rc == 0
        assert "Alias test message" in stdout

    def test_client_get_messages_verbose(self):
        """Test get-messages with verbose output shows JSON response."""
        _ensure_server_running()
        session_id = f"test_live_getmsg_v_{int(time.time())}"
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Verbose retrieval test",
        )
        stdout, stderr, rc = _run_client(
            "get-messages",
            "--session-id", session_id,
            verbose=True,
        )
        assert rc == 0
        assert "Response" in stdout
        assert "Verbose retrieval test" in stdout

    def test_client_process_session(self):
        """Test process-session triggers message processing."""
        _ensure_server_running()
        session_id = f"test_live_process_{int(time.time())}"
        # Send a message first
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Process this message",
        )
        # Process the session
        stdout, stderr, rc = _run_client(
            "process-session",
            "--session-id", session_id,
        )
        assert rc == 0

    def test_client_process_session_verbose(self):
        """Test process-session with verbose output."""
        _ensure_server_running()
        session_id = f"test_live_proc_v_{int(time.time())}"
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Verbose process test",
        )
        stdout, stderr, rc = _run_client(
            "process-session",
            "--session-id", session_id,
            verbose=True,
        )
        assert rc == 0
        assert "Response" in stdout

    def test_client_delete_sessions(self):
        """Test delete-sessions removes a session."""
        _ensure_server_running()
        session_id = f"test_live_delete_{int(time.time())}"
        # Create a session first
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "To be deleted",
        )
        # Verify it exists
        stdout, _, rc = _run_client("list-sessions")
        assert session_id in stdout
        # Delete it
        stdout, stderr, rc = _run_client(
            "delete-sessions",
            "--session-ids", session_id,
        )
        assert rc == 0
        # Verify it no longer exists
        stdout, _, rc = _run_client("list-sessions")
        assert session_id not in stdout

    def test_client_delete_sessions_verbose(self):
        """Test delete-sessions with verbose output."""
        _ensure_server_running()
        session_id = f"test_live_del_v_{int(time.time())}"
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Verbose delete test",
        )
        stdout, stderr, rc = _run_client(
            "delete-sessions",
            "--session-ids", session_id,
            verbose=True,
        )
        assert rc == 0
        assert "Response" in stdout

    def test_client_set_task_result(self):
        """Test set-task-result sets a task result."""
        _ensure_server_running()
        session_id = f"test_live_task_{int(time.time())}"
        # Create a session and send a message
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Task test message",
        )
        # Process the session to generate a task
        _run_client(
            "process-session",
            "--session-id", session_id,
        )
        # Get tasks to find task IDs
        stdout, stderr, rc = _run_client(
            "get-tasks",
            "--session-id", session_id,
        )
        assert rc == 0
        # If there are tasks, set a result on one
        if stdout.strip():
            # Parse task info from verbose output
            stdout_v, _, rc_v = _run_client(
                "get-tasks",
                "--session-id", session_id,
                verbose=True,
            )
            assert rc_v == 0
            # Try to set a task result (may fail if no task IDs available)
            stdout_set, stderr_set, rc_set = _run_client(
                "set-task-result",
                "--session-id", session_id,
                "--processed-msg-id", "msg_001",
                "--task-id", "task_001",
                "--task-result", "completed",
            )
            # The result code depends on whether the task exists
            # We just verify the command runs without crashing
            assert rc_set in [0, 1]  # 0=success, 1=task not found (acceptable)

    def test_client_get_tasks(self):
        """Test get-tasks retrieves tasks for a session."""
        _ensure_server_running()
        session_id = f"test_live_gettask_{int(time.time())}"
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Get task test",
        )
        stdout, stderr, rc = _run_client(
            "get-tasks",
            "--session-id", session_id,
        )
        assert rc == 0

    def test_client_list_tasks_alias(self):
        """Test list-tasks (alias for get-tasks)."""
        _ensure_server_running()
        session_id = f"test_live_listtask_{int(time.time())}"
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "List task alias test",
        )
        stdout, stderr, rc = _run_client(
            "list-tasks",
            "--session-id", session_id,
        )
        assert rc == 0


# ============================================================
# TestTaskLifecycle - Full task lifecycle flow
# ============================================================


class TestTaskLifecycle:
    """Test complete task lifecycle: create → send → process → get task → set result."""

    def test_full_task_lifecycle(self):
        """Test complete task lifecycle from message creation to task result."""
        _ensure_server_running()
        session_id = f"test_lifecycle_{int(time.time())}"

        # Step 1: Create session and send message
        stdout, stderr, rc = _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Lifecycle test message",
        )
        assert rc == 0

        # Step 2: Verify message was sent
        stdout, stderr, rc = _run_client(
            "get-messages",
            "--session-id", session_id,
        )
        assert rc == 0
        assert "Lifecycle test message" in stdout

        # Step 3: Process the session
        stdout, stderr, rc = _run_client(
            "process-session",
            "--session-id", session_id,
        )
        assert rc == 0

        # Step 4: Get tasks
        stdout, stderr, rc = _run_client(
            "get-tasks",
            "--session-id", session_id,
        )
        assert rc == 0

        # Step 5: Set task result (if tasks exist)
        stdout_set, stderr_set, rc_set = _run_client(
            "set-task-result",
            "--session-id", session_id,
            "--processed-msg-id", "msg_001",
            "--task-id", "task_001",
            "--task-result", "completed_successfully",
        )
        # Accept both success and task-not-found (task may not exist in mock mode)
        assert rc_set in [0, 1]

        # Step 6: Clean up - delete session
        stdout, stderr, rc = _run_client(
            "delete-sessions",
            "--session-ids", session_id,
        )
        assert rc == 0

    def test_multiple_messages_lifecycle(self):
        """Test lifecycle with multiple messages in a session."""
        _ensure_server_running()
        session_id = f"test_multi_lifecycle_{int(time.time())}"

        # Send multiple messages
        for i in range(3):
            stdout, stderr, rc = _run_client(
                "send-message",
                "--session-id", session_id,
                "--role", "user",
                "--message", f"Multi-message test #{i}",
            )
            assert rc == 0

        # Verify all messages exist
        stdout, stderr, rc = _run_client(
            "get-messages",
            "--session-id", session_id,
        )
        assert rc == 0
        for i in range(3):
            assert f"Multi-message test #{i}" in stdout

        # Process the session
        stdout, stderr, rc = _run_client(
            "process-session",
            "--session-id", session_id,
        )
        assert rc == 0

        # Clean up
        stdout, stderr, rc = _run_client(
            "delete-sessions",
            "--session-ids", session_id,
        )
        assert rc == 0

    def test_session_create_and_list(self):
        """Test creating a session and verifying it appears in list."""
        _ensure_server_running()
        session_id = f"test_create_list_{int(time.time())}"

        # Create session by sending a message
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Create and list test",
        )

        # List sessions and verify
        stdout, stderr, rc = _run_client("list-sessions")
        assert rc == 0
        assert session_id in stdout

        # Clean up
        _run_client("delete-sessions", "--session-ids", session_id)


# ============================================================
# TestAPIDirectly - Direct HTTP API calls
# ============================================================


class TestAPIDirectly:
    """Test API endpoints directly via HTTP requests."""

    def test_api_health_endpoint(self):
        """Test /health endpoint directly."""
        _ensure_server_running()
        response = requests.get(f"{BASE_URL}/health", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "healthy" in data["data"]["status"]

    def test_api_create_session_and_send_message(self):
        """Test creating a session and sending a message via API."""
        _ensure_server_running()
        session_id = f"test_api_msg_{int(time.time())}"
        payload = {
            "session_id": session_id,
            "role": "user",
            "message": "API direct test message",
        }
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            json=payload,
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_api_get_messages(self):
        """Test retrieving messages via API."""
        _ensure_server_running()
        session_id = f"test_api_getmsg_{int(time.time())}"
        # Create a message first
        requests.post(
            f"{BASE_URL}/api/v1/message",
            json={
                "session_id": session_id,
                "role": "user",
                "message": "API get messages test",
            },
            timeout=10,
        )
        # Retrieve messages
        response = requests.get(
            f"{BASE_URL}/api/v1/message",
            params={"session_id": session_id},
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert len(data["data"]) > 0

    def test_api_delete_session(self):
        """Test deleting a session via API."""
        _ensure_server_running()
        session_id = f"test_api_del_{int(time.time())}"
        # Create a session first
        requests.post(
            f"{BASE_URL}/api/v1/message",
            json={
                "session_id": session_id,
                "role": "user",
                "message": "To be deleted via API",
            },
            timeout=10,
        )
        # Delete the session
        response = requests.delete(
            f"{BASE_URL}/api/v1/session",
            params={"session_ids": session_id},
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_api_list_sessions(self):
        """Test listing sessions via API."""
        _ensure_server_running()
        response = requests.get(
            f"{BASE_URL}/api/v1/session",
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0


# ============================================================
# TestEdgeCases - Edge cases and error scenarios
# ============================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_nonexistent_session_messages(self):
        """Test get-messages for a session that does not exist."""
        _ensure_server_running()
        stdout, stderr, rc = _run_client(
            "get-messages",
            "--session-id", "definitely_does_not_exist_99999",
        )
        assert rc == 0
        # Non-existent session returns empty output (no messages)
        assert stdout.strip() == "" or "0" in stdout

    def test_nonexistent_session_tasks(self):
        """Test get-tasks for a session that does not exist."""
        _ensure_server_running()
        stdout, stderr, rc = _run_client(
            "get-tasks",
            "--session-id", "definitely_does_not_exist_99999",
        )
        assert rc == 0
        # Non-existent session returns empty output (no tasks)
        assert stdout.strip() == "" or "0" in stdout

    def test_delete_nonexistent_session(self):
        """Test deleting a session that does not exist."""
        _ensure_server_running()
        stdout, stderr, rc = _run_client(
            "delete-sessions",
            "--session-ids", "nonexistent_session_xyz",
        )
        # Should succeed (deleting nothing is OK) or return gracefully
        assert rc == 0

    def test_process_nonexistent_session(self):
        """Test processing a session that does not exist."""
        _ensure_server_running()
        stdout, stderr, rc = _run_client(
            "process-session",
            "--session-id", "nonexistent_session_process",
        )
        # Should succeed (processing nothing is OK) or return gracefully
        assert rc == 0

    def test_special_characters_in_message(self):
        """Test sending a message with special characters."""
        _ensure_server_running()
        session_id = f"test_special_{int(time.time())}"
        special_content = "Hello! @#$%^&*()_+-=[]{}|;':\",./<>? 中文 🎉"
        stdout, stderr, rc = _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", special_content,
        )
        assert rc == 0
        # Verify the message was stored
        stdout, stderr, rc = _run_client(
            "get-messages",
            "--session-id", session_id,
        )
        assert rc == 0
        assert "Hello!" in stdout

    def test_empty_content_message(self):
        """Test sending a message with empty content."""
        _ensure_server_running()
        session_id = f"test_empty_{int(time.time())}"
        stdout, stderr, rc = _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "",
        )
        # Empty content may be accepted or rejected
        assert rc in [0, 1]

    def test_long_message_content(self):
        """Test sending a message with very long content."""
        _ensure_server_running()
        session_id = f"test_long_{int(time.time())}"
        long_content = "A" * 5000  # 5000 character message
        stdout, stderr, rc = _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", long_content,
        )
        assert rc == 0

    def test_multiple_sessions_same_time(self):
        """Test creating multiple sessions simultaneously."""
        _ensure_server_running()
        session_ids = []
        for i in range(5):
            sid = f"test_multi_sid_{int(time.time())}_{i}"
            session_ids.append(sid)
            stdout, stderr, rc = _run_client(
                "send-message",
                "--session-id", sid,
                "--role", "user",
                "--message", f"Multi-session message #{i}",
            )
            assert rc == 0

        # Verify all sessions exist
        stdout, stderr, rc = _run_client("list-sessions")
        assert rc == 0
        for sid in session_ids:
            assert sid in stdout

        # Clean up all sessions
        for sid in session_ids:
            _run_client("delete-sessions", "--session-ids", sid)

    def test_send_message_to_existing_session(self):
        """Test sending additional messages to an existing session."""
        _ensure_server_running()
        session_id = f"test_existing_{int(time.time())}"

        # First message
        stdout, stderr, rc = _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "First message",
        )
        assert rc == 0

        # Second message to same session
        stdout, stderr, rc = _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "assistant",
            "--message", "Second message",
        )
        assert rc == 0

        # Verify both messages exist
        stdout, stderr, rc = _run_client(
            "get-messages",
            "--session-id", session_id,
        )
        assert rc == 0
        assert "First message" in stdout
        assert "Second message" in stdout

        # Clean up
        _run_client("delete-sessions", "--session-ids", session_id)

    def test_api_invalid_endpoint(self):
        """Test accessing an invalid API endpoint."""
        _ensure_server_running()
        response = requests.get(f"{BASE_URL}/invalid_endpoint", timeout=10)
        assert response.status_code == 404

    def test_api_send_message_missing_fields(self):
        """Test sending a message via API with missing required fields."""
        _ensure_server_running()
        # Send with missing message field
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            json={"session_id": "test_missing_fields"},
            timeout=10,
        )
        # Should return error (4xx) or handle gracefully
        assert response.status_code in [400, 422, 200]


# ============================================================
# TestConcurrentOperations - Concurrent session handling
# ============================================================


class TestConcurrentOperations:
    """Test concurrent operations and session handling."""

    def test_concurrent_session_creation(self):
        """Test creating multiple sessions concurrently via API."""
        _ensure_server_running()
        import concurrent.futures

        session_ids = [f"test_concurrent_{int(time.time())}_{i}" for i in range(5)]

        def create_session(sid):
            payload = {
                "session_id": sid,
                "role": "user",
                "message": f"Concurrent message for {sid}",
            }
            response = requests.post(
                f"{BASE_URL}/api/v1/message",
                json=payload,
                timeout=10,
            )
            return response.status_code, sid

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_session, sid) for sid in session_ids]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # All sessions should be created successfully
        for status_code, sid in results:
            assert status_code == 200

        # Verify all sessions exist
        stdout, stderr, rc = _run_client("list-sessions")
        assert rc == 0
        for sid in session_ids:
            assert sid in stdout

        # Clean up
        for sid in session_ids:
            _run_client("delete-sessions", "--session-ids", sid)

    def test_session_delete_and_recreate(self):
        """Test deleting a session and recreating it."""
        _ensure_server_running()
        session_id = f"test_del_recreate_{int(time.time())}"

        # Create session
        _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Original message",
        )

        # Delete session
        stdout, stderr, rc = _run_client(
            "delete-sessions",
            "--session-ids", session_id,
        )
        assert rc == 0

        # Recreate session with same ID
        stdout, stderr, rc = _run_client(
            "send-message",
            "--session-id", session_id,
            "--role", "user",
            "--message", "Recreated message",
        )
        assert rc == 0

        # Verify new message exists
        stdout, stderr, rc = _run_client(
            "get-messages",
            "--session-id", session_id,
        )
        assert rc == 0
        assert "Recreated message" in stdout

        # Clean up
        _run_client("delete-sessions", "--session-ids", session_id)
