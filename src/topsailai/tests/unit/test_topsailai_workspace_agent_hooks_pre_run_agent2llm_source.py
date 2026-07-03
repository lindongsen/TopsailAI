"""
Unit tests for workspace/agent/hooks/pre_run_agent2llm_source.py

Tests the pre-run hook that registers an Agent2LLM runtime message source.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from topsailai.ai_base.agent2llm_message_source import (
    get_agent2llm_message_source,
)
from topsailai.utils.thread_local_tool import rid_all_thread_vars
from topsailai.workspace.agent.hooks.pre_run_agent2llm_source import (
    pre_run_set_agent2llm_message_source,
)
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK


class TestPreRunAgent2LLMMessageSource(unittest.TestCase):
    """Test pre-run hook for Agent2LLM message source registration."""

    def setUp(self):
        rid_all_thread_vars()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        rid_all_thread_vars()

    def test_hook_registers_file_source_with_default_path(self):
        env = {
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED": "1",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE": "file",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_FILE": "",
            "TOPSAILAI_WORK_FOLDER": self.tmpdir,
        }
        with patch.dict(os.environ, env, clear=False):
            pre_run_set_agent2llm_message_source(None)

        source = get_agent2llm_message_source()
        self.assertIsNotNone(source)
        self.assertTrue(
            source.file_path.startswith(FOLDER_WORKSPACE_TASK),
            f"expected path under {FOLDER_WORKSPACE_TASK}, got {source.file_path}",
        )
        self.assertTrue(
            source.file_path.endswith(".session.agent2llm_inject_messages.jsonl"),
            f"expected session-scoped filename suffix, got {source.file_path}",
        )
        basename = os.path.basename(source.file_path)
        parts = basename.split(".")
        # basename: {session_id}.{pid}.session.agent2llm_inject_messages.jsonl
        self.assertEqual(len(parts), 5)
        self.assertEqual(parts[2], "session")
        self.assertEqual(parts[3], "agent2llm_inject_messages")
        self.assertEqual(parts[4], "jsonl")
        self.assertTrue(parts[1].isdigit(), "pid part should be numeric")

    def test_hook_default_path_includes_session_id_and_pid(self):
        env = {
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED": "1",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE": "file",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_FILE": "",
            "TOPSAILAI_SESSION_ID": "test-session-123",
        }
        with patch.dict(os.environ, env, clear=False):
            pre_run_set_agent2llm_message_source(None)

        source = get_agent2llm_message_source()
        self.assertIsNotNone(source)
        basename = os.path.basename(source.file_path)
        parts = basename.split(".")
        self.assertEqual(parts[0], "test-session-123")
        self.assertEqual(parts[1], str(os.getpid()))

    def test_hook_default_path_falls_back_to_topsailai_without_session(self):
        env = {
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED": "1",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE": "file",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_FILE": "",
        }
        # Ensure neither TOPSAILAI_SESSION_ID nor SESSION_ID is set.
        with patch.dict(
            os.environ,
            env,
            clear=False,
        ), patch("topsailai.utils.env_tool.get_session_id", return_value=None):
            pre_run_set_agent2llm_message_source(None)

        source = get_agent2llm_message_source()
        self.assertIsNotNone(source)
        basename = os.path.basename(source.file_path)
        self.assertTrue(
            basename.startswith("topsailai."),
            f"expected fallback basename starting with 'topsailai.', got {basename}",
        )

    def test_hook_uses_custom_file_path_when_set(self):
        custom_path = os.path.join(self.tmpdir, "custom_inject.jsonl")
        env = {
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED": "1",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE": "file",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_FILE": custom_path,
        }
        with patch.dict(os.environ, env, clear=False):
            pre_run_set_agent2llm_message_source(None)

        source = get_agent2llm_message_source()
        self.assertIsNotNone(source)
        self.assertEqual(source.file_path, custom_path)

    def test_hook_disabled_leaves_source_unset(self):
        env = {
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            pre_run_set_agent2llm_message_source(None)

        self.assertIsNone(get_agent2llm_message_source())

    def test_hook_unknown_source_leaves_source_unset(self):
        env = {
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED": "1",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE": "unknown",
        }
        with patch.dict(os.environ, env, clear=False):
            pre_run_set_agent2llm_message_source(None)

        self.assertIsNone(get_agent2llm_message_source())


if __name__ == '__main__':
    unittest.main()
