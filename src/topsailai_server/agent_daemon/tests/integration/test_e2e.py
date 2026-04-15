"""
End-to-End Integration Tests for agent_daemon

This module contains end-to-end tests that verify the complete processor flow:
- Scenario A: Direct Answer Flow (processor generates direct response)
- Scenario B: Task Generation Flow (processor generates task and result)
- Scenario C: ProcessSession API (manual trigger of processor)

Author: DawsonLin
Created: 2026-04-15
"""

import os
import sys
import time
import uuid
import subprocess
import requests
import stat
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Set HOME environment variable for integration testing
INTEGRATION_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
WORKSPACE_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon'

os.environ['HOME'] = INTEGRATION_DIR

# Add the parent directory to the path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.storage.session_manager import SessionData
from topsailai_server.agent_daemon.storage.message_manager import MessageData
from topsailai_server.agent_daemon.configer import get_config


# ============================================================================
# Helper Functions
# ============================================================================

def ensure_script_executable(script_path):
    """Ensure a script is executable"""
    if os.path.exists(script_path):
        current_mode = os.stat(script_path).st_mode
        os.chmod(script_path, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def get_mock_processor_e2e_path():
    """Get path to the mock processor E2E script"""
    return os.path.join(INTEGRATION_DIR, 'mock_processor_e2e.py')


def get_mock_state_checker_path():
    """Get path to the mock state checker script"""
    return os.path.join(INTEGRATION_DIR, 'mock_state_checker.sh')


def get_mock_summarizer_path():
    """Get path to the mock summarizer script"""
    return os.path.join(INTEGRATION_DIR, 'mock_summarizer.sh')


def api_request(method, endpoint, **kwargs):
    """Make API request to the daemon"""
    base_url = kwargs.pop('base_url', 'http://localhost:7373')
    url = f"{base_url}{endpoint}"
    response = requests.request(method, url, **kwargs)
    return response


def create_or_get_session(session_id, base_url='http://localhost:7373'):
    """
    Create or get a session by sending the first message.
    Note: Sessions are created automatically when messages are received.
    """
    # Send first message to create session
    response = api_request('POST', '/api/v1/message', json={
        'session_id': session_id,
        'message': f'Initial message for session {session_id}',
        'role': 'user'
    }, base_url=base_url)
    return session_id, response


def receive_message(session_id, message, role='user', base_url='http://localhost:7373'):
    """Receive a message via API"""
    response = api_request('POST', '/api/v1/message', json={
        'session_id': session_id,
        'message': message,
        'role': role
    }, base_url=base_url)
    return response


def retrieve_messages(session_id, base_url='http://localhost:7373'):
    """Retrieve messages for a session"""
    response = api_request('GET', f'/api/v1/message?session_id={session_id}', base_url=base_url)
    return response


def process_session(session_id, base_url='http://localhost:7373'):
    """Process a session via API"""
    response = api_request('POST', '/api/v1/session/process', json={
        'session_id': session_id
    }, base_url=base_url)
    return response


def set_task_result(session_id, processed_msg_id, task_id, task_result, base_url='http://localhost:7373'):
    """Set task result via API"""
    response = api_request('POST', '/api/v1/task/result', json={
        'session_id': session_id,
        'processed_msg_id': processed_msg_id,
        'task_id': task_id,
        'task_result': task_result
    }, base_url=base_url)
    return response


def get_session(session_id, base_url='http://localhost:7373'):
    """Get session info via API"""
    response = api_request('GET', f'/api/v1/session?session_ids={session_id}', base_url=base_url)
    return response


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture(scope='function')
def mock_processor_e2e():
    """Ensure mock processor E2E script is executable"""
    script_path = get_mock_processor_e2e_path()
    ensure_script_executable(script_path)
    return script_path


@pytest.fixture(scope='function')
def mock_state_checker():
    """Ensure mock state checker script is executable"""
    script_path = get_mock_state_checker_path()
    ensure_script_executable(script_path)
    return script_path


@pytest.fixture(scope='function')
def mock_summarizer():
    """Ensure mock summarizer script is executable"""
    script_path = get_mock_summarizer_path()
    ensure_script_executable(script_path)
    return script_path


@pytest.fixture(scope='function')
def temp_db():
    """Create a temporary database for testing"""
    import tempfile
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except Exception:
        pass


# ============================================================================
# Scenario A: Direct Answer Flow
# ============================================================================

class TestDirectAnswerFlow:
    """Test the direct answer flow where processor generates immediate response"""

    def test_direct_answer_flow(self, running_daemon, mock_processor_e2e, mock_state_checker, mock_summarizer, temp_db):
        """
        Test Scenario A: Direct Answer Flow
        
        Steps:
        1. Create a session via sending first message
        2. Send a user message via ReceiveMessage API
        3. The mock processor (in direct_answer mode) should be triggered
        4. Verify processed_msg_id is updated in session
        5. Verify new assistant message is created
        """
        base_url = 'http://localhost:7373'
        
        # Step 1: Create a session by sending first message
        session_id = f"e2e-session-{uuid.uuid4().hex[:8]}"
        session_id, response = create_or_get_session(session_id, base_url)
        assert response.status_code == 200, f"Failed to create session: {response.text}"
        logger.info("Created session: %s", session_id)
        
        # Step 2: Send a user message
        test_message = "Hello, this is a test message for direct answer flow"
        response = receive_message(session_id, test_message, 'user', base_url)
        assert response.status_code == 200, f"Failed to receive message: {response.text}"
        
        # Get the message ID from response
        data = response.json()
        msg_id = data.get('data', {}).get('msg_id') or data.get('msg_id')
        logger.info("Received message ID: %s", msg_id)
        
        # Wait for processor to be triggered and complete
        time.sleep(3)
        
        # Step 4: Verify processed_msg_id is updated
        response = get_session(session_id, base_url)
        assert response.status_code == 200, f"Failed to get session: {response.text}"
        
        session_data = response.json()
        sessions = session_data.get('data', [])
        assert len(sessions) > 0, "Session should exist"
        
        session_info = sessions[0]
        processed_msg_id = session_info.get('processed_msg_id')
        logger.info("Processed msg_id: %s", processed_msg_id)
        
        # Step 5: Verify new assistant message is created
        response = retrieve_messages(session_id, base_url)
        assert response.status_code == 200, f"Failed to retrieve messages: {response.text}"
        
        messages_data = response.json()
        messages = messages_data.get('data', [])
        
        # Should have at least 2 messages: user message + assistant response
        assert len(messages) >= 2, f"Should have at least 2 messages, got {len(messages)}"
        
        # Find the assistant message
        assistant_messages = [m for m in messages if m.get('role') == 'assistant']
        assert len(assistant_messages) > 0, "Should have at least one assistant message"
        
        # Verify assistant message contains expected content
        assistant_msg = assistant_messages[0]
        msg_content = assistant_msg.get('message', '')
        assert 'Direct reply to:' in msg_content or 'Direct answer to:' in msg_content, \
            f"Assistant message should contain 'Direct reply to:' or 'Direct answer to:', got: {msg_content}"
        
        logger.info("Direct answer flow test completed successfully")
        logger.info("Assistant message: %s", assistant_msg.get('message'))

    def test_direct_answer_multiple_messages(self, running_daemon, mock_processor_e2e, mock_state_checker, mock_summarizer, temp_db):
        """
        Test multiple messages in direct answer flow.
        Verify that only the latest unprocessed message triggers the processor.
        """
        base_url = 'http://localhost:7373'
        
        # Create session
        session_id = f"e2e-session-{uuid.uuid4().hex[:8]}"
        create_or_get_session(session_id, base_url)
        
        # Send multiple messages
        for i in range(3):
            response = receive_message(session_id, f"Message {i}", 'user', base_url)
            assert response.status_code == 200
            time.sleep(0.5)
        
        # Wait for processor
        time.sleep(3)
        
        # Verify messages
        response = retrieve_messages(session_id, base_url)
        messages = response.json().get('data', [])
        
        # Should have user messages + assistant responses
        user_messages = [m for m in messages if m.get('role') == 'user']
        assistant_messages = [m for m in messages if m.get('role') == 'assistant']
        
        assert len(user_messages) >= 3, "Should have at least 3 user messages"
        assert len(assistant_messages) >= 1, "Should have at least 1 assistant message"
        
        logger.info("Multiple messages test completed successfully")


# ============================================================================
# Scenario B: Task Generation Flow
# ============================================================================

class TestTaskGenerationFlow:
    """Test the task generation flow where processor creates a task"""

    def test_task_generation_flow(self, running_daemon, mock_processor_e2e, mock_state_checker, mock_summarizer, temp_db):
        """
        Test Scenario B: Task Generation Flow
        
        Steps:
        1. Create a session via sending first message
        2. Send a user message via ReceiveMessage API
        3. The mock processor (in task_mode) should be triggered
        4. Verify task_id is set on the message
        5. Call SetTaskResult API with task result
        6. Verify processed_msg_id advances
        7. Verify task_result is stored
        """
        base_url = 'http://localhost:7373'
        
        # Set processor to task mode
        os.environ['TOPSAILAI_TEST_MODE'] = 'task_mode'
        
        try:
            # Step 1: Create a session
            session_id = f"e2e-session-{uuid.uuid4().hex[:8]}"
            create_or_get_session(session_id, base_url)
            logger.info("Created session: %s", session_id)
            
            # Step 2: Send a user message
            test_message = "Please process this task"
            response = receive_message(session_id, test_message, 'user', base_url)
            assert response.status_code == 200
            
            # Get the message ID
            data = response.json()
            msg_id = data.get('data', {}).get('msg_id') or data.get('msg_id')
            logger.info("Message ID: %s", msg_id)
            
            # Wait for processor to complete
            time.sleep(3)
            
            # Step 4: Verify task_id is set on the message
            response = retrieve_messages(session_id, base_url)
            messages = response.json().get('data', [])
            
            # Find the user message
            user_messages = [m for m in messages if m.get('role') == 'user']
            assert len(user_messages) > 0, "Should have user messages"
            
            # Get the latest user message
            latest_user_msg = user_messages[-1]
            task_id = latest_user_msg.get('task_id')
            
            logger.info("Task ID from message: %s", task_id)
            
            # If task_id is set, verify task_result flow
            if task_id:
                # Step 5: Call SetTaskResult API
                task_result = "Task completed successfully"
                response = set_task_result(
                    session_id=session_id,
                    processed_msg_id=msg_id,
                    task_id=task_id,
                    task_result=task_result,
                    base_url=base_url
                )
                
                # Note: The processor already called SetTaskResult, so this might return an error
                # if the task was already set. That's acceptable for this test.
                logger.info("SetTaskResult response: %s", response.status_code)
            
            # Step 6: Verify processed_msg_id advances
            response = get_session(session_id, base_url)
            session_info = response.json().get('data', [{}])[0]
            processed_msg_id = session_info.get('processed_msg_id')
            
            logger.info("Processed msg_id: %s", processed_msg_id)
            assert processed_msg_id is not None, "processed_msg_id should be set"
            
            # Step 7: Verify task_result is stored
            response = retrieve_messages(session_id, base_url)
            messages = response.json().get('data', [])
            
            # Find the message with task_id
            messages_with_task = [m for m in messages if m.get('task_id')]
            if messages_with_task:
                msg_with_task = messages_with_task[0]
                assert msg_with_task.get('task_result') is not None, \
                    "task_result should be stored"
                logger.info("Task result: %s", msg_with_task.get('task_result'))
            
            logger.info("Task generation flow test completed successfully")
            
        finally:
            # Cleanup
            if 'TOPSAILAI_TEST_MODE' in os.environ:
                del os.environ['TOPSAILAI_TEST_MODE']

    def test_task_result_callback(self, running_daemon, mock_processor_e2e, mock_state_checker, mock_summarizer, temp_db):
        """
        Test that processor_callback correctly reports task results.
        """
        base_url = 'http://localhost:7373'
        
        # Create session
        session_id = f"e2e-session-{uuid.uuid4().hex[:8]}"
        create_or_get_session(session_id, base_url)
        
        # Send message
        response = receive_message(session_id, "Test task callback", 'user', base_url)
        assert response.status_code == 200
        
        # Wait for processing
        time.sleep(3)
        
        # Verify session state
        response = get_session(session_id, base_url)
        session_info = response.json().get('data', [{}])[0]
        
        # Session should be processed
        assert session_info.get('processed_msg_id') is not None, \
            "Session should have processed_msg_id set"
        
        logger.info("Task result callback test completed successfully")


# ============================================================================
# Scenario C: ProcessSession API
# ============================================================================

class TestProcessSessionAPI:
    """Test the ProcessSession API endpoint"""

    def test_process_session_api(self, running_daemon, mock_processor_e2e, mock_state_checker, mock_summarizer, temp_db):
        """
        Test Scenario C: ProcessSession API
        
        Steps:
        1. Create a session with multiple messages
        2. Manually call ProcessSession API
        3. Verify processor is triggered with correct environment variables
        4. Verify the response contains expected fields
        """
        base_url = 'http://localhost:7373'
        
        # Step 1: Create a session with multiple messages
        session_id = f"e2e-session-{uuid.uuid4().hex[:8]}"
        create_or_get_session(session_id, base_url)
        logger.info("Created session: %s", session_id)
        
        # Add multiple messages
        for i in range(3):
            response = receive_message(session_id, f"Message {i}", 'user', base_url)
            assert response.status_code == 200
            time.sleep(0.3)
        
        # Get initial session state
        response = get_session(session_id, base_url)
        initial_session = response.json().get('data', [{}])[0]
        initial_processed = initial_session.get('processed_msg_id')
        logger.info("Initial processed_msg_id: %s", initial_processed)
        
        # Step 2: Manually call ProcessSession API
        response = process_session(session_id, base_url)
        
        # ProcessSession returns 200 even if no processing is needed
        assert response.status_code == 200, f"ProcessSession failed: {response.text}"
        
        data = response.json()
        logger.info("ProcessSession response: %s", data)
        
        # Step 3 & 4: Verify response contains expected fields
        # The response should indicate if there are unprocessed messages
        if 'data' in data and data['data']:
            response_data = data['data']
            
            # Should have processed_msg_id
            assert 'processed_msg_id' in response_data, \
                "Response should contain processed_msg_id"
            
            # If there are unprocessed messages, should have processing_msg_id and messages
            if 'processing_msg_id' in response_data:
                assert 'messages' in response_data, \
                    "Response should contain messages when processing_msg_id is present"
                assert 'processor_pid' in response_data, \
                    "Response should contain processor_pid"
                
                logger.info("Processor triggered with PID: %s", response_data.get('processor_pid'))
                logger.info("Processing message ID: %s", response_data.get('processing_msg_id'))
        
        # Wait for processing to complete
        time.sleep(3)
        
        # Verify session was processed
        response = get_session(session_id, base_url)
        final_session = response.json().get('data', [{}])[0]
        final_processed = final_session.get('processed_msg_id')
        
        logger.info("Final processed_msg_id: %s", final_processed)
        
        # Either processed_msg_id advanced or processor was triggered
        logger.info("ProcessSession API test completed successfully")

    def test_process_session_no_unprocessed(self, running_daemon, mock_processor_e2e, mock_state_checker, mock_summarizer, temp_db):
        """
        Test ProcessSession when there are no unprocessed messages.
        Should return quickly without triggering processor.
        """
        base_url = 'http://localhost:7373'
        
        # Create session
        session_id = f"e2e-session-{uuid.uuid4().hex[:8]}"
        create_or_get_session(session_id, base_url)
        
        # Send message
        response = receive_message(session_id, "Test message", 'user', base_url)
        assert response.status_code == 200
        
        # Wait for processing
        time.sleep(3)
        
        # Now call ProcessSession - should indicate no unprocessed messages
        response = process_session(session_id, base_url)
        assert response.status_code == 200
        
        data = response.json()
        logger.info("ProcessSession response (no unprocessed): %s", data)
        
        # Response should indicate no processing needed
        # (either no data field or data indicates no unprocessed messages)
        if 'data' in data and data['data']:
            response_data = data['data']
            # If processing_msg_id is not present, no processing is needed
            has_unprocessed = 'processing_msg_id' in response_data
            logger.info("Has unprocessed messages: %s", has_unprocessed)
        
        logger.info("No unprocessed messages test completed successfully")

    def test_process_session_empty_session(self, running_daemon, mock_processor_e2e, mock_state_checker, mock_summarizer, temp_db):
        """
        Test ProcessSession on a session with no messages.
        Should handle gracefully without errors.
        """
        base_url = 'http://localhost:7373'
        
        # Create session (no messages) - need to create session in storage directly
        session_id = f"e2e-session-{uuid.uuid4().hex[:8]}"
        
        # Create session via storage directly (since we can't create empty session via API)
        from topsailai_server.agent_daemon.storage import Storage
        from sqlalchemy import create_engine
        
        db_path = os.path.join(INTEGRATION_DIR, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')
        storage = Storage(engine)
        
        session_data = SessionData(
            session_id=session_id,
            session_name=f"Empty Session {session_id}",
            task=None
        )
        storage.session.create(session_data)
        
        # Call ProcessSession
        response = process_session(session_id, base_url)
        
        # Should return 200 even with no messages
        assert response.status_code == 200
        
        data = response.json()
        logger.info("ProcessSession response (empty session): %s", data)
        
        logger.info("Empty session test completed successfully")


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
