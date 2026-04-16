"""
Unit Tests for Agent Daemon Client Package

This module contains comprehensive unit tests for the client package modules:
- client/base.py: BaseClient class
- client/session.py: SessionClient class
- client/session_do.py: Session do_xxx functions
- client/message.py: MessageClient class
- client/message_do.py: Message do_xxx functions
- client/task.py: TaskClient class
- client/task_do.py: Task do_xxx functions
- topsailai_agent_client.py: CLI entry point

Test IDs: U-100 to U-150
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from topsailai_server.agent_daemon.client.base import BaseClient, APIError
from topsailai_server.agent_daemon.client.session import SessionClient
from topsailai_server.agent_daemon.client.message import MessageClient
from topsailai_server.agent_daemon.client.task import TaskClient
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


# =============================================================================
# Test BaseClient (U-100 to U-109)
# =============================================================================

class TestBaseClientUnit(unittest.TestCase):
    """Unit tests for BaseClient class (U-100 to U-109)"""

    def test_base_client_init_default(self):
        """U-100: Test BaseClient initialization with default values"""
        client = BaseClient()
        self.assertEqual(client.base_url, "http://127.0.0.1:7373")
        self.assertEqual(client.timeout, 10)

    def test_base_client_init_custom(self):
        """U-101: Test BaseClient initialization with custom values"""
        client = BaseClient(base_url="http://custom:8080", timeout=30)
        self.assertEqual(client.base_url, "http://custom:8080")
        self.assertEqual(client.timeout, 30)

    def test_base_client_url_strips_trailing_slash(self):
        """U-102: Test that trailing slashes are stripped from URL"""
        client = BaseClient(base_url="http://localhost:8080/")
        self.assertEqual(client.base_url, "http://localhost:8080")

    def test_base_client_env_override(self):
        """U-103: Test BaseClient initialization from environment variables"""
        with patch.dict(os.environ, {"TOPSAILAI_AGENT_DAEMON_HOST": "env-host", "TOPSAILAI_AGENT_DAEMON_PORT": "9999"}):
            client = BaseClient()
            self.assertEqual(client.base_url, "http://env-host:9999")

    def test_format_time_iso_format(self):
        """U-104: Test time formatting with ISO format"""
        result = BaseClient.format_time("2026-04-13T23:27:53.123456")
        self.assertEqual(result, "2026-04-13 23:27:53")

    def test_format_time_no_microseconds(self):
        """U-105: Test time formatting without microseconds"""
        result = BaseClient.format_time("2026-04-13T23:27:53")
        self.assertEqual(result, "2026-04-13 23:27:53")

    def test_format_time_none(self):
        """U-106: Test format_time with None input"""
        result = BaseClient.format_time(None)
        self.assertEqual(result, "N/A")

    def test_format_time_empty_string(self):
        """U-107: Test format_time with empty string"""
        result = BaseClient.format_time("")
        self.assertEqual(result, "N/A")

    def test_format_time_already_formatted(self):
        """U-108: Test format_time with already formatted string"""
        result = BaseClient.format_time("2026-04-13 23:27:53")
        self.assertEqual(result, "2026-04-13 23:27:53")

    def test_split_line_constant(self):
        """U-109: Test SPLIT_LINE constant exists"""
        from topsailai_server.agent_daemon.client.base import SPLIT_LINE
        self.assertEqual(len(SPLIT_LINE), 78)
        self.assertTrue(all(c == "=" for c in SPLIT_LINE.strip()))


# =============================================================================
# Test SessionClient (U-110 to U-119)
# =============================================================================

class TestSessionClientUnit(unittest.TestCase):
    """Unit tests for SessionClient class (U-110 to U-119)"""

    def test_session_client_init_default(self):
        """U-110: Test SessionClient initialization with default values"""
        client = SessionClient()
        self.assertEqual(client.base_url, "http://127.0.0.1:7373")

    def test_session_client_init_custom(self):
        """U-111: Test SessionClient initialization with custom base_url"""
        client = SessionClient(base_url="http://custom:8080")
        self.assertEqual(client.base_url, "http://custom:8080")

    @patch.object(SessionClient, 'get')
    def test_health_check_success(self, mock_get):
        """U-112: Test health_check returns True on success"""
        mock_get.return_value = {"status": "ok"}
        client = SessionClient()
        result = client.health_check()
        self.assertTrue(result)
        mock_get.assert_called_once_with("/health", timeout=5)

    @patch.object(SessionClient, 'get')
    def test_health_check_failure(self, mock_get):
        """U-113: Test health_check returns False on failure"""
        mock_get.side_effect = Exception("Connection refused")
        client = SessionClient()
        result = client.health_check()
        self.assertFalse(result)

    @patch.object(SessionClient, 'get')
    def test_list_sessions_success(self, mock_get):
        """U-114: Test list_sessions returns sessions on success"""
        mock_sessions = [
            {"session_id": "s1", "session_name": "s1", "create_time": "2026-04-13T23:27:53"}
        ]
        mock_get.return_value = mock_sessions
        client = SessionClient()
        result = client.list_sessions()
        self.assertEqual(len(result), 1)
        mock_get.assert_called_once()

    @patch.object(SessionClient, 'get')
    def test_list_sessions_empty(self, mock_get):
        """U-115: Test list_sessions with empty result"""
        mock_get.return_value = []
        client = SessionClient()
        result = client.list_sessions()
        self.assertEqual(result, [])

    @patch.object(SessionClient, 'get')
    def test_get_session_success(self, mock_get):
        """U-116: Test get_session returns session details"""
        mock_session = {"session_id": "s1", "session_name": "Test", "status": "idle"}
        mock_get.return_value = mock_session
        client = SessionClient()
        result = client.get_session("s1")
        self.assertEqual(result["session_id"], "s1")
        mock_get.assert_called_once_with("/api/v1/session/s1")

    @patch.object(SessionClient, 'post')
    def test_process_session_success(self, mock_post):
        """U-117: Test process_session returns processing result"""
        mock_result = {"processed": True, "processor_pid": 12345}
        mock_post.return_value = mock_result
        client = SessionClient()
        result = client.process_session("s1")
        self.assertTrue(result["processed"])
        self.assertEqual(result["processor_pid"], 12345)

    @patch.object(SessionClient, 'delete')
    def test_delete_sessions_success(self, mock_delete):
        """U-118: Test delete_sessions returns deletion result"""
        mock_result = {"deleted_count": 2}
        mock_delete.return_value = mock_result
        client = SessionClient()
        result = client.delete_sessions(["s1", "s2"])
        self.assertEqual(result["deleted_count"], 2)

    def test_delete_sessions_empty_list(self):
        """U-119: Test delete_sessions raises error for empty list"""
        client = SessionClient()
        with self.assertRaises(ValueError):
            client.delete_sessions([])


# =============================================================================
# Test MessageClient (U-120 to U-129)
# =============================================================================

class TestMessageClientUnit(unittest.TestCase):
    """Unit tests for MessageClient class (U-120 to U-129)"""

    def test_message_client_init_default(self):
        """U-120: Test MessageClient initialization with default values"""
        client = MessageClient()
        self.assertEqual(client.base_url, "http://127.0.0.1:7373")

    def test_message_client_init_custom(self):
        """U-121: Test MessageClient initialization with custom base_url"""
        client = MessageClient(base_url="http://custom:8080")
        self.assertEqual(client.base_url, "http://custom:8080")

    @patch.object(MessageClient, 'post')
    @patch.object(MessageClient, 'get')
    def test_send_message_success(self, mock_get, mock_post):
        """U-122: Test send_message success"""
        mock_post.return_value = {"code": 0, "data": {"msg_id": "msg-123"}}
        client = MessageClient()
        result = client.send_message("s1", "Hello!")
        self.assertEqual(result["code"], 0)
        mock_post.assert_called_once()

    @patch.object(MessageClient, 'post')
    @patch.object(MessageClient, 'get')
    def test_send_message_with_role(self, mock_get, mock_post):
        """U-123: Test send_message with custom role"""
        mock_post.return_value = {"code": 0, "data": {}}
        client = MessageClient()
        client.send_message("s1", "Hello!", role="assistant")
        call_args = mock_post.call_args
        self.assertEqual(call_args[1]["json_data"]["role"], "assistant")

    @patch.object(MessageClient, 'get')
    def test_list_messages_success(self, mock_get):
        """U-124: Test list_messages returns messages on success"""
        mock_messages = [
            {"msg_id": "msg-1", "session_id": "s1", "role": "user", "message": "Hello"}
        ]
        mock_get.return_value = mock_messages
        client = MessageClient()
        result = client.list_messages("s1")
        self.assertEqual(len(result), 1)
        mock_get.assert_called_once()

    @patch.object(MessageClient, 'get')
    def test_list_messages_with_filters(self, mock_get):
        """U-125: Test list_messages with filters"""
        mock_get.return_value = []
        client = MessageClient()
        client.list_messages(
            "s1",
            start_time="2026-04-14T00:00:00",
            end_time="2026-04-14T23:59:59",
            offset=10,
            limit=50
        )
        call_args = mock_get.call_args
        params = call_args[1]["params"]
        self.assertEqual(params["start_time"], "2026-04-14T00:00:00")
        self.assertEqual(params["offset"], 10)

    @patch.object(MessageClient, 'get')
    def test_list_messages_empty(self, mock_get):
        """U-126: Test list_messages with empty result"""
        mock_get.return_value = []
        client = MessageClient()
        result = client.list_messages("s1")
        self.assertEqual(result, [])

    @patch.object(MessageClient, 'get')
    def test_list_messages_with_task_info(self, mock_get):
        """U-127: Test list_messages includes task_id and task_result"""
        mock_messages = [
            {"msg_id": "msg-1", "task_id": "task-1", "task_result": "Done"}
        ]
        mock_get.return_value = mock_messages
        client = MessageClient()
        result = client.list_messages("s1")
        self.assertEqual(result[0]["task_id"], "task-1")
        self.assertEqual(result[0]["task_result"], "Done")


# =============================================================================
# Test TaskClient (U-130 to U-139)
# =============================================================================

class TestTaskClientUnit(unittest.TestCase):
    """Unit tests for TaskClient class (U-130 to U-139)"""

    def test_task_client_init_default(self):
        """U-130: Test TaskClient initialization with default values"""
        client = TaskClient()
        self.assertEqual(client.base_url, "http://127.0.0.1:7373")

    def test_task_client_init_custom(self):
        """U-131: Test TaskClient initialization with custom base_url"""
        client = TaskClient(base_url="http://custom:8080")
        self.assertEqual(client.base_url, "http://custom:8080")

    @patch.object(TaskClient, 'post')
    @patch.object(TaskClient, 'get')
    def test_set_task_result_success(self, mock_get, mock_post):
        """U-132: Test set_task_result success"""
        mock_post.return_value = {"code": 0, "data": {}}
        client = TaskClient()
        result = client.set_task_result("s1", "msg-1", "task-1", "Done")
        self.assertEqual(result["code"], 0)
        mock_post.assert_called_once()

    @patch.object(TaskClient, 'post')
    @patch.object(TaskClient, 'get')
    def test_set_task_result_empty(self, mock_get, mock_post):
        """U-133: Test set_task_result with empty result"""
        mock_post.return_value = {"code": 0, "data": {}}
        client = TaskClient()
        result = client.set_task_result("s1", "msg-1", "task-1", "")
        self.assertEqual(result["code"], 0)

    @patch.object(TaskClient, 'get')
    def test_list_tasks_success(self, mock_get):
        """U-134: Test list_tasks returns tasks on success"""
        mock_tasks = [
            {"task_id": "task-1", "session_id": "s1", "msg_id": "msg-1", "message": "Task 1"}
        ]
        mock_get.return_value = mock_tasks
        client = TaskClient()
        result = client.list_tasks("s1")
        self.assertEqual(len(result), 1)
        mock_get.assert_called_once()

    @patch.object(TaskClient, 'get')
    def test_list_tasks_with_filters(self, mock_get):
        """U-135: Test list_tasks with filters"""
        mock_get.return_value = []
        client = TaskClient()
        client.list_tasks(
            "s1",
            task_ids=["task-1", "task-2"],
            start_time="2026-04-14T00:00:00",
            offset=10,
            limit=50
        )
        call_args = mock_get.call_args
        params = call_args[1]["params"]
        self.assertEqual(params["task_ids"], ["task-1", "task-2"])

    @patch.object(TaskClient, 'get')
    def test_list_tasks_empty(self, mock_get):
        """U-136: Test list_tasks with empty result"""
        mock_get.return_value = []
        client = TaskClient()
        result = client.list_tasks("s1")
        self.assertEqual(result, [])


# =============================================================================
# Test Session Do Functions (U-140 to U-144)
# =============================================================================

class TestSessionDoFunctions(unittest.TestCase):
    """Unit tests for session do_xxx functions (U-140 to U-144)"""

    @patch.object(SessionClient, 'health_check')
    def test_do_client_health_success(self, mock_health):
        """U-140: Test do_client_health success"""
        mock_health.return_value = True
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        result = do_client_health(args)
        self.assertTrue(result)

    @patch.object(SessionClient, 'health_check')
    def test_do_client_health_failure(self, mock_health):
        """U-141: Test do_client_health failure"""
        mock_health.return_value = False
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        result = do_client_health(args)
        self.assertFalse(result)

    @patch.object(SessionClient, 'list_sessions')
    def test_do_client_list_sessions(self, mock_list):
        """U-142: Test do_client_list_sessions"""
        mock_list.return_value = []
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        args.session_ids = None
        args.start_time = None
        args.end_time = None
        args.offset = 0
        args.limit = 1000
        args.sort_key = "create_time"
        args.order_by = "desc"
        args.verbose = False
        result = do_client_list_sessions(args)
        self.assertTrue(result)
        mock_list.assert_called_once()

    @patch.object(SessionClient, 'get_session')
    def test_do_client_get_session(self, mock_get):
        """U-143: Test do_client_get_session"""
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        args.session_id = "s1"
        args.verbose = False
        result = do_client_get_session(args)
        self.assertTrue(result)
        mock_get.assert_called_once_with("s1", verbose=False)

    @patch.object(SessionClient, 'delete_sessions')
    def test_do_client_delete_sessions(self, mock_delete):
        """U-144: Test do_client_delete_sessions"""
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        args.session_ids = ["s1", "s2"]
        args.session_ids_str = None
        args.verbose = False
        result = do_client_delete_sessions(args)
        self.assertTrue(result)
        mock_delete.assert_called_once()

    def test_do_client_delete_sessions_no_ids(self):
        """U-144: Test do_client_delete_sessions with no IDs"""
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        args.session_ids = []
        args.session_ids_str = None
        args.verbose = False
        result = do_client_delete_sessions(args)
        self.assertFalse(result)


# =============================================================================
# Test Message Do Functions (U-145 to U-147)
# =============================================================================

class TestMessageDoFunctions(unittest.TestCase):
    """Unit tests for message do_xxx functions (U-145 to U-147)"""

    @patch.object(MessageClient, 'send_message')
    def test_do_client_send_message(self, mock_send):
        """U-145: Test do_client_send_message"""
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        args.session_id = "s1"
        args.message = "Hello!"
        args.role = "user"
        args.processed_msg_id = None
        args.verbose = False
        result = do_client_send_message(args)
        self.assertTrue(result)
        mock_send.assert_called_once()

    @patch.object(MessageClient, 'list_messages')
    def test_do_client_get_messages(self, mock_list):
        """U-146: Test do_client_get_messages"""
        mock_list.return_value = []
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        args.session_id = "s1"
        args.start_time = None
        args.end_time = None
        args.offset = 0
        args.limit = 1000
        args.sort_key = "create_time"
        args.order_by = "desc"
        args.verbose = False
        result = do_client_get_messages(args)
        self.assertTrue(result)
        mock_list.assert_called_once()


# =============================================================================
# Test Task Do Functions (U-148 to U-150)
# =============================================================================

class TestTaskDoFunctions(unittest.TestCase):
    """Unit tests for task do_xxx functions (U-148 to U-150)"""

    @patch.object(TaskClient, 'set_task_result')
    def test_do_client_set_task_result(self, mock_set):
        """U-148: Test do_client_set_task_result"""
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        args.session_id = "s1"
        args.processed_msg_id = "msg-1"
        args.task_id = "task-1"
        args.task_result = "Done"
        args.verbose = False
        result = do_client_set_task_result(args)
        self.assertTrue(result)
        mock_set.assert_called_once()

    @patch.object(TaskClient, 'list_tasks')
    def test_do_client_get_tasks(self, mock_list):
        """U-149: Test do_client_get_tasks"""
        mock_list.return_value = []
        args = MagicMock()
        args.host = "localhost"
        args.port = 7373
        args.session_id = "s1"
        args.task_ids = None
        args.start_time = None
        args.end_time = None
        args.offset = 0
        args.limit = 1000
        args.sort_key = "create_time"
        args.order_by = "desc"
        args.verbose = False
        result = do_client_get_tasks(args)
        self.assertTrue(result)
        mock_list.assert_called_once()


# =============================================================================
# Test Argument Parsers (U-150)
# =============================================================================

class TestArgumentParsers(unittest.TestCase):
    """Unit tests for argument parsers (U-150)"""

    def test_add_session_parsers(self):
        """U-150: Test add_session_parsers adds all session subcommands"""
        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_session_parsers(subparsers)
        
        # Parse test commands
        args = parser.parse_args(['health'])
        self.assertEqual(args.func, do_client_health)
        
        args = parser.parse_args(['list-sessions'])
        self.assertEqual(args.func, do_client_list_sessions)
        
        args = parser.parse_args(['get-session', '--session-id', 's1'])
        self.assertEqual(args.func, do_client_get_session)
        self.assertEqual(args.session_id, 's1')
        
        args = parser.parse_args(['delete-sessions', 's1', 's2'])
        self.assertEqual(args.func, do_client_delete_sessions)
        
        args = parser.parse_args(['process-session', '--session-id', 's1'])
        self.assertEqual(args.func, do_client_process_session)

    def test_add_message_parsers(self):
        """U-150: Test add_message_parsers adds all message subcommands"""
        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_message_parsers(subparsers)
        
        args = parser.parse_args(['send-message', '--message', 'Hello'])
        self.assertEqual(args.func, do_client_send_message)
        self.assertEqual(args.message, 'Hello')
        
        args = parser.parse_args(['get-messages', '--session-id', 's1'])
        self.assertEqual(args.func, do_client_get_messages)
        
        args = parser.parse_args(['list-messages', '--session-id', 's1'])
        self.assertEqual(args.func, do_client_get_messages)

    def test_add_task_parsers(self):
        """U-150: Test add_task_parsers adds all task subcommands"""
        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_task_parsers(subparsers)
        
        args = parser.parse_args(['set-task-result', '--processed-msg-id', 'm1', '--task-id', 't1', '--task-result', 'Done'])
        self.assertEqual(args.func, do_client_set_task_result)
        
        args = parser.parse_args(['get-tasks', '--session-id', 's1'])
        self.assertEqual(args.func, do_client_get_tasks)
        
        args = parser.parse_args(['list-tasks', '--session-id', 's1'])
        self.assertEqual(args.func, do_client_get_tasks)


if __name__ == "__main__":
    unittest.main()
