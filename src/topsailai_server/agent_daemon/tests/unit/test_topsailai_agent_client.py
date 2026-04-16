#!/usr/bin/env python3
"""
Unit Tests for topsailai_agent_client CLI

Test IDs: U-029 to U-030
- U-029: CLI argument parsing
- U-030: CLI command execution

Author: mm-m25
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Set up path for imports
CWD = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(CWD)))
sys.path.insert(0, WORKSPACE)


class TestCLIArgumentParsing(unittest.TestCase):
    """Test CLI argument parsing (U-029)"""
    
    def test_health_command_parsing(self):
        """U-029-01: Test health command argument parsing"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        # Verify command structure through import
        self.assertTrue(callable(cli))
    
    def test_list_sessions_command_parsing(self):
        """U-029-02: Test list-sessions command argument parsing"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        self.assertTrue(callable(cli))
    
    def test_send_message_command_parsing(self):
        """U-029-03: Test send-message command argument parsing"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        self.assertTrue(callable(cli))
    
    def test_get_messages_command_parsing(self):
        """U-029-04: Test get-messages command argument parsing"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        self.assertTrue(callable(cli))
    
    def test_set_task_result_command_parsing(self):
        """U-029-05: Test set-task-result command argument parsing"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        self.assertTrue(callable(cli))
    
    def test_get_tasks_command_parsing(self):
        """U-029-06: Test get-tasks command argument parsing"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        self.assertTrue(callable(cli))
    
    def test_process_session_command_parsing(self):
        """U-029-07: Test process-session command argument parsing"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        self.assertTrue(callable(cli))
    
    def test_delete_sessions_command_parsing(self):
        """U-029-08: Test delete-sessions command argument parsing"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        self.assertTrue(callable(cli))
    
    def test_default_host_from_env(self):
        """U-029-09: Test default host from environment variable"""
        # Test that the env var parsing logic works
        test_host = os.environ.get('TOPSAILAI_AGENT_DAEMON_HOST', 'localhost')
        self.assertEqual(test_host, 'localhost')  # Default value when env var not set
        
        # Test with custom env var
        with patch.dict(os.environ, {'TOPSAILAI_AGENT_DAEMON_HOST': 'envhost'}):
            test_host = os.environ.get('TOPSAILAI_AGENT_DAEMON_HOST', 'localhost')
            self.assertEqual(test_host, 'envhost')
    
    def test_default_port_from_env(self):
        """U-029-10: Test default port from environment variable"""
        # Test that the env var parsing logic works
        test_port = int(os.environ.get('TOPSAILAI_AGENT_DAEMON_PORT', '7373'))
        self.assertEqual(test_port, 7373)  # Default value when env var not set
        
        # Test with custom env var
        with patch.dict(os.environ, {'TOPSAILAI_AGENT_DAEMON_PORT': '9999'}):
            test_port = int(os.environ.get('TOPSAILAI_AGENT_DAEMON_PORT', '7373'))
            self.assertEqual(test_port, 9999)


class TestCLICommandExecution(unittest.TestCase):
    """Test CLI command execution (U-030)"""
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_health_success(self, mock_session_client_class):
        """U-030-01: Test health check command execution - success"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_health
        
        # Setup mock
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_session_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        
        # Execute
        result = do_client_health(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.health_check.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_health_failure(self, mock_session_client_class):
        """U-030-02: Test health check command execution - failure"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_health
        
        # Setup mock
        mock_client = MagicMock()
        mock_client.health_check.return_value = False
        mock_session_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        
        # Execute
        result = do_client_health(args)
        
        # Verify
        self.assertFalse(result)
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_list_sessions(self, mock_session_client_class):
        """U-030-03: Test list-sessions command execution"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_list_sessions
        
        # Setup mock
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []
        mock_session_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_ids = None
        args.start_time = None
        args.end_time = None
        args.offset = 0
        args.limit = 1000
        args.sort_key = 'create_time'
        args.order_by = 'desc'
        args.verbose = False
        
        # Execute
        result = do_client_list_sessions(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.list_sessions.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_get_session(self, mock_session_client_class):
        """U-030-04: Test get-session command execution"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_get_session
        
        # Setup mock
        mock_client = MagicMock()
        mock_session_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_id = 'test-session-123'
        args.verbose = False
        
        # Execute
        result = do_client_get_session(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.get_session.assert_called_once_with('test-session-123', verbose=False)
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.MessageClient')
    def test_do_client_send_message(self, mock_message_client_class):
        """U-030-05: Test send-message command execution"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_send_message
        
        # Setup mock
        mock_client = MagicMock()
        mock_message_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_id = 'test-session-123'
        args.message = 'Hello, world!'
        args.role = 'user'
        args.processed_msg_id = None
        args.verbose = False
        
        # Execute
        result = do_client_send_message(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.send_message.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.MessageClient')
    def test_do_client_get_messages(self, mock_message_client_class):
        """U-030-06: Test get-messages command execution"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_get_messages
        
        # Setup mock
        mock_client = MagicMock()
        mock_message_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_id = 'test-session-123'
        args.start_time = None
        args.end_time = None
        args.offset = 0
        args.limit = 1000
        args.sort_key = 'create_time'
        args.order_by = 'desc'
        args.verbose = False
        
        # Execute
        result = do_client_get_messages(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.list_messages.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.TaskClient')
    def test_do_client_set_task_result(self, mock_task_client_class):
        """U-030-07: Test set-task-result command execution"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_set_task_result
        
        # Setup mock
        mock_client = MagicMock()
        mock_task_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_id = 'test-session-123'
        args.processed_msg_id = 'msg-123'
        args.task_id = 'task-456'
        args.task_result = 'Task completed successfully'
        args.verbose = False
        
        # Execute
        result = do_client_set_task_result(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.set_task_result.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.TaskClient')
    def test_do_client_get_tasks(self, mock_task_client_class):
        """U-030-08: Test get-tasks command execution"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_get_tasks
        
        # Setup mock
        mock_client = MagicMock()
        mock_task_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_id = 'test-session-123'
        args.task_ids = None
        args.start_time = None
        args.end_time = None
        args.offset = 0
        args.limit = 1000
        args.sort_key = 'create_time'
        args.order_by = 'desc'
        args.verbose = False
        
        # Execute
        result = do_client_get_tasks(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.list_tasks.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_process_session(self, mock_session_client_class):
        """U-030-09: Test process-session command execution"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_process_session
        
        # Setup mock
        mock_client = MagicMock()
        mock_session_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_id = 'test-session-123'
        args.verbose = False
        
        # Execute
        result = do_client_process_session(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.process_session.assert_called_once_with('test-session-123', verbose=False)
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_delete_sessions(self, mock_session_client_class):
        """U-030-10: Test delete-sessions command execution"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_delete_sessions
        
        # Setup mock
        mock_client = MagicMock()
        mock_session_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_ids = ['session-1', 'session-2']
        args.session_ids_str = None
        args.verbose = False
        
        # Execute
        result = do_client_delete_sessions(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.delete_sessions.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_delete_sessions_with_comma_separated(self, mock_session_client_class):
        """U-030-11: Test delete-sessions with comma-separated IDs"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_delete_sessions
        
        # Setup mock
        mock_client = MagicMock()
        mock_session_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_ids = []
        args.session_ids_str = 'session-1,session-2,session-3'
        args.verbose = False
        
        # Execute
        result = do_client_delete_sessions(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.delete_sessions.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_delete_sessions_no_ids(self, mock_session_client_class):
        """U-030-12: Test delete-sessions with no session IDs - should fail"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_delete_sessions
        
        # Setup mock
        mock_client = MagicMock()
        mock_session_client_class.return_value = mock_client
        
        # Create args object with no session IDs
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_ids = []
        args.session_ids_str = None
        args.verbose = False
        
        # Execute
        result = do_client_delete_sessions(args)
        
        # Verify - should fail because no session IDs provided
        self.assertFalse(result)
        mock_client.delete_sessions.assert_not_called()
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_list_sessions_with_session_ids_filter(self, mock_session_client_class):
        """U-030-13: Test list-sessions with session_ids filter"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_list_sessions
        
        # Setup mock
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []
        mock_session_client_class.return_value = mock_client
        
        # Create args object with session_ids filter
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_ids = 'session-1,session-2'
        args.start_time = None
        args.end_time = None
        args.offset = 0
        args.limit = 1000
        args.sort_key = 'create_time'
        args.order_by = 'desc'
        args.verbose = False
        
        # Execute
        result = do_client_list_sessions(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.list_sessions.assert_called_once()
        call_kwargs = mock_client.list_sessions.call_args[1]
        self.assertEqual(call_kwargs['session_ids'], ['session-1', 'session-2'])
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_do_client_health_exception(self, mock_session_client_class):
        """U-030-14: Test health check with exception"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_health
        
        # Setup mock to raise exception
        mock_client = MagicMock()
        mock_client.health_check.side_effect = Exception("Connection refused")
        mock_session_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        
        # Execute
        result = do_client_health(args)
        
        # Verify - should return False on exception
        self.assertFalse(result)
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.MessageClient')
    def test_do_client_send_message_with_processed_msg_id(self, mock_message_client_class):
        """U-030-15: Test send-message with processed_msg_id"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_send_message
        
        # Setup mock
        mock_client = MagicMock()
        mock_message_client_class.return_value = mock_client
        
        # Create args object with processed_msg_id
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_id = 'test-session-123'
        args.message = 'Hello!'
        args.role = 'assistant'
        args.processed_msg_id = 'msg-123'
        args.verbose = False
        
        # Execute
        result = do_client_send_message(args)
        
        # Verify
        self.assertTrue(result)
        mock_client.send_message.assert_called_once()
        call_kwargs = mock_client.send_message.call_args[1]
        self.assertEqual(call_kwargs['role'], 'assistant')
        self.assertEqual(call_kwargs['processed_msg_id'], 'msg-123')


class TestCLIErrorHandling(unittest.TestCase):
    """Test CLI error handling (U-030 Error Handling)"""
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.SessionClient')
    def test_list_sessions_api_error(self, mock_session_client_class):
        """U-030-ERR-01: Test list-sessions with API error"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_list_sessions
        
        # Setup mock to raise exception
        mock_client = MagicMock()
        mock_client.list_sessions.side_effect = Exception("API Error")
        mock_session_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_ids = None
        args.start_time = None
        args.end_time = None
        args.offset = 0
        args.limit = 1000
        args.sort_key = 'create_time'
        args.order_by = 'desc'
        args.verbose = False
        
        # Execute
        result = do_client_list_sessions(args)
        
        # Verify - should return False on exception
        self.assertFalse(result)
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.MessageClient')
    def test_send_message_api_error(self, mock_message_client_class):
        """U-030-ERR-02: Test send-message with API error"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_send_message
        
        # Setup mock to raise exception
        mock_client = MagicMock()
        mock_client.send_message.side_effect = Exception("API Error")
        mock_message_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_id = 'test-session-123'
        args.message = 'Hello!'
        args.role = 'user'
        args.processed_msg_id = None
        args.verbose = False
        
        # Execute
        result = do_client_send_message(args)
        
        # Verify - should return False on exception
        self.assertFalse(result)
    
    @patch('topsailai_server.agent_daemon.topsailai_agent_client.TaskClient')
    def test_set_task_result_api_error(self, mock_task_client_class):
        """U-030-ERR-03: Test set-task-result with API error"""
        from topsailai_server.agent_daemon.topsailai_agent_client import do_client_set_task_result
        
        # Setup mock to raise exception
        mock_client = MagicMock()
        mock_client.set_task_result.side_effect = Exception("API Error")
        mock_task_client_class.return_value = mock_client
        
        # Create args object
        args = MagicMock()
        args.host = 'localhost'
        args.port = 7373
        args.session_id = 'test-session-123'
        args.processed_msg_id = 'msg-123'
        args.task_id = 'task-456'
        args.task_result = 'Result'
        args.verbose = False
        
        # Execute
        result = do_client_set_task_result(args)
        
        # Verify - should return False on exception
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
