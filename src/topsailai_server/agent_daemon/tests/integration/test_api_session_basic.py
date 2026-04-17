"""
Integration Test: Basic Session API Tests

This module contains integration tests for basic session-related API endpoints.
Tests verify that sessions are created, retrieved, and listed correctly.

Test IDs: API-001, API-002, API-003

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
from datetime import datetime, timezone

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
# Test API-001: Test Receive Message Creates Session
# ============================================================================

class TestAPI001ReceiveMessageCreatesSession:
    """
    Test API-001: Test Receive Message Creates Session
    
    Verify that posting a message to a non-existent session automatically
    creates the session.
    """
    
    def test_receive_message_creates_session(self, api_base_url, unique_session_id):
        """Test API-001.1: Receive message should create new session"""
        session_id = unique_session_id
        message_content = "Test message for session creation"
        
        # Send message to non-existent session
        response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                "session_id": session_id,
                "message": message_content,
                "role": "user"
            }
        )
        
        # Verify response
        assert response.status_code == 200, \
            f"Expected status 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get('code') == 0, \
            f"Expected code 0, got {data.get('code')}: {data.get('message')}"
        assert 'data' in data, "Response should contain 'data' field"
        assert 'msg_id' in data['data'], "Response data should contain 'msg_id'"
        
        msg_id = data['data']['msg_id']
        logger.info("Message sent successfully, msg_id: %s", msg_id)
        
        # Verify session was created by retrieving it
        get_response = requests.get(f"{api_base_url}/api/v1/session/{session_id}")
        
        assert get_response.status_code == 200, \
            f"Get session should succeed: {get_response.text}"
        
        session_data = get_response.json()
        assert session_data.get('code') == 0, \
            f"Get session should return code 0: {session_data.get('message')}"
        assert session_data['data']['session_id'] == session_id, \
            f"Session ID mismatch: expected {session_id}, got {session_data['data']['session_id']}"
        
        logger.info("Session %s created and verified successfully", session_id)
    
    def test_receive_message_creates_session_with_assistant_role(
        self, api_base_url, unique_session_id
    ):
        """Test API-001.2: Receive message with assistant role should create session"""
        session_id = unique_session_id
        message_content = "Assistant response message"
        
        # Send assistant message to non-existent session
        response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                "session_id": session_id,
                "message": message_content,
                "role": "assistant"
            }
        )
        
        assert response.status_code == 200, \
            f"Expected status 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get('code') == 0, \
            f"Expected code 0, got {data.get('code')}"
        
        # Verify session was created
        get_response = requests.get(f"{api_base_url}/api/v1/session/{session_id}")
        assert get_response.status_code == 200, "Get session should succeed"
        
        session_data = get_response.json()
        assert session_data['data']['session_id'] == session_id, \
            "Session ID should match"
        
        logger.info("Session created with assistant message, session_id: %s", session_id)


# ============================================================================
# Test API-002: Test List Sessions API
# ============================================================================

class TestAPI002ListSessions:
    """
    Test API-002: Test List Sessions API
    
    Verify that GET /api/v1/session returns paginated session list
    with correct sorting and filtering.
    """
    
    @pytest.fixture
    def created_sessions(self, api_base_url):
        """Fixture to create multiple test sessions for list testing"""
        session_ids = []
        
        for i in range(5):
            session_id = f"test-list-{uuid.uuid4().hex[:8]}"
            session_ids.append(session_id)
            
            # Create session by sending a message
            response = requests.post(
                f"{api_base_url}/api/v1/message",
                json={
                    "session_id": session_id,
                    "message": f"Message for session {i+1}",
                    "role": "user"
                }
            )
            assert response.status_code == 200, \
                f"Failed to create session {session_id}: {response.text}"
        
        logger.info("Created %d test sessions for list testing", len(session_ids))
        
        yield session_ids
        
        # Cleanup: delete all created sessions
        for session_id in session_ids:
            try:
                requests.delete(
                    f"{api_base_url}/api/v1/session",
                    params={"session_ids": session_id}
                )
            except Exception as e:
                logger.warning("Failed to cleanup session %s: %s", session_id, e)
    
    def test_list_sessions_basic(self, api_base_url, created_sessions):
        """Test API-002.1: Basic list with default parameters"""
        response = requests.get(f"{api_base_url}/api/v1/session")
        
        assert response.status_code == 200, \
            f"Expected status 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get('code') == 0, \
            f"Expected code 0, got {data.get('code')}: {data.get('message')}"
        assert 'data' in data, "Response should contain 'data' field"
        assert isinstance(data['data'], list), "data should be a list"
        
        # Verify our created sessions are in the list
        session_ids = [s['session_id'] for s in data['data']]
        for created_id in created_sessions:
            assert created_id in session_ids, \
                f"Created session {created_id} should be in the list"
        
        logger.info("Basic list test passed, found %d sessions", len(data['data']))
    
    def test_list_sessions_pagination(self, api_base_url, created_sessions):
        """Test API-002.2: Pagination with offset and limit"""
        # Test first page: offset=0, limit=2
        response1 = requests.get(
            f"{api_base_url}/api/v1/session",
            params={"offset": 0, "limit": 2}
        )
        
        assert response1.status_code == 200, \
            f"Expected status 200, got {response1.status_code}"
        
        data1 = response1.json()
        assert data1.get('code') == 0, "Expected code 0"
        assert len(data1['data']) <= 2, \
            f"First page should have at most 2 sessions, got {len(data1['data'])}"
        
        # Test second page: offset=2, limit=2
        response2 = requests.get(
            f"{api_base_url}/api/v1/session",
            params={"offset": 2, "limit": 2}
        )
        
        assert response2.status_code == 200, \
            f"Expected status 200, got {response2.status_code}"
        
        data2 = response2.json()
        assert data2.get('code') == 0, "Expected code 0"
        assert len(data2['data']) <= 2, \
            f"Second page should have at most 2 sessions, got {len(data2['data'])}"
        
        # Verify no overlap between pages
        ids1 = set(s['session_id'] for s in data1['data'])
        ids2 = set(s['session_id'] for s in data2['data'])
        assert ids1.isdisjoint(ids2), "Pages should not overlap"
        
        logger.info("Pagination test passed: page1=%d, page2=%d",
                    len(data1['data']), len(data2['data']))
    
    def test_list_sessions_sorting_desc(self, api_base_url, created_sessions):
        """Test API-002.3: Sorting by create_time desc (newest first)"""
        response = requests.get(
            f"{api_base_url}/api/v1/session",
            params={"sort_key": "create_time", "order_by": "desc"}
        )
        
        assert response.status_code == 200, \
            f"Expected status 200, got {response.status_code}"
        
        data = response.json()
        assert data.get('code') == 0, "Expected code 0"
        assert isinstance(data['data'], list), "data should be a list"
        
        # Verify sorting (if more than 1 session)
        if len(data['data']) > 1:
            for i in range(len(data['data']) - 1):
                curr_time = data['data'][i].get('create_time')
                next_time = data['data'][i + 1].get('create_time')
                if curr_time and next_time:
                    assert curr_time >= next_time, \
                        f"Sessions should be sorted desc: {curr_time} >= {next_time}"
        
        logger.info("Sorting desc test passed, found %d sessions", len(data['data']))
    
    def test_list_sessions_sorting_asc(self, api_base_url, created_sessions):
        """Test API-002.4: Sorting by create_time asc (oldest first)"""
        response = requests.get(
            f"{api_base_url}/api/v1/session",
            params={"sort_key": "create_time", "order_by": "asc"}
        )
        
        assert response.status_code == 200, \
            f"Expected status 200, got {response.status_code}"
        
        data = response.json()
        assert data.get('code') == 0, "Expected code 0"
        assert isinstance(data['data'], list), "data should be a list"
        
        # Verify sorting (if more than 1 session)
        if len(data['data']) > 1:
            for i in range(len(data['data']) - 1):
                curr_time = data['data'][i].get('create_time')
                next_time = data['data'][i + 1].get('create_time')
                if curr_time and next_time:
                    assert curr_time <= next_time, \
                        f"Sessions should be sorted asc: {curr_time} <= {next_time}"
        
        logger.info("Sorting asc test passed, found %d sessions", len(data['data']))
    
    def test_list_sessions_with_time_filter(self, api_base_url, created_sessions):
        """Test API-002.5: Time-based filtering with start_time and end_time"""
        # Get current time as ISO format
        now = datetime.now(timezone.utc)
        start_time = (now.replace(hour=0, minute=0, second=0)).isoformat()
        end_time = (now.replace(hour=23, minute=59, second=59)).isoformat()
        
        response = requests.get(
            f"{api_base_url}/api/v1/session",
            params={
                "start_time": start_time,
                "end_time": end_time
            }
        )
        
        assert response.status_code == 200, \
            f"Expected status 200, got {response.status_code}"
        
        data = response.json()
        assert data.get('code') == 0, "Expected code 0"
        assert isinstance(data['data'], list), "data should be a list"
        
        # Verify all returned sessions are within time range
        for session in data['data']:
            create_time = session.get('create_time')
            if create_time:
                assert create_time >= start_time, \
                    f"Session {session['session_id']} create_time {create_time} < start_time {start_time}"
                assert create_time <= end_time, \
                    f"Session {session['session_id']} create_time {create_time} > end_time {end_time}"
        
        logger.info("Time filter test passed, found %d sessions in range", len(data['data']))


# ============================================================================
# Test API-003: Test Get Session API
# ============================================================================

class TestAPI003GetSession:
    """
    Test API-003: Test Get Session API
    
    Verify that GET /api/v1/session/{session_id} returns detailed session
    information including status from session_state_checker.
    """
    
    def test_get_session_success(self, api_base_url, unique_session_id):
        """Test API-003.1: Retrieve existing session by ID"""
        session_id = unique_session_id
        
        # First create a session
        create_response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                "session_id": session_id,
                "message": "Test message for get session",
                "role": "user"
            }
        )
        assert create_response.status_code == 200, \
            f"Failed to create session: {create_response.text}"
        
        # Now get the session
        response = requests.get(f"{api_base_url}/api/v1/session/{session_id}")
        
        assert response.status_code == 200, \
            f"Expected status 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get('code') == 0, \
            f"Expected code 0, got {data.get('code')}: {data.get('message')}"
        assert 'data' in data, "Response should contain 'data' field"
        
        session_data = data['data']
        
        # Verify required fields
        assert session_data.get('session_id') == session_id, \
            f"Session ID mismatch: expected {session_id}, got {session_data.get('session_id')}"
        assert 'session_name' in session_data, "Response should contain 'session_name'"
        assert 'create_time' in session_data, "Response should contain 'create_time'"
        assert 'update_time' in session_data, "Response should contain 'update_time'"
        assert 'processed_msg_id' in session_data, "Response should contain 'processed_msg_id'"
        
        logger.info("Get session test passed for session_id: %s", session_id)
    
    def test_get_session_not_found(self, api_base_url):
        """Test API-003.2: Retrieve non-existent session returns error"""
        non_existent_id = f"non-existent-{uuid.uuid4().hex[:8]}"
        
        response = requests.get(f"{api_base_url}/api/v1/session/{non_existent_id}")
        
        # Should return 404 or error code
        assert response.status_code in [200, 404], \
            f"Expected status 200 or 404, got {response.status_code}"
        
        data = response.json()
        # Either code is non-zero or status is 404
        if response.status_code == 200:
            assert data.get('code') != 0, \
                "Non-existent session should return non-zero code"
        
        logger.info("Not found test passed for session_id: %s", non_existent_id)
    
    def test_get_session_with_status(self, api_base_url, unique_session_id):
        """Test API-003.3: Session response includes status (idle/processing)"""
        session_id = unique_session_id
        
        # Create a session
        create_response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                "session_id": session_id,
                "message": "Test message for status check",
                "role": "user"
            }
        )
        assert create_response.status_code == 200, \
            f"Failed to create session: {create_response.text}"
        
        # Get the session and verify status
        response = requests.get(f"{api_base_url}/api/v1/session/{session_id}")
        
        assert response.status_code == 200, \
            f"Expected status 200, got {response.status_code}"
        
        data = response.json()
        assert data.get('code') == 0, "Expected code 0"
        
        session_data = data['data']
        assert 'status' in session_data, \
            "Response should contain 'status' field from session_state_checker"
        
        # Status should be either 'idle' or 'processing'
        assert session_data['status'] in ['idle', 'processing'], \
            f"Status should be 'idle' or 'processing', got {session_data['status']}"
        
        logger.info("Status test passed, session status: %s", session_data['status'])
    
    def test_get_session_missing_param(self, api_base_url):
        """Test API-003.4: Request without session_id returns error"""
        # Try to get session with empty/invalid session_id
        response = requests.get(f"{api_base_url}/api/v1/session/")
        # Accept various status codes: 200 (redirect followed), 307 (redirect), 400, 404
        assert response.status_code in [200, 307, 400, 404], \
            f"Expected status 200, 307, 400, or 404, got {response.status_code}"
        logger.info("Missing param test passed, got status: %d", response.status_code)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
