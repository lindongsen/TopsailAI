'''
  Author: mm-m25
  Created: 2026-04-15
  Purpose: Unit tests for processor_helper module - format_pending_messages
'''

import unittest
from datetime import datetime

from topsailai_server.agent_daemon.api.processor_helper import format_pending_messages
from topsailai_server.agent_daemon.storage import MessageData


class TestFormatPendingMessages(unittest.TestCase):
    """Test cases for format_pending_messages function"""

    def test_single_user_message(self):
        """Single user message should be formatted with --- separators"""
        now = datetime.now()
        messages = [
            MessageData(
                msg_id="msg1",
                session_id="session1",
                message="Hello",
                role="user",
                create_time=now,
                update_time=now
            )
        ]

        result = format_pending_messages(messages)

        self.assertEqual(result, "---\nHello\n---")

    def test_multiple_user_messages(self):
        """Multiple user messages separated by ---"""
        now = datetime.now()
        messages = [
            MessageData(
                msg_id="msg1",
                session_id="session1",
                message="Hello",
                role="user",
                create_time=now,
                update_time=now
            ),
            MessageData(
                msg_id="msg2",
                session_id="session1",
                message="World",
                role="user",
                create_time=now,
                update_time=now
            )
        ]

        result = format_pending_messages(messages)

        self.assertEqual(result, "---\nHello\n---\nWorld\n---")

    def test_assistant_message_without_task_id_excluded(self):
        """Assistant messages without task_id should be excluded"""
        now = datetime.now()
        messages = [
            MessageData(
                msg_id="msg1",
                session_id="session1",
                message="I am assistant",
                role="assistant",
                create_time=now,
                update_time=now
            )
        ]

        result = format_pending_messages(messages)

        self.assertEqual(result, "")

    def test_assistant_message_with_task_id_included(self):
        """Assistant messages WITH task_id should be included"""
        now = datetime.now()
        messages = [
            MessageData(
                msg_id="msg1",
                session_id="session1",
                message="I am assistant",
                role="assistant",
                task_id="task-001",
                create_time=now,
                update_time=now
            )
        ]

        result = format_pending_messages(messages)

        self.assertIn("I am assistant", result)
        self.assertIn(">>> task_id: task-001", result)

    def test_task_id_and_task_result_included(self):
        """When task_id and task_result exist, they should be in the format"""
        now = datetime.now()
        messages = [
            MessageData(
                msg_id="msg1",
                session_id="session1",
                message="Do something",
                role="user",
                task_id="task-123",
                task_result="Done successfully",
                create_time=now,
                update_time=now
            )
        ]

        result = format_pending_messages(messages)

        self.assertEqual(result, "---\nDo something\n>>> task_id: task-123\n>>> task_result: Done successfully\n---")

    def test_task_id_only_included(self):
        """Only task_id exists (no task_result)"""
        now = datetime.now()
        messages = [
            MessageData(
                msg_id="msg1",
                session_id="session1",
                message="Do something",
                role="user",
                task_id="task-456",
                create_time=now,
                update_time=now
            )
        ]

        result = format_pending_messages(messages)

        self.assertEqual(result, "---\nDo something\n>>> task_id: task-456\n---")
        self.assertNotIn("task_result", result)

    def test_mixed_messages(self):
        """Mix of user and assistant messages, some with task_id"""
        now = datetime.now()
        messages = [
            MessageData(
                msg_id="msg1",
                session_id="session1",
                message="User question",
                role="user",
                create_time=now,
                update_time=now
            ),
            MessageData(
                msg_id="msg2",
                session_id="session1",
                message="Assistant reply without task",
                role="assistant",
                create_time=now,
                update_time=now
            ),
            MessageData(
                msg_id="msg3",
                session_id="session1",
                message="Another user message",
                role="user",
                create_time=now,
                update_time=now
            ),
            MessageData(
                msg_id="msg4",
                session_id="session1",
                message="Assistant reply with task",
                role="assistant",
                task_id="task-789",
                task_result="Task completed",
                create_time=now,
                update_time=now
            )
        ]

        result = format_pending_messages(messages)

        # msg2 (assistant without task_id) should be excluded
        self.assertIn("User question", result)
        self.assertNotIn("Assistant reply without task", result)
        self.assertIn("Another user message", result)
        self.assertIn("Assistant reply with task", result)
        self.assertIn(">>> task_id: task-789", result)
        self.assertIn(">>> task_result: Task completed", result)

    def test_empty_message_list(self):
        """Empty list returns empty string"""
        result = format_pending_messages([])

        self.assertEqual(result, "")

    def test_all_assistant_without_task_id(self):
        """All assistant messages without task_id returns empty string"""
        now = datetime.now()
        messages = [
            MessageData(
                msg_id="msg1",
                session_id="session1",
                message="Reply 1",
                role="assistant",
                create_time=now,
                update_time=now
            ),
            MessageData(
                msg_id="msg2",
                session_id="session1",
                message="Reply 2",
                role="assistant",
                create_time=now,
                update_time=now
            )
        ]

        result = format_pending_messages(messages)

        self.assertEqual(result, "")

    def test_format_matches_spec(self):
        """Verify the exact format matches the spec example:
        ---
        msg4内容
        ---
        msg5内容
        >>> task_id: msg5的task_id
        >>> task_result: msg5的task_result
        ---
        """
        now = datetime.now()
        messages = [
            MessageData(
                msg_id="msg4",
                session_id="session1",
                message="msg4内容",
                role="user",
                create_time=now,
                update_time=now
            ),
            MessageData(
                msg_id="msg5",
                session_id="session1",
                message="msg5内容",
                role="user",
                task_id="msg5的task_id",
                task_result="msg5的task_result",
                create_time=now,
                update_time=now
            )
        ]

        result = format_pending_messages(messages)

        expected = "---\nmsg4内容\n---\nmsg5内容\n>>> task_id: msg5的task_id\n>>> task_result: msg5的task_result\n---"
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
