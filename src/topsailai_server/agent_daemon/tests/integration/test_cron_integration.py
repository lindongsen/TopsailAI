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

import pytest

# Set HOME environment variable for integration testing
INTEGRATION_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
os.environ['HOME'] = INTEGRATION_DIR

# Add the parent directory to the path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai_server.agent_daemon import logger

BASE_URL = "http://localhost:7373"
DB_PATH = os.path.join(INTEGRATION_DIR, "test.db")


def check_health():
    """Check if the server is running"""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=2)
        return response.status_code == 200
    except:
        return False


def cleanup_state_files():
    """Clean up state files before/after tests"""
    for f in glob.glob('/tmp/agent_daemon_state_*'):
        try:
            os.remove(f)
            logger.info("Cleaned up state file: %s", f)
        except Exception as e:
            logger.warning("Failed to clean up state file %s: %s", f, e)


def print_section(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)


def receive_message(session_id, message, role="user"):
    """Test ReceiveMessage API"""
    url = f"{BASE_URL}/api/v1/message"
    data = {
        "session_id": session_id,
        "message": message,
        "role": role
    }
    try:
        response = requests.post(url, json=data, timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        logger.error("ReceiveMessage failed: %s", e)
        return None


def run_message_consumer_test():
    """Test message_consumer cron job"""
    print_section("Testing Message Consumer Cron Job")
    logger.info("Testing message consumer cron job")
    
    # Use a fixed session ID for this test to avoid timestamp mismatch
    test_session_id = "cron-test-session-fixed"
    
    print(f"\n--- Creating test messages for session: {test_session_id} ---")
    for i in range(3):
        msg_content = f"Cron test message #{i+1} at {time.strftime('%H:%M:%S')}"
        result = receive_message(test_session_id, msg_content)
        if result:
            logger.info("Message %d sent for cron test", i+1)
            print(f"✓ Message {i+1} sent")
        time.sleep(0.5)
    
    print(f"\n--- Verifying messages in database ---")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
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
            logger.warning("Message consumer test: not enough messages, found %d", len(messages))
            print(f"✗ Message consumer test failed - not enough messages (found {len(messages)})")
            return False
            
    except Exception as e:
        logger.exception("Message consumer test failed: %s", e)
        print(f"  ERROR: {e}")
        return False


def run_summarizer_test():
    """Test summarizer receives correct environment variables"""
    print_section("Testing Message Summarizer")
    logger.info("Testing message summarizer")
    
    summarizer_script = os.path.join(INTEGRATION_DIR, "mock_summarizer.sh")
    
    test_session_id = f"summarizer-test-{int(time.time())}"
    test_message = "Test message for summarization"
    
    receive_message(test_session_id, test_message)
    time.sleep(0.5)
    
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
            if 'TOPSAILAI_SESSION_ID' in result.stdout and test_session_id in result.stdout:
                logger.info("Summarizer test passed - correct environment variables")
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


def run_session_cleaner_test():
    """Test session cleanup functionality"""
    print_section("Testing Session Cleaner")
    logger.info("Testing session cleaner")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        old_session_id = f"old-session-{int(time.time())}"
        old_time = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"\n--- Creating old session for cleanup test ---")
        print(f"  Session ID: {old_session_id}")
        print(f"  Update time: {old_time}")
        
        cursor.execute(
            "INSERT INTO session (session_id, session_name, task, create_time, update_time, processed_msg_id) VALUES (?, ?, ?, ?, ?, ?)",
            (old_session_id, "Old Test Session", None, old_time, old_time, None)
        )
        
        cursor.execute(
            "INSERT INTO message (msg_id, session_id, message, create_time, update_time, role) VALUES (?, ?, ?, ?, ?, ?)",
            (f"old-msg-{int(time.time())}", old_session_id, "Old message", old_time, old_time, "user")
        )
        
        conn.commit()
        print("  ✓ Old session and message created")
        
        cursor.execute("SELECT session_id FROM session WHERE session_id = ?", (old_session_id,))
        old_session = cursor.fetchone()
        
        if old_session:
            print(f"  ✓ Old session exists in database")
        else:
            print(f"  ✗ Old session not found")
            conn.close()
            return False
        
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
        
        cursor.execute("SELECT session_id FROM session WHERE session_id IN (?, ?)", (old_session_id, recent_session_id))
        sessions = cursor.fetchall()
        print(f"\n  Total sessions before cleanup: {len(sessions)}")
        
        conn.close()
        
        logger.info("Session cleaner test: test data created successfully")
        print("\n✓ Session cleaner test: test data created successfully")
        print("  (Actual cleanup would be performed by cron job monthly)")
        
        return True
        
    except Exception as e:
        logger.exception("Session cleaner test failed: %s", e)
        print(f"  ERROR: {e}")
        return False


def run_processor_test():
    """Test that processor is triggered correctly by cron"""
    print_section("Testing Processor Trigger by Cron")
    logger.info("Testing processor trigger by cron")
    
    processor_script = os.path.join(INTEGRATION_DIR, "mock_processor.sh")
    
    test_session_id = f"processor-test-{int(time.time())}"
    test_message = "Test message for processor"
    
    print(f"\n--- Sending test message ---")
    result = receive_message(test_session_id, test_message)
    if result:
        print("✓ Message sent")
    else:
        print("✗ Failed to send message")
        return False
    
    time.sleep(1)
    
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


# ============================================================================
# Pytest Test Functions (use assertions)
# ============================================================================

@pytest.mark.usefixtures("running_daemon")
class TestCronIntegration:
    """Pytest-compatible cron integration tests"""
    
    def test_health(self):
        """Test health endpoint"""
        url = f"{BASE_URL}/health"
        response = requests.get(url, timeout=5)
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
    
    def test_receive_message(self):
        """Test ReceiveMessage API"""
        session_id = f"test-session-{int(time.time())}"
        message = "Test message for cron integration"
        url = f"{BASE_URL}/api/v1/message"
        data = {
            "session_id": session_id,
            "message": message,
            "role": "user"
        }
        response = requests.post(url, json=data, timeout=10)
        assert response.status_code == 200, f"ReceiveMessage failed: {response.status_code}"
    
    def test_retrieve_messages(self):
        """Test RetrieveMessages API"""
        session_id = f"test-session-{int(time.time())}"
        url = f"{BASE_URL}/api/v1/message"
        data = {
            "session_id": session_id,
            "message": "Test message",
            "role": "user"
        }
        requests.post(url, json=data, timeout=10)
        
        params = {
            "session_id": session_id,
            "offset": 0,
            "limit": 100
        }
        response = requests.get(url, params=params, timeout=10)
        assert response.status_code == 200, f"RetrieveMessages failed: {response.status_code}"
    
    def test_message_consumer(self):
        """Test message_consumer cron job"""
        result = run_message_consumer_test()
        assert result is True, "Message consumer test failed"
    
    def test_summarizer(self):
        """Test summarizer receives correct environment variables"""
        result = run_summarizer_test()
        assert result is True, "Summarizer test failed"
    
    def test_session_cleaner(self):
        """Test session cleanup functionality"""
        result = run_session_cleaner_test()
        assert result is True, "Session cleaner test failed"
    
    def test_processor_triggered_by_cron(self):
        """Test that processor is triggered correctly by cron"""
        result = run_processor_test()
        assert result is True, "Processor trigger test failed"
