"""
Unit tests for context/ctx_manager.py module.

This module tests the context management functions including:
- get_managers_by_env(): Get chat history managers from environment config
- get_session_manager(): Get session manager with fallback logic
- get_messages_by_session(): Retrieve messages for a session
- exists_session(): Check if session exists
- create_session(): Create a new session
- add_session_message(): Add message to session
- del_session_messages(): Delete messages from session
- cut_messages(): Cut messages to head and tail

Author: mm-m25
"""

import os
import unittest
from unittest.mock import MagicMock, patch


class TestGetManagersByEnv(unittest.TestCase):
    """Test cases for get_managers_by_env() function."""

    def setUp(self):
        """Set up test fixtures."""
        # Store original environment
        self.original_env = os.environ.copy()

    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch('topsailai.context.ctx_manager.ALL_MANAGERS')
    @patch('topsailai.context.ctx_manager.logger')
    def test_get_managers_by_env_with_valid_config(self, mock_logger, mock_all_managers):
        """Test get_managers_by_env with valid environment configuration."""
        from topsailai.context.ctx_manager import get_managers_by_env

        # Setup mock manager
        mock_manager_instance = MagicMock()
        mock_all_managers.__contains__ = MagicMock(return_value=True)
        mock_all_managers.__getitem__ = MagicMock(return_value=lambda *a, **kw: mock_manager_instance)

        # Set environment variable
        os.environ['CONTEXT_HISTORY_MANAGERS'] = 'sql.ChatHistorySQLAlchemy conn=sqlite://memory.db'

        # Execute
        result = get_managers_by_env()

        # Verify
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)

    @patch('topsailai.context.ctx_manager.ALL_MANAGERS')
    @patch('topsailai.context.ctx_manager.logger')
    def test_get_managers_by_env_with_empty_env(self, mock_logger, mock_all_managers):
        """Test get_managers_by_env when environment variable is empty."""
        from topsailai.context.ctx_manager import get_managers_by_env

        # Ensure environment variable is not set
        os.environ.pop('CONTEXT_HISTORY_MANAGERS', None)

        # Execute
        result = get_managers_by_env()

        # Verify
        self.assertIsNone(result)
        mock_logger.info.assert_not_called()

    @patch('topsailai.context.ctx_manager.ALL_MANAGERS')
    @patch('topsailai.context.ctx_manager.logger')
    def test_get_managers_by_env_with_invalid_manager(self, mock_logger, mock_all_managers):
        """Test get_managers_by_env with invalid manager name."""
        from topsailai.context.ctx_manager import get_managers_by_env

        # Setup mock - manager not in ALL_MANAGERS
        mock_all_managers.__contains__ = MagicMock(return_value=False)

        # Set environment variable with invalid manager
        os.environ['CONTEXT_HISTORY_MANAGERS'] = 'invalid.Manager'

        # Execute
        result = get_managers_by_env()

        # Verify - should return empty list or None
        self.assertFalse(result)
        mock_logger.warning.assert_called()

    @patch('topsailai.context.ctx_manager.ALL_MANAGERS')
    @patch('topsailai.context.ctx_manager.logger')
    def test_get_managers_by_env_with_multiple_managers(self, mock_logger, mock_all_managers):
        """Test get_managers_by_env with multiple manager specifications."""
        from topsailai.context.ctx_manager import get_managers_by_env

        # Setup mock managers
        mock_manager1 = MagicMock()
        mock_manager2 = MagicMock()
        mock_all_managers.__contains__ = MagicMock(return_value=True)
        mock_all_managers.__getitem__ = MagicMock(side_effect=[
            lambda *a, **kw: mock_manager1,
            lambda *a, **kw: mock_manager2
        ])

        # Set environment variable with multiple managers (both need params)
        os.environ['CONTEXT_HISTORY_MANAGERS'] = 'sql.Manager1 param1=value1; sql.Manager2 param2=value2'

        # Execute with count=2 to get both managers
        result = get_managers_by_env(count=2)

        # Verify
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)

    @patch('topsailai.context.ctx_manager.ALL_MANAGERS')
    @patch('topsailai.context.ctx_manager.logger')
    def test_get_managers_by_env_with_count_limit(self, mock_logger, mock_all_managers):
        """Test get_managers_by_env respects count parameter."""
        from topsailai.context.ctx_manager import get_managers_by_env

        # Setup mock managers
        mock_manager = MagicMock()
        mock_all_managers.__contains__ = MagicMock(return_value=True)
        mock_all_managers.__getitem__ = MagicMock(return_value=lambda *a, **kw: mock_manager)

        # Set environment variable with multiple managers
        os.environ['CONTEXT_HISTORY_MANAGERS'] = 'sql.Manager1 param1=v1; sql.Manager2 param2=v2; sql.Manager3 param3=v3'

        # Execute with count=2
        result = get_managers_by_env(count=2)

        # Verify - should only return 2 managers
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)


class TestGetSessionManager(unittest.TestCase):
    """Test cases for get_session_manager() function."""

    @patch('topsailai.context.ctx_manager.SessionSQLAlchemy')
    @patch('topsailai.context.ctx_manager.get_managers_by_env')
    def test_get_session_manager_with_provided_conn(self, mock_get_managers, mock_session_sql):
        """Test get_session_manager with provided connection string."""
        from topsailai.context.ctx_manager import get_session_manager

        mock_instance = MagicMock()
        mock_session_sql.return_value = mock_instance

        # Execute with provided connection
        result = get_session_manager(conn='sqlite://test.db')

        # Verify
        mock_session_sql.assert_called_once_with('sqlite://test.db')
        self.assertEqual(result, mock_instance)

    @patch('topsailai.context.ctx_manager.SessionSQLAlchemy')
    @patch('topsailai.context.ctx_manager.get_managers_by_env')
    def test_get_session_manager_from_env(self, mock_get_managers, mock_session_sql):
        """Test get_session_manager falls back to environment config."""
        from topsailai.context.ctx_manager import get_session_manager

        mock_manager = MagicMock()
        mock_manager.conn = 'sqlite://env.db'
        mock_get_managers.return_value = [mock_manager]

        mock_instance = MagicMock()
        mock_session_sql.return_value = mock_instance

        # Execute without connection
        result = get_session_manager()

        # Verify
        mock_get_managers.assert_called_once_with(1)
        mock_session_sql.assert_called_once_with('sqlite://env.db')

    @patch('topsailai.context.ctx_manager.SessionSQLAlchemy')
    @patch('topsailai.context.ctx_manager.get_managers_by_env')
    def test_get_session_manager_with_default_conn(self, mock_get_managers, mock_session_sql):
        """Test get_session_manager uses default connection."""
        from topsailai.context.ctx_manager import get_session_manager

        mock_get_managers.return_value = None

        mock_instance = MagicMock()
        mock_session_sql.return_value = mock_instance

        # Execute
        result = get_session_manager(default_conn='sqlite://default.db')

        # Verify
        mock_session_sql.assert_called_once_with('sqlite://default.db')

    @patch('topsailai.context.ctx_manager.SessionSQLAlchemy')
    @patch('topsailai.context.ctx_manager.get_managers_by_env')
    def test_get_session_manager_raises_exception(self, mock_get_managers, mock_session_sql):
        """Test get_session_manager raises exception when no config available."""
        from topsailai.context.ctx_manager import get_session_manager

        mock_get_managers.return_value = None

        # Execute and expect exception
        with self.assertRaises(Exception) as context:
            get_session_manager(conn=None, default_conn=None)

        self.assertIn('fail to get session manager', str(context.exception))


class TestGetMessagesBySession(unittest.TestCase):
    """Test cases for get_messages_by_session() function."""

    @patch('topsailai.context.ctx_manager.get_session_manager')
    @patch('topsailai.context.ctx_manager.env_tool.get_session_id')
    @patch('topsailai.context.ctx_manager.logger')
    def test_get_messages_by_session_with_valid_id(self, mock_logger, mock_get_session_id, mock_get_session_mgr):
        """Test get_messages_by_session with valid session ID."""
        from topsailai.context.ctx_manager import get_messages_by_session

        mock_get_session_id.return_value = 'test-session-123'
        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = True
        mock_session_mgr.retrieve_messages.return_value = [{'role': 'user', 'content': 'hello'}]
        mock_get_session_mgr.return_value = mock_session_mgr

        # Execute
        result = get_messages_by_session(session_id='test-session-123')

        # Verify
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        mock_logger.info.assert_called()

    @patch('topsailai.context.ctx_manager.get_session_manager')
    @patch('topsailai.context.ctx_manager.env_tool.get_session_id')
    @patch('topsailai.context.ctx_manager.logger')
    def test_get_messages_by_session_with_empty_id(self, mock_logger, mock_get_session_id, mock_get_session_mgr):
        """Test get_messages_by_session with empty session ID."""
        from topsailai.context.ctx_manager import get_messages_by_session

        mock_get_session_id.return_value = None

        # Execute with empty session_id
        result = get_messages_by_session(session_id='')

        # Verify
        self.assertEqual(result, [])
        mock_get_session_mgr.assert_not_called()

    @patch('topsailai.context.ctx_manager.get_session_manager')
    @patch('topsailai.context.ctx_manager.env_tool.get_session_id')
    @patch('topsailai.context.ctx_manager.logger')
    def test_get_messages_by_session_not_exists(self, mock_logger, mock_get_session_id, mock_get_session_mgr):
        """Test get_messages_by_session when session doesn't exist."""
        from topsailai.context.ctx_manager import get_messages_by_session

        mock_get_session_id.return_value = 'non-existent-session'
        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = False
        mock_get_session_mgr.return_value = mock_session_mgr

        # Execute
        result = get_messages_by_session(session_id='non-existent-session')

        # Verify
        self.assertEqual(result, [])

    @patch('topsailai.context.ctx_manager.get_session_manager')
    @patch('topsailai.context.ctx_manager.env_tool.get_session_id')
    @patch('topsailai.context.ctx_manager.logger')
    def test_get_messages_by_session_for_raw(self, mock_logger, mock_get_session_id, mock_get_session_mgr):
        """Test get_messages_by_session with for_raw=True."""
        from topsailai.context.ctx_manager import get_messages_by_session

        mock_get_session_id.return_value = 'test-session'
        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = True
        mock_session_mgr.get_messages_by_session.return_value = ['raw_message_1', 'raw_message_2']
        mock_get_session_mgr.return_value = mock_session_mgr

        # Execute with for_raw=True
        result = get_messages_by_session(session_id='test-session', for_raw=True)

        # Verify
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)


class TestExistsSession(unittest.TestCase):
    """Test cases for exists_session() function."""

    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_exists_session_with_valid_id(self, mock_get_session_mgr):
        """Test exists_session returns True for existing session."""
        from topsailai.context.ctx_manager import exists_session

        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = True
        mock_get_session_mgr.return_value = mock_session_mgr

        # Execute
        result = exists_session(session_id='existing-session')

        # Verify
        self.assertTrue(result)
        mock_session_mgr.exists_session.assert_called_once_with('existing-session')

    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_exists_session_with_empty_id(self, mock_get_session_mgr):
        """Test exists_session returns False for empty session ID."""
        from topsailai.context.ctx_manager import exists_session

        # Execute with empty session_id
        result = exists_session(session_id='')

        # Verify
        self.assertFalse(result)
        mock_get_session_mgr.assert_not_called()

    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_exists_session_not_found(self, mock_get_session_mgr):
        """Test exists_session returns False for non-existing session."""
        from topsailai.context.ctx_manager import exists_session

        mock_session_mgr = MagicMock()
        mock_session_mgr.exists_session.return_value = False
        mock_get_session_mgr.return_value = mock_session_mgr

        # Execute
        result = exists_session(session_id='non-existing-session')

        # Verify
        self.assertFalse(result)


class TestCreateSession(unittest.TestCase):
    """Test cases for create_session() function."""

    @patch('topsailai.context.ctx_manager.generate_session_name')
    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_create_session_success(self, mock_get_session_mgr, mock_generate):
        """Test create_session successfully creates a session."""
        from topsailai.context.ctx_manager import create_session

        mock_session_mgr = MagicMock()
        mock_get_session_mgr.return_value = mock_session_mgr
        mock_generate.return_value = ''

        # Execute
        result = create_session(session_id='new-session', task='Test task')

        # Verify
        self.assertTrue(result)
        mock_session_mgr.create_session.assert_called_once()

    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_create_session_with_empty_id(self, mock_get_session_mgr):
        """Test create_session returns False for empty session ID."""
        from topsailai.context.ctx_manager import create_session

        # Execute with empty session_id
        result = create_session(session_id='', task='Test task')

        # Verify
        self.assertFalse(result)
        mock_get_session_mgr.assert_not_called()

    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_create_session_with_empty_task(self, mock_get_session_mgr):
        """Test create_session returns False for empty task."""
        from topsailai.context.ctx_manager import create_session

        # Execute with empty task
        result = create_session(session_id='session-123', task='')

        # Verify
        self.assertFalse(result)
        mock_get_session_mgr.assert_not_called()

    @patch('topsailai.context.ctx_manager.generate_session_name')
    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_create_session_populates_environment_paths(self, mock_get_session_mgr, mock_generate):
        """Test create_session populates environment path fields from env vars."""
        from topsailai.context.ctx_manager import create_session
        from topsailai.context.session_manager.__base import SessionData

        os.environ['TOPSAILAI_PROJECT_WORKSPACE'] = '/workspace/project'
        os.environ['TOPSAILAI_PWD'] = '/workspace/project/src'
        os.environ['TOPSAILAI_HOME'] = '/home/user/.topsailai'

        mock_session_mgr = MagicMock()
        mock_get_session_mgr.return_value = mock_session_mgr
        mock_generate.return_value = ''

        result = create_session(session_id='session-123', task='Test task')

        self.assertTrue(result)
        mock_session_mgr.create_session.assert_called_once()
        session_data = mock_session_mgr.create_session.call_args.args[0]
        self.assertIsInstance(session_data, SessionData)
        self.assertEqual(session_data.project_workspace, '/workspace/project')
        self.assertEqual(session_data.pwd, '/workspace/project/src')
        self.assertEqual(session_data.topsailai_home, '/home/user/.topsailai')

    @patch('topsailai.context.ctx_manager.generate_session_name')
    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_create_session_environment_paths_optional(self, mock_get_session_mgr, mock_generate):
        """Test create_session leaves environment path fields None when env vars absent."""
        from topsailai.context.ctx_manager import create_session
        from topsailai.context.session_manager.__base import SessionData

        os.environ.pop('TOPSAILAI_PROJECT_WORKSPACE', None)
        os.environ.pop('TOPSAILAI_PWD', None)
        os.environ.pop('TOPSAILAI_HOME', None)

        mock_session_mgr = MagicMock()
        mock_get_session_mgr.return_value = mock_session_mgr
        mock_generate.return_value = ''
        with patch('topsailai.workspace.folder_constants.TOPSAILAI_HOME', None):
            result = create_session(session_id='session-123', task='Test task')
        self.assertTrue(result)
        session_data = mock_session_mgr.create_session.call_args.args[0]
        self.assertIsInstance(session_data, SessionData)
        self.assertIsNone(session_data.topsailai_home)

    @patch('topsailai.context.ctx_manager.generate_session_name')
    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_create_session_uses_pwd_fallback_for_workspace(self, mock_get_session_mgr, mock_generate):
        """Test create_session falls back to TOPSAILAI_PWD for project workspace."""
        from topsailai.context.ctx_manager import create_session
        from topsailai.context.session_manager.__base import SessionData

        os.environ.pop('TOPSAILAI_PROJECT_WORKSPACE', None)
        os.environ['TOPSAILAI_PWD'] = '/workspace/project/src'

        mock_session_mgr = MagicMock()
        mock_get_session_mgr.return_value = mock_session_mgr
        mock_generate.return_value = ''

        result = create_session(session_id='session-123', task='Test task')

        self.assertTrue(result)
        session_data = mock_session_mgr.create_session.call_args.args[0]
        self.assertIsInstance(session_data, SessionData)
        self.assertEqual(session_data.project_workspace, '/workspace/project/src')

class TestUpdateSessionName(unittest.TestCase):
    """Test cases for update_session_name() function."""

    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_update_session_name_success(self, mock_get_session_mgr):
        """Test update_session_name successfully updates session name."""
        from topsailai.context.ctx_manager import update_session_name

        mock_session_mgr = MagicMock()
        mock_session_mgr.update_session_name.return_value = True
        mock_get_session_mgr.return_value = mock_session_mgr

        # Execute
        result = update_session_name(session_id='session-123', session_name='New Name')

        # Verify
        self.assertTrue(result)
        mock_session_mgr.update_session_name.assert_called_once_with('session-123', 'New Name')

    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_update_session_name_with_empty_id(self, mock_get_session_mgr):
        """Test update_session_name returns False for empty session ID."""
        from topsailai.context.ctx_manager import update_session_name

        # Execute with empty session_id
        result = update_session_name(session_id='', session_name='New Name')

        # Verify
        self.assertFalse(result)
        mock_get_session_mgr.assert_not_called()

    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_update_session_name_with_provided_mgr(self, mock_get_session_mgr):
        """Test update_session_name uses provided session manager."""
        from topsailai.context.ctx_manager import update_session_name

        mock_session_mgr = MagicMock()
        mock_session_mgr.update_session_name.return_value = True

        # Execute with provided manager
        result = update_session_name(session_id='session-123', session_name='New Name', session_mgr=mock_session_mgr)

        # Verify
        self.assertTrue(result)
        mock_get_session_mgr.assert_not_called()
        mock_session_mgr.update_session_name.assert_called_once_with('session-123', 'New Name')

    @patch('topsailai.context.ctx_manager.get_session_manager')
    def test_update_session_name_with_none_name(self, mock_get_session_mgr):
        """Test update_session_name returns False when session_name is None."""
        from topsailai.context.ctx_manager import update_session_name

        result = update_session_name(session_id='session-123', session_name=None)

        self.assertFalse(result)
        mock_get_session_mgr.assert_not_called()


class TestAddSessionMessage(unittest.TestCase):
    """Test cases for add_session_message() function."""

    @patch('topsailai.context.ctx_manager.get_managers_by_env')
    def test_add_session_message_success(self, mock_get_managers):
        """Test add_session_message successfully adds message."""
        from topsailai.context.ctx_manager import add_session_message

        mock_manager1 = MagicMock()
        mock_manager2 = MagicMock()
        mock_get_managers.return_value = [mock_manager1, mock_manager2]

        message = {'role': 'user', 'content': 'Hello'}

        # Execute
        result = add_session_message(session_id='test-session', message=message)

        # Verify
        self.assertTrue(result)
        mock_manager1.add_session_message.assert_called_once_with(message, session_id='test-session')
        mock_manager2.add_session_message.assert_called_once_with(message, session_id='test-session')

    @patch('topsailai.context.ctx_manager.get_managers_by_env')
    def test_add_session_message_no_managers(self, mock_get_managers):
        """Test add_session_message returns False when no managers configured."""
        from topsailai.context.ctx_manager import add_session_message

        mock_get_managers.return_value = None

        # Execute
        result = add_session_message(session_id='test-session', message={'role': 'user'})

        # Verify
        self.assertFalse(result)


class TestDelSessionMessages(unittest.TestCase):
    """Test cases for del_session_messages() function."""

    @patch('topsailai.context.ctx_manager.to_list')
    @patch('topsailai.context.ctx_manager.get_managers_by_env')
    def test_del_session_messages_success(self, mock_get_managers, mock_to_list):
        """Test del_session_messages successfully deletes messages."""
        from topsailai.context.ctx_manager import del_session_messages

        mock_manager = MagicMock()
        mock_get_managers.return_value = [mock_manager]
        mock_to_list.return_value = ['msg1', 'msg2']

        # Execute
        result = del_session_messages(session_id='test-session', message_ids=['msg1', 'msg2'])

        # Verify
        self.assertTrue(result)
        mock_manager.del_messages.assert_called()

    @patch('topsailai.context.ctx_manager.get_managers_by_env')
    def test_del_session_messages_no_managers(self, mock_get_managers):
        """Test del_session_messages returns False when no managers configured."""
        from topsailai.context.ctx_manager import del_session_messages

        mock_get_managers.return_value = None

        # Execute
        result = del_session_messages(session_id='test-session', message_ids=['msg1'])

        # Verify
        self.assertFalse(result)

    @patch('topsailai.context.ctx_manager.get_managers_by_env')
    def test_del_session_messages_empty_ids(self, mock_get_managers):
        """Test del_session_messages returns False for empty message_ids."""
        from topsailai.context.ctx_manager import del_session_messages

        # Execute with empty message_ids
        result = del_session_messages(session_id='test-session', message_ids=[])

        # Verify
        self.assertFalse(result)


class TestCutMessages(unittest.TestCase):
    """Test cases for cut_messages() function."""

    @patch('topsailai.context.ctx_manager.logger')
    def test_cut_messages_with_long_list(self, mock_logger):
        """Test cut_messages cuts long message list to head and tail."""
        from topsailai.context.ctx_manager import cut_messages

        messages = list(range(20))  # 20 messages

        # Execute
        result = cut_messages(messages, head_tail_offset=5)

        # Verify - should return first 5 and last 5
        self.assertEqual(len(result), 10)
        self.assertEqual(result[:5], [0, 1, 2, 3, 4])
        self.assertEqual(result[5:], [15, 16, 17, 18, 19])
        mock_logger.info.assert_called()

    @patch('topsailai.context.ctx_manager.logger')
    def test_cut_messages_with_short_list(self, mock_logger):
        """Test cut_messages returns original list when short."""
        from topsailai.context.ctx_manager import cut_messages

        messages = [1, 2, 3]  # Only 3 messages

        # Execute
        result = cut_messages(messages, head_tail_offset=5)

        # Verify - should return original list
        self.assertEqual(result, messages)
        mock_logger.info.assert_not_called()

    def test_cut_messages_with_empty_list(self):
        """Test cut_messages returns empty list as-is."""
        from topsailai.context.ctx_manager import cut_messages

        # Execute
        result = cut_messages([], head_tail_offset=5)

        # Verify
        self.assertEqual(result, [])

    @patch('topsailai.context.ctx_manager.logger')
    def test_cut_messages_with_string_offset(self, mock_logger):
        """Test cut_messages handles string head_tail_offset."""
        from topsailai.context.ctx_manager import cut_messages

        messages = list(range(20))

        # Execute with string offset
        result = cut_messages(messages, head_tail_offset='5')

        # Verify
        self.assertEqual(len(result), 10)

    @patch('topsailai.context.ctx_manager.logger')
    def test_cut_messages_with_zero_offset(self, mock_logger):
        """Test cut_messages with zero offset returns original list."""
        from topsailai.context.ctx_manager import cut_messages

        messages = list(range(20))

        # Execute with zero offset
        result = cut_messages(messages, head_tail_offset=0)

        # Verify - should return original list
        self.assertEqual(result, messages)


class TestModuleIntegration(unittest.TestCase):
    """Integration tests for ctx_manager module."""

    def test_module_import(self):
        """Test that the module can be imported successfully."""
        from topsailai.context import ctx_manager

        # Verify module has expected functions
        self.assertTrue(hasattr(ctx_manager, 'get_managers_by_env'))
        self.assertTrue(hasattr(ctx_manager, 'get_session_manager'))
        self.assertTrue(hasattr(ctx_manager, 'get_messages_by_session'))
        self.assertTrue(hasattr(ctx_manager, 'exists_session'))
        self.assertTrue(hasattr(ctx_manager, 'create_session'))
        self.assertTrue(hasattr(ctx_manager, 'add_session_message'))
        self.assertTrue(hasattr(ctx_manager, 'del_session_messages'))
        self.assertTrue(hasattr(ctx_manager, 'cut_messages'))

    def test_all_functions_exported(self):
        """Test that all functions are properly exported."""
        from topsailai.context.ctx_manager import (
            get_managers_by_env,
            get_session_manager,
            get_messages_by_session,
            exists_session,
            create_session,
            add_session_message,
            del_session_messages,
            cut_messages,
        )

        # Verify all functions are callable
        self.assertTrue(callable(get_managers_by_env))
        self.assertTrue(callable(get_session_manager))
        self.assertTrue(callable(get_messages_by_session))
        self.assertTrue(callable(exists_session))
        self.assertTrue(callable(create_session))
        self.assertTrue(callable(add_session_message))
        self.assertTrue(callable(del_session_messages))
        self.assertTrue(callable(cut_messages))




class TestGenerateSessionName(unittest.TestCase):
    """Test cases for generate_session_name() function."""

    def setUp(self):
        """Store original environment."""
        self.original_env = os.environ.copy()

    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch('topsailai.workspace.llm_shell.get_llm_chat')
    def test_generate_session_name_success(self, mock_get_llm_chat):
        """Test generate_session_name returns cleaned LLM output."""
        from topsailai.context.ctx_manager import generate_session_name

        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = '"  My Session Name  "'
        mock_get_llm_chat.return_value = mock_llm_chat

        result = generate_session_name('session-123', 'Please help me write a Python script.')

        self.assertEqual(result, 'My Session Name')
        mock_get_llm_chat.assert_called_once()
        call_kwargs = mock_get_llm_chat.call_args.kwargs
        self.assertIn('system_prompt', call_kwargs)
        self.assertIn('message', call_kwargs)
        self.assertNotEqual(call_kwargs['system_prompt'], call_kwargs['message'])
        self.assertIn('naming assistant', call_kwargs['system_prompt'].lower())
        self.assertIn('Python script', call_kwargs['message'])

    @patch('topsailai.workspace.llm_shell.get_llm_chat')
    def test_generate_session_name_truncates_to_max_length(self, mock_get_llm_chat):
        """Test generate_session_name truncates result to max length."""
        from topsailai.context.ctx_manager import generate_session_name

        os.environ['TOPSAILAI_AUTO_SESSION_NAME_MAX_LENGTH'] = '10'

        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = 'A very long session name that exceeds limit'
        mock_get_llm_chat.return_value = mock_llm_chat

        result = generate_session_name('session-123', 'Some task')

        self.assertEqual(len(result), 10)
        self.assertEqual(result, 'A very lon')

    @patch('topsailai.workspace.llm_shell.get_llm_chat')
    def test_generate_session_name_empty_input(self, mock_get_llm_chat):
        """Test generate_session_name returns empty for empty inputs."""
        from topsailai.context.ctx_manager import generate_session_name

        self.assertEqual(generate_session_name('', 'task'), '')
        self.assertEqual(generate_session_name('session', ''), '')
        mock_get_llm_chat.assert_not_called()

    @patch('topsailai.workspace.llm_shell.get_llm_chat')
    def test_generate_session_name_empty_llm_output(self, mock_get_llm_chat):
        """Test generate_session_name returns empty when LLM returns empty."""
        from topsailai.context.ctx_manager import generate_session_name

        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = '   '
        mock_get_llm_chat.return_value = mock_llm_chat

        result = generate_session_name('session-123', 'Some task')

        self.assertEqual(result, '')

    @patch('topsailai.workspace.llm_shell.get_llm_chat')
    def test_generate_session_name_none_llm_output(self, mock_get_llm_chat):
        """Test generate_session_name returns empty when LLM returns None."""
        from topsailai.context.ctx_manager import generate_session_name

        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = None
        mock_get_llm_chat.return_value = mock_llm_chat

        result = generate_session_name('session-123', 'Some task')

        self.assertEqual(result, '')

    @patch('topsailai.workspace.llm_shell.get_llm_chat')
    def test_generate_session_name_exception_swallowed(self, mock_get_llm_chat):
        """Test generate_session_name swallows exceptions and returns empty."""
        from topsailai.context.ctx_manager import generate_session_name

        mock_get_llm_chat.side_effect = Exception('LLM failed')

        result = generate_session_name('session-123', 'Some task')

        self.assertEqual(result, '')

    @patch('topsailai.workspace.llm_shell.get_llm_chat')
    def test_generate_session_name_invalid_max_length_fallback(self, mock_get_llm_chat):
        """Test generate_session_name falls back to 30 for invalid max length."""
        from topsailai.context.ctx_manager import generate_session_name

        os.environ['TOPSAILAI_AUTO_SESSION_NAME_MAX_LENGTH'] = 'not-a-number'

        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = 'A' * 40
        mock_get_llm_chat.return_value = mock_llm_chat

        result = generate_session_name('session-123', 'Some task')

        self.assertEqual(len(result), 30)

    @patch('topsailai.workspace.llm_shell.get_llm_chat')
    def test_generate_session_name_non_positive_max_length_fallback(self, mock_get_llm_chat):
        """Test generate_session_name falls back to 30 for non-positive max length."""
        from topsailai.context.ctx_manager import generate_session_name

        os.environ['TOPSAILAI_AUTO_SESSION_NAME_MAX_LENGTH'] = '0'

        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = 'A' * 40
        mock_get_llm_chat.return_value = mock_llm_chat

        result = generate_session_name('session-123', 'Some task')

        self.assertEqual(len(result), 30)


class TestCreateSessionAutoRename(unittest.TestCase):
    """Test cases for create_session() auto-rename behavior."""

    def setUp(self):
        """Store original environment."""
        self.original_env = os.environ.copy()

    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch('topsailai.context.ctx_manager.get_session_manager')
    @patch('topsailai.context.ctx_manager.generate_session_name')
    def test_create_session_triggers_auto_rename(self, mock_generate, mock_get_session_mgr):
        """Test create_session starts auto-rename when session_name is empty."""
        from topsailai.context.ctx_manager import create_session

        mock_session_mgr = MagicMock()
        mock_get_session_mgr.return_value = mock_session_mgr
        mock_generate.return_value = 'Auto Name'

        result = create_session(session_id='session-123', task='Help me refactor code.')

        self.assertTrue(result)
        # Wait briefly for daemon thread to finish
        import time
        time.sleep(0.1)
        mock_generate.assert_called_once_with('session-123', 'Help me refactor code.')
        mock_session_mgr.update_session_name.assert_called_once_with('session-123', 'Auto Name')

    @patch('topsailai.context.ctx_manager.get_session_manager')
    @patch('topsailai.context.ctx_manager.generate_session_name')
    def test_create_session_skips_auto_rename_when_name_provided(self, mock_generate, mock_get_session_mgr):
        """Test create_session skips auto-rename when session_name is provided."""
        from topsailai.context.ctx_manager import create_session

        mock_session_mgr = MagicMock()
        mock_get_session_mgr.return_value = mock_session_mgr

        result = create_session(
            session_id='session-123',
            task='Help me refactor code.',
            session_name='Manual Name',
        )

        self.assertTrue(result)
        mock_generate.assert_not_called()
        mock_session_mgr.update_session_name.assert_not_called()

    @patch('topsailai.context.ctx_manager.get_session_manager')
    @patch('topsailai.context.ctx_manager.generate_session_name')
    def test_create_session_skips_auto_rename_when_disabled(self, mock_generate, mock_get_session_mgr):
        """Test create_session skips auto-rename when disabled."""
        from topsailai.context.ctx_manager import create_session

        os.environ['TOPSAILAI_AUTO_SESSION_NAME_ENABLED'] = '0'

        mock_session_mgr = MagicMock()
        mock_get_session_mgr.return_value = mock_session_mgr

        result = create_session(session_id='session-123', task='Help me refactor code.')

        self.assertTrue(result)
        mock_generate.assert_not_called()
        mock_session_mgr.update_session_name.assert_not_called()

    @patch('topsailai.context.ctx_manager.get_session_manager')
    @patch('topsailai.context.ctx_manager.generate_session_name')
    def test_create_session_auto_rename_failure_swallowed(self, mock_generate, mock_get_session_mgr):
        """Test create_session swallows auto-rename failures."""
        from topsailai.context.ctx_manager import create_session

        mock_session_mgr = MagicMock()
        mock_get_session_mgr.return_value = mock_session_mgr
        mock_generate.side_effect = Exception('generation failed')

        result = create_session(session_id='session-123', task='Help me refactor code.')

        self.assertTrue(result)
        import time
        time.sleep(0.1)
        mock_session_mgr.update_session_name.assert_not_called()

    @patch('topsailai.context.ctx_manager.get_session_manager')
    @patch('topsailai.context.ctx_manager.generate_session_name')
    def test_create_session_auto_rename_updates_even_if_name_exists(self, mock_generate, mock_get_session_mgr):
        """Test auto-rename calls update_session_name without checking existing name."""
        from topsailai.context.ctx_manager import create_session

        mock_session_mgr = MagicMock()
        mock_get_session_mgr.return_value = mock_session_mgr
        mock_generate.return_value = 'Auto Name'

        result = create_session(session_id='session-123', task='Help me refactor code.')

        self.assertTrue(result)
        import time
        time.sleep(0.1)
        mock_generate.assert_called_with('session-123', 'Help me refactor code.')
        mock_session_mgr.update_session_name.assert_called_once_with('session-123', 'Auto Name')
if __name__ == '__main__':
    unittest.main()
