"""
Unit tests for AgentChat control server singleton integration.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-05
Purpose: Verify that multiple AgentChat instances in the same process and
session share a single ControlServer and manage its lifecycle safely.
"""

import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from topsailai.workspace.agent.agent_shell_base import AgentChat
from topsailai.workspace.control_channel.server import _control_servers
from topsailai.workspace.control_channel.transport import is_socket_live


def _make_agent_chat(session_id: str, socket_path: str):
    """Build a minimal AgentChat instance for lifecycle testing."""
    chat = AgentChat.__new__(AgentChat)
    chat.control_server = None
    chat.ctx_rt_aiagent = SimpleNamespace(
        ctx_runtime_data=SimpleNamespace(session_id=session_id)
    )
    return chat

@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure the process-level singleton registry is empty after each test."""
    yield
    # Copy keys to avoid mutating the dict while iterating.
    for key, entry in list(_control_servers.items()):
        try:
            entry.server.stop()
        except Exception:
            pass
        _control_servers.pop(key, None)


class TestAgentChatControlServerSingleton:
    """Tests for AgentChat control server singleton behavior."""

    @pytest.fixture
    def socket_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "agent_chat.sock")

    def test_two_agent_chats_share_server(self, socket_path):
        session_id = "shared-agent-session"
        chat1 = _make_agent_chat(session_id, socket_path)
        chat2 = _make_agent_chat(session_id, socket_path)

        with patch(
            "topsailai.workspace.control_channel.server.resolve_socket_path",
            return_value=socket_path,
        ):
            chat1._start_control_server()
            chat2._start_control_server()

        try:
            assert chat1.control_server is not None
            assert chat1.control_server is chat2.control_server
            assert is_socket_live(socket_path)
        finally:
            chat1._stop_control_server()
            chat2._stop_control_server()

    def test_first_release_does_not_stop_shared_server(self, socket_path):
        session_id = "shared-release-session"
        chat1 = _make_agent_chat(session_id, socket_path)
        chat2 = _make_agent_chat(session_id, socket_path)

        with patch(
            "topsailai.workspace.control_channel.server.resolve_socket_path",
            return_value=socket_path,
        ):
            chat1._start_control_server()
            chat2._start_control_server()

        try:
            shared_server = chat1.control_server
            chat1._stop_control_server()
            assert shared_server.is_running()
            assert is_socket_live(socket_path)
            assert chat1.control_server is None
            assert chat2.control_server is shared_server
        finally:
            chat2._stop_control_server()

    def test_last_release_stops_server(self, socket_path):
        session_id = "last-release-session"
        chat1 = _make_agent_chat(session_id, socket_path)
        chat2 = _make_agent_chat(session_id, socket_path)

        with patch(
            "topsailai.workspace.control_channel.server.resolve_socket_path",
            return_value=socket_path,
        ):
            chat1._start_control_server()
            chat2._start_control_server()

        shared_server = chat1.control_server
        chat1._stop_control_server()
        chat2._stop_control_server()
        time.sleep(0.1)

        assert chat2.control_server is None
        assert not shared_server.is_running()
        assert not os.path.exists(socket_path)
        assert (session_id, os.getpid()) not in _control_servers

    def test_different_sessions_create_separate_servers(self, socket_path):
        base_dir = os.path.dirname(socket_path)
        path_a = os.path.join(base_dir, "session_a.sock")
        path_b = os.path.join(base_dir, "session_b.sock")

        chat_a = _make_agent_chat("session-a", path_a)
        chat_b = _make_agent_chat("session-b", path_b)

        def resolve_path(session_id):
            return path_a if session_id == "session-a" else path_b

        with patch(
            "topsailai.workspace.control_channel.server.resolve_socket_path",
            side_effect=resolve_path,
        ):
            chat_a._start_control_server()
            chat_b._start_control_server()

        try:
            assert chat_a.control_server is not chat_b.control_server
            assert is_socket_live(path_a)
            assert is_socket_live(path_b)
        finally:
            chat_a._stop_control_server()
            chat_b._stop_control_server()
