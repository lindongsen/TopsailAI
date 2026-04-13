#!/usr/bin/env python3
"""
Integration test script for agent_daemon
Tests the full workflow: ReceiveMessage -> RetrieveMessages -> SetTaskResult -> processed_msg_id verification
"""

import requests
import json
import time
import sys
import os
import sqlite3
import subprocess
import glob
import signal
from datetime import datetime

# Set HOME environment variable for integration testing
INTEGRATION_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
os.environ['HOME'] = INTEGRATION_DIR

# Add the parent directory to the path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai_server.agent_daemon import logger

BASE_URL = "http://localhost:7373"
SESSION_ID = "test-session-001"
DB_PATH = os.path.join(INTEGRATION_DIR, "test.db")

# Server process handle
_server_process = None


def cleanup_state_files():
    """Clean up state files before/after tests"""
    for f in glob.glob('/tmp/agent_daemon_state_*'):
        try:
            os.remove(f)
            logger.info("Cleaned up state file: %s", f)
        except Exception as e:
            logger.warning("Failed to clean up state file %s: %s", f, e)


def create_session_in_db(session_id, session_name=None):
    """Create a session directly in the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Create session table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session (
                session_id TEXT PRIMARY KEY,
                session_name TEXT,
                task TEXT,
                create_time TEXT,
                update_time TEXT,
                processed_msg_id TEXT
            )
        """)
        
        # Insert session
        cursor.execute("""
            INSERT OR REPLACE INTO session 
            (session_id, session_name, task, create_time, update_time, processed_msg_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, session_name or session_id, None, now, now, None))
        
        conn.commit()
        conn.close()
        logger.info("Created session in database: %s", session_id)
        return True
    except Exception as e:
        logger.exception("Failed to create session: %s", e)
        return False


def start_server():
    """Start agent_daemon server for testing"""
    global _server_process
    
    logger.info("Starting agent_daemon server for integration testing")
    
    # Clean up old state files
    cleanup_state_files()
    
    # Set environment variables
    env = os.environ.copy()
    env['HOME'] = INTEGRATION_DIR
    env['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = os.path.join(INTEGRATION_DIR, 'mock_processor.sh')
    env['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = os.path.join(INTEGRATION_DIR, 'mock_summarizer.sh')
    env['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = os.path.join(INTEGRATION_DIR, 'mock_state_checker.sh')
    env['TOPSAILAI_AGENT_DAEMON_DB_URL'] = f'sqlite:///{DB_PATH}'
    env['TOPSAILAI_AGENT_DAEMON_PORT'] = '7373'
    env['TOPSAILAI_AGENT_DAEMON_HOST'] = '0.0.0.0'
    
    # Remove old database if exists to start fresh
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
            logger.info("Removed old database: %s", DB_PATH)
        except Exception as e:
            logger.warning("Failed to remove old database: %s", e)
    
    # Start server process
    log_file = open(os.path.join(INTEGRATION_DIR, 'server.log'), 'w')
    
    _server_process = subprocess.Popen(
        ['python3', '-m', 'topsailai_server.agent_daemon.main'],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd='/root/ai/TopsailAI/src',
        preexec_fn=os.setsid  # Create new process group for clean shutdown
    )
    
    # Wait for server to start
    logger.info("Waiting for server to start (PID: %d)", _server_process.pid)
    for i in range(30):
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=1)
            if response.status_code == 200:
                logger.info("Server started successfully after %d seconds", i + 1)
                print(f"Server started successfully (PID: {_server_process.pid})")
                return True
        except:
            pass
        time.sleep(1)
    
    logger.error("Server failed to start within 30 seconds")
    print("ERROR: Server failed to start")
    return False


def stop_server():
    """Stop the agent_daemon server"""
    global _server_process
    
    if _server_process is None:
        logger.warning("No server process to stop")
        return
    
    logger.info("Stopping agent_daemon server (PID: %d)", _server_process.pid)
    
    try:
        # Send SIGTERM to the process group
        os.killpg(os.getpgid(_server_process.pid), signal.SIGTERM)
        
        # Wait for process to stop
        for _ in range(10):
            if _server_process.poll() is not None:
                break
            time.sleep(0.5)
        
        # Force kill if still running
        if _server_process.poll() is None:
            logger.warning("Server did not stop gracefully, forcing...")
            os.killpg(os.getpgid(_server_process.pid), signal.SIGKILL)
            time.sleep(0.5)
        
        logger.info("Server stopped successfully")
        print("Server stopped")
        
    except Exception as e:
        logger.exception("Error stopping server: %s", e)
        print(f"Error stopping server: {e}")
    
    _server_process = None
    
    # Clean up state files
    cleanup_state_files()


def print_section(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)


def print_request(method, url, data=None):
    print(f"\n>>> REQUEST: {method} {url}")
    if data:
        print(f"    Payload: {json.dumps(data, indent=2)}")


def print_response(response):
    print(f"\n<<< RESPONSE: Status {response.status_code}")
    try:
        print(f"    Body: {json.dumps(response.json(), indent=2)}")
    except:
        print(f"    Body: {response.text}")


def test_health():
    """Test health endpoint"""
    print_section("1. Health Check")
    url = f"{BASE_URL}/health"
    print_request("GET", url)
    try:
        response = requests.get(url, timeout=5)
        print_response(response)
        return response.status_code == 200
    except Exception as e:
        logger.error("Health check failed: %s", e)
        print(f"    ERROR: {e}")
        return False


def test_receive_message(msg_id, message, role="user", processed_msg_id=None):
    """Test ReceiveMessage API"""
    url = f"{BASE_URL}/api/v1/message"
    data = {
        "session_id": SESSION_ID,
        "message": message,
        "role": role
    }
    if processed_msg_id:
        data["processed_msg_id"] = processed_msg_id
    
    print_request("POST", url, data)
    try:
        response = requests.post(url, json=data, timeout=10)
        print_response(response)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        logger.error("ReceiveMessage failed: %s", e)
        print(f"    ERROR: {e}")
        return None


def test_retrieve_messages():
    """Test RetrieveMessages API"""
    url = f"{BASE_URL}/api/v1/message"
    params = {
        "session_id": SESSION_ID,
        "offset": 0,
        "limit": 100
    }
    print_request("GET", f"{url}?{requests.compat.urlencode(params)}")
    try:
        response = requests.get(url, params=params, timeout=10)
        print_response(response)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        logger.error("RetrieveMessages failed: %s", e)
        print(f"    ERROR: {e}")
        return None


def test_retrieve_tasks():
    """Test RetrieveTasks API"""
    url = f"{BASE_URL}/api/v1/task"
    params = {
        "session_id": SESSION_ID,
        "offset": 0,
        "limit": 100
    }
    print_request("GET", f"{url}?{requests.compat.urlencode(params)}")
    try:
        response = requests.get(url, params=params, timeout=10)
        print_response(response)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        logger.error("RetrieveTasks failed: %s", e)
        print(f"    ERROR: {e}")
        return None


def test_set_task_result(session_id, processed_msg_id, task_id, task_result):
    """Test SetTaskResult API"""
    url = f"{BASE_URL}/api/v1/task"
    data = {
        "session_id": session_id,
        "processed_msg_id": processed_msg_id,
        "task_id": task_id,
        "task_result": task_result
    }
    print_request("POST", url, data)
    try:
        response = requests.post(url, json=data, timeout=10)
        print_response(response)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        logger.error("SetTaskResult failed: %s", e)
        print(f"    ERROR: {e}")
        return None


def verify_processed_msg_id(expected_msg_id):
    """Verify session's processed_msg_id is updated correctly"""
    print(f"\n--- Verifying processed_msg_id ---")
    logger.info("Checking processed_msg_id, expected: %s", expected_msg_id)
    
    try:
        # Query the database directly
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT processed_msg_id FROM session WHERE session_id = ?",
            (SESSION_ID,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            actual_msg_id = result[0]
            logger.info("Actual processed_msg_id: %s", actual_msg_id)
            print(f"  Expected: {expected_msg_id}")
            print(f"  Actual: {actual_msg_id}")
            
            if actual_msg_id == expected_msg_id:
                print("  ✓ processed_msg_id matches!")
                return True
            else:
                print("  ✗ processed_msg_id mismatch!")
                return False
        else:
            logger.warning("Session not found in database")
            print("  ✗ Session not found in database")
            return False
    except Exception as e:
        logger.exception("Failed to verify processed_msg_id: %s", e)
        print(f"  ERROR: {e}")
        return False


def verify_database_state():
    """Verify database state after operations"""
    print(f"\n--- Verifying Database State ---")
    logger.info("Verifying database state")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check session table
        cursor.execute("SELECT session_id, session_name, processed_msg_id, update_time FROM session WHERE session_id = ?", (SESSION_ID,))
        session = cursor.fetchone()
        if session:
            print(f"  Session: {session}")
        else:
            print("  ✗ No session found")
        
        # Check message table
        cursor.execute("SELECT COUNT(*) FROM message WHERE session_id = ?", (SESSION_ID,))
        msg_count = cursor.fetchone()[0]
        print(f"  Messages count: {msg_count}")
        
        # Check task table
        cursor.execute("SELECT COUNT(*) FROM message WHERE session_id = ? AND task_id IS NOT NULL", (SESSION_ID,))
        task_count = cursor.fetchone()[0]
        print(f"  Tasks count: {task_count}")
        
        conn.close()
        return True
    except Exception as e:
        logger.exception("Failed to verify database state: %s", e)
        print(f"  ERROR: {e}")
        return False


def test_concurrent_processing():
    """Test concurrent message processing scenario"""
    print_section("Concurrent Processing Test")
    logger.info("Testing concurrent message processing scenario")
    
    # First, check current state
    state_checker = os.path.join(INTEGRATION_DIR, "mock_state_checker.sh")
    
    # Set state to "processing" to simulate concurrent processing
    state_file = f"/tmp/agent_daemon_state_{SESSION_ID}"
    try:
        with open(state_file, 'w') as f:
            f.write("processing")
        logger.info("Set state file to processing: %s", state_file)
        print(f"  State file created: {state_file}")
    except Exception as e:
        logger.error("Failed to create state file: %s", e)
        print(f"  ERROR: {e}")
        return False
    
    # Try to send a message - it should not trigger processor due to "processing" state
    msg_content = "Test message during processing state"
    result = test_receive_message("msg-concurrent", msg_content)
    
    # Clean up state file
    try:
        os.remove(state_file)
        logger.info("Cleaned up state file")
    except:
        pass
    
    if result:
        print("  ✓ Message sent during processing state")
        return True
    else:
        print("  ✗ Failed to send message during processing state")
        return False


def run_integration_test():
    """Run the full integration test workflow"""
    print_section("AGENT DAEMON INTEGRATION TEST")
    logger.info("Starting integration test")
    print(f"Session ID: {SESSION_ID}")
    print(f"Base URL: {BASE_URL}")
    print(f"DB Path: {DB_PATH}")
    print(f"HOME: {os.environ.get('HOME')}")
    
    # Start the server
    if not start_server():
        logger.error("Failed to start server")
        print("ERROR: Failed to start server")
        return False
    
    try:
        # Create session in database first
        print("\n--- Creating session in database ---")
        create_session_in_db(SESSION_ID, "Integration Test Session")
        
        # Test iterations
        messages_sent = []
        last_msg_id = None
        
        for i in range(1, 6):  # 5 iterations
            print_section(f"ITERATION {i}: Send and Retrieve Message")
            
            # Step 2: Send message
            msg_content = f"Test message #{i} from integration test at {time.strftime('%H:%M:%S')}"
            result = test_receive_message(f"msg-{i}", msg_content)
            if result:
                messages_sent.append(msg_content)
                logger.info("Message %d sent successfully", i)
                print(f"✓ Message {i} sent successfully")
            else:
                logger.error("Failed to send message %d", i)
                print(f"✗ Failed to send message {i}")
                continue
            
            # Small delay to allow processing
            time.sleep(1)
            
            # Step 3: Retrieve messages
            print(f"\n--- Retrieving messages after sending message {i} ---")
            messages = test_retrieve_messages()
            if messages and messages.get('code') == 0:
                # API returns list directly, not dict with 'items' key
                data = messages.get('data', [])
                if isinstance(data, list):
                    items = data
                else:
                    items = data.get('items', []) if isinstance(data, dict) else []
                print(f"✓ Retrieved {len(items)} messages")
                for msg in items[:3]:  # Show first 3
                    print(f"    - [{msg.get('role')}] {msg.get('message')[:50]}...")
                    last_msg_id = msg.get('msg_id')
            else:
                logger.warning("Failed to retrieve messages")
                print("✗ Failed to retrieve messages")
            
            # Step 4: Check for tasks
            print(f"\n--- Checking for tasks ---")
            tasks = test_retrieve_tasks()
            if tasks and tasks.get('code') == 0:
                # API returns list directly, not dict with 'items' key
                data = tasks.get('data', [])
                if isinstance(data, list):
                    items = data
                else:
                    items = data.get('items', []) if isinstance(data, dict) else []
                if items:
                    print(f"✓ Found {len(items)} tasks")
                    for task in items[:3]:
                        print(f"    - Task: {task.get('task_id')}, Result: {task.get('task_result', 'N/A')[:50]}...")
                else:
                    print("ℹ No tasks found (expected for mock processor)")
            else:
                logger.warning("Failed to retrieve tasks")
                print("✗ Failed to retrieve tasks")
            
            time.sleep(1)  # Delay between iterations
        
        # Test SetTaskResult API
        print_section("Testing SetTaskResult API")
        task_result = test_set_task_result(
            session_id=SESSION_ID,
            processed_msg_id="msg-test-task",
            task_id="task-test-001",
            task_result="Test task result from integration test"
        )
        if task_result and task_result.get('code') == 0:
            logger.info("SetTaskResult API test passed")
            print("✓ SetTaskResult API test passed")
        else:
            logger.warning("SetTaskResult API test failed or returned error")
            print("ℹ SetTaskResult API test result:", task_result)
        
        # Verify processed_msg_id
        if last_msg_id:
            verify_processed_msg_id(last_msg_id)
        
        # Verify database state
        verify_database_state()
        
        # Test concurrent processing scenario
        test_concurrent_processing()
        
        # Final summary
        print_section("TEST SUMMARY")
        print(f"Messages sent: {len(messages_sent)}")
        print(f"Session ID: {SESSION_ID}")
        print("\nAll iterations completed!")
        logger.info("Integration test completed")
        
        return True
        
    finally:
        # Stop the server
        stop_server()


if __name__ == "__main__":
    success = run_integration_test()
    sys.exit(0 if success else 1)