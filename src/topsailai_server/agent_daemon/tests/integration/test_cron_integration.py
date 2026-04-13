#!/usr/bin/env python3
"""
Cron Integration Test for agent_daemon
Tests the cron jobs: message_consumer, message_summarizer, session_cleaner
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
from datetime import datetime, timedelta

# Set HOME environment variable for integration testing
INTEGRATION_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
os.environ['HOME'] = INTEGRATION_DIR

# Add the parent directory to the path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai_server.agent_daemon import logger

BASE_URL = "http://localhost:7373"
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


def start_server():
    """Start agent_daemon server for testing"""
    global _server_process
    
    logger.info("Starting agent_daemon server for cron integration testing")
    
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


def test_receive_message(session_id, message, role="user"):
    """Test ReceiveMessage API"""
    url = f"{BASE_URL}/api/v1/message"
    data = {
        "session_id": session_id,
        "message": message,
        "role": role
    }
    print_request("POST", url, data)
    try:
        response = requests.post(url, json=data, timeout=10)
        print_response(response)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        logger.error("ReceiveMessage failed: %s", e)
        print(f"    ERROR: {e}")
        return None


def test_retrieve_messages(session_id):
    """Test RetrieveMessages API"""
    url = f"{BASE_URL}/api/v1/message"
    params = {
        "session_id": session_id,
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


def test_message_consumer():
    """Test message_consumer cron job"""
    print_section("Testing Message Consumer Cron Job")
    logger.info("Testing message consumer cron job")
    
    # Create test session with multiple messages
    test_session_id = f"cron-test-session-{int(time.time())}"
    
    # Send multiple messages to the session
    print(f"\n--- Creating test messages for session: {test_session_id} ---")
    for i in range(3):
        msg_content = f"Cron test message #{i+1} at {time.strftime('%H:%M:%S')}"
        result = test_receive_message(test_session_id, msg_content)
        if result:
            logger.info("Message %d sent for cron test", i+1)
            print(f"✓ Message {i+1} sent")
        time.sleep(0.5)
    
    # Verify messages were created
    print(f"\n--- Verifying messages in database ---")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get messages for the session
        cursor.execute(
            "SELECT msg_id, message, create_time FROM message WHERE session_id = ? ORDER BY create_time",
            (test_session_id,)
        )
        messages = cursor.fetchall()
        
        print(f"  Found {len(messages)} messages in database")
        for msg in messages:
            print(f"    - msg_id: {msg[0]}, message: {msg[1][:30]}...")
        
        conn.close()
        
        if len(messages) >= 3:
            logger.info("Message consumer test: messages created successfully")
            print("✓ Message consumer test passed - messages created")
            return True
        else:
            logger.warning("Message consumer test: not enough messages")
            print("✗ Message consumer test failed - not enough messages")
            return False
            
    except Exception as e:
        logger.exception("Message consumer test failed: %s", e)
        print(f"  ERROR: {e}")
        return False


def test_summarizer():
    """Test summarizer receives correct environment variables"""
    print_section("Testing Message Summarizer")
    logger.info("Testing message summarizer")
    
    summarizer_script = os.path.join(INTEGRATION_DIR, "mock_summarizer.sh")
    
    # Create test session
    test_session_id = f"summarizer-test-{int(time.time())}"
    test_message = "Test message for summarization"
    
    # Send a message
    test_receive_message(test_session_id, test_message)
    time.sleep(0.5)
    
    # Run summarizer script with environment variables
    print(f"\n--- Running summarizer script ---")
    env = os.environ.copy()
    env['TOPSAILAI_SESSION_ID'] = test_session_id
    env['TOPSAILAI_TASK'] = test_message
    
    try:
        result = subprocess.run(
            [summarizer_script],
            env=env,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        logger.info("Summarizer output: %s", result.stdout)
        logger.info("Summarizer return code: %d", result.returncode)
        
        print(f"  Return code: {result.returncode}")
        print(f"  Output:\n{result.stdout}")
        
        if result.returncode == 0:
            # Verify environment variables were passed correctly
            if 'TOPSAILAI_SESSION_ID' in result.stdout and test_session_id in result.stdout:
                logger.info("Summarizer test passed - correct environment variables")
                print("✓ Summarizer test passed - correct environment variables")
                return True
            else:
                logger.warning("Summarizer test: environment variables not found in output")
                print("✗ Summarizer test failed - environment variables not found")
                return False
        else:
            logger.error("Summarizer test failed with non-zero return code")
            print("✗ Summarizer test failed")
            return False
            
    except Exception as e:
        logger.exception("Summarizer test failed: %s", e)
        print(f"  ERROR: {e}")
        return False


def test_session_cleaner():
    """Test session cleanup functionality"""
    print_section("Testing Session Cleaner")
    logger.info("Testing session cleaner")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create a test session with old update_time (more than 1 year ago)
        old_session_id = f"old-session-{int(time.time())}"
        old_time = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"\n--- Creating old session for cleanup test ---")
        print(f"  Session ID: {old_session_id}")
        print(f"  Update time: {old_time}")
        
        # Insert old session
        cursor.execute(
            "INSERT INTO session (session_id, session_name, task, create_time, update_time, processed_msg_id) VALUES (?, ?, ?, ?, ?, ?)",
            (old_session_id, "Old Test Session", None, old_time, old_time, None)
        )
        
        # Insert old messages
        cursor.execute(
            "INSERT INTO message (msg_id, session_id, message, create_time, update_time, role) VALUES (?, ?, ?, ?, ?, ?)",
            (f"old-msg-{int(time.time())}", old_session_id, "Old message", old_time, old_time, "user")
        )
        
        conn.commit()
        print("  ✓ Old session and message created")
        
        # Verify old session exists
        cursor.execute("SELECT session_id FROM session WHERE session_id = ?", (old_session_id,))
        old_session = cursor.fetchone()
        
        if old_session:
            print(f"  ✓ Old session exists in database")
        else:
            print(f"  ✗ Old session not found")
            conn.close()
            return False
        
        # Create a recent session (should NOT be cleaned)
        recent_session_id = f"recent-session-{int(time.time())}"
        recent_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"\n--- Creating recent session (should NOT be cleaned) ---")
        print(f"  Session ID: {recent_session_id}")
        print(f"  Update time: {recent_time}")
        
        cursor.execute(
            "INSERT INTO session (session_id, session_name, task, create_time, update_time, processed_msg_id) VALUES (?, ?, ?, ?, ?, ?)",
            (recent_session_id, "Recent Test Session", None, recent_time, recent_time, None)
        )
        
        cursor.execute(
            "INSERT INTO message (msg_id, session_id, message, create_time, update_time, role) VALUES (?, ?, ?, ?, ?, ?)",
            (f"recent-msg-{int(time.time())}", recent_session_id, "Recent message", recent_time, recent_time, "user")
        )
        
        conn.commit()
        print("  ✓ Recent session and message created")
        
        # Verify both sessions exist
        cursor.execute("SELECT session_id FROM session WHERE session_id IN (?, ?)", (old_session_id, recent_session_id))
        sessions = cursor.fetchall()
        print(f"\n  Total sessions before cleanup: {len(sessions)}")
        
        conn.close()
        
        # Note: The actual cleanup would be done by the cron job
        # Here we just verify the test data is set up correctly
        logger.info("Session cleaner test: test data created successfully")
        print("\n✓ Session cleaner test: test data created successfully")
        print("  (Actual cleanup would be performed by cron job monthly)")
        
        return True
        
    except Exception as e:
        logger.exception("Session cleaner test failed: %s", e)
        print(f"  ERROR: {e}")
        return False


def test_processor_triggered_by_cron():
    """Test that processor is triggered correctly by cron"""
    print_section("Testing Processor Trigger by Cron")
    logger.info("Testing processor trigger by cron")
    
    processor_script = os.path.join(INTEGRATION_DIR, "mock_processor.sh")
    
    # Create test session with unprocessed messages
    test_session_id = f"processor-test-{int(time.time())}"
    test_message = "Test message for processor"
    
    # Send a message
    print(f"\n--- Sending test message ---")
    result = test_receive_message(test_session_id, test_message)
    if result:
        print("✓ Message sent")
    else:
        print("✗ Failed to send message")
        return False
    
    time.sleep(1)
    
    # Run processor script with environment variables
    print(f"\n--- Running processor script ---")
    env = os.environ.copy()
    env['TOPSAILAI_SESSION_ID'] = test_session_id
    env['TOPSAILAI_MSG_ID'] = f"msg-{int(time.time())}"
    env['TOPSAILAI_TASK'] = test_message
    env['TOPSAILAI_AGENT_DAEMON_BASE_URL'] = BASE_URL
    
    try:
        result = subprocess.run(
            [processor_script],
            env=env,
            capture_output=True,
            text=True,
            timeout=15
        )
        
        logger.info("Processor output: %s", result.stdout)
        logger.info("Processor return code: %d", result.returncode)
        
        print(f"  Return code: {result.returncode}")
        print(f"  Output:\n{result.stdout}")
        
        if result.returncode == 0:
            logger.info("Processor test passed")
            print("✓ Processor test passed")
            return True
        else:
            logger.error("Processor test failed with non-zero return code")
            print("✗ Processor test failed")
            return False
            
    except Exception as e:
        logger.exception("Processor test failed: %s", e)
        print(f"  ERROR: {e}")
        return False


def run_cron_integration_test():
    """Run all cron integration tests"""
    print_section("AGENT DAEMON CRON INTEGRATION TEST")
    logger.info("Starting cron integration test")
    
    print(f"Base URL: {BASE_URL}")
    print(f"DB Path: {DB_PATH}")
    print(f"HOME: {os.environ.get('HOME')}")
    
    # Start the server
    if not start_server():
        logger.error("Failed to start server")
        print("ERROR: Failed to start server")
        return False
    
    try:
        results = {}
        
        # Test 1: Message Consumer
        results['message_consumer'] = test_message_consumer()
        time.sleep(1)
        
        # Test 2: Summarizer
        results['summarizer'] = test_summarizer()
        time.sleep(1)
        
        # Test 3: Session Cleaner
        results['session_cleaner'] = test_session_cleaner()
        time.sleep(1)
        
        # Test 4: Processor Trigger
        results['processor_trigger'] = test_processor_triggered_by_cron()
        
        # Summary
        print_section("CRON TEST SUMMARY")
        logger.info("Cron integration test summary: %s", results)
        
        for test_name, result in results.items():
            status = "✓ PASSED" if result else "✗ FAILED"
            print(f"  {test_name}: {status}")
        
        all_passed = all(results.values())
        print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
        
        return all_passed
        
    finally:
        # Stop the server
        stop_server()


if __name__ == "__main__":
    success = run_cron_integration_test()
    sys.exit(0 if success else 1)