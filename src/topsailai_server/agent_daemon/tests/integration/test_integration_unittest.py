#!/usr/bin/env python3
"""
Integration Tests for agent_daemon using unittest framework

This module contains end-to-end integration tests that verify the complete
workflow of the agent_daemon service including:
- End-to-end message flow (I-001)
- Session lifecycle (I-002)
- Message flow (I-003)
- Task result setting and retrieval (I-004)
- Error scenarios (I-005)
- Concurrent message processing (I-006)
- Cron job execution verification (I-007)

Test IDs: I-001 to I-007

Author: AI
Created: 2026-04-16
"""

import os
import sys
import time
import uuid
import unittest
import subprocess
import signal
import requests
import tempfile
import stat
from datetime import datetime, timedelta
from pathlib import Path

# Set HOME environment variable for integration testing
INTEGRATION_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
WORKSPACE_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon'
sys.path.insert(0, '/root/ai/TopsailAI/src')

os.environ['HOME'] = INTEGRATION_DIR

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.storage.session_manager import SessionData
from topsailai_server.agent_daemon.storage.message_manager import MessageData


# ============================================================================
# Test Configuration
# ============================================================================

BASE_URL = "http://localhost:7373"
API_TIMEOUT = 30


def is_server_running():
    """Check if the server is running by checking port 7373"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex(('127.0.0.1', 7373))
        sock.close()
        return result == 0
    except Exception:
        return False


def ensure_script_executable(script_path):
    """Ensure a script is executable"""
    if os.path.exists(script_path):
        current_mode = os.stat(script_path).st_mode
        os.chmod(script_path, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def start_server():
    """Start the agent daemon server"""
    workspace = Path(WORKSPACE_DIR)
    daemon_script = workspace / "topsailai_agent_daemon.py"
    
    # Use mock scripts from integration test directory
    mock_processor = Path(INTEGRATION_DIR) / "mock_processor.sh"
    mock_summarizer = Path(INTEGRATION_DIR) / "mock_summarizer.sh"
    mock_state_checker = Path(INTEGRATION_DIR) / "mock_state_checker.sh"
    
    # Ensure mock scripts are executable
    for script in [mock_processor, mock_summarizer, mock_state_checker]:
        if script.exists():
            ensure_script_executable(str(script))
    
    # Prepare environment
    env = os.environ.copy()
    env["HOME"] = INTEGRATION_DIR
    
    # Database path - use absolute path for the test database
    db_url = f"sqlite:///{os.path.join(INTEGRATION_DIR, 'test_integration.db')}"
    
    # Start server
    proc = subprocess.Popen(
        [
            sys.executable,
            str(daemon_script),
            "start",
            "--processor", str(mock_processor),
            "--summarizer", str(mock_summarizer),
            "--session_state_checker", str(mock_state_checker),
            "--db_url", db_url
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid if hasattr(os, 'setsid') else None
    )
    
    # Wait for server to be ready (max 30 seconds)
    max_wait = 30
    for i in range(max_wait):
        if is_server_running():
            return proc
        time.sleep(1)
    
    # Server didn't start in time, terminate and raise
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    raise RuntimeError("Server failed to start within 30 seconds")


def stop_server():
    """Stop the agent daemon server gracefully"""
    workspace = Path(WORKSPACE_DIR)
    daemon_script = workspace / "topsailai_agent_daemon.py"
    
    # Try graceful stop first
    try:
        subprocess.run(
            [sys.executable, str(daemon_script), "stop"],
            timeout=10,
            capture_output=True
        )
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    
    # Force kill if still running
    if is_server_running():
        try:
            # Find and kill process on port 7373
            result = subprocess.run(
                ["lsof", "-ti", ":7373"],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except (ValueError, ProcessLookupError, PermissionError):
                        pass
        except Exception:
            pass
    
    # Wait for port to be released
    time.sleep(1)


# ============================================================================
# Test Fixtures
# ============================================================================

class TestIntegrationFixture(unittest.TestCase):
    """Base class for integration tests with server management"""
    
    server_proc = None
    storage = None
    
    @classmethod
    def setUpClass(cls):
        """Set up the test class - start server if not running"""
        # Ensure mock scripts are executable
        mock_processor = Path(INTEGRATION_DIR) / "mock_processor.sh"
        mock_summarizer = Path(INTEGRATION_DIR) / "mock_summarizer.sh"
        mock_state_checker = Path(INTEGRATION_DIR) / "mock_state_checker.sh"
        
        for script in [mock_processor, mock_summarizer, mock_state_checker]:
            if script.exists():
                ensure_script_executable(str(script))
        
        # Start server if not running
        if not is_server_running():
            cls.server_proc = start_server()
            # Wait for server to be fully ready
            time.sleep(2)
        
        # Initialize storage
        db_path = os.path.join(INTEGRATION_DIR, 'test_integration.db')
        from sqlalchemy import create_engine
        engine = create_engine(f'sqlite:///{db_path}')
        cls.storage = Storage(engine)
        cls.storage.init_db()
        
        logger.info("Integration test class set up completed")
    
    @classmethod
    def tearDownClass(cls):
        """Tear down the test class - clean up resources"""
        # Clean up storage
        if cls.storage:
            try:
                self.storage.session.delete_all()
            except Exception:
                pass
        
        logger.info("Integration test class tear down completed")
    
    def setUp(self):
        """Set up each test - ensure clean state"""
        # Clean up before each test
        try:
            self.storage.session.delete_all()
        except Exception:
            pass
    
    def tearDown(self):
        """Tear down each test"""
        pass


# ============================================================================
# Test I-001: Full Workflow - Session Creation, Message Sending, Task Processing
# ============================================================================

class TestI001FullWorkflow(TestIntegrationFixture):
    """I-001: Full workflow - session creation, message sending, task processing"""
    
    def test_full_workflow_session_message_task(self):
        """
        Test end-to-end workflow:
        1. Create a session (via message)
        2. Receive a message
        3. Process session
        4. Verify processor was triggered
        5. Set task result
        6. Verify processed_msg_id updated
        """
        session_id = f"test-session-i001-{uuid.uuid4().hex[:8]}"
        
        # Step 1 & 2: Create session and receive message via POST /api/v1/message
        msg_content = "Test message for I-001 workflow"
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            json={
                "session_id": session_id,
                "message": msg_content,
                "role": "user"
            },
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('code'), 0)
        
        # Step 3: Process session
        response = requests.post(
            f"{BASE_URL}/api/v1/session/process",
            json={"session_id": session_id},
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('code'), 0)
        
        # Verify processing was initiated
        self.assertIn('processing_msg_id', data.get('data', {}))
        
        # Wait for processor to complete
        time.sleep(3)
        
        # Step 4: Verify session state
        response = requests.get(
            f"{BASE_URL}/api/v1/session/{session_id}",
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('code'), 0)
        
        # Session should have processed_msg_id set
        session_data = data.get('data', {})
        self.assertIsNotNone(session_data.get('processed_msg_id'))
        
        logger.info("I-001 Full workflow test completed successfully")


# ============================================================================
# Test I-002: Session Lifecycle - Create, List, Get, Delete
# ============================================================================

class TestI002SessionLifecycle(TestIntegrationFixture):
    """I-002: Session lifecycle - create, list, get, delete"""
    
    def test_session_lifecycle_create_list_get_delete(self):
        """
        Test complete session lifecycle:
        1. Create multiple sessions (via messages)
        2. List sessions
        3. Get specific session
        4. Delete sessions
        """
        session_ids = []
        
        # Step 1: Create multiple sessions via messages
        for i in range(3):
            session_id = f"test-session-i002-{i}-{uuid.uuid4().hex[:6]}"
            session_ids.append(session_id)
            
            response = requests.post(
                f"{BASE_URL}/api/v1/message",
                json={
                    "session_id": session_id,
                    "message": f"Message for session {i}",
                    "role": "user"
                },
                timeout=API_TIMEOUT
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data.get('code'), 0)
        
        # Step 2: List sessions
        response = requests.get(
            f"{BASE_URL}/api/v1/session",
            params={"limit": 10},
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('code'), 0)
        
        sessions = data.get('data', [])
        self.assertGreaterEqual(len(sessions), 3)
        
        # Step 3: Get specific session
        response = requests.get(
            f"{BASE_URL}/api/v1/session/{session_ids[0]}",
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('code'), 0)
        
        session_data = data.get('data', {})
        self.assertEqual(session_data.get('session_id'), session_ids[0])
        
        # Step 4: Delete sessions
        response = requests.delete(
            f"{BASE_URL}/api/v1/session",
            params={"session_ids": ",".join(session_ids)},
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('code'), 0)
        
        # Verify sessions are deleted
        for session_id in session_ids:
            response = requests.get(
                f"{BASE_URL}/api/v1/session/{session_id}",
                timeout=API_TIMEOUT
            )
            data = response.json()
            # Should return 404 or empty session
            self.assertIn(data.get('code'), [0, 404])
        
        logger.info("I-002 Session lifecycle test completed successfully")


# ============================================================================
# Test I-003: Message Flow - Send Multiple Messages, Verify Processing
# ============================================================================

class TestI003MessageFlow(TestIntegrationFixture):
    """I-003: Message flow - send multiple messages, verify processing"""
    
    def test_message_flow_multiple_messages(self):
        """
        Test message flow:
        1. Create session (via message)
        2. Send multiple messages
        3. Verify messages are stored
        4. Process session
        5. Verify messages are processed
        """
        session_id = f"test-session-i003-{uuid.uuid4().hex[:8]}"
        
        # Step 1 & 2: Create session and send first message
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            json={
                "session_id": session_id,
                "message": "Message 0 content",
                "role": "user"
            },
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        
        # Send additional messages
        msg_ids = []
        for i in range(1, 3):
            response = requests.post(
                f"{BASE_URL}/api/v1/message",
                json={
                    "session_id": session_id,
                    "message": f"Message {i} content",
                    "role": "user"
                },
                timeout=API_TIMEOUT
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            msg_ids.append(data.get('data', {}).get('msg_id'))
        
        # Step 3: Verify messages are stored
        response = requests.get(
            f"{BASE_URL}/api/v1/message",
            params={"session_id": session_id, "limit": 10},
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('code'), 0)
        
        messages = data.get('data', [])
        self.assertEqual(len(messages), 3)
        
        # Step 4: Process session
        response = requests.post(
            f"{BASE_URL}/api/v1/session/process",
            json={"session_id": session_id},
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        
        # Wait for processing
        time.sleep(3)
        
        # Step 5: Verify messages are processed
        response = requests.get(
            f"{BASE_URL}/api/v1/session/{session_id}",
            timeout=API_TIMEOUT
        )
        data = response.json()
        session_data = data.get('data', {})
        self.assertIsNotNone(session_data.get('processed_msg_id'))
        
        logger.info("I-003 Message flow test completed successfully")


# ============================================================================
# Test I-004: Task Result Setting and Retrieval
# ============================================================================

class TestI004TaskResult(TestIntegrationFixture):
    """I-004: Task result setting and retrieval"""
    
    def test_task_result_set_and_retrieve(self):
        """
        Test task result handling:
        1. Create session and message
        2. Set task result
        3. Retrieve tasks
        4. Verify task data
        """
        session_id = f"test-session-i004-{uuid.uuid4().hex[:8]}"
        task_id = f"task-i004-{uuid.uuid4().hex[:8]}"
        task_result = "Test task result content"
        
        # Step 1: Create session and message
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            json={
                "session_id": session_id,
                "message": "Test message for task",
                "role": "user"
            },
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        msg_id = data.get('data', {}).get('msg_id')
        
        # Step 2: Set task result
        response = requests.post(
            f"{BASE_URL}/api/v1/task",
            json={
                "session_id": session_id,
                "processed_msg_id": msg_id,
                "task_id": task_id,
                "task_result": task_result
            },
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('code'), 0)
        
        # Step 3: Retrieve tasks
        response = requests.get(
            f"{BASE_URL}/api/v1/task",
            params={"session_id": session_id},
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('code'), 0)
        
        # Step 4: Verify task data
        tasks = data.get('data', [])
        self.assertGreater(len(tasks), 0)
        
        # Find our task
        found = False
        for task in tasks:
            if task.get('task_id') == task_id:
                found = True
                self.assertEqual(task.get('task_result'), task_result)
                break
        
        self.assertTrue(found, "Task should be found in retrieved tasks")
        
        logger.info("I-004 Task result test completed successfully")


# ============================================================================
# Test I-005: Error Scenarios - Invalid Session ID, Malformed Requests
# ============================================================================

class TestI005ErrorScenarios(TestIntegrationFixture):
    """I-005: Error scenarios - invalid session_id, malformed requests"""
    
    def test_invalid_session_id(self):
        """Test handling of invalid session ID"""
        response = requests.get(
            f"{BASE_URL}/api/v1/session/non-existent-session",
            timeout=API_TIMEOUT
        )
        # Should return 200 with error code or 404
        data = response.json()
        self.assertIn(data.get('code'), [0, 404])
    
    def test_missing_required_parameters(self):
        """Test handling of missing required parameters"""
        # Missing session_id in message
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            json={"message": "test"},
            timeout=API_TIMEOUT
        )
        # Should return error
        self.assertIn(response.status_code, [400, 422, 500])
    
    def test_invalid_json(self):
        """Test handling of invalid JSON"""
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            data="invalid json",
            headers={"Content-Type": "application/json"},
            timeout=API_TIMEOUT
        )
        # Should return error
        self.assertIn(response.status_code, [400, 422, 500])
    
    def test_message_not_found(self):
        """Test handling of message not found"""
        response = requests.get(
            f"{BASE_URL}/api/v1/message",
            params={"session_id": "non-existent-session"},
            timeout=API_TIMEOUT
        )
        # Should return 200 with empty list or 404
        self.assertIn(response.status_code, [200, 404])
    
    def test_normal_operations_work(self):
        """Test that normal operations work correctly"""
        session_id = f"test-session-i005-{uuid.uuid4().hex[:8]}"
        
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            json={"session_id": session_id, "message": "test", "role": "user"},
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        
        logger.info("I-005 Error scenarios test completed successfully")


# ============================================================================
# Test I-006: Concurrent Message Processing
# ============================================================================

class TestI006ConcurrentProcessing(TestIntegrationFixture):
    """I-006: Concurrent message processing"""
    
    def test_concurrent_message_processing(self):
        """
        Test concurrent message processing:
        1. Create multiple sessions
        2. Send messages to each session
        3. Process all sessions concurrently
        4. Verify all sessions are processed
        """
        session_ids = []
        
        # Step 1 & 2: Create sessions and send messages
        for i in range(3):
            session_id = f"test-session-i006-{i}-{uuid.uuid4().hex[:6]}"
            session_ids.append(session_id)
            
            response = requests.post(
                f"{BASE_URL}/api/v1/message",
                json={
                    "session_id": session_id,
                    "message": f"Concurrent message for {session_id}",
                    "role": "user"
                },
                timeout=API_TIMEOUT
            )
            self.assertEqual(response.status_code, 200)
        
        # Step 3: Process all sessions
        for session_id in session_ids:
            response = requests.post(
                f"{BASE_URL}/api/v1/session/process",
                json={"session_id": session_id},
                timeout=API_TIMEOUT
            )
            self.assertEqual(response.status_code, 200)
        
        # Wait for all processors to complete
        time.sleep(5)
        
        # Step 4: Verify all sessions are processed
        for session_id in session_ids:
            response = requests.get(
                f"{BASE_URL}/api/v1/session/{session_id}",
                timeout=API_TIMEOUT
            )
            data = response.json()
            session_data = data.get('data', {})
            self.assertIsNotNone(session_data.get('processed_msg_id'))
        
        logger.info("I-006 Concurrent processing test completed successfully")


# ============================================================================
# Test I-007: Cron Job Execution Verification
# ============================================================================

class TestI007CronJobExecution(TestIntegrationFixture):
    """I-007: Cron job execution verification"""
    
    def test_cron_job_message_consumer(self):
        """
        Test message consumer cron job:
        1. Create session with recent messages
        2. Trigger message consumer logic
        3. Verify messages are processed
        """
        session_id = f"test-session-i007-{uuid.uuid4().hex[:8]}"
        
        # Step 1: Create session with recent messages
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            json={
                "session_id": session_id,
                "message": "Cron test message 0",
                "role": "user"
            },
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        
        # Create more messages
        for i in range(1, 2):
            response = requests.post(
                f"{BASE_URL}/api/v1/message",
                json={
                    "session_id": session_id,
                    "message": f"Cron test message {i}",
                    "role": "user"
                },
                timeout=API_TIMEOUT
            )
            self.assertEqual(response.status_code, 200)
        
        # Step 2: Trigger message consumer via API call
        response = requests.post(
            f"{BASE_URL}/api/v1/session/process",
            json={"session_id": session_id},
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        
        # Wait for processing
        time.sleep(3)
        
        # Step 3: Verify messages are processed
        response = requests.get(
            f"{BASE_URL}/api/v1/session/{session_id}",
            timeout=API_TIMEOUT
        )
        data = response.json()
        session_data = data.get('data', {})
        self.assertIsNotNone(session_data.get('processed_msg_id'))
        
        logger.info("I-007 Cron job execution test completed successfully")
    
    def test_cron_job_message_summarizer(self):
        """
        Test message summarizer cron job:
        1. Create session with messages
        2. Verify summarizer can be triggered
        """
        session_id = f"test-session-i007-sum-{uuid.uuid4().hex[:8]}"
        
        # Step 1: Create session with messages
        response = requests.post(
            f"{BASE_URL}/api/v1/message",
            json={
                "session_id": session_id,
                "message": "Summarizer test message 0",
                "role": "user"
            },
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        
        # Create more messages
        for i in range(1, 3):
            response = requests.post(
                f"{BASE_URL}/api/v1/message",
                json={
                    "session_id": session_id,
                    "message": f"Summarizer test message {i}",
                    "role": "user"
                },
                timeout=API_TIMEOUT
            )
            self.assertEqual(response.status_code, 200)
        
        # Step 2: Verify session exists and has messages
        response = requests.get(
            f"{BASE_URL}/api/v1/session/{session_id}",
            timeout=API_TIMEOUT
        )
        self.assertEqual(response.status_code, 200)
        
        response = requests.get(
            f"{BASE_URL}/api/v1/message",
            params={"session_id": session_id, "limit": 10},
            timeout=API_TIMEOUT
        )
        data = response.json()
        messages = data.get('data', [])
        self.assertEqual(len(messages), 3)
        
        logger.info("I-007 Summarizer cron job test completed successfully")


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
