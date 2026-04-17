#!/usr/bin/env python3
"""
Client Operations Integration Tests for agent_daemon

Tests all CLI operations of topsailai_agent_client comprehensively.
These tests require the server to be running. Use --start-server flag to auto-start.
"""

import subprocess
import uuid
import pytest
import time
import concurrent.futures
from pathlib import Path

# Constants
CLIENT_SCRIPT = Path(__file__).parent.parent.parent / "topsailai_agent_client.py"
BASE_URL = "http://localhost:7373"


def run_client_command(args, check=True):
    """Run a client command and return result"""
    cmd = ["python", str(CLIENT_SCRIPT)] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=CLIENT_SCRIPT.parent
    )
    if check and result.returncode != 0:
        # Some commands return 0 but print error messages
        pass
    return result


class TestClientBasicOperations:
    """Test basic client operations"""

    def test_health_check(self, require_server):
        """Test health command"""
        result = run_client_command(['health'])
        assert result.returncode == 0
        assert 'healthy' in result.stdout.lower() or 'health' in result.stdout.lower()

    def test_list_sessions_empty(self, require_server):
        """Test list-sessions with no sessions"""
        result = run_client_command(['list-sessions'])
        assert result.returncode == 0
        # Should show empty or no sessions message


class TestClientSessionManagement:
    """Test session management operations"""

    def test_send_message_creates_session(self, require_server):
        """Test send-message creates a new session"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        result = run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', 'Hello from test'
        ])
        assert result.returncode == 0
        assert 'sent successfully' in result.stdout.lower()
        
        # Verify session was created
        result = run_client_command(['list-sessions'])
        assert session_id in result.stdout
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_send_message_with_assistant_role(self, require_server):
        """Test send-message with assistant role"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        result = run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'assistant',
            '--message', 'Assistant response'
        ])
        assert result.returncode == 0
        assert 'sent successfully' in result.stdout.lower()
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_get_messages(self, require_server):
        """Test get-messages command"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        # Send a message
        run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', 'Test message for get'
        ])
        
        # Get messages
        result = run_client_command(['get-messages', '--session-id', session_id])
        assert result.returncode == 0
        assert 'retrieved' in result.stdout.lower()
        assert 'Test message for get' in result.stdout
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_list_messages(self, require_server):
        """Test list-messages command"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        # Send multiple messages
        for i in range(3):
            run_client_command([
                'send-message',
                '--session-id', session_id,
                '--role', 'user',
                '--message', f'Message {i}'
            ])
        
        # List messages
        result = run_client_command(['list-messages', '--session-id', session_id])
        assert result.returncode == 0
        assert 'retrieved' in result.stdout.lower()
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_send_message_with_processed_msg_id(self, require_server):
        """Test send-message with processed-msg-id"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        # Send first message
        run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', 'First message'
        ])
        
        # Get the message ID - format: [timestamp] [msg_id] [role]
        result = run_client_command(['get-messages', '--session-id', session_id])
        lines = result.stdout.split('\n')
        msg_id = None
        for line in lines:
            # Look for line with pattern: [timestamp] [msg_id] [user]
            if '[' in line and 'user' in line:
                # Parse: [2026-04-15 21:51:46] [126d3eda162aa7] [user]
                parts = line.split('] [')
                if len(parts) >= 2:
                    msg_id = parts[1].strip()
                    break
        
        if msg_id:
            # Send reply with processed-msg-id
            result = run_client_command([
                'send-message',
                '--session-id', session_id,
                '--role', 'assistant',
                '--message', 'Reply to first',
                '--processed-msg-id', msg_id
            ])
            assert result.returncode == 0
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)


class TestClientTaskManagement:
    """Test task management operations"""

    def test_set_task_result(self, require_server):
        """Test set-task-result command"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        # Send message
        run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', 'Task message'
        ])
        
        # Get message ID - format: [timestamp] [msg_id] [role]
        result = run_client_command(['get-messages', '--session-id', session_id])
        lines = result.stdout.split('\n')
        msg_id = None
        for line in lines:
            # Parse: [2026-04-15 21:51:46] [126d3eda162aa7] [user]
            if '[' in line and 'user' in line:
                parts = line.split('] [')
                if len(parts) >= 2:
                    msg_id = parts[1].strip()
                    break
        
        # Set task result
        if msg_id:
            result = run_client_command([
                'set-task-result',
                '--session-id', session_id,
                '--processed-msg-id', msg_id,
                '--task-id', 'task-001',
                '--task-result', 'Task completed successfully'
            ])
            assert result.returncode == 0
            assert 'set successfully' in result.stdout.lower() or 'success' in result.stdout.lower()
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_get_tasks(self, require_server):
        """Test get-tasks command"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        # Send message and create task
        run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', 'Task for get-tasks'
        ])
        
        # Get tasks
        result = run_client_command(['get-tasks', '--session-id', session_id])
        assert result.returncode == 0
        assert 'retrieved' in result.stdout.lower() or 'task' in result.stdout.lower()
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_list_tasks(self, require_server):
        """Test list-tasks command"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        # Send message
        run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', 'Task for list-tasks'
        ])
        
        # List tasks
        result = run_client_command(['list-tasks', '--session-id', session_id])
        assert result.returncode == 0
        assert 'retrieved' in result.stdout.lower() or 'task' in result.stdout.lower()
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)


class TestClientSessionProcessing:
    """Test session processing operations"""

    def test_process_session(self, require_server):
        """Test process-session command"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        # Send message
        run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', 'Process this session'
        ])
        
        # Process session
        result = run_client_command(['process-session', '--session-id', session_id])
        assert result.returncode == 0
        assert 'processed' in result.stdout.lower()
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_delete_single_session(self, require_server):
        """Test delete-sessions with single session"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        # Create session
        run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', 'Session to delete'
        ])
        
        # Verify session exists
        result = run_client_command(['list-sessions'])
        assert session_id in result.stdout
        
        # Delete session
        result = run_client_command(['delete-sessions', session_id])
        assert result.returncode == 0
        assert 'deleted' in result.stdout.lower()
        
        # Verify session is gone
        result = run_client_command(['list-sessions'])
        assert session_id not in result.stdout

    def test_delete_multiple_sessions(self, require_server):
        """Test delete-sessions with multiple sessions"""
        session_ids = [f"test-session-{uuid.uuid4().hex[:8]}" for _ in range(3)]
        
        # Create sessions
        for session_id in session_ids:
            run_client_command([
                'send-message',
                '--session-id', session_id,
                '--role', 'user',
                '--message', f'Message for {session_id}'
            ])
        
        # Delete all sessions
        result = run_client_command(['delete-sessions'] + session_ids)
        assert result.returncode == 0
        assert 'deleted' in result.stdout.lower()
        
        # Verify all sessions are gone
        result = run_client_command(['list-sessions'])
        for session_id in session_ids:
            assert session_id not in result.stdout


class TestClientEdgeCases:
    """Test edge cases and error handling"""

    def test_send_message_special_characters(self, require_server):
        """Test send-message with special characters"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        special_content = "Special chars: <>&\"' and unicode: 你好世界 🌍"
        result = run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', special_content
        ])
        assert result.returncode == 0
        
        # Verify message was stored
        result = run_client_command(['get-messages', '--session-id', session_id])
        assert '你好世界' in result.stdout or '🌍' in result.stdout
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_send_message_unicode(self, require_server):
        """Test send-message with unicode content"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        unicode_content = "Unicode test: 日本語 한국어 العربية עברית"
        result = run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', unicode_content
        ])
        assert result.returncode == 0
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_send_message_long_content(self, require_server):
        """Test send-message with long content"""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        long_content = "A" * 1000  # 1000 character message
        result = run_client_command([
            'send-message',
            '--session-id', session_id,
            '--role', 'user',
            '--message', long_content
        ])
        assert result.returncode == 0
        
        # Cleanup
        run_client_command(['delete-sessions', session_id], check=False)

    def test_get_messages_nonexistent_session(self, require_server):
        """Test get-messages with non-existent session"""
        result = run_client_command([
            'get-messages',
            '--session-id', f"nonexistent-{uuid.uuid4().hex}"
        ])
        # Should handle gracefully
        assert result.returncode == 0

    def test_process_session_nonexistent(self, require_server):
        """Test process-session with non-existent session"""
        result = run_client_command([
            'process-session',
            '--session-id', f"nonexistent-{uuid.uuid4().hex}"
        ])
        # Should handle gracefully
        assert result.returncode == 0

    def test_delete_nonexistent_session(self, require_server):
        """Test delete-sessions with non-existent session"""
        result = run_client_command([
            'delete-sessions',
            f"nonexistent-session-{uuid.uuid4().hex}"
        ])
        assert result.returncode == 0
        # Should report 0 deleted or similar
        assert '0' in result.stdout or 'deleted' in result.stdout.lower()


class TestClientConcurrentOperations:
    """Test concurrent operations"""

    def test_multiple_sessions_independent(self, require_server):
        """Test that multiple sessions are independent"""
        session_ids = [f"test-session-{uuid.uuid4().hex[:8]}" for _ in range(5)]
        
        # Create sessions concurrently
        def create_session(session_id):
            return run_client_command([
                'send-message',
                '--session-id', session_id,
                '--role', 'user',
                '--message', f'Message for {session_id}'
            ])
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_session, sid) for sid in session_ids]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # All should succeed
        for result in results:
            assert result.returncode == 0
        
        # Verify all sessions exist
        result = run_client_command(['list-sessions'])
        for session_id in session_ids:
            assert session_id in result.stdout
        
        # Cleanup
        run_client_command(['delete-sessions'] + session_ids, check=False)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
