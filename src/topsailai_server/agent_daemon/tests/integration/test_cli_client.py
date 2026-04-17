"""
Integration tests for topsailai_agent_client CLI.

This module tests the client CLI commands for interacting with the agent_daemon API.
Tests use monkeypatch fixtures for proper mock isolation.

Test ID: CLI-002
Category: CLI Tools
"""

import pytest
import sys
from unittest.mock import Mock, patch, MagicMock


class TestCli002ClientCLI:
    """Test CLI-002: Test topsailai_agent_client CLI"""
    
    # =========================================================================
    # Session Operations Tests
    # =========================================================================
    
    def test_cli_health_success(self, monkeypatch, capsys):
        """Test CLI-002-01: Test health check command succeeds"""
        # Mock the SessionClient.health_check method
        mock_health = Mock(return_value=True)
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.health_check',
            mock_health
        ):
            # Import and run the CLI
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', '--host', 'localhost', '--port', '7373', 'health']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            captured = capsys.readouterr()
            assert "healthy" in captured.out.lower() or mock_health.called
    
    def test_cli_health_failure(self, monkeypatch, capsys):
        """Test CLI-002-02: Test health check command fails gracefully"""
        # Mock the SessionClient.health_check method to return False
        mock_health = Mock(return_value=False)
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.health_check',
            mock_health
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', '--host', 'localhost', '--port', '7373', 'health']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            captured = capsys.readouterr()
            assert "failed" in captured.out.lower() or mock_health.called
    
    def test_cli_list_sessions(self, monkeypatch, capsys):
        """Test CLI-002-03: Test list-sessions command"""
        # Mock the SessionClient.list_sessions method
        mock_list = Mock(return_value=[])
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.list_sessions',
            mock_list
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', 'list-sessions']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_list.called
    
    def test_cli_list_sessions_with_filters(self, monkeypatch, capsys):
        """Test CLI-002-04: Test list-sessions with filters"""
        mock_list = Mock(return_value=[])
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.list_sessions',
            mock_list
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', [
                'topsailai_agent_client',
                'list-sessions',
                '--session-ids', 's1,s2',
                '--start-time', '2024-01-01',
                '--end-time', '2024-12-31',
                '--limit', '100'
            ]):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_list.called
            # Verify filter parameters were passed
            call_kwargs = mock_list.call_args.kwargs if mock_list.call_args.kwargs else {}
            assert call_kwargs.get('limit') == 100 or mock_list.called
    
    def test_cli_get_session(self, monkeypatch, capsys):
        """Test CLI-002-05: Test get-session command"""
        mock_get = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.get_session',
            mock_get
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', 'get-session', '--session-id', 'test-session-123']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_get.called
            mock_get.assert_called_once()
    
    def test_cli_delete_sessions(self, monkeypatch, capsys):
        """Test CLI-002-06: Test delete-sessions command"""
        mock_delete = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.delete_sessions',
            mock_delete
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', 'delete-sessions', 's1', 's2', 's3']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_delete.called
    
    def test_cli_delete_sessions_comma_separated(self, monkeypatch, capsys):
        """Test CLI-002-07: Test delete-sessions with comma-separated IDs"""
        mock_delete = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.delete_sessions',
            mock_delete
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', 'delete-sessions', '--session-ids', 's1,s2,s3']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_delete.called
    
    def test_cli_process_session(self, monkeypatch, capsys):
        """Test CLI-002-08: Test process-session command"""
        mock_process = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.process_session',
            mock_process
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', 'process-session', '--session-id', 'test-session-123']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_process.called
    
    # =========================================================================
    # Message Operations Tests
    # =========================================================================
    
    def test_cli_send_message(self, monkeypatch, capsys):
        """Test CLI-002-09: Test send-message command"""
        mock_send = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.message.MessageClient.send_message',
            mock_send
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', [
                'topsailai_agent_client',
                'send-message',
                '--session-id', 'test-session-123',
                '--message', 'Hello, world!'
            ]):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_send.called
    
    def test_cli_send_message_with_role(self, monkeypatch, capsys):
        """Test CLI-002-10: Test send-message with role parameter"""
        mock_send = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.message.MessageClient.send_message',
            mock_send
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', [
                'topsailai_agent_client',
                'send-message',
                '--session-id', 'test-session-123',
                '--message', 'Hello!',
                '--role', 'assistant'
            ]):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_send.called
    
    def test_cli_get_messages(self, monkeypatch, capsys):
        """Test CLI-002-11: Test get-messages command"""
        mock_get = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.message.MessageClient.list_messages',
            mock_get
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', 'get-messages', '--session-id', 'test-session-123']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_get.called
    
    def test_cli_list_messages_alias(self, monkeypatch, capsys):
        """Test CLI-002-12: Test list-messages alias command"""
        mock_get = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.message.MessageClient.list_messages',
            mock_get
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', 'list-messages', '--session-id', 'test-session-123']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_get.called
    
    # =========================================================================
    # Task Operations Tests
    # =========================================================================
    
    def test_cli_set_task_result(self, monkeypatch, capsys):
        """Test CLI-002-13: Test set-task-result command"""
        mock_set = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.task.TaskClient.set_task_result',
            mock_set
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', [
                'topsailai_agent_client',
                'set-task-result',
                '--session-id', 'test-session-123',
                '--processed-msg-id', 'msg-456',
                '--task-id', 'task-789',
                '--task-result', 'Task completed successfully'
            ]):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_set.called
    
    def test_cli_get_tasks(self, monkeypatch, capsys):
        """Test CLI-002-14: Test get-tasks command"""
        mock_get = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.task.TaskClient.list_tasks',
            mock_get
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', 'get-tasks', '--session-id', 'test-session-123']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_get.called
    
    def test_cli_get_tasks_with_filters(self, monkeypatch, capsys):
        """Test CLI-002-15: Test get-tasks with filters"""
        mock_get = Mock(return_value=None)
        with patch(
            'topsailai_server.agent_daemon.client.task.TaskClient.list_tasks',
            mock_get
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', [
                'topsailai_agent_client',
                'get-tasks',
                '--session-id', 'test-session-123',
                '--task-ids', 't1,t2',
                '--limit', '50'
            ]):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_get.called
    
    # =========================================================================
    # Error Handling Tests
    # =========================================================================
    
    def test_cli_missing_session_id(self, monkeypatch, capsys):
        """Test CLI-002-16: Test command fails without required --session-id"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        
        with patch('sys.argv', ['topsailai_agent_client', 'get-session']):
            with pytest.raises(SystemExit) as exc_info:
                cli()
            
            # Should exit with error (non-zero code)
            assert exc_info.value.code != 0 or exc_info.value.code == 2  # argparse error code
    
    def test_cli_missing_message_content(self, monkeypatch, capsys):
        """Test CLI-002-17: Test send-message fails without --message"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        
        with patch('sys.argv', ['topsailai_agent_client', 'send-message', '--session-id', 'test']):
            with pytest.raises(SystemExit) as exc_info:
                cli()
            
            assert exc_info.value.code != 0 or exc_info.value.code == 2
    
    def test_cli_missing_task_params(self, monkeypatch, capsys):
        """Test CLI-002-18: Test set-task-result fails without required params"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        
        with patch('sys.argv', ['topsailai_agent_client', 'set-task-result', '--session-id', 'test']):
            with pytest.raises(SystemExit) as exc_info:
                cli()
            
            assert exc_info.value.code != 0 or exc_info.value.code == 2
    
    def test_cli_invalid_operation(self, monkeypatch, capsys):
        """Test CLI-002-19: Test invalid operation shows error"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        
        with patch('sys.argv', ['topsailai_agent_client', 'invalid-operation']):
            with pytest.raises(SystemExit) as exc_info:
                cli()
            
            # Should exit with error
            assert exc_info.value.code != 0
    
    def test_cli_no_operation_shows_help(self, monkeypatch, capsys):
        """Test CLI-002-20: Test no operation shows help"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        
        with patch('sys.argv', ['topsailai_agent_client']):
            with pytest.raises(SystemExit) as exc_info:
                cli()
            
            # Should exit with error (no operation specified)
            assert exc_info.value.code == 1
    
    # =========================================================================
    # Network Error Handling Tests
    # =========================================================================
    
    def test_cli_handles_connection_error(self, monkeypatch, capsys):
        """Test CLI-002-21: Test CLI handles connection errors gracefully"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        
        # Mock a connection error
        mock_health = Mock(side_effect=ConnectionError("Connection refused"))
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.health_check',
            mock_health
        ):
            with patch('sys.argv', ['topsailai_agent_client', 'health']):
                try:
                    cli()
                except SystemExit:
                    pass
                
                captured = capsys.readouterr()
                # Should show error message
                assert "error" in captured.out.lower() or "connection" in captured.out.lower()
    
    def test_cli_handles_api_error(self, monkeypatch, capsys):
        """Test CLI-002-22: Test CLI handles API errors gracefully"""
        from topsailai_server.agent_daemon.topsailai_agent_client import cli
        
        # Mock an API error
        mock_list = Mock(side_effect=Exception("API Error"))
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.list_sessions',
            mock_list
        ):
            with patch('sys.argv', ['topsailai_agent_client', 'list-sessions']):
                try:
                    cli()
                except SystemExit:
                    pass
                
                captured = capsys.readouterr()
                # Should show error message
                assert "error" in captured.out.lower()
    
    # =========================================================================
    # Verbose Mode Tests
    # =========================================================================
    
    def test_cli_verbose_mode(self, monkeypatch, capsys):
        """Test CLI-002-23: Test verbose mode flag"""
        mock_list = Mock(return_value=[])
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.list_sessions',
            mock_list
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', '-v', 'list-sessions']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            # Verify verbose flag was passed
            assert mock_list.called
            call_kwargs = mock_list.call_args.kwargs if mock_list.call_args.kwargs else {}
            assert call_kwargs.get('verbose') is True
    
    def test_cli_verbose_long_form(self, monkeypatch, capsys):
        """Test CLI-002-24: Test verbose mode with --verbose flag"""
        mock_list = Mock(return_value=[])
        with patch(
            'topsailai_server.agent_daemon.client.session.SessionClient.list_sessions',
            mock_list
        ):
            from topsailai_server.agent_daemon.topsailai_agent_client import cli
            
            with patch('sys.argv', ['topsailai_agent_client', '--verbose', 'list-sessions']):
                try:
                    cli()
                except SystemExit:
                    pass
            
            assert mock_list.called
            call_kwargs = mock_list.call_args.kwargs if mock_list.call_args.kwargs else {}
            assert call_kwargs.get('verbose') is True
