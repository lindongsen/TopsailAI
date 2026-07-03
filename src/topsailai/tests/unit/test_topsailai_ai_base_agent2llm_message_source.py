"""
Unit tests for ai_base/agent2llm_message_source.py

Tests Agent2LLMMessageSource interface, thread-local helpers,
apply_agent2llm_message_source injection logic, and build_message helpers.
"""

import unittest
from unittest.mock import MagicMock

from topsailai.ai_base.agent2llm_message_source import (
    Agent2LLMMessageSource,
    apply_agent2llm_message_source,
    get_agent2llm_message_source,
    set_agent2llm_message_source,
    unset_agent2llm_message_source,
)
from topsailai.ai_base.constants import (
    MSG_KEY_RAW_TEXT,
    MSG_KEY_STEP_NAME,
    ROLE_ASSISTANT,
    ROLE_USER,
    STEP_NAME_OBSERVATION,
    STEP_NAME_TASK,
)
from topsailai.utils.thread_local_tool import KEY_AGENT2LLM_MESSAGE_SOURCE, rid_all_thread_vars


class DummySource(Agent2LLMMessageSource):
    """Test source that yields configured messages once."""

    def __init__(self, messages):
        self._messages = list(messages)
        self._produced = []

    def consume_messages(self):
        while self._messages:
            yield self._messages.pop(0)

    def produce_message(self, content, role=ROLE_USER, step_name=STEP_NAME_OBSERVATION):
        self._produced.append({"content": content, "role": role, "step_name": step_name})
        return True


class TestAgent2LLMMessageSourceBuildMessage(unittest.TestCase):
    """Test build_message and build_simple_message helpers."""

    def test_build_message_defaults(self):
        msg = Agent2LLMMessageSource.build_message("hello")
        self.assertEqual(msg["role"], ROLE_USER)
        self.assertEqual(msg["content"][MSG_KEY_STEP_NAME], STEP_NAME_OBSERVATION)
        self.assertEqual(msg["content"][MSG_KEY_RAW_TEXT], "hello")

    def test_build_message_custom_role_and_step_name(self):
        msg = Agent2LLMMessageSource.build_message(
            "task text", role=ROLE_ASSISTANT, step_name=STEP_NAME_TASK
        )
        self.assertEqual(msg["role"], ROLE_ASSISTANT)
        self.assertEqual(msg["content"][MSG_KEY_STEP_NAME], STEP_NAME_TASK)
        self.assertEqual(msg["content"][MSG_KEY_RAW_TEXT], "task text")

    def test_build_message_dict_content_passthrough(self):
        content = {"custom": "value"}
        msg = Agent2LLMMessageSource.build_message(content)
        self.assertEqual(msg["role"], ROLE_USER)
        self.assertEqual(msg["content"], content)

    def test_build_message_static_method_no_instance_required(self):
        # Calling on the class should work without instantiation.
        msg = Agent2LLMMessageSource.build_message("static")
        self.assertEqual(msg["content"][MSG_KEY_RAW_TEXT], "static")

    def test_build_simple_message_defaults(self):
        msg = Agent2LLMMessageSource.build_simple_message("hello")
        self.assertEqual(msg["role"], ROLE_USER)
        self.assertEqual(msg["content"], "hello")

    def test_build_simple_message_custom_role(self):
        msg = Agent2LLMMessageSource.build_simple_message(
            {"key": "value"}, role=ROLE_ASSISTANT
        )
        self.assertEqual(msg["role"], ROLE_ASSISTANT)
        self.assertEqual(msg["content"], {"key": "value"})


class TestAgent2LLMMessageSourceInterface(unittest.TestCase):
    """Test abstract producer interface contract."""

    def test_cannot_instantiate_abstract_class(self):
        with self.assertRaises(TypeError):
            Agent2LLMMessageSource()

    def test_produce_message_interface_on_dummy(self):
        source = DummySource([])
        result = source.produce_message("hello", role=ROLE_ASSISTANT, step_name=STEP_NAME_TASK)
        self.assertTrue(result)
        self.assertEqual(len(source._produced), 1)
        self.assertEqual(source._produced[0]["content"], "hello")
        self.assertEqual(source._produced[0]["role"], ROLE_ASSISTANT)
        self.assertEqual(source._produced[0]["step_name"], STEP_NAME_TASK)

    def test_produce_message_dict_content_passthrough(self):
        source = DummySource([])
        content = {"step_name": "observation", "raw_text": "structured"}
        source.produce_message(content, role=ROLE_USER)
        self.assertEqual(source._produced[0]["content"], content)


class TestAgent2LLMMessageSourceThreadLocal(unittest.TestCase):
    """Test thread-local getter/setter/unset for agent2llm message source."""

    def setUp(self):
        rid_all_thread_vars()

    def tearDown(self):
        rid_all_thread_vars()

    def test_set_and_get_source(self):
        source = DummySource([{"role": ROLE_USER, "content": "hello"}])
        set_agent2llm_message_source(source)
        self.assertIs(get_agent2llm_message_source(), source)

    def test_unset_source(self):
        source = DummySource([{"role": ROLE_USER, "content": "hello"}])
        set_agent2llm_message_source(source)
        unset_agent2llm_message_source()
        self.assertIsNone(get_agent2llm_message_source())

    def test_get_without_set_returns_none(self):
        self.assertIsNone(get_agent2llm_message_source())

    def test_set_none_unsets_source(self):
        source = DummySource([{"role": ROLE_USER, "content": "hello"}])
        set_agent2llm_message_source(source)
        set_agent2llm_message_source(None)
        self.assertIsNone(get_agent2llm_message_source())

    def test_thread_local_key_constant(self):
        self.assertEqual(KEY_AGENT2LLM_MESSAGE_SOURCE, "agent2llm_message_source")


class TestApplyAgent2LLMMessageSource(unittest.TestCase):
    """Test apply_agent2llm_message_source injection behavior."""

    def setUp(self):
        rid_all_thread_vars()
        self.agent = MagicMock()
        self.agent.messages = []

    def tearDown(self):
        rid_all_thread_vars()

    def test_no_source_returns_zero(self):
        count = apply_agent2llm_message_source(self.agent)
        self.assertEqual(count, 0)
        self.agent.add_user_message.assert_not_called()

    def test_source_injects_messages_at_tail(self):
        source = DummySource([
            {"role": ROLE_USER, "content": "first"},
            {"role": ROLE_USER, "content": "second"},
        ])
        set_agent2llm_message_source(source)

        count = apply_agent2llm_message_source(self.agent)

        self.assertEqual(count, 2)
        self.assertEqual(self.agent.add_user_message.call_count, 2)

        first_call = self.agent.add_user_message.call_args_list[0]
        second_call = self.agent.add_user_message.call_args_list[1]

        self.assertEqual(first_call.kwargs["need_print"], False)
        self.assertEqual(first_call.args[0][MSG_KEY_STEP_NAME], STEP_NAME_OBSERVATION)
        self.assertEqual(first_call.args[0][MSG_KEY_RAW_TEXT], "first")

        self.assertEqual(second_call.args[0][MSG_KEY_STEP_NAME], STEP_NAME_OBSERVATION)
        self.assertEqual(second_call.args[0][MSG_KEY_RAW_TEXT], "second")

    def test_empty_content_messages_are_skipped(self):
        source = DummySource([
            {"role": ROLE_USER, "content": ""},
            {"role": ROLE_USER, "content": "valid"},
            {"role": ROLE_USER, "content": None},
        ])
        set_agent2llm_message_source(source)

        count = apply_agent2llm_message_source(self.agent)

        self.assertEqual(count, 1)
        self.agent.add_user_message.assert_called_once()
        self.assertEqual(
            self.agent.add_user_message.call_args.args[0][MSG_KEY_RAW_TEXT],
            "valid",
        )

    def test_default_role_is_user(self):
        source = DummySource([{"content": "no role"}])
        set_agent2llm_message_source(source)

        apply_agent2llm_message_source(self.agent)

        self.agent.add_user_message.assert_called_once()

    def test_source_consumed_only_once(self):
        source = DummySource([{"role": ROLE_USER, "content": "once"}])
        set_agent2llm_message_source(source)

        count1 = apply_agent2llm_message_source(self.agent)
        count2 = apply_agent2llm_message_source(self.agent)

        self.assertEqual(count1, 1)
        self.assertEqual(count2, 0)
        self.assertEqual(self.agent.add_user_message.call_count, 1)

    def test_structured_content_passed_through_unchanged(self):
        structured = {
            MSG_KEY_STEP_NAME: STEP_NAME_OBSERVATION,
            MSG_KEY_RAW_TEXT: "structured content",
        }
        source = DummySource([{"role": ROLE_USER, "content": structured}])
        set_agent2llm_message_source(source)

        count = apply_agent2llm_message_source(self.agent)

        self.assertEqual(count, 1)
        self.agent.add_user_message.assert_called_once()
        self.assertEqual(self.agent.add_user_message.call_args.args[0], structured)

    def test_structured_content_missing_keys_is_coerced(self):
        invalid = {"missing": "keys"}
        source = DummySource([{"role": ROLE_USER, "content": invalid}])
        set_agent2llm_message_source(source)

        count = apply_agent2llm_message_source(self.agent)

        self.assertEqual(count, 1)
        self.agent.add_user_message.assert_called_once()
        content = self.agent.add_user_message.call_args.args[0]
        self.assertEqual(content[MSG_KEY_STEP_NAME], STEP_NAME_OBSERVATION)
        self.assertIn("missing", content[MSG_KEY_RAW_TEXT])

    def test_structured_content_empty_raw_text_is_skipped(self):
        structured = {
            MSG_KEY_STEP_NAME: STEP_NAME_OBSERVATION,
            MSG_KEY_RAW_TEXT: "",
        }
        source = DummySource([{"role": ROLE_USER, "content": structured}])
        set_agent2llm_message_source(source)

        count = apply_agent2llm_message_source(self.agent)

        self.assertEqual(count, 0)
        self.agent.add_user_message.assert_not_called()


if __name__ == '__main__':
    unittest.main()
