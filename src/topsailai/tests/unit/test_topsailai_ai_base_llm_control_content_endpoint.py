"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-07
Purpose: Unit tests for ai_base/llm_control/content_endpoint.py
"""

import pytest

from topsailai.ai_base.llm_control.content_endpoint import (
    ContentSender,
    ContentStdout,
)


class TestContentSender:
    """Tests for ContentSender base class."""

    def test_finish_returns_true(self):
        """finish() should return True by default."""
        sender = ContentSender()
        assert sender.finish() is True

    def test_send_not_implemented(self):
        """send() on the base class must raise NotImplementedError."""
        sender = ContentSender()
        with pytest.raises(NotImplementedError):
            sender.send("any content")

    def test_custom_subclass_override(self):
        """A custom subclass can override send() and finish() as expected."""
        class CustomSender(ContentSender):
            def __init__(self):
                self.sent = []
                self.finished = False

            def send(self, content):
                self.sent.append(content)

            def finish(self):
                self.finished = True
                return "done"

        sender = CustomSender()
        sender.send("hello")
        sender.send("world")
        result = sender.finish()

        assert sender.sent == ["hello", "world"]
        assert sender.finished is True
        assert result == "done"


class TestContentStdout:
    """Tests for ContentStdout implementation."""

    def test_send_writes_to_stdout(self, capsys):
        """send() should write the provided string to stdout."""
        sender = ContentStdout()
        sender.send("hello world")

        captured = capsys.readouterr()
        assert captured.out == "hello world"
        assert captured.err == ""

    def test_send_unicode(self, capsys):
        """send() should handle unicode content correctly."""
        sender = ContentStdout()
        content = "你好世界 🌍 café"
        sender.send(content)

        captured = capsys.readouterr()
        assert captured.out == content

    def test_send_empty_string(self, capsys):
        """send() should handle an empty string without error."""
        sender = ContentStdout()
        sender.send("")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_finish_returns_true(self):
        """finish() should inherit the base behavior and return True."""
        sender = ContentStdout()
        assert sender.finish() is True
