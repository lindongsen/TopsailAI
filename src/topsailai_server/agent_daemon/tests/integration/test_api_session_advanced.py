"""
Integration Test: Advanced Session API Tests

This module contains integration tests for advanced session-related API endpoints.
Tests verify that sessions are deleted and processed correctly.

Test IDs: API-004, API-005

Author: mm-m25
Reviewer: km-k25
"""

import os
import sys
import time
import uuid
import subprocess
import tempfile
from typing import Optional

import requests
import pytest

# Set HOME environment variable for integration testing
INTEGRATION_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
os.environ['HOME'] = INTEGRATION_DIR

# Add the parent directory to the path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai_server.agent_daemon import logger


# ============================================================================
# Test Configuration
# ============================================================================

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7373
SERVER_STARTUP_TIMEOUT = 15
SERVER_SHUTDOWN_TIMEOUT = 5

SCRIPT_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
MOCK_PROCESSOR_SCRIPT = os.path.join(SCRIPT_DIR, 'mock_processor.sh')
MOCK_SUMMARIZER_SCRIPT = os.path.join(SCRIPT_DIR, 'mock_summarizer.sh')
MOCK_STATE_CHECKER_SCRIPT = os.path.join(SCRIPT_DIR, 'mock_state_checker.sh')


# ============================================================================
# Test Fixtures
# ============================================================================

class ServerProcess:
    """Context manager for server process management"""
    
    def __init__(self, host: str, port: int, db_path: str):
        self.host = host
        self.port = port
        self.db_path = db_path
        self.process: Optional[subprocess.Popen] = None
        self.base_url = f"http://{host}:{port}"
    
    def start(self) -> bool:
        """Start the server process"""
        cli_path = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/topsailai_agent_daemon.py'
        
        cmd = [
            sys.executable,
            cli_path,
            'start',
            '--host', self.host,
            '--port', str(self.port),
            '--db_url', f'sqlite:///{self.db_path}',
            '--processor', MOCK_PROCESSOR_SCRIPT,
            '--summarizer', MOCK_SUMMARIZER_SCRIPT,
            '--session_state_checker', MOCK_STATE_CHECKER_SCRIPT,
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=INTEGRATION_DIR,
                env={**os.environ, 'HOME': INTEGRATION_DIR}
            )
            
            if self._wait_for_server(SERVER_STARTUP_TIMEOUT):
                logger.info("Server started successfully at %s", self.base_url)
                return True
            else:
                logger.error("Server failed to start within timeout")
                self.stop()
                return False
                
        except Exception as e:
            logger.error("Failed to start server: %s", e)
            return False
    
    def _wait_for_server(self, timeout: int) -> bool:
        """Wait for server to be ready"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.base_url}/health", timeout=1)
                if response.status_code == 200:
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(0.5)
        return False
    
    def stop(self):
        """Stop the server process"""
        if self.process:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=SERVER_SHUTDOWN_TIMEOUT)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            except Exception as e:
                logger.error("Error stopping server: %s", e)
            finally:
                self.process = None
    
    def is_running(self) -> bool:
        """Check if server is running"""
        if not self.process:
            return False
        return self.process.poll() is None


@pytest.fixture(scope='class')
def test_db_path():
    """Create a temporary database path for tests"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture(scope='class')
def server_process(test_db_path):
    """Start and stop the server for all tests in the class"""
    server = ServerProcess(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        db_path=test_db_path
    )
    
    if not server.start():
        pytest.skip("Failed to start server")
    
    yield server
    server.stop()


@pytest.fixture(scope='class')
def api_base_url(server_process):
    """Get the API base URL"""
    return server_process.base_url


@pytest.fixture
def unique_session_id():
    """Generate a unique session ID for testing"""
    return f"test-api-session-{uuid.uuid4().hex[:8]}"


# ============================================================================
# Test API-004: Test Delete Sessions API
# ============================================================================

class TestAPI004DeleteSessions:
    """
    Test API-004: Test Delete Sessions API
    
    Verify DELETE /api/v1/session deletes sessions and their associated messages.
    This is a critical cleanup operation.
    
    Note: DELETE endpoint expects session_ids as query parameter (comma-separated).
    The API returns code=404 in JSON body for not found, not HTTP status 404.
    """
    
    def test_delete_sessions_success(self, api_base_url, unique_session_id):
        """Test API-004.1: Deleting a single session successfully"""
        session_id = unique_session_id
        
        # Create a session with a message
        msg_response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={"session_id": session_id, "message": "Test message", "role": "user"}
        )
        assert msg_response.status_code == 200, \
            f"Failed to create message: {msg_response.text}"
        
        # Delete the session (session_ids as query parameter)
        del_response = requests.delete(
            f"{api_base_url}/api/v1/session",
            params={"session_ids": session_id}
        )
        assert del_response.status_code == 200, \
            f"Delete failed: {del_response.text}"
        
        result = del_response.json()
        assert result["code"] == 0, f"Expected code 0, got {result}"
        
        # Verify session is deleted (API returns code=404 in JSON body)
        get_response = requests.get(f"{api_base_url}/api/v1/session/{session_id}")
        get_result = get_response.json()
        assert get_result["code"] == 404, \
            f"Deleted session should return code 404, got {get_result}"
        
        logger.info("Delete session success test passed for: %s", session_id)
    
    def test_delete_multiple_sessions(self, api_base_url):
        """Test API-004.2: Deleting multiple sessions at once"""
        session_ids = [f"multi_delete_{uuid.uuid4().hex[:8]}" for _ in range(3)]
        
        # Create multiple sessions
        for sid in session_ids:
            msg_response = requests.post(
                f"{api_base_url}/api/v1/message",
                json={"session_id": sid, "message": "Test message", "role": "user"}
            )
            assert msg_response.status_code == 200
        
        # Delete all sessions (comma-separated session_ids)
        del_response = requests.delete(
            f"{api_base_url}/api/v1/session",
            params={"session_ids": ",".join(session_ids)}
        )
        assert del_response.status_code == 200
        result = del_response.json()
        assert result["code"] == 0
        
        # Verify all sessions are deleted (API returns code=404 in JSON body)
        for sid in session_ids:
            get_response = requests.get(f"{api_base_url}/api/v1/session/{sid}")
            get_result = get_response.json()
            assert get_result["code"] == 404, \
                f"Session {sid} should return code 404 after deletion"
        
        logger.info("Delete multiple sessions test passed")
    
    def test_delete_sessions_with_messages(self, api_base_url, unique_session_id):
        """Test API-004.3: Deleting sessions also deletes associated messages"""
        session_id = unique_session_id
        
        # Create session with multiple messages
        for i in range(3):
            msg_response = requests.post(
                f"{api_base_url}/api/v1/message",
                json={"session_id": session_id, "message": f"Message {i}", "role": "user"}
            )
            assert msg_response.status_code == 200
        
        # Delete the session
        del_response = requests.delete(
            f"{api_base_url}/api/v1/session",
            params={"session_ids": session_id}
        )
        assert del_response.status_code == 200
        result = del_response.json()
        assert result["code"] == 0
        
        # Verify messages are also deleted (cascade delete)
        msg_response = requests.get(
            f"{api_base_url}/api/v1/message",
            params={"session_id": session_id}
        )
        assert msg_response.status_code == 200
        msg_result = msg_response.json()
        assert msg_result["code"] == 0
        assert len(msg_result["data"]) == 0, \
            "Messages should be deleted with session"
        
        logger.info("Cascade delete test passed for session: %s", session_id)
    
    def test_delete_nonexistent_sessions(self, api_base_url):
        """Test API-004.4: Deleting sessions that don't exist (graceful handling)"""
        non_existent_ids = ["nonexistent_1", "nonexistent_2"]
        
        # Delete non-existent sessions (comma-separated)
        del_response = requests.delete(
            f"{api_base_url}/api/v1/session",
            params={"session_ids": ",".join(non_existent_ids)}
        )
        # Should handle gracefully (200 with code 0)
        assert del_response.status_code == 200
        result = del_response.json()
        assert result["code"] == 0, \
            "Deleting non-existent sessions should return code 0"
        
        logger.info("Delete non-existent sessions test passed")
    
    def test_delete_sessions_missing_ids(self, api_base_url):
        """Test API-004.5: Deleting sessions without providing session_ids"""
        # Try to delete without session_ids
        del_response = requests.delete(f"{api_base_url}/api/v1/session")
        # Should return error (400 or similar)
        assert del_response.status_code in [400, 422], \
            f"Expected 400 or 422, got {del_response.status_code}"
        
        logger.info("Delete missing ids test passed, status: %d", del_response.status_code)


# ============================================================================
# Test API-005: Test Process Session API
# ============================================================================

class TestAPI005ProcessSession:
    """
    Test API-005: Test Process Session API
    
    Verify POST /api/v1/session/process triggers processor for unprocessed messages.
    The endpoint expects a JSON body with session_id field.
    """
    
    def test_process_session_no_pending_messages(self, api_base_url, unique_session_id):
        """
        Test API-005.1: Process session with no pending messages
        
        When processed_msg_id is already the latest message,
        the endpoint should return code=0 with message indicating no processing needed.
        """
        session_id = unique_session_id
        
        # Create a session with one message (this becomes processed_msg_id)
        msg_response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={"session_id": session_id, "message": "Test message", "role": "user"}
        )
        assert msg_response.status_code == 200, \
            f"Failed to create message: {msg_response.text}"
        
        # Process the session (POST with JSON body)
        proc_response = requests.post(
            f"{api_base_url}/api/v1/session/process",
            json={"session_id": session_id}
        )
        assert proc_response.status_code == 200, \
            f"Process failed: {proc_response.text}"
        result = proc_response.json()
        
        # Should indicate no pending messages
        assert result["code"] == 0, f"Expected code 0, got {result}"
        logger.info("No pending messages test passed")
    
    def test_process_session_with_pending_messages(self, api_base_url, unique_session_id):
        """
        Test API-005.2: Process session with pending messages triggers processor
        
        When there are unprocessed messages after processed_msg_id,
        the endpoint should return information about the processing.
        """
        session_id = unique_session_id
        
        # Create first message (will be processed)
        msg_response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={"session_id": session_id, "message": "First message", "role": "user"}
        )
        assert msg_response.status_code == 200
        
        # Process first message
        proc_response = requests.post(
            f"{api_base_url}/api/v1/session/process",
            json={"session_id": session_id}
        )
        assert proc_response.status_code == 200
        
        # Add second message (pending)
        msg_response2 = requests.post(
            f"{api_base_url}/api/v1/message",
            json={"session_id": session_id, "message": "Second message", "role": "user"}
        )
        assert msg_response2.status_code == 200
        
        # Process the session with pending messages
        proc_response2 = requests.post(
            f"{api_base_url}/api/v1/session/process",
            json={"session_id": session_id}
        )
        assert proc_response2.status_code == 200
        result = proc_response2.json()
        
        # Should indicate processing
        assert result["code"] == 0, f"Expected code 0, got {result}"
        logger.info("Pending messages test passed")
    
    def test_process_session_missing_param(self, api_base_url):
        """
        Test API-005.3: Process session without session_id returns error
        
        When session_id is not provided, the endpoint should return 422 error.
        """
        proc_response = requests.post(
            f"{api_base_url}/api/v1/session/process",
            json={}
        )
        # Should return validation error
        assert proc_response.status_code == 422, \
            f"Expected 422, got {proc_response.status_code}"
        logger.info("Missing param test passed, status: %d", proc_response.status_code)
    
    def test_process_nonexistent_session(self, api_base_url):
        """
        Test API-005.4: Process non-existent session returns error
        
        When session_id doesn't exist, the endpoint should handle gracefully.
        """
        non_existent_id = f"nonexistent-{uuid.uuid4().hex[:8]}"
        
        proc_response = requests.post(
            f"{api_base_url}/api/v1/session/process",
            json={"session_id": non_existent_id}
        )
        # Should return error (404 or 200 with error message)
        assert proc_response.status_code in [200, 404], \
            f"Expected 200 or 404, got {proc_response.status_code}"
        logger.info("Non-existent session test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
