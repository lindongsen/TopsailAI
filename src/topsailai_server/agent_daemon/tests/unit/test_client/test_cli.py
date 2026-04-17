"""
Test CLI Module

This module contains unit tests for the agent_daemon CLI functionality.
Tests cover argument parsing, CLI entry point, and all do_xxx functions.

Test Classes:
    - TestCLIParsing: Tests for argument parsing
    - TestCLISessionOperations: Tests for session-related CLI operations
    - TestCLIMessageOperations: Tests for message-related CLI operations
    - TestCLITaskOperations: Tests for task-related CLI operations
    - TestCLIEdgeCases: Tests for edge cases and error handling

Usage:
    Run all CLI tests:
        pytest tests/unit/test_client/test_cli.py -v
"""

import argparse
import sys
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest


# Import CLI modules
from topsailai_server.agent_daemon.client.session_do import (
    do_client_health,
    do_client_list_sessions,
    do_client_get_session,
    do_client_delete_sessions,
    do_client_process_session,
    add_session_parsers,
)
from topsailai_server.agent_daemon.client.message_do import (
    do_client_send_message,
    do_client_get_messages,
    add_message_parsers,
)
from topsailai_server.agent_daemon.client.task_do import (
    do_client_set_task_result,
    do_client_get_tasks,
    add_task_parsers,
)


class MockArgs:
    """Mock argparse.Namespace for testing"""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestCLIParsing:
    """Tests for CLI argument parsing"""
    
    def test_add_session_parsers(self):
        """Test that session parsers are added correctly"""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_session_parsers(subparsers)
        
        # Parse various session commands
        args = parser.parse_args(['health'])
        assert hasattr(args, 'func')
        assert args.func == do_client_health
        
        args = parser.parse_args(['list-sessions'])
        assert hasattr(args, 'func')
        assert args.func == do_client_list_sessions
        assert args.limit == 1000
        
        args = parser.parse_args(['get-session', '--session-id', 'test123'])
        assert args.session_id == 'test123'
        assert args.func == do_client_get_session
        
        args = parser.parse_args(['process-session', '--session-id', 'test123'])
        assert args.session_id == 'test123'
        assert args.func == do_client_process_session
        
        args = parser.parse_args(['delete-sessions', 'id1', 'id2'])
        assert args.session_ids == ['id1', 'id2']
        assert args.func == do_client_delete_sessions
    
    def test_add_message_parsers(self):
        """Test that message parsers are added correctly"""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_message_parsers(subparsers)
        
        # Parse send-message command
        args = parser.parse_args([
            'send-message',
            '--message', 'Hello World',
            '--session-id', 'test123',
            '--role', 'user'
        ])
        assert args.message == 'Hello World'
        assert args.session_id == 'test123'
        assert args.role == 'user'
        assert args.func == do_client_send_message
        
        # Parse get-messages command
        args = parser.parse_args(['get-messages', '--session-id', 'test123'])
        assert hasattr(args, 'func')
        assert args.func == do_client_get_messages
        assert args.session_id == 'test123'
        assert args.limit == 1000
        
        # Parse list-messages command (alias)
        args = parser.parse_args(['list-messages', '--session-id', 'test123'])
        assert args.func == do_client_get_messages
    
    def test_add_task_parsers(self):
        """Test that task parsers are added correctly"""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_task_parsers(subparsers)
        
        # Parse set-task-result command
        args = parser.parse_args([
            'set-task-result',
            '--processed-msg-id', 'msg123',
            '--task-id', 'task456',
            '--task-result', 'Result content'
        ])
        assert args.processed_msg_id == 'msg123'
        assert args.task_id == 'task456'
        assert args.task_result == 'Result content'
        assert args.func == do_client_set_task_result
        
        # Parse get-tasks command
        args = parser.parse_args(['get-tasks', '--session-id', 'test123'])
        assert hasattr(args, 'func')
        assert args.func == do_client_get_tasks
        assert args.session_id == 'test123'
        
        # Parse list-tasks command (alias)
        args = parser.parse_args(['list-tasks', '--session-id', 'test123'])
        assert args.func == do_client_get_tasks
    
    def test_session_list_with_filters(self):
        """Test session list with various filters"""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_session_parsers(subparsers)
        
        args = parser.parse_args([
            'list-sessions',
            '--session-ids', 'id1,id2,id3',
            '--start-time', '2024-01-01',
            '--end-time', '2024-12-31',
            '--offset', '10',
            '--limit', '50',
            '--sort-key', 'update_time',
            '--order-by', 'asc'
        ])
        
        assert args.session_ids == 'id1,id2,id3'
        assert args.start_time == '2024-01-01'
        assert args.end_time == '2024-12-31'
        assert args.offset == 10
        assert args.limit == 50
        assert args.sort_key == 'update_time'
        assert args.order_by == 'asc'
    
    def test_message_list_with_filters(self):
        """Test message list with various filters"""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_message_parsers(subparsers)
        
        args = parser.parse_args([
            'get-messages',
            '--session-id', 'test123',
            '--start-time', '2024-01-01',
            '--end-time', '2024-12-31',
            '--offset', '5',
            '--limit', '25',
            '--sort-key', 'update_time',
            '--order-by', 'asc'
        ])
        
        assert args.session_id == 'test123'
        assert args.start_time == '2024-01-01'
        assert args.end_time == '2024-12-31'
        assert args.offset == 5
        assert args.limit == 25
        assert args.sort_key == 'update_time'
        assert args.order_by == 'asc'
    
    def test_task_list_with_filters(self):
        """Test task list with various filters"""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_task_parsers(subparsers)
        
        args = parser.parse_args([
            'get-tasks',
            '--session-id', 'test123',
            '--task-ids', 'task1,task2',
            '--start-time', '2024-01-01',
            '--end-time', '2024-12-31',
            '--offset', '0',
            '--limit', '100',
            '--sort-key', 'update_time',
            '--order-by', 'desc'
        ])
        
        assert args.session_id == 'test123'
        assert args.task_ids == 'task1,task2'
        assert args.start_time == '2024-01-01'
        assert args.end_time == '2024-12-31'
        assert args.offset == 0
        assert args.limit == 100
        assert args.sort_key == 'update_time'
        assert args.order_by == 'desc'


class TestCLISessionOperations:
    """Tests for session-related CLI operations"""
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_do_client_health_success(self, mock_client_class):
        """Test health check success"""
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client_class.return_value = mock_client
        
        args = MockArgs(host='localhost', port=7373)
        result = do_client_health(args)
        
        assert result is True
        mock_client.health_check.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_do_client_health_failure(self, mock_client_class):
        """Test health check failure"""
        mock_client = MagicMock()
        mock_client.health_check.return_value = False
        mock_client_class.return_value = mock_client
        
        args = MockArgs(host='localhost', port=7373)
        result = do_client_health(args)
        
        assert result is False
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_do_client_health_exception(self, mock_client_class):
        """Test health check exception"""
        mock_client = MagicMock()
        mock_client.health_check.side_effect = Exception("Connection refused")
        mock_client_class.return_value = mock_client
        
        args = MockArgs(host='localhost', port=7373)
        result = do_client_health(args)
        
        assert result is False
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_do_client_list_sessions_success(self, mock_client_class):
        """Test list sessions success"""
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = [{'session_id': 'test1'}]
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_ids='id1,id2',
            start_time=None,
            end_time=None,
            offset=0,
            limit=1000,
            sort_key='create_time',
            order_by='desc',
            verbose=False
        )
        result = do_client_list_sessions(args)
        
        assert result is True
        mock_client.list_sessions.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_do_client_list_sessions_no_filter(self, mock_client_class):
        """Test list sessions without session_ids filter"""
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_ids=None,
            start_time='2024-01-01',
            end_time='2024-12-31',
            offset=10,
            limit=50,
            sort_key='update_time',
            order_by='asc',
            verbose=True
        )
        result = do_client_list_sessions(args)
        
        assert result is True
        mock_client.list_sessions.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_do_client_get_session_success(self, mock_client_class):
        """Test get session success"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(host='localhost', port=7373, session_id='test123', verbose=False)
        result = do_client_get_session(args)
        
        assert result is True
        mock_client.get_session.assert_called_once_with('test123', verbose=False)
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_do_client_delete_sessions_success(self, mock_client_class):
        """Test delete sessions success"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(host='localhost', port=7373, session_ids=['id1', 'id2'], verbose=False)
        result = do_client_delete_sessions(args)
        
        assert result is True
        mock_client.delete_sessions.assert_called_once_with(['id1', 'id2'], verbose=False)
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_do_client_delete_sessions_comma_separated(self, mock_client_class):
        """Test delete sessions with comma-separated string"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(host='localhost', port=7373, session_ids_str='id1,id2,id3', verbose=False)
        result = do_client_delete_sessions(args)
        
        assert result is True
        mock_client.delete_sessions.assert_called_once()
    
    def test_do_client_delete_sessions_no_ids(self):
        """Test delete sessions with no IDs provided"""
        args = MockArgs(host='localhost', port=7373, session_ids=[], verbose=False)
        result = do_client_delete_sessions(args)
        
        assert result is False
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_do_client_process_session_success(self, mock_client_class):
        """Test process session success"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(host='localhost', port=7373, session_id='test123', verbose=False)
        result = do_client_process_session(args)
        
        assert result is True
        mock_client.process_session.assert_called_once_with('test123', verbose=False)


class TestCLIMessageOperations:
    """Tests for message-related CLI operations"""
    
    @patch('topsailai_server.agent_daemon.client.message_do.MessageClient')
    def test_do_client_send_message_success(self, mock_client_class):
        """Test send message success"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            message='Hello World',
            role='user',
            processed_msg_id=None,
            verbose=False
        )
        result = do_client_send_message(args)
        
        assert result is True
        mock_client.send_message.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.client.message_do.MessageClient')
    def test_do_client_send_message_assistant_role(self, mock_client_class):
        """Test send message with assistant role"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            message='Response content',
            role='assistant',
            processed_msg_id='msg123',
            verbose=True
        )
        result = do_client_send_message(args)
        
        assert result is True
        mock_client.send_message.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.client.message_do.MessageClient')
    def test_do_client_send_message_exception(self, mock_client_class):
        """Test send message exception handling"""
        mock_client = MagicMock()
        mock_client.send_message.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            message='Hello',
            role='user',
            processed_msg_id=None,
            verbose=False
        )
        result = do_client_send_message(args)
        
        assert result is False
    
    @patch('topsailai_server.agent_daemon.client.message_do.MessageClient')
    def test_do_client_get_messages_success(self, mock_client_class):
        """Test get messages success"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            start_time=None,
            end_time=None,
            offset=0,
            limit=1000,
            sort_key='create_time',
            order_by='desc',
            verbose=False
        )
        result = do_client_get_messages(args)
        
        assert result is True
        mock_client.list_messages.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.client.message_do.MessageClient')
    def test_do_client_get_messages_with_filters(self, mock_client_class):
        """Test get messages with all filters"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            start_time='2024-01-01',
            end_time='2024-12-31',
            offset=10,
            limit=50,
            sort_key='update_time',
            order_by='asc',
            verbose=True
        )
        result = do_client_get_messages(args)
        
        assert result is True
        mock_client.list_messages.assert_called_once()


class TestCLITaskOperations:
    """Tests for task-related CLI operations"""
    
    @patch('topsailai_server.agent_daemon.client.task_do.TaskClient')
    def test_do_client_set_task_result_success(self, mock_client_class):
        """Test set task result success"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            processed_msg_id='msg123',
            task_id='task456',
            task_result='Task completed',
            verbose=False
        )
        result = do_client_set_task_result(args)
        
        assert result is True
        mock_client.set_task_result.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.client.task_do.TaskClient')
    def test_do_client_set_task_result_exception(self, mock_client_class):
        """Test set task result exception handling"""
        mock_client = MagicMock()
        mock_client.set_task_result.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            processed_msg_id='msg123',
            task_id='task456',
            task_result='Result',
            verbose=False
        )
        result = do_client_set_task_result(args)
        
        assert result is False
    
    @patch('topsailai_server.agent_daemon.client.task_do.TaskClient')
    def test_do_client_get_tasks_success(self, mock_client_class):
        """Test get tasks success"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            task_ids=None,
            start_time=None,
            end_time=None,
            offset=0,
            limit=1000,
            sort_key='create_time',
            order_by='desc',
            verbose=False
        )
        result = do_client_get_tasks(args)
        
        assert result is True
        mock_client.list_tasks.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.client.task_do.TaskClient')
    def test_do_client_get_tasks_with_task_ids(self, mock_client_class):
        """Test get tasks with task_ids filter"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            task_ids='task1,task2,task3',
            start_time='2024-01-01',
            end_time='2024-12-31',
            offset=5,
            limit=25,
            sort_key='update_time',
            order_by='asc',
            verbose=True
        )
        result = do_client_get_tasks(args)
        
        assert result is True
        mock_client.list_tasks.assert_called_once()


class TestCLIEdgeCases:
    """Tests for edge cases and error handling"""
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_health_with_custom_host_port(self, mock_client_class):
        """Test health check with custom host and port"""
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client_class.return_value = mock_client
        
        args = MockArgs(host='192.168.1.100', port=8080)
        result = do_client_health(args)
        
        assert result is True
        mock_client_class.assert_called_once_with(base_url='http://192.168.1.100:8080')
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_list_sessions_empty_session_ids(self, mock_client_class):
        """Test list sessions with empty session_ids string"""
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_ids='',  # Empty string
            start_time=None,
            end_time=None,
            offset=0,
            limit=1000,
            sort_key='create_time',
            order_by='desc',
            verbose=False
        )
        result = do_client_list_sessions(args)
        
        assert result is True
        # Should be called with None since empty string produces empty list
        call_kwargs = mock_client.list_sessions.call_args[1]
        assert call_kwargs['session_ids'] is None
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_delete_sessions_with_whitespace(self, mock_client_class):
        """Test delete sessions with whitespace in IDs"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(host='localhost', port=7373, session_ids=[' id1 ', ' id2 '], verbose=False)
        result = do_client_delete_sessions(args)
        
        assert result is True
    
    @patch('topsailai_server.agent_daemon.client.message_do.MessageClient')
    def test_send_message_with_multiline_content(self, mock_client_class):
        """Test send message with multiline content"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        multiline_message = "Line 1\nLine 2\nLine 3"
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            message=multiline_message,
            role='user',
            processed_msg_id=None,
            verbose=False
        )
        result = do_client_send_message(args)
        
        assert result is True
        call_kwargs = mock_client.send_message.call_args[1]
        assert call_kwargs['message'] == multiline_message
    
    @patch('topsailai_server.agent_daemon.client.task_do.TaskClient')
    def test_set_task_result_with_empty_result(self, mock_client_class):
        """Test set task result with empty result string"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            processed_msg_id='msg123',
            task_id='task456',
            task_result='',
            verbose=False
        )
        result = do_client_set_task_result(args)
        
        assert result is True
    
    @patch('topsailai_server.agent_daemon.client.task_do.TaskClient')
    def test_get_tasks_with_special_characters(self, mock_client_class):
        """Test get tasks with special characters in task_ids"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_id='test123',
            task_ids='task-1,task_2,task.3',
            start_time=None,
            end_time=None,
            offset=0,
            limit=1000,
            sort_key='create_time',
            order_by='desc',
            verbose=False
        )
        result = do_client_get_tasks(args)
        
        assert result is True
        mock_client.list_tasks.assert_called_once()
    
    @patch('topsailai_server.agent_daemon.client.session_do.SessionClient')
    def test_client_exception_logging(self, mock_client_class):
        """Test that exceptions are properly logged"""
        mock_client = MagicMock()
        mock_client.list_sessions.side_effect = Exception("Network error")
        mock_client_class.return_value = mock_client
        
        args = MockArgs(
            host='localhost',
            port=7373,
            session_ids=None,
            start_time=None,
            end_time=None,
            offset=0,
            limit=1000,
            sort_key='create_time',
            order_by='desc',
            verbose=False
        )
        result = do_client_list_sessions(args)
        
        assert result is False
