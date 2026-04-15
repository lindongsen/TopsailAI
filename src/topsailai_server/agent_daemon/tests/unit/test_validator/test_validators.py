'''
  Author: km-k25
  Email: km-k25@topsail.ai
  Created: 2026-04-15
  Purpose: Comprehensive unit tests for validator functions
'''

import unittest
from unittest.mock import patch, MagicMock

from topsailai_server.agent_daemon.validator.validators import (
    validate_session_id,
    validate_message_content,
    validate_role,
    validate_task_id,
    validate_msg_id,
)


class TestValidateSessionId(unittest.TestCase):
    """Test cases for validate_session_id function"""

    def test_valid_session_id_alphanumeric(self):
        """Test valid alphanumeric session_id"""
        valid_ids = [
            'session123',
            'test_session_456',
            'Session789',
            'abc123def456',
            'a',
            'ABC',
            '123',
            'test123ABC',
        ]
        for session_id in valid_ids:
            # Should not raise any exception
            validate_session_id(session_id)

    def test_valid_session_id_with_special_chars(self):
        """Test valid session_id with allowed special characters"""
        valid_ids = [
            'session:123',
            'test.session.456',
            'session-123',
            'session_123',
            'session:abc.def-ghi_jkl',
            'a:b.c-d_e',
            'session:1.2-3_4',
        ]
        for session_id in valid_ids:
            validate_session_id(session_id)

    def test_valid_session_id_uuid_format(self):
        """Test valid UUID format session_id"""
        valid_uuids = [
            '550e8400-e29b-41d4-a716-446655440000',
            '12345678-1234-1234-1234-123456789abc',
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            '00000000-0000-0000-0000-000000000000',
        ]
        for session_id in valid_uuids:
            validate_session_id(session_id)

    def test_invalid_session_id_empty_string(self):
        """Test invalid empty string session_id"""
        with self.assertRaises(ValueError) as context:
            validate_session_id('')
        self.assertIn('cannot be empty', str(context.exception))

    def test_invalid_session_id_whitespace_only(self):
        """Test invalid whitespace-only session_id - treated as invalid format"""
        invalid_ids = [
            '   ',
            '\t',
            '\n',
            '\r',
            '\t\n\r ',
        ]
        for session_id in invalid_ids:
            with self.assertRaises(ValueError) as context:
                validate_session_id(session_id)
            # Whitespace-only strings fail format validation, not empty check
            self.assertIn('Invalid session_id format', str(context.exception))

    def test_invalid_session_id_none(self):
        """Test invalid None session_id"""
        with self.assertRaises((ValueError, TypeError)):
            validate_session_id(None)

    def test_invalid_session_id_special_chars(self):
        """Test invalid session_id with disallowed special characters"""
        invalid_ids = [
            'session@domain.com',
            'session#hash',
            'session space',
            'session!exclamation',
            'session$money',
            'session%percent',
            'session^caret',
            'session&ampersand',
            'session*star',
            'session(paren)',
            'session+plus',
            'session=equal',
            'session[bracket]',
            'session{brace}',
            'session|pipe',
            'session\\backslash',
            'session<less>',
            'session>greater',
            'session?question',
            'session/slash',
            'session\'quote',
            'session"doublequote',
            'session`backtick',
            'session~tilde',
        ]
        for session_id in invalid_ids:
            with self.assertRaises(ValueError) as context:
                validate_session_id(session_id)
            self.assertIn('Invalid session_id format', str(context.exception))

    def test_invalid_session_id_unicode(self):
        """Test invalid session_id with unicode characters"""
        invalid_ids = [
            'session\u4e2d\u6587',  # Chinese characters
            'session\u3042\u3044',  # Japanese hiragana
            'session\u0430\u0431\u0432',  # Cyrillic
            'session\u00e9\u00e8',  # Accented characters
            'session\U0001f600',  # Emoji
            'session\u2600',  # Symbol
        ]
        for session_id in invalid_ids:
            with self.assertRaises(ValueError):
                validate_session_id(session_id)

    def test_valid_session_id_very_long(self):
        """Test valid very long session_id (no max length limit)"""
        # 200+ characters - should be valid
        long_session_id = 'a' * 200
        validate_session_id(long_session_id)

    def test_invalid_session_id_sql_injection(self):
        """Test invalid session_id with SQL injection patterns"""
        invalid_ids = [
            "session'; DROP TABLE sessions; --",
            'session" OR "1"="1',
            'session; DELETE FROM sessions;',
            'session<script>alert(1)</script>',
            'session../../../etc/passwd',
            'session\x00nullbyte',
        ]
        for session_id in invalid_ids:
            with self.assertRaises(ValueError):
                validate_session_id(session_id)

    def test_boundary_session_id_single_char(self):
        """Test boundary case: single character session_id"""
        # Single alphanumeric character should be valid
        validate_session_id('a')
        validate_session_id('A')
        validate_session_id('1')
        validate_session_id('_')
        validate_session_id('-')

    def test_boundary_session_id_max_length(self):
        """Test boundary case: maximum reasonable length session_id"""
        # 100 characters should be valid
        session_id = 'a' * 100
        validate_session_id(session_id)


class TestValidateMessageContent(unittest.TestCase):
    """Test cases for validate_message_content function"""

    def test_valid_message_content_normal(self):
        """Test valid normal message content"""
        valid_contents = [
            'Hello, world!',
            'This is a test message.',
            'Message with numbers 123 and symbols !@#$%',
            'Multi\nline\nmessage',
            'Message with\ttabs',
        ]
        for content in valid_contents:
            validate_message_content(content)

    def test_valid_message_content_unicode(self):
        """Test valid unicode message content"""
        valid_contents = [
            '\u4e2d\u6587\u6d88\u606f',  # Chinese
            '\u3042\u3044\u3046\u3048\u304a',  # Japanese hiragana
            '\u043f\u0440\u0438\u0432\u0435\u0442',  # Russian
            'Hello \u4e16\u754c',  # Mixed
            '\U0001f600 \U0001f601 \U0001f602',  # Emojis
            '\u2600 \u2601 \u2602',  # Weather symbols
            'Caf\u00e9 r\u00e9sum\u00e9',  # Accented characters
        ]
        for content in valid_contents:
            validate_message_content(content)

    def test_valid_message_content_very_long(self):
        """Test valid very long message content (10K+ chars)"""
        long_content = 'x' * 10000
        validate_message_content(long_content)

        very_long_content = 'Test message ' * 10000  # ~130K chars
        validate_message_content(very_long_content)

    def test_invalid_message_content_empty_string(self):
        """Test invalid empty string message content"""
        with self.assertRaises(ValueError) as context:
            validate_message_content('')
        self.assertIn('cannot be empty', str(context.exception))

    def test_invalid_message_content_whitespace_only(self):
        """Test invalid whitespace-only message content"""
        invalid_contents = [
            '   ',
            '\t',
            '\n',
            '\r',
            '\t\n\r ',
            ' \t \n \r ',
        ]
        for content in invalid_contents:
            with self.assertRaises(ValueError) as context:
                validate_message_content(content)
            self.assertIn('cannot be only whitespace', str(context.exception))

    def test_invalid_message_content_none(self):
        """Test invalid None message content"""
        with self.assertRaises((ValueError, TypeError)):
            validate_message_content(None)

    def test_invalid_message_content_non_string_types(self):
        """Test invalid non-string message content types"""
        invalid_contents = [
            123,
            45.67,
            ['message'],
            {'message': 'content'},
            {'message'},
            True,
            False,
            object(),
        ]
        for content in invalid_contents:
            with self.assertRaises((ValueError, TypeError)):
                validate_message_content(content)

    def test_boundary_message_content_single_char(self):
        """Test boundary case: single character message content"""
        validate_message_content('a')
        validate_message_content('1')
        validate_message_content('!')
        validate_message_content('\u4e2d')  # Single Chinese character


class TestValidateRole(unittest.TestCase):
    """Test cases for validate_role function"""

    def test_valid_role_user(self):
        """Test valid 'user' role"""
        validate_role('user')

    def test_valid_role_assistant(self):
        """Test valid 'assistant' role"""
        validate_role('assistant')

    def test_invalid_role_empty_string(self):
        """Test invalid empty string role"""
        with self.assertRaises(ValueError) as context:
            validate_role('')
        self.assertIn('Invalid role', str(context.exception))

    def test_invalid_role_whitespace(self):
        """Test invalid whitespace role"""
        invalid_roles = [
            ' ',
            '  ',
            '\t',
            '\n',
            'user ',
            ' user',
            ' user ',
            'assistant ',
            ' assistant',
        ]
        for role in invalid_roles:
            with self.assertRaises(ValueError) as context:
                validate_role(role)
            self.assertIn('Invalid role', str(context.exception))

    def test_invalid_role_none(self):
        """Test invalid None role"""
        with self.assertRaises((ValueError, TypeError)):
            validate_role(None)

    def test_invalid_role_case_sensitivity(self):
        """Test role validation is case sensitive"""
        invalid_roles = [
            'User',
            'USER',
            'USER',
            'Assistant',
            'ASSISTANT',
            'ASSISTANT',
        ]
        for role in invalid_roles:
            with self.assertRaises(ValueError) as context:
                validate_role(role)
            self.assertIn('Invalid role', str(context.exception))

    def test_invalid_role_other_values(self):
        """Test invalid other role values"""
        invalid_roles = [
            'system',
            'admin',
            'bot',
            'ai',
            'human',
            '123',
            'role',
            'test',
            'developer',
            'operator',
        ]
        for role in invalid_roles:
            with self.assertRaises(ValueError) as context:
                validate_role(role)
            self.assertIn('Invalid role', str(context.exception))

    def test_invalid_role_non_string_types(self):
        """Test invalid non-string role types"""
        invalid_roles = [
            123,
            ['user'],
            {'role': 'user'},
            True,
        ]
        for role in invalid_roles:
            with self.assertRaises((ValueError, TypeError)):
                validate_role(role)


class TestValidateTaskId(unittest.TestCase):
    """Test cases for validate_task_id function"""

    def test_valid_task_id_alphanumeric(self):
        """Test valid alphanumeric task_id"""
        valid_ids = [
            'task123',
            'task_456',
            'Task789',
            'abc123def456',
            'task',
            'TASK',
            '123',
        ]
        for task_id in valid_ids:
            validate_task_id(task_id)

    def test_valid_task_id_with_special_chars(self):
        """Test valid task_id with allowed special characters"""
        valid_ids = [
            'task:123',
            'task.456',
            'task-789',
            'task_abc',
            'task:abc.def-ghi_jkl',
        ]
        for task_id in valid_ids:
            validate_task_id(task_id)

    def test_valid_task_id_uuid_format(self):
        """Test valid UUID format task_id"""
        valid_uuids = [
            '550e8400-e29b-41d4-a716-446655440000',
            '12345678-1234-1234-1234-123456789abc',
        ]
        for task_id in valid_uuids:
            validate_task_id(task_id)

    def test_invalid_task_id_empty_string(self):
        """Test invalid empty string task_id"""
        with self.assertRaises(ValueError) as context:
            validate_task_id('')
        self.assertIn('cannot be empty', str(context.exception))

    def test_invalid_task_id_whitespace_only(self):
        """Test invalid whitespace-only task_id - treated as invalid format"""
        invalid_ids = [
            '   ',
            '\t',
            '\n',
        ]
        for task_id in invalid_ids:
            with self.assertRaises(ValueError) as context:
                validate_task_id(task_id)
            # Whitespace-only strings fail format validation
            self.assertIn('Invalid task_id format', str(context.exception))

    def test_invalid_task_id_none(self):
        """Test invalid None task_id"""
        with self.assertRaises((ValueError, TypeError)):
            validate_task_id(None)

    def test_invalid_task_id_special_chars(self):
        """Test invalid task_id with disallowed special characters"""
        invalid_ids = [
            'task@domain',
            'task#hash',
            'task space',
            'task!exclamation',
            'task$money',
            'task<script>',
        ]
        for task_id in invalid_ids:
            with self.assertRaises(ValueError) as context:
                validate_task_id(task_id)
            self.assertIn('Invalid task_id format', str(context.exception))

    def test_invalid_task_id_unicode(self):
        """Test invalid task_id with unicode characters"""
        invalid_ids = [
            'task\u4e2d\u6587',
            'task\u3042\u3044',
            'task\U0001f600',
        ]
        for task_id in invalid_ids:
            with self.assertRaises(ValueError):
                validate_task_id(task_id)


class TestValidateMsgId(unittest.TestCase):
    """Test cases for validate_msg_id function"""

    def test_valid_msg_id_alphanumeric(self):
        """Test valid alphanumeric msg_id"""
        valid_ids = [
            'msg123',
            'msg_456',
            'Msg789',
            'abc123def456',
            'msg',
            'MSG',
            '123',
        ]
        for msg_id in valid_ids:
            validate_msg_id(msg_id)

    def test_valid_msg_id_with_underscores_hyphens(self):
        """Test valid msg_id with underscores and hyphens"""
        valid_ids = [
            'msg-123',
            'msg_456',
            'msg-abc_def',
            'msg_abc-def',
            'a-b_c',
        ]
        for msg_id in valid_ids:
            validate_msg_id(msg_id)

    def test_valid_msg_id_uuid_format(self):
        """Test valid UUID format msg_id"""
        valid_uuids = [
            '550e8400-e29b-41d4-a716-446655440000',
            '12345678-1234-1234-1234-123456789abc',
        ]
        for msg_id in valid_uuids:
            validate_msg_id(msg_id)

    def test_invalid_msg_id_empty_string(self):
        """Test invalid empty string msg_id"""
        with self.assertRaises(ValueError) as context:
            validate_msg_id('')
        self.assertIn('cannot be empty', str(context.exception))

    def test_invalid_msg_id_whitespace_only(self):
        """Test invalid whitespace-only msg_id - treated as invalid format"""
        invalid_ids = [
            '   ',
            '\t',
            '\n',
        ]
        for msg_id in invalid_ids:
            with self.assertRaises(ValueError) as context:
                validate_msg_id(msg_id)
            # Whitespace-only strings fail format validation
            self.assertIn('Invalid msg_id format', str(context.exception))

    def test_invalid_msg_id_none(self):
        """Test invalid None msg_id"""
        with self.assertRaises((ValueError, TypeError)):
            validate_msg_id(None)

    def test_invalid_msg_id_colons(self):
        """Test invalid msg_id with colons (not allowed for msg_id)"""
        invalid_ids = [
            'msg:123',
            'msg:abc',
            'a:b:c',
        ]
        for msg_id in invalid_ids:
            with self.assertRaises(ValueError) as context:
                validate_msg_id(msg_id)
            self.assertIn('Invalid msg_id format', str(context.exception))

    def test_invalid_msg_id_periods(self):
        """Test invalid msg_id with periods (not allowed for msg_id)"""
        invalid_ids = [
            'msg.123',
            'msg.abc',
            'a.b.c',
        ]
        for msg_id in invalid_ids:
            with self.assertRaises(ValueError) as context:
                validate_msg_id(msg_id)
            self.assertIn('Invalid msg_id format', str(context.exception))

    def test_invalid_msg_id_special_chars(self):
        """Test invalid msg_id with other disallowed special characters"""
        invalid_ids = [
            'msg@domain',
            'msg#hash',
            'msg space',
            'msg!exclamation',
            'msg$money',
            'msg<script>',
        ]
        for msg_id in invalid_ids:
            with self.assertRaises(ValueError) as context:
                validate_msg_id(msg_id)
            self.assertIn('Invalid msg_id format', str(context.exception))

    def test_invalid_msg_id_unicode(self):
        """Test invalid msg_id with unicode characters"""
        invalid_ids = [
            'msg\u4e2d\u6587',
            'msg\u3042\u3044',
            'msg\U0001f600',
        ]
        for msg_id in invalid_ids:
            with self.assertRaises(ValueError):
                validate_msg_id(msg_id)

    def test_boundary_msg_id_single_char(self):
        """Test boundary case: single character msg_id"""
        validate_msg_id('a')
        validate_msg_id('A')
        validate_msg_id('1')
        validate_msg_id('_')
        validate_msg_id('-')


class TestValidatorEdgeCases(unittest.TestCase):
    """Test edge cases and cross-validator scenarios"""

    def test_unicode_in_all_validators(self):
        """Test unicode handling across all validators"""
        unicode_strings = [
            '\u4e2d\u6587',
            '\u3042\u3044\u3046',
            '\u0430\u0431\u0432',
            '\U0001f600',
        ]
        for s in unicode_strings:
            # All should fail for session_id, task_id, msg_id
            with self.assertRaises(ValueError):
                validate_session_id(s)
            with self.assertRaises(ValueError):
                validate_task_id(s)
            with self.assertRaises(ValueError):
                validate_msg_id(s)
            # Should succeed for message_content
            validate_message_content(s)

    def test_type_coercion_attempts(self):
        """Test type coercion attempts"""
        # Integer-like strings should be valid for IDs
        validate_session_id('123')
        validate_task_id('456')
        validate_msg_id('789')

        # But actual integers should fail
        with self.assertRaises((ValueError, TypeError)):
            validate_session_id(123)
        with self.assertRaises((ValueError, TypeError)):
            validate_task_id(456)
        with self.assertRaises((ValueError, TypeError)):
            validate_msg_id(789)

    def test_error_message_format(self):
        """Test error message format consistency"""
        # Session ID error
        with self.assertRaises(ValueError) as context:
            validate_session_id('invalid@id')
        error_msg = str(context.exception)
        self.assertIn('Invalid session_id format', error_msg)
        self.assertIn('invalid@id', error_msg)

        # Task ID error
        with self.assertRaises(ValueError) as context:
            validate_task_id('invalid@id')
        error_msg = str(context.exception)
        self.assertIn('Invalid task_id format', error_msg)

        # Msg ID error
        with self.assertRaises(ValueError) as context:
            validate_msg_id('invalid@id')
        error_msg = str(context.exception)
        self.assertIn('Invalid msg_id format', error_msg)

        # Role error
        with self.assertRaises(ValueError) as context:
            validate_role('invalid_role')
        error_msg = str(context.exception)
        self.assertIn('Invalid role', error_msg)
        self.assertIn('invalid_role', error_msg)

    def test_boundary_lengths(self):
        """Test boundary length conditions"""
        # Very short (1 char) - valid for IDs
        validate_session_id('a')
        validate_task_id('b')
        validate_msg_id('c')

        # Medium length - valid
        validate_session_id('abc123def456')
        validate_task_id('task_123_456')
        validate_msg_id('msg-123-456')

        # Long but valid (100 chars)
        long_id = 'a' * 100
        validate_session_id(long_id)
        validate_task_id(long_id)
        validate_msg_id(long_id)

    def test_similar_looking_characters(self):
        """Test similar-looking characters (security consideration)"""
        # Zero vs letter O
        validate_session_id('session0')  # Zero
        validate_session_id('sessionO')  # Letter O

        # One vs lowercase L vs uppercase I
        validate_session_id('session1')  # One
        validate_session_id('sessionl')  # Lowercase L
        validate_session_id('sessionI')  # Uppercase I

        # Underscore vs hyphen
        validate_session_id('session_test')
        validate_session_id('session-test')


if __name__ == '__main__':
    unittest.main()
