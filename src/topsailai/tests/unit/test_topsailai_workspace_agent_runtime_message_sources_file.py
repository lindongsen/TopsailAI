"""
Unit tests for workspace/agent/runtime_message_sources/file.py

Tests FileAgent2LLMMessageSource read/parse/clear behavior, default path
construction, write_message helper, and produce_message interface.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from topsailai.ai_base.agent2llm_message_source import (
    Agent2LLMMessageSource,
    apply_agent2llm_message_source,
)
from topsailai.ai_base.constants import (
    MSG_KEY_RAW_TEXT,
    MSG_KEY_STEP_NAME,
    ROLE_ASSISTANT,
    ROLE_USER,
    STEP_NAME_OBSERVATION,
    STEP_NAME_TASK,
)
from topsailai.workspace.agent.runtime_message_sources.file import (
    FileAgent2LLMMessageSource,
    get_default_inject_message_file_path,
    write_message,
)
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK


class TestGetDefaultInjectMessageFilePath(unittest.TestCase):
    """Test default path construction."""

    def test_default_path_uses_session_id_and_pid(self):
        path = get_default_inject_message_file_path("my-session")
        self.assertTrue(path.startswith(FOLDER_WORKSPACE_TASK))
        basename = os.path.basename(path)
        self.assertTrue(basename.startswith("my-session."))
        self.assertTrue(basename.endswith(".session.agent2llm_inject_messages.jsonl"))
        parts = basename.split(".")
        self.assertEqual(len(parts), 5)
        self.assertEqual(parts[1], str(os.getpid()))

    def test_default_path_falls_back_to_topsailai(self):
        with patch("topsailai.utils.env_tool.get_session_id", return_value=None):
            path = get_default_inject_message_file_path()
        basename = os.path.basename(path)
        self.assertTrue(basename.startswith("topsailai."))


class TestWriteMessage(unittest.TestCase):
    """Test write_message helper."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.tmpdir, "inject_messages.jsonl")

    def tearDown(self):
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_write_message_appends_jsonl_line(self):
        result = write_message(self.file_path, "hello")
        self.assertTrue(result)

        with open(self.file_path, "r", encoding="utf-8") as fd:
            lines = [line.strip() for line in fd if line.strip()]

        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["role"], ROLE_USER)
        self.assertEqual(parsed["content"][MSG_KEY_STEP_NAME], STEP_NAME_OBSERVATION)
        self.assertEqual(parsed["content"][MSG_KEY_RAW_TEXT], "hello")

    def test_write_message_custom_role_and_step_name(self):
        result = write_message(
            self.file_path,
            "task text",
            role=ROLE_ASSISTANT,
            step_name=STEP_NAME_TASK,
        )
        self.assertTrue(result)

        with open(self.file_path, "r", encoding="utf-8") as fd:
            parsed = json.loads(fd.readline())

        self.assertEqual(parsed["role"], ROLE_ASSISTANT)
        self.assertEqual(parsed["content"][MSG_KEY_STEP_NAME], STEP_NAME_TASK)
        self.assertEqual(parsed["content"][MSG_KEY_RAW_TEXT], "task text")

    def test_write_message_dict_content_passthrough(self):
        content = {"custom": "value"}
        result = write_message(self.file_path, content, role=ROLE_ASSISTANT)
        self.assertTrue(result)

        with open(self.file_path, "r", encoding="utf-8") as fd:
            parsed = json.loads(fd.readline())

        self.assertEqual(parsed["role"], ROLE_ASSISTANT)
        self.assertEqual(parsed["content"], content)

    def test_write_message_creates_parent_directories(self):
        nested_path = os.path.join(self.tmpdir, "a", "b", "messages.jsonl")
        result = write_message(nested_path, "hello")
        self.assertTrue(result)
        self.assertTrue(os.path.exists(nested_path))

        with open(nested_path, "r", encoding="utf-8") as fd:
            parsed = json.loads(fd.readline())
        self.assertEqual(parsed["content"][MSG_KEY_RAW_TEXT], "hello")

    def test_write_message_multiple_appends(self):
        write_message(self.file_path, "first")
        write_message(self.file_path, "second")

        with open(self.file_path, "r", encoding="utf-8") as fd:
            lines = [line.strip() for line in fd if line.strip()]

        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["content"][MSG_KEY_RAW_TEXT], "first")
        self.assertEqual(json.loads(lines[1])["content"][MSG_KEY_RAW_TEXT], "second")

    def test_write_message_returns_false_on_failure(self):
        # Patch the open call inside write_message to raise an error so the
        # write fails and returns False.
        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = write_message(self.file_path, "hello")
        self.assertFalse(result)

    def test_write_message_includes_ts_field(self):
        result = write_message(self.file_path, "hello")
        self.assertTrue(result)

        with open(self.file_path, "r", encoding="utf-8") as fd:
            parsed = json.loads(fd.readline())

        self.assertIn("ts", parsed)
        self.assertIsInstance(parsed["ts"], str)
        self.assertTrue(parsed["ts"].endswith("+00:00"))

    def test_write_message_ts_is_iso_8601_utc(self):
        from datetime import datetime, timezone

        before = datetime.now(timezone.utc)
        write_message(self.file_path, "hello")
        after = datetime.now(timezone.utc)

        with open(self.file_path, "r", encoding="utf-8") as fd:
            parsed = json.loads(fd.readline())

        ts = datetime.fromisoformat(parsed["ts"])
        self.assertTrue(before <= ts <= after)
        self.assertEqual(ts.tzinfo, timezone.utc)


class TestFileAgent2LLMMessageSource(unittest.TestCase):
    """Test file-based runtime message source."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.tmpdir, "inject_messages.jsonl")

    def tearDown(self):
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def _write_lines(self, lines):
        with open(self.file_path, "w", encoding="utf-8") as fd:
            for line in lines:
                fd.write(line + "\n")

    def test_missing_file_returns_empty(self):
        source = FileAgent2LLMMessageSource(self.file_path)
        messages = list(source.consume_messages())
        self.assertEqual(messages, [])

    def test_empty_file_returns_empty(self):
        open(self.file_path, "w").close()
        source = FileAgent2LLMMessageSource(self.file_path)
        messages = list(source.consume_messages())
        self.assertEqual(messages, [])
        self.assertEqual(os.path.getsize(self.file_path), 0)

    def test_reads_and_clears_file(self):
        self._write_lines([
            json.dumps({"role": "user", "content": "hello"}),
            json.dumps({"role": "assistant", "content": "hi"}),
        ])
        source = FileAgent2LLMMessageSource(self.file_path)

        messages = list(source.consume_messages())

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "hello")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(os.path.getsize(self.file_path), 0)

    def test_skips_invalid_json_lines(self):
        self._write_lines([
            json.dumps({"role": "user", "content": "valid"}),
            "not-json",
            json.dumps({"role": "user", "content": "also valid"}),
        ])
        source = FileAgent2LLMMessageSource(self.file_path)

        messages = list(source.consume_messages())

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "valid")
        self.assertEqual(messages[1]["content"], "also valid")
        self.assertEqual(os.path.getsize(self.file_path), 0)

    def test_skips_non_dict_lines(self):
        self._write_lines([
            json.dumps({"role": "user", "content": "valid"}),
            json.dumps(["not", "a", "dict"]),
        ])
        source = FileAgent2LLMMessageSource(self.file_path)

        messages = list(source.consume_messages())

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "valid")

    def test_clear_failure_does_not_inject(self):
        self._write_lines([
            json.dumps({"role": "user", "content": "hello"}),
        ])
        source = FileAgent2LLMMessageSource(self.file_path)

        with patch.object(source, '_clear_file', return_value=False):
            messages = list(source.consume_messages())

        self.assertEqual(messages, [])
        # File should still contain the original content
        with open(self.file_path, "r", encoding="utf-8") as fd:
            self.assertTrue(fd.read().strip())

    def test_duplicate_digest_protection(self):
        self._write_lines([
            json.dumps({"role": "user", "content": "hello"}),
        ])
        source = FileAgent2LLMMessageSource(self.file_path)

        messages1 = list(source.consume_messages())
        # Simulate clear failure leaving same content
        self._write_lines([
            json.dumps({"role": "user", "content": "hello"}),
        ])
        messages2 = list(source.consume_messages())

        self.assertEqual(len(messages1), 1)
        self.assertEqual(messages2, [])

    def test_blank_lines_are_ignored(self):
        self._write_lines([
            json.dumps({"role": "user", "content": "first"}),
            "",
            "   ",
            json.dumps({"role": "user", "content": "second"}),
        ])
        source = FileAgent2LLMMessageSource(self.file_path)

        messages = list(source.consume_messages())

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "first")
        self.assertEqual(messages[1]["content"], "second")

    def test_whitespace_only_file_returns_empty(self):
        self._write_lines(["", "   ", ""])
        source = FileAgent2LLMMessageSource(self.file_path)
        messages = list(source.consume_messages())
        self.assertEqual(messages, [])

    def test_invalid_content_only_file_is_cleared(self):
        self._write_lines(["not-json", json.dumps(["list"])])
        source = FileAgent2LLMMessageSource(self.file_path)

        messages = list(source.consume_messages())

        self.assertEqual(messages, [])
        self.assertEqual(os.path.getsize(self.file_path), 0)

    def test_write_then_consume_round_trip(self):
        write_message(self.file_path, "first")
        write_message(self.file_path, "second", role=ROLE_ASSISTANT)

        source = FileAgent2LLMMessageSource(self.file_path)
        messages = list(source.consume_messages())

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], ROLE_USER)
        self.assertEqual(messages[0]["content"][MSG_KEY_RAW_TEXT], "first")
        self.assertEqual(messages[1]["role"], ROLE_ASSISTANT)
        self.assertEqual(messages[1]["content"][MSG_KEY_RAW_TEXT], "second")
        self.assertEqual(os.path.getsize(self.file_path), 0)


class TestFileAgent2LLMMessageSourceProduceMessage(unittest.TestCase):
    """Test produce_message interface on FileAgent2LLMMessageSource."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.tmpdir, "inject_messages.jsonl")

    def tearDown(self):
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_produce_message_string_content(self):
        source = FileAgent2LLMMessageSource(self.file_path)
        result = source.produce_message("hello")
        self.assertTrue(result)

        with open(self.file_path, "r", encoding="utf-8") as fd:
            parsed = json.loads(fd.readline())

        self.assertEqual(parsed["role"], ROLE_USER)
        self.assertEqual(parsed["content"][MSG_KEY_STEP_NAME], STEP_NAME_OBSERVATION)
        self.assertEqual(parsed["content"][MSG_KEY_RAW_TEXT], "hello")

    def test_produce_message_dict_content_passthrough(self):
        source = FileAgent2LLMMessageSource(self.file_path)
        content = {"custom": "value"}
        result = source.produce_message(content, role=ROLE_ASSISTANT)
        self.assertTrue(result)

        with open(self.file_path, "r", encoding="utf-8") as fd:
            parsed = json.loads(fd.readline())

        self.assertEqual(parsed["role"], ROLE_ASSISTANT)
        self.assertEqual(parsed["content"], content)

    def test_produce_message_custom_role_and_step_name(self):
        source = FileAgent2LLMMessageSource(self.file_path)
        result = source.produce_message(
            "task text", role=ROLE_ASSISTANT, step_name=STEP_NAME_TASK
        )
        self.assertTrue(result)

        with open(self.file_path, "r", encoding="utf-8") as fd:
            parsed = json.loads(fd.readline())

        self.assertEqual(parsed["role"], ROLE_ASSISTANT)
        self.assertEqual(parsed["content"][MSG_KEY_STEP_NAME], STEP_NAME_TASK)
        self.assertEqual(parsed["content"][MSG_KEY_RAW_TEXT], "task text")

    def test_produce_then_consume_round_trip(self):
        source = FileAgent2LLMMessageSource(self.file_path)
        source.produce_message("first")
        source.produce_message("second", role=ROLE_ASSISTANT)

        messages = list(source.consume_messages())

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], ROLE_USER)
        self.assertEqual(messages[0]["content"][MSG_KEY_RAW_TEXT], "first")
        self.assertEqual(messages[1]["role"], ROLE_ASSISTANT)
        self.assertEqual(messages[1]["content"][MSG_KEY_RAW_TEXT], "second")
        self.assertEqual(os.path.getsize(self.file_path), 0)

    def test_produce_message_uses_abstract_base_signature(self):
        # Ensure FileAgent2LLMMessageSource properly implements the abstract
        # produce_message method from Agent2LLMMessageSource.
        self.assertTrue(
            issubclass(FileAgent2LLMMessageSource, Agent2LLMMessageSource)
        )
        source = FileAgent2LLMMessageSource(self.file_path)
        self.assertTrue(callable(getattr(source, "produce_message", None)))



class TestFileAgent2LLMMessageSourceTsStripping(unittest.TestCase):
    """Test that the ts field is stripped before injection into Agent2LLM."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.tmpdir, "inject_messages.jsonl")

    def tearDown(self):
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def _write_lines(self, lines):
        with open(self.file_path, "w", encoding="utf-8") as fd:
            for line in lines:
                fd.write(line + "\n")

    def test_ts_field_stripped_by_apply_agent2llm_message_source(self):
        from unittest.mock import MagicMock
        from topsailai.ai_base.agent2llm_message_source import (
            set_agent2llm_message_source,
            unset_agent2llm_message_source,
        )
        from topsailai.utils.thread_local_tool import rid_all_thread_vars

        rid_all_thread_vars()
        try:
            self._write_lines([
                json.dumps({
                    "role": ROLE_USER,
                    "content": "hello",
                    "ts": "2026-07-04T12:34:56.789012+00:00",
                }),
            ])
            source = FileAgent2LLMMessageSource(self.file_path)
            set_agent2llm_message_source(source)

            agent = MagicMock()
            agent.messages = []

            count = apply_agent2llm_message_source(agent)

            self.assertEqual(count, 1)
            agent.add_user_message.assert_called_once()
            content = agent.add_user_message.call_args.args[0]
            self.assertEqual(content[MSG_KEY_STEP_NAME], STEP_NAME_OBSERVATION)
            self.assertEqual(content[MSG_KEY_RAW_TEXT], "hello")
            self.assertNotIn("ts", content)
        finally:
            unset_agent2llm_message_source()

    def test_produce_message_includes_ts_field(self):
        source = FileAgent2LLMMessageSource(self.file_path)
        result = source.produce_message("hello")
        self.assertTrue(result)

        with open(self.file_path, "r", encoding="utf-8") as fd:
            parsed = json.loads(fd.readline())

        self.assertIn("ts", parsed)
        self.assertIsInstance(parsed["ts"], str)

    def test_consume_messages_preserves_ts_for_consumer(self):
        """consume_messages yields the raw line including ts; stripping happens
        later in apply_agent2llm_message_source."""
        self._write_lines([
            json.dumps({
                "role": ROLE_USER,
                "content": "hello",
                "ts": "2026-07-04T12:34:56.789012+00:00",
            }),
        ])
        source = FileAgent2LLMMessageSource(self.file_path)
        messages = list(source.consume_messages())

        self.assertEqual(len(messages), 1)
        self.assertIn("ts", messages[0])
        self.assertEqual(messages[0]["ts"], "2026-07-04T12:34:56.789012+00:00")

    def test_file_deleted_on_process_exit(self):
        """The inject file should be removed when the source is cleaned up at
        process exit."""
        source = FileAgent2LLMMessageSource(self.file_path)
        source.produce_message("hello")
        self.assertTrue(os.path.exists(self.file_path))

        source._delete_file_on_exit()

        self.assertFalse(os.path.exists(self.file_path))

    def test_atexit_handler_registered(self):
        """Creating a source should register an atexit cleanup handler."""
        from unittest.mock import patch

        with patch("atexit.register") as mock_register:
            source = FileAgent2LLMMessageSource(self.file_path)

        mock_register.assert_called_once()
        self.assertEqual(mock_register.call_args.args[0], source._delete_file_on_exit)


if __name__ == '__main__':
    unittest.main()

if __name__ == '__main__':
    unittest.main()
