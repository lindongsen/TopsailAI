"""
Unit tests for API validation functions.

This module contains comprehensive unit tests for the validation functions
in topsailai_server.agent_daemon.validator module.

Test Coverage:
    - Session ID validation
    - Message content validation
    - Role validation
    - Task ID validation
    - Message ID validation

Author: mm-m25
"""

import pytest
from topsailai_server.agent_daemon.validator import (
    validate_session_id,
    validate_message_content,
    validate_role,
    validate_task_id,
    validate_msg_id,
)


class TestValidateSessionId:
    """Tests for validate_session_id function."""

    def test_valid_uuid_format(self):
        """Test valid UUID format session IDs."""
        valid_uuids = [
            "550e8400-e29b-41d4-a716-446655440000",
            "123e4567-e89b-12d3-a456-426614174000",
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        ]
        for uuid_str in valid_uuids:
            # Should not raise any exception
            validate_session_id(uuid_str)

    def test_valid_alphanumeric_format(self):
        """Test valid alphanumeric session IDs."""
        valid_ids = [
            "session123",
            "my_session",
            "test-session",
            "session:001",
            "session.name",
            "a",
            "A1B2C3",
            "test_123-hello",
        ]
        for session_id in valid_ids:
            # Should not raise any exception
            validate_session_id(session_id)

    def test_empty_session_id(self):
        """Test that empty session_id raises ValueError."""
        with pytest.raises(ValueError, match="session_id cannot be empty"):
            validate_session_id("")

    def test_none_session_id(self):
        """Test that None session_id raises ValueError."""
        with pytest.raises(ValueError, match="session_id cannot be empty"):
            validate_session_id(None)

    def test_invalid_characters(self):
        """Test that session IDs with invalid characters raise ValueError."""
        invalid_ids = [
            "session@123",      # @ is not allowed
            "session#123",      # # is not allowed
            "session$123",      # $ is not allowed
            "session!123",      # ! is not allowed
            "session 123",      # space is not allowed
            "session\t123",     # tab is not allowed
            "session\n123",     # newline is not allowed
        ]
        for session_id in invalid_ids:
            with pytest.raises(ValueError):
                validate_session_id(session_id)

    def test_invalid_format_error_message(self):
        """Test that error message contains helpful information."""
        with pytest.raises(ValueError, match="Invalid session_id format"):
            validate_session_id("invalid@session")


class TestValidateMessageContent:
    """Tests for validate_message_content function."""

    def test_valid_message_content(self):
        """Test valid message content strings."""
        valid_contents = [
            "Hello, world!",
            "This is a test message.",
            "Message with numbers 12345",
            "Multi-line\nmessage\ncontent",
            "   Message with leading/trailing spaces   ",
            "Short",
            "a" * 1000,  # Long message
        ]
        for content in valid_contents:
            # Should not raise any exception
            validate_message_content(content)

    def test_empty_message_content(self):
        """Test that empty message content raises ValueError."""
        with pytest.raises(ValueError, match="message content cannot be empty"):
            validate_message_content("")

    def test_none_message_content(self):
        """Test that None message content raises ValueError."""
        with pytest.raises(ValueError, match="message content cannot be empty"):
            validate_message_content(None)

    def test_whitespace_only_content(self):
        """Test that whitespace-only content raises ValueError."""
        whitespace_contents = [
            "   ",
            "\t",
            "\n",
            "\t\n  \t",
        ]
        for content in whitespace_contents:
            with pytest.raises(ValueError, match="message content cannot be only whitespace"):
                validate_message_content(content)

    def test_non_string_content(self):
        """Test that non-string content raises ValueError.
        
        Note: The function checks 'if not content' first, so falsy non-string
        values like [], {}, None raise 'message content cannot be empty'.
        Non-falsy non-strings like 123, 45.67 raise 'message must be a string'.
        """
        # Falsy non-string values raise 'cannot be empty'
        falsy_values = [[], {}]
        for content in falsy_values:
            with pytest.raises(ValueError, match="message content"):
                validate_message_content(content)
        
        # Non-falsy non-string values raise 'must be a string'
        non_string_values = [123, 45.67]
        for content in non_string_values:
            with pytest.raises(ValueError, match="message must be a string"):
                validate_message_content(content)


class TestValidateRole:
    """Tests for validate_role function."""

    def test_valid_user_role(self):
        """Test valid 'user' role."""
        # Should not raise any exception
        validate_role("user")

    def test_valid_assistant_role(self):
        """Test valid 'assistant' role."""
        # Should not raise any exception
        validate_role("assistant")

    def test_invalid_role(self):
        """Test that invalid roles raise ValueError."""
        invalid_roles = [
            "admin",
            "system",
            "guest",
            "moderator",
            "USER",      # case sensitive
            "Assistant", # case sensitive
            "",
            "user ",     # trailing space
            " user",     # leading space
        ]
        for role in invalid_roles:
            with pytest.raises(ValueError, match="Invalid role"):
                validate_role(role)

    def test_error_message_contains_valid_roles(self):
        """Test that error message lists valid roles."""
        with pytest.raises(ValueError, match="user.*assistant"):
            validate_role("invalid_role")


class TestValidateTaskId:
    """Tests for validate_task_id function."""

    def test_valid_uuid_format(self):
        """Test valid UUID format task IDs."""
        valid_uuids = [
            "550e8400-e29b-41d4-a716-446655440000",
            "123e4567-e89b-12d3-a456-426614174000",
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        ]
        for uuid_str in valid_uuids:
            # Should not raise any exception
            validate_task_id(uuid_str)

    def test_valid_alphanumeric_format(self):
        """Test valid alphanumeric task IDs."""
        valid_ids = [
            "task123",
            "my_task",
            "test-task",
            "task:001",
            "task.name",
            "a",
            "A1B2C3",
            "task_123-hello",
        ]
        for task_id in valid_ids:
            # Should not raise any exception
            validate_task_id(task_id)

    def test_empty_task_id(self):
        """Test that empty task_id raises ValueError."""
        with pytest.raises(ValueError, match="task_id cannot be empty"):
            validate_task_id("")

    def test_none_task_id(self):
        """Test that None task_id raises ValueError."""
        with pytest.raises(ValueError, match="task_id cannot be empty"):
            validate_task_id(None)

    def test_invalid_characters(self):
        """Test that task IDs with invalid characters raise ValueError."""
        invalid_ids = [
            "task@123",
            "task#123",
            "task$123",
            "task!123",
            "task 123",
            "task\t123",
            "task\n123",
        ]
        for task_id in invalid_ids:
            with pytest.raises(ValueError):
                validate_task_id(task_id)

    def test_invalid_format_error_message(self):
        """Test that error message contains helpful information."""
        with pytest.raises(ValueError, match="Invalid task_id format"):
            validate_task_id("invalid@task")


class TestValidateMsgId:
    """Tests for validate_msg_id function."""

    def test_valid_uuid_format(self):
        """Test valid UUID format message IDs."""
        valid_uuids = [
            "550e8400-e29b-41d4-a716-446655440000",
            "123e4567-e89b-12d3-a456-426614174000",
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        ]
        for uuid_str in valid_uuids:
            # Should not raise any exception
            validate_msg_id(uuid_str)

    def test_valid_alphanumeric_format(self):
        """Test valid alphanumeric message IDs."""
        valid_ids = [
            "msg123",
            "my_msg",
            "test-msg",
            "msg_001",
            "a",
            "A1B2C3",
            "msg_123-hello",
        ]
        for msg_id in valid_ids:
            # Should not raise any exception
            validate_msg_id(msg_id)

    def test_empty_msg_id(self):
        """Test that empty msg_id raises ValueError."""
        with pytest.raises(ValueError, match="msg_id cannot be empty"):
            validate_msg_id("")

    def test_none_msg_id(self):
        """Test that None msg_id raises ValueError."""
        with pytest.raises(ValueError, match="msg_id cannot be empty"):
            validate_msg_id(None)

    def test_invalid_characters(self):
        """Test that message IDs with invalid characters raise ValueError."""
        invalid_ids = [
            "msg@123",
            "msg#123",
            "msg:123",     # colon is not allowed for msg_id
            "msg.123",     # period is not allowed for msg_id
            "msg 123",
            "msg\t123",
            "msg\n123",
        ]
        for msg_id in invalid_ids:
            with pytest.raises(ValueError):
                validate_msg_id(msg_id)

    def test_invalid_format_error_message(self):
        """Test that error message contains helpful information."""
        with pytest.raises(ValueError, match="Invalid msg_id format"):
            validate_msg_id("invalid@msg")


class TestValidationEdgeCases:
    """Tests for edge cases across all validation functions."""

    def test_very_long_session_id(self):
        """Test very long but valid session ID."""
        long_id = "a" * 500
        # Should not raise any exception
        validate_session_id(long_id)

    def test_unicode_characters_in_session_id(self):
        """Test that unicode characters raise ValueError."""
        with pytest.raises(ValueError):
            validate_session_id("session_你好")

    def test_emoji_in_session_id(self):
        """Test that emoji characters raise ValueError."""
        with pytest.raises(ValueError):
            validate_session_id("session_😀")

    def test_newline_in_message_content(self):
        """Test that newlines are allowed in message content."""
        # Should not raise any exception
        validate_message_content("Line 1\nLine 2\nLine 3")

    def test_tab_in_message_content(self):
        """Test that tabs are allowed in message content."""
        # Should not raise any exception
        validate_message_content("Column1\tColumn2")

    def test_special_unicode_in_message_content(self):
        """Test that special unicode is allowed in message content."""
        valid_contents = [
            "Hello 你好",
            "Greetings 👋",
            "Message with émoji",
        ]
        for content in valid_contents:
            # Should not raise any exception
            validate_message_content(content)


class TestValidationIntegration:
    """Integration tests for validation functions working together."""

    def test_multiple_valid_ids(self):
        """Test validating multiple IDs in sequence."""
        ids = [
            ("session", "550e8400-e29b-41d4-a716-446655440000"),
            ("task", "task_123-hello"),
            ("msg", "msg_001"),
        ]
        for id_type, id_value in ids:
            if id_type == "session":
                validate_session_id(id_value)
            elif id_type == "task":
                validate_task_id(id_value)
            elif id_type == "msg":
                validate_msg_id(id_value)

    def test_validation_chain(self):
        """Test a chain of validations."""
        # All should pass without raising
        validate_session_id("test_session")
        validate_message_content("Test message content")
        validate_role("user")
        validate_task_id("test_task")
        validate_msg_id("test_msg")
