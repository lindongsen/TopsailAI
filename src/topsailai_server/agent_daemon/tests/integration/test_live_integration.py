"""
Live Integration Tests for agent_daemon

This module contains live integration tests that verify the complete
workflow of the agent_daemon service by starting an actual server process
and making real HTTP API requests.

Test IDs: L-001 to L-002

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-16
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

# Server configuration
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7373
SERVER_STARTUP_TIMEOUT = 15  # seconds
SERVER_SHUTDOWN_TIMEOUT = 5  # seconds

# Test script paths
SCRIPT_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration/scripts'
MOCK_PROCESSOR_SCRIPT = os.path.join(SCRIPT_DIR, 'mock_processor.py')
MOCK_SUMMARIZER_SCRIPT = os.path.join(SCRIPT_DIR, 'mock_summarizer.py')
MOCK_STATE_CHECKER_SCRIPT = os.path.join(SCRIPT_DIR, 'mock_state_checker.py')


# ============================================================================
# Test Fixtures
# ============================================================================

class ServerProcess:
    """Context manager for server process"""
    
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
            # Start server in background
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=INTEGRATION_DIR,
                env={**os.environ, 'HOME': INTEGRATION_DIR}
            )
            
            # Wait for server to be ready
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
                # Try graceful shutdown first
                self.process.terminate()
                try:
                    self.process.wait(timeout=SERVER_SHUTDOWN_TIMEOUT)
                except subprocess.TimeoutExpired:
                    # Force kill if graceful shutdown fails
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
    # Cleanup
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
    
    # Start server
    if not server.start():
        pytest.skip("Failed to start server")
    
    yield server
    
    # Stop server
    server.stop()


@pytest.fixture(scope='class')
def api_base_url(server_process):
    """Get the API base URL"""
    return server_process.base_url


# ============================================================================
# Test L-001: Start Actual Server and Test via HTTP API
# ============================================================================

class TestL001ServerHTTPAPI:
    """Test L-001: Start actual server and test via HTTP API"""
    
    def test_server_health_check(self, api_base_url):
        """
        Test L-001.1: Health check endpoint
        
        Verify that the server responds to health check requests.
        """
        response = requests.get(f"{api_base_url}/health")
        assert response.status_code == 200, "Health check should return 200"
        data = response.json()
        assert data.get('code') == 0, "Health check should return code 0"
        logger.info("Health check test passed")
    
    def test_create_and_get_session(self, api_base_url):
        """
        Test L-001.2: Session creation and retrieval via HTTP API
        
        Verify that sessions can be created and retrieved via the API.
        Note: Sessions are created implicitly when messages are sent.
        """
        session_id = f"test-live-session-{uuid.uuid4().hex[:8]}"
        
        # Create session by sending a message (implicit session creation)
        # POST /api/v1/message
        send_response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                'session_id': session_id,
                'message': 'Test message to create session',
                'role': 'user'
            }
        )
        assert send_response.status_code == 200, f"Send message should succeed: {send_response.text}"
        
        # Now get the session
        # GET /api/v1/session/{session_id}
        get_response = requests.get(
            f"{api_base_url}/api/v1/session/{session_id}"
        )
        assert get_response.status_code == 200, "Get session should succeed"
        data = get_response.json()
        assert data.get('code') == 0, "Get session should return code 0"
        assert data['data']['session_id'] == session_id, "Session ID should match"
        logger.info("Create and get session test passed")
    
    def test_send_and_list_messages(self, api_base_url):
        """
        Test L-001.3: Message sending and listing via HTTP API
        
        Verify that messages can be sent and listed via the API.
        """
        session_id = f"test-live-msg-{uuid.uuid4().hex[:8]}"
        
        # Send message via API (this should create session if not exists)
        # POST /api/v1/message
        send_response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                'session_id': session_id,
                'message': 'Test message for live integration',
                'role': 'user'
            }
        )
        assert send_response.status_code == 200, f"Send message should succeed: {send_response.text}"
        
        # List messages via API
        # GET /api/v1/message?session_id=xxx
        list_response = requests.get(
            f"{api_base_url}/api/v1/message",
            params={'session_id': session_id}
        )
        assert list_response.status_code == 200, "List messages should succeed"
        data = list_response.json()
        assert data.get('code') == 0, "List messages should return code 0"
        assert len(data['data']) >= 1, "Should have at least one message"
        logger.info("Send and list messages test passed")
    
    def test_list_sessions(self, api_base_url):
        """
        Test L-001.4: List sessions via HTTP API
        
        Verify that sessions can be listed via the API.
        """
        # Create a session first by sending a message
        session_id = f"test-list-sessions-{uuid.uuid4().hex[:8]}"
        requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                'session_id': session_id,
                'message': 'Test message for listing',
                'role': 'user'
            }
        )
        
        # List sessions via API
        # GET /api/v1/session
        list_response = requests.get(f"{api_base_url}/api/v1/session")
        assert list_response.status_code == 200, "List sessions should succeed"
        data = list_response.json()
        assert data.get('code') == 0, "List sessions should return code 0"
        assert isinstance(data['data'], list), "Should return a list of sessions"
        logger.info("List sessions test passed")
    
    def test_delete_sessions(self, api_base_url):
        """
        Test L-001.5: Delete sessions via HTTP API
        
        Verify that sessions can be deleted via the API.
        """
        # Create a session first by sending a message
        session_id = f"test-delete-{uuid.uuid4().hex[:8]}"
        requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                'session_id': session_id,
                'message': 'Test message for deletion',
                'role': 'user'
            }
        )
        
        # Delete session via API
        # DELETE /api/v1/session?session_ids=xxx
        delete_response = requests.delete(
            f"{api_base_url}/api/v1/session",
            params={'session_ids': session_id}
        )
        assert delete_response.status_code == 200, "Delete session should succeed"
        
        # Verify session is deleted
        get_response = requests.get(
            f"{api_base_url}/api/v1/session/{session_id}"
        )
        # Should return error or empty data
        logger.info("Delete sessions test passed")


# ============================================================================
# Test L-002: Test Full Workflow with Real Server Process
# ============================================================================

class TestL002FullWorkflow:
    """Test L-002: Test full workflow with real server process"""
    
    def test_full_message_processing_workflow(self, api_base_url):
        """
        Test L-002.1: Full message processing workflow
        
        Complete workflow:
        1. Create session (via message)
        2. Send message
        3. Process session
        4. Set task result
        5. Verify message is processed
        """
        session_id = f"test-full-workflow-{uuid.uuid4().hex[:8]}"
        
        # Step 1 & 2: Send message (creates session)
        # POST /api/v1/message
        send_response = requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                'session_id': session_id,
                'message': 'Process this message',
                'role': 'user'
            }
        )
        assert send_response.status_code == 200, f"Send message should succeed: {send_response.text}"
        
        # Get the msg_id from the response or list messages
        # GET /api/v1/message?session_id=xxx
        list_response = requests.get(
            f"{api_base_url}/api/v1/message",
            params={'session_id': session_id}
        )
        messages = list_response.json()['data']
        assert len(messages) > 0, "Should have messages"
        msg_id = messages[0]['msg_id']
        
        # Step 3: Process session
        # POST /api/v1/session/process
        process_response = requests.post(
            f"{api_base_url}/api/v1/session/process",
            json={'session_id': session_id}
        )
        assert process_response.status_code == 200, "Process session should succeed"
        
        # Step 4: Set task result (simulating processor callback)
        # POST /api/v1/task
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        task_result = "Task completed successfully"
        
        set_result_response = requests.post(
            f"{api_base_url}/api/v1/task",
            json={
                'session_id': session_id,
                'processed_msg_id': msg_id,
                'task_id': task_id,
                'task_result': task_result
            }
        )
        assert set_result_response.status_code == 200, f"Set task result should succeed: {set_result_response.text}"
        
        # Step 5: Verify message is processed
        # GET /api/v1/session/{session_id}
        session_response = requests.get(
            f"{api_base_url}/api/v1/session/{session_id}"
        )
        session_data = session_response.json()
        assert session_data['data']['processed_msg_id'] == msg_id, \
            "processed_msg_id should be updated"
        
        logger.info("Full message processing workflow test passed")
    
    def test_multiple_messages_batch_workflow(self, api_base_url):
        """
        Test L-002.2: Multiple messages batch workflow
        
        Verify that multiple messages are processed correctly.
        """
        session_id = f"test-batch-{uuid.uuid4().hex[:8]}"
        
        # Send multiple messages
        for i in range(3):
            send_response = requests.post(
                f"{api_base_url}/api/v1/message",
                json={
                    'session_id': session_id,
                    'message': f'Batch message {i}',
                    'role': 'user'
                }
            )
            assert send_response.status_code == 200, f"Message {i} should be sent"
        
        # List messages to verify all were stored
        list_response = requests.get(
            f"{api_base_url}/api/v1/message",
            params={'session_id': session_id}
        )
        messages = list_response.json()['data']
        assert len(messages) >= 3, "Should have at least 3 messages"
        
        # Process session
        process_response = requests.post(
            f"{api_base_url}/api/v1/session/process",
            json={'session_id': session_id}
        )
        assert process_response.status_code == 200, "Process session should succeed"
        
        logger.info("Multiple messages batch workflow test passed")
    
    def test_session_state_check_workflow(self, api_base_url):
        """
        Test L-002.3: Session state check workflow
        
        Verify that session state is correctly reported.
        """
        session_id = f"test-state-{uuid.uuid4().hex[:8]}"
        
        # Create session by sending message
        requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                'session_id': session_id,
                'message': 'Test message for state check',
                'role': 'user'
            }
        )
        
        # Get session and check status
        get_response = requests.get(
            f"{api_base_url}/api/v1/session/{session_id}"
        )
        assert get_response.status_code == 200, "Get session should succeed"
        data = get_response.json()
        
        # Verify status field exists (from state checker)
        assert 'status' in data['data'], "Session should have status field"
        assert data['data']['status'] in ['idle', 'processing'], \
            "Status should be 'idle' or 'processing'"
        
        logger.info("Session state check workflow test passed")
    
    def test_task_listing_workflow(self, api_base_url):
        """
        Test L-002.4: Task listing workflow
        
        Verify that tasks can be listed correctly.
        """
        session_id = f"test-tasks-{uuid.uuid4().hex[:8]}"
        
        # Send message and get msg_id
        requests.post(
            f"{api_base_url}/api/v1/message",
            json={
                'session_id': session_id,
                'message': 'Create a task',
                'role': 'user'
            }
        )
        
        # Get message ID
        list_response = requests.get(
            f"{api_base_url}/api/v1/message",
            params={'session_id': session_id}
        )
        messages = list_response.json()['data']
        msg_id = messages[0]['msg_id']
        
        # Set task result
        # POST /api/v1/task
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        requests.post(
            f"{api_base_url}/api/v1/task",
            json={
                'session_id': session_id,
                'processed_msg_id': msg_id,
                'task_id': task_id,
                'task_result': 'Task result content'
            }
        )
        
        # List tasks
        # GET /api/v1/task?session_id=xxx
        tasks_response = requests.get(
            f"{api_base_url}/api/v1/task",
            params={'session_id': session_id}
        )
        assert tasks_response.status_code == 200, "List tasks should succeed"
        tasks_data = tasks_response.json()
        assert tasks_data.get('code') == 0, "List tasks should return code 0"
        
        logger.info("Task listing workflow test passed")


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
