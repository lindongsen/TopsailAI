"""
Unit tests for workspace/print_tool module.

Test coverage:
- TeeOutput class (file + stdout dual output)
- ContentDots class (ContentSender implementation)
- print_context_messages function
- print_raw_messages function

Author: AI
"""

import sys
import os
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock, mock_open
from io import StringIO

# Import the module under test
from topsailai.workspace.print_tool import (
    TeeOutput,
    ContentDots,
    print_context_messages,
    print_raw_messages,
    decorator_tee_output,
    decorator_tee_output_by_session,
)


class TestTeeOutput(unittest.TestCase):
    """Test cases for TeeOutput class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_file = "/tmp/test_tee_output.txt"
        # Clean up any existing test file
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def tearDown(self):
        """Clean up test fixtures."""
        # Restore stdout if it was modified
        if isinstance(sys.stdout, type(sys.__stdout__)):
            pass  # Already restored
        else:
            sys.stdout = sys.__stdout__
        # Clean up test file
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_tee_output_context_manager_basic(self):
        """Test TeeOutput context manager basic usage."""
        with TeeOutput(self.test_file, mode='w') as tee:
            print("Hello, World!")

        # Verify file content
        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, "Hello, World!\n")

    def test_tee_output_context_manager_multiple_writes(self):
        """Test TeeOutput with multiple write operations."""
        with TeeOutput(self.test_file, mode='w') as tee:
            print("Line 1")
            print("Line 2")
            print("Line 3")

        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("Line 1", content)
        self.assertIn("Line 2", content)
        self.assertIn("Line 3", content)

    def test_tee_output_context_manager_append_mode(self):
        """Test TeeOutput append mode."""
        # First write
        with TeeOutput(self.test_file, mode='w') as tee:
            print("First")

        # Append
        with TeeOutput(self.test_file, mode='a') as tee:
            print("Second")

        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("First", content)
        self.assertIn("Second", content)

    def test_tee_output_restores_stdout(self):
        """Test that stdout is restored after context manager exits."""
        original_stdout = sys.stdout

        with TeeOutput(self.test_file, mode='w') as tee:
            self.assertIsNot(sys.stdout, original_stdout)

        # After exiting, stdout should be restored
        self.assertEqual(sys.stdout, original_stdout)

    def test_tee_output_manual_mode(self):
        """Test TeeOutput manual mode without context manager."""
        tee = TeeOutput(self.test_file, mode='w')
        sys.stdout = tee

        print("Manual write")

        sys.stdout = tee.terminal
        tee.close()

        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("Manual write", content)

    def test_tee_output_flush(self):
        """Test TeeOutput flush method."""
        tee = TeeOutput(self.test_file, mode='w')
        tee.write("Test")
        tee.flush()
        # Should not raise any exception
        tee.close()

    def test_tee_output_close(self):
        """Test TeeOutput close method."""
        tee = TeeOutput(self.test_file, mode='w')
        tee.write("Test")
        tee.close()
        # File should be closed, but we can still read content
        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("Test", content)

    def test_tee_output_filename_property(self):
        """Test TeeOutput filename property."""
        tee = TeeOutput(self.test_file, mode='w')
        self.assertEqual(tee.filename, self.test_file)
        tee.close()

    def test_tee_output_logrotate_max_file_bytes(self):
        """Test TeeOutput logrotate functionality."""
        # Create a test file larger than the limit
        with open(self.test_file, 'w') as f:
            f.write('x' * (100 * 1024 * 1024 + 1))  # 100MB + 1 byte

        # Create TeeOutput with smaller limit
        tee = TeeOutput(self.test_file, mode='a', logrotate_max_file_bytes=50 * 1024 * 1024)  # 50MB limit
        tee.close()

        # Check if file was rotated
        rotated_file = f"{self.test_file}.1"
        self.assertTrue(os.path.exists(rotated_file))
        self.assertTrue(os.path.exists(self.test_file))

        # Clean up
        if os.path.exists(rotated_file):
            os.remove(rotated_file)

    def test_tee_output_logrotate_no_rotation_needed(self):
        """Test TeeOutput logrotate when file is under limit."""
        # Create a small test file
        with open(self.test_file, 'w') as f:
            f.write('small content')

        # Create TeeOutput with larger limit
        tee = TeeOutput(self.test_file, mode='a', logrotate_max_file_bytes=100 * 1024 * 1024)  # 100MB limit
        tee.close()

        # Check that no rotation occurred
        rotated_file = f"{self.test_file}.1"
        self.assertFalse(os.path.exists(rotated_file))
        self.assertTrue(os.path.exists(self.test_file))

    def test_tee_output_logrotate_nonexistent_file(self):
        """Test TeeOutput logrotate when file doesn't exist."""
        # Ensure file doesn't exist
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

        # Create TeeOutput
        tee = TeeOutput(self.test_file, mode='w', logrotate_max_file_bytes=100 * 1024 * 1024)
        tee.close()

        # Should not raise exception
        self.assertTrue(os.path.exists(self.test_file))

    def test_tee_output_exit_method(self):
        """Test TeeOutput __exit__ method behavior."""
        original_stdout = sys.stdout

        with TeeOutput(self.test_file, mode='w') as tee:
            # Inside context, stdout should be the tee
            self.assertIs(sys.stdout, tee)
            print("Inside context")

        # After exiting, stdout should be restored
        self.assertEqual(sys.stdout, original_stdout)

        # File should be closed and contain content
        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("Inside context", content)


class TestContentDots(unittest.TestCase):
    """Test cases for ContentDots class."""

    def setUp(self):
        """Set up test fixtures."""
        self.captured_output = StringIO()
        sys.stdout = self.captured_output

    def tearDown(self):
        """Restore stdout."""
        sys.stdout = sys.__stdout__

    def test_content_dots_send_returns_true(self):
        """Test ContentDots send method returns True."""
        dots = ContentDots()
        result = dots.send("any content")
        self.assertTrue(result)

    def test_content_dots_send_writes_dot(self):
        """Test ContentDots send method writes a dot."""
        dots = ContentDots()
        self.captured_output.truncate(0)
        self.captured_output.seek(0)

        dots.send("test content")

        output = self.captured_output.getvalue()
        self.assertEqual(output, ".")

    def test_content_dots_send_multiple(self):
        """Test ContentDots with multiple send calls."""
        dots = ContentDots()
        self.captured_output.truncate(0)
        self.captured_output.seek(0)

        dots.send("first")
        dots.send("second")
        dots.send("third")

        output = self.captured_output.getvalue()
        self.assertEqual(output, "...")

    def test_content_dots_send_ignores_content(self):
        """Test ContentDots ignores the content parameter."""
        dots = ContentDots()
        self.captured_output.truncate(0)
        self.captured_output.seek(0)

        dots.send(None)
        dots.send("")
        dots.send(123)

        output = self.captured_output.getvalue()
        self.assertEqual(output, "...")


class TestPrintContextMessages(unittest.TestCase):
    """Test cases for print_context_messages function."""

    def setUp(self):
        """Set up test fixtures."""
        self.captured_output = StringIO()

    def tearDown(self):
        """Restore stdout."""
        sys.stdout = sys.__stdout__

    def test_print_context_messages_basic(self):
        """Test print_context_messages with basic messages."""
        sys.stdout = self.captured_output

        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there'}
        ]

        print_context_messages(messages)

        output = self.captured_output.getvalue()
        self.assertIn("USER", output)
        self.assertIn("ASSISTANT", output)
        self.assertIn("Hello", output)
        self.assertIn("Hi there", output)

    def test_print_context_messages_empty_list(self):
        """Test print_context_messages with empty list."""
        sys.stdout = self.captured_output

        print_context_messages([])

        output = self.captured_output.getvalue()
        # Should not raise exception, output may be empty or contain separators

    def test_print_context_messages_missing_fields(self):
        """Test print_context_messages with missing role/content fields."""
        sys.stdout = self.captured_output

        messages = [
            {'content': 'Only content'},
            {'role': 'user'},  # Missing content
            {},  # Missing both
        ]

        # Should not raise exception
        print_context_messages(messages)

        output = self.captured_output.getvalue()
        self.assertIn("UNKNOWN", output)

    def test_print_context_messages_multiline_content(self):
        """Test print_context_messages with multiline content."""
        sys.stdout = self.captured_output

        messages = [
            {'role': 'user', 'content': 'Line 1\nLine 2\nLine 3'}
        ]

        print_context_messages(messages)

        output = self.captured_output.getvalue()
        self.assertIn("Line 1", output)
        self.assertIn("Line 2", output)
        self.assertIn("Line 3", output)

    def test_print_context_messages_with_step_format(self):
        """Test print_context_messages with step_name/raw_text format."""
        sys.stdout = self.captured_output

        messages = [
            {'role': 'user', 'content': 'step_name=thought\nraw_text=I am thinking'}
        ]

        print_context_messages(messages)

        output = self.captured_output.getvalue()
        # Should handle the format gracefully


class TestPrintRawMessages(unittest.TestCase):
    """Test cases for print_raw_messages function."""

    def setUp(self):
        """Set up test fixtures."""
        self.captured_output = StringIO()

    def tearDown(self):
        """Restore stdout."""
        sys.stdout = sys.__stdout__

    def test_print_raw_messages_basic(self):
        """Test print_raw_messages with basic messages."""
        sys.stdout = self.captured_output

        # Create mock message objects
        msg1 = MagicMock()
        msg1.msg_id = "msg-001"
        msg1.message = '{"role": "user", "content": "Hello"}'

        msg2 = MagicMock()
        msg2.msg_id = "msg-002"
        msg2.message = '{"role": "assistant", "content": "Hi"}'

        print_raw_messages([msg1, msg2])

        output = self.captured_output.getvalue()
        self.assertIn("USER", output)
        self.assertIn("ASSISTANT", output)
        self.assertIn("msg-001", output)
        self.assertIn("msg-002", output)

    def test_print_raw_messages_empty_list(self):
        """Test print_raw_messages with empty list."""
        sys.stdout = self.captured_output

        print_raw_messages([])

        # Should not raise exception

    def test_print_raw_messages_invalid_json(self):
        """Test print_raw_messages with invalid JSON content."""
        sys.stdout = self.captured_output

        msg = MagicMock()
        msg.msg_id = "msg-001"
        msg.message = "not valid json"

        # Should not raise exception
        print_raw_messages([msg])

        output = self.captured_output.getvalue()
        self.assertIn("msg-001", output)
        self.assertIn("UNKNOWN", output)

    def test_print_raw_messages_missing_role(self):
        """Test print_raw_messages when role is missing from JSON."""
        sys.stdout = self.captured_output

        msg = MagicMock()
        msg.msg_id = "msg-001"
        msg.message = '{"content": "Hello"}'

        print_raw_messages([msg])

        output = self.captured_output.getvalue()
        self.assertIn("UNKNOWN", output)

    def test_print_raw_messages_multiline_content(self):
        """Test print_raw_messages with multiline content."""
        sys.stdout = self.captured_output

        msg = MagicMock()
        msg.msg_id = "msg-001"
        msg.message = '{"role": "user", "content": "Line 1\\nLine 2"}'

        print_raw_messages([msg])

        output = self.captured_output.getvalue()
        self.assertIn("Line 1", output)
        self.assertIn("Line 2", output)


class TestDecoratorTeeOutput(unittest.TestCase):
    """Test cases for decorator_tee_output function."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_file = "/tmp/test_decorator_tee_output.txt"
        # Clean up any existing test file
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_decorator_tee_output_basic(self):
        """Test decorator_tee_output basic functionality."""
        @decorator_tee_output(self.test_file, mode='w')
        def my_function():
            print("Hello from decorated function")
            return "result"

        result = my_function()

        # Verify function returns correct result
        self.assertEqual(result, "result")

        # Verify file contains the printed output
        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("Hello from decorated function", content)

    def test_decorator_tee_output_multiple_prints(self):
        """Test decorator_tee_output with multiple print statements."""
        @decorator_tee_output(self.test_file, mode='w')
        def my_function():
            print("Line 1")
            print("Line 2")
            print("Line 3")

        my_function()

        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("Line 1", content)
        self.assertIn("Line 2", content)
        self.assertIn("Line 3", content)

    def test_decorator_tee_output_with_arguments(self):
        """Test decorator_tee_output with function arguments."""
        @decorator_tee_output(self.test_file, mode='w')
        def add_numbers(a, b):
            print(f"Adding {a} and {b}")
            return a + b

        result = add_numbers(3, 4)

        self.assertEqual(result, 7)

        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("Adding 3 and 4", content)

    def test_decorator_tee_output_with_kwargs(self):
        """Test decorator_tee_output with keyword arguments."""
        @decorator_tee_output(self.test_file, mode='w')
        def greet(name, greeting="Hello"):
            print(f"{greeting}, {name}!")
            return f"{greeting}, {name}!"

        result = greet("World", greeting="Hi")

        self.assertEqual(result, "Hi, World!")

        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("Hi, World!", content)

    def test_decorator_tee_output_append_mode(self):
        """Test decorator_tee_output append mode."""
        @decorator_tee_output(self.test_file, mode='w')
        def first_function():
            print("First")

        @decorator_tee_output(self.test_file, mode='a')
        def second_function():
            print("Second")

        first_function()
        second_function()

        with open(self.test_file, 'r') as f:
            content = f.read()
        self.assertIn("First", content)
        self.assertIn("Second", content)

    def test_decorator_tee_output_stdout_restored(self):
        """Test that stdout is restored after decorated function completes."""
        original_stdout = sys.stdout

        @decorator_tee_output(self.test_file, mode='w')
        def my_function():
            print("Inside")

        my_function()

        # stdout should be restored
        self.assertEqual(sys.stdout, original_stdout)


class TestDecoratorTeeOutputBySession(unittest.TestCase):
    """Test cases for decorator_tee_output_by_session function."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_file = "/tmp/test_decorator_tee_output_by_session.txt"
        # Clean up any existing test file
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    @patch('topsailai.workspace.print_tool.FOLDER_WORKSPACE_TASK', '/tmp')
    def test_decorator_tee_output_by_session_without_session_id(self):
        """Test decorator_tee_output_by_session without session ID."""
        # Ensure no session ID is set
        with patch.dict(os.environ, {'TOPSAILAI_ENABLE_SESSION_TEE_OUT': '1'}, clear=True):
            @decorator_tee_output_by_session(mode='w')
            def my_function():
                print("Hello from session function")
                return "result"

            result = my_function()

            # Verify function returns correct result
            self.assertEqual(result, "result")

            # Verify file contains the printed output with default filename
            expected_file = os.path.join('/tmp', 'session.stdout')
            with open(expected_file, 'r') as f:
                content = f.read()
            self.assertIn("Hello from session function", content)

            # Clean up
            if os.path.exists(expected_file):
                os.remove(expected_file)

    @patch('topsailai.workspace.print_tool.FOLDER_WORKSPACE_TASK', '/tmp')
    def test_decorator_tee_output_by_session_with_session_id(self):
        """Test decorator_tee_output_by_session with session ID."""
        session_id = "test-session-123"

        with patch.dict(os.environ, {'TOPSAILAI_SESSION_ID': session_id, 'TOPSAILAI_ENABLE_SESSION_TEE_OUT': '1'}):
            @decorator_tee_output_by_session(mode='w')
            def my_function():
                print("Hello from session function")
                return "result"

            result = my_function()

            # Verify function returns correct result
            self.assertEqual(result, "result")

            # Verify file contains the printed output with session ID in filename
            expected_file = os.path.join('/tmp', f'{session_id}.session.stdout')
            with open(expected_file, 'r') as f:
                content = f.read()
            self.assertIn("Hello from session function", content)

            # Clean up
            if os.path.exists(expected_file):
                os.remove(expected_file)

    @patch('topsailai.workspace.print_tool.FOLDER_WORKSPACE_TASK', '/tmp')
    def test_decorator_tee_output_by_session_multiple_prints(self):
        """Test decorator_tee_output_by_session with multiple print statements."""
        with patch.dict(os.environ, {'TOPSAILAI_SESSION_ID': 'test-123', 'TOPSAILAI_ENABLE_SESSION_TEE_OUT': '1'}):
            @decorator_tee_output_by_session(mode='w')
            def my_function():
                print("Line 1")
                print("Line 2")
                print("Line 3")

            my_function()

            expected_file = os.path.join('/tmp', 'test-123.session.stdout')
            with open(expected_file, 'r') as f:
                content = f.read()
            self.assertIn("Line 1", content)
            self.assertIn("Line 2", content)
            self.assertIn("Line 3", content)

            # Clean up
            if os.path.exists(expected_file):
                os.remove(expected_file)

    @patch('topsailai.workspace.print_tool.FOLDER_WORKSPACE_TASK', '/tmp')
    def test_decorator_tee_output_by_session_stdout_restored(self):
        """Test that stdout is restored after decorated function completes."""
        original_stdout = sys.stdout

        with patch.dict(os.environ, {'TOPSAILAI_SESSION_ID': 'test-456'}):
            @decorator_tee_output_by_session(mode='w')
            def my_function():
                print("Inside")

            my_function()

            # stdout should be restored
            self.assertEqual(sys.stdout, original_stdout)

            # Clean up
            expected_file = os.path.join('/tmp', 'test-456.session.stdout')
            if os.path.exists(expected_file):
                os.remove(expected_file)


if __name__ == '__main__':
    unittest.main()
