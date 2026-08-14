"""
Test module for ai_base/llm_control/message.py

Author: AI
Purpose: Unit tests for message handling functions
"""

from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

class TestToList:
    """Test suite for _to_list function."""

    def test_to_list_with_list(self):
        """Verify _to_list returns list unchanged."""
        from topsailai.ai_base.llm_control.message import _to_list

        input_list = [1, 2, 3]
        result = _to_list(input_list)
        assert result == [1, 2, 3]
        assert result is input_list

    def test_to_list_with_none(self):
        """Verify _to_list returns None for None input."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list(None)
        assert result is None

    def test_to_list_with_string(self):
        """Verify _to_list wraps string in list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list("hello")
        assert result == ["hello"]

    def test_to_list_with_tuple(self):
        """Verify _to_list converts tuple to list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list((1, 2, 3))
        assert result == [1, 2, 3]

    def test_to_list_with_set(self):
        """Verify _to_list converts set to list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list({1, 2, 3})
        assert result == [1, 2, 3]

    def test_to_list_with_dict(self):
        """Verify _to_list wraps dict in list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list({"key": "value"})
        assert result == [{"key": "value"}]

    def test_to_list_with_int(self):
        """Verify _to_list wraps int in list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list(42)
        assert result == [42]


class TestGetResponseMessage:
    """Test suite for get_response_message function."""

    def test_get_response_message_with_chat_completion_message(self):
        """Verify returns ChatCompletionMessage directly."""
        from openai.types.chat import ChatCompletionMessage
        from topsailai.ai_base.llm_control.message import get_response_message

        mock_msg = MagicMock(spec=ChatCompletionMessage)
        result = get_response_message(mock_msg)
        assert result is mock_msg

    def test_get_response_message_with_response_object(self):
        """Verify extracts message from response.choices[0].message."""
        from topsailai.ai_base.llm_control.message import get_response_message

        mock_msg = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_msg

        result = get_response_message(mock_response)
        assert result is mock_msg

    def test_get_response_message_with_empty_choices(self):
        """Verify handles empty choices list."""
        from topsailai.ai_base.llm_control.message import get_response_message

        mock_response = MagicMock()
        mock_response.choices = []

        # Should raise IndexError when accessing choices[0]
        with pytest.raises(IndexError):
            get_response_message(mock_response)


class TestGetToolCallsOfRsp:
    """Test suite for get_tool_calls_of_rsp function."""

    def test_get_tool_calls_with_none_response(self):
        """Verify returns None for None response."""
        from topsailai.ai_base.llm_control.message import get_tool_calls_of_rsp

        result = get_tool_calls_of_rsp(None)
        assert result is None

    def test_get_tool_calls_with_empty_response(self):
        """Verify returns None for empty response."""
        from topsailai.ai_base.llm_control.message import get_tool_calls_of_rsp

        result = get_tool_calls_of_rsp("")
        assert result is None

    def test_get_tool_calls_with_valid_response(self):
        """Verify extracts tool_calls from response."""
        from topsailai.ai_base.llm_control.message import get_tool_calls_of_rsp

        mock_tool_calls = [MagicMock(), MagicMock()]
        mock_msg = MagicMock()
        mock_msg.tool_calls = mock_tool_calls

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_msg

        result = get_tool_calls_of_rsp(mock_response)
        assert result is mock_tool_calls


class TestGetCountOfAction:
    """Test suite for get_count_of_action function."""

    def test_get_count_of_action_with_none(self):
        """Verify returns 0 for None."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        result = get_count_of_action(None)
        assert result == 0

    def test_get_count_of_action_with_empty_list(self):
        """Verify returns 0 for empty list."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        result = get_count_of_action([])
        assert result == 0

    def test_get_count_of_action_with_messages(self):
        """Verify counts messages with step_name action."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "thought"'},
            {"role": "assistant", "content": '"step_name": "action"'},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]

        result = get_count_of_action(messages)
        assert result == 2

    def test_get_count_of_action_ignores_non_dict(self):
        """Verify ignores non-dict messages."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            "not a dict",
            {"role": "assistant", "content": '"step_name": "action"'},
        ]

        result = get_count_of_action(messages)
        assert result == 1

    def test_get_count_of_action_ignores_missing_content(self):
        """Verify ignores messages without content."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user"},  # missing content
            {"role": "assistant", "content": '"step_name": "action"'},
        ]

        result = get_count_of_action(messages)
        assert result == 1

    def test_get_count_of_action_uses_tool_stat_when_available(self):
        """Verify returns tool_stat total_calls when it has recorded calls."""
        from topsailai.ai_base.llm_control.message import get_count_of_action
        from topsailai.context.tool_stat import ToolStat

        stat = ToolStat()
        stat.record("file_tool-read_file", {"files": ["/tmp/1.txt"]})
        stat.record("cmd_tool-exec_cmd", {"cmd": "echo hello"})

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]

        result = get_count_of_action(messages, tool_stat=stat)
        assert result == 2

    def test_get_count_of_action_falls_back_when_tool_stat_is_empty(self):
        """Verify scans messages when tool_stat has no recorded calls."""
        from topsailai.ai_base.llm_control.message import get_count_of_action
        from topsailai.context.tool_stat import ToolStat

        stat = ToolStat()

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]

        result = get_count_of_action(messages, tool_stat=stat)
        assert result == 2

    def test_get_count_of_action_resolves_tool_stat_from_thread_local(self):
        """Verify resolves agent-bound tool_stat when no explicit instance is passed."""
        from topsailai.ai_base.llm_control.message import get_count_of_action
        from topsailai.context.tool_stat import ToolStat
        from topsailai.utils.thread_local_tool import ctxm_set_agent

        stat = ToolStat()
        stat.record("file_tool-read_file", {"files": ["/tmp/1.txt"]})

        mock_agent = MagicMock()
        mock_agent.llm_model.tool_stat = stat

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]

        with ctxm_set_agent(mock_agent):
            result = get_count_of_action(messages)

        assert result == 1



class TestUpdateResponseItem:
    """Test suite for update_response_item function."""

    def test_update_response_item_with_action_and_raw_text(self):
        """Verify updates item with hook result."""
        from topsailai.ai_base.llm_control.message import update_response_item

        item = {
            "step_name": "action",
            "raw_text": "test action"
        }

        with patch('topsailai.ai_base.llm_control.message.hook_execute') as mock_hook:
            mock_hook.return_value = [{"new_key": "new_value"}]
            result = update_response_item(item)

            mock_hook.assert_called_once_with("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "test action")
            assert result.get("new_key") == "new_value"

    def test_update_response_item_without_action_step(self):
        """Verify returns item unchanged if not action step."""
        from topsailai.ai_base.llm_control.message import update_response_item

        item = {
            "step_name": "thought",
            "raw_text": "test thought"
        }

        result = update_response_item(item)
        assert result is item
        assert "step_name" in result

    def test_update_response_item_without_raw_text(self):
        """Verify returns item unchanged if no raw_text."""
        from topsailai.ai_base.llm_control.message import update_response_item

        item = {
            "step_name": "action"
        }

        result = update_response_item(item)
        assert result is item

    def test_update_response_item_with_invalid_hook_result(self):
        """Verify handles invalid hook result gracefully."""
        from topsailai.ai_base.llm_control.message import update_response_item

        item = {
            "step_name": "action",
            "raw_text": "test action"
        }

        with patch('topsailai.ai_base.llm_control.message.hook_execute') as mock_hook:
            mock_hook.return_value = "not a list"
            result = update_response_item(item)
            assert result is item


class TestAssertModelServiceError:
    """Test suite for assert_model_service_error function."""

    def test_assert_model_service_error_with_none(self):
        """Verify does not raise for None."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error

        # Should not raise
        assert_model_service_error(None)

    def test_assert_model_service_error_with_empty_list(self):
        """Verify does not raise for empty list."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error

        # Should not raise
        assert_model_service_error([])

    def test_assert_model_service_error_with_multiple_items(self):
        """Verify does not raise for list with multiple items."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error

        # Should not raise
        assert_model_service_error([{"step_name": "action"}, {"step_name": "thought"}])

    def test_assert_model_service_error_raises_for_error_response(self):
        """Verify raises ModelServiceError for error response."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error
        from topsailai.ai_base.llm_control.exception import ModelServiceError

        error_response = [
            {"status": 500, "message": "Internal Server Error"}
        ]

        with pytest.raises(ModelServiceError):
            assert_model_service_error(error_response)

    def test_assert_model_service_error_raises_for_status_and_message(self):
        """Verify raises for response with only status and message."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error
        from topsailai.ai_base.llm_control.exception import ModelServiceError

        error_response = [
            {"status": 429, "message": "Rate limit exceeded"}
        ]

        with pytest.raises(ModelServiceError):
            assert_model_service_error(error_response)

    def test_assert_model_service_error_does_not_raise_for_valid(self):
        """Verify does not raise for valid action response."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error

        valid_response = [
            {"step_name": "action", "raw_text": "do something"}
        ]

        # Should not raise
        assert_model_service_error(valid_response)


class TestFixLlmMistakes:
    """Test suite for fix_llm_mistakes function."""

    def test_fix_llm_mistakes_with_none(self):
        """Verify returns None for None input."""
        from topsailai.ai_base.llm_control.message import fix_llm_mistakes

        result = fix_llm_mistakes(None)
        assert result is None

    def test_fix_llm_mistakes_with_empty_list(self):
        """Verify returns empty list unchanged."""
        from topsailai.ai_base.llm_control.message import fix_llm_mistakes

        result = fix_llm_mistakes([])
        assert result == []

    def test_fix_llm_mistakes_adds_step_name(self):
        """Verify adds step_name for tool_call and tool_args."""
        from topsailai.ai_base.llm_control.message import fix_llm_mistakes

        response = [
            {"tool_call": "test_tool", "tool_args": {}}
        ]

        result = fix_llm_mistakes(response)
        assert result[0].get("step_name") == "action"

    def test_fix_llm_mistakes_preserves_existing_step_name(self):
        """Verify preserves existing step_name."""
        from topsailai.ai_base.llm_control.message import fix_llm_mistakes

        response = [
            {"step_name": "thought", "raw_text": "thinking"}
        ]

        result = fix_llm_mistakes(response)
        assert result[0].get("step_name") == "thought"


class TestParseXmlFunctionCall:
    """Test suite for _parse_xml_function_call helper."""

    def test_parse_xml_function_call_with_leading_text(self):
        """Verify leading text is preserved as thought and tool call is extracted."""
        from topsailai.ai_base.llm_control.message import _parse_xml_function_call

        text = (
            "The subagent response was truncated.\n"
            "<function=subagent_tool-call_assistant>\n"
            '<parameter=task>{"task": "do it", "role": "km1-tester"}</parameter>\n'
            "</function>"
        )
        result = _parse_xml_function_call(text)
        assert result == [
            {"step_name": "thought", "raw_text": "The subagent response was truncated."},
            {
                "step_name": "action",
                "tool_call": "subagent_tool-call_assistant",
                "tool_args": {"task": "do it", "role": "km1-tester"},
            },
        ]

    def test_parse_xml_function_call_no_leading_text(self):
        """Verify tool call is extracted when there is no leading text."""
        from topsailai.ai_base.llm_control.message import _parse_xml_function_call

        text = (
            "<function=file_tool-read_file>\n"
            '<parameter=files>["/tmp/1.txt"]</parameter>\n'
            "</function>"
        )
        result = _parse_xml_function_call(text)
        assert result == [
            {
                "step_name": "action",
                "tool_call": "file_tool-read_file",
                "tool_args": {"files": ["/tmp/1.txt"]},
            },
        ]

    def test_parse_xml_function_call_no_function_block(self):
        """Verify None is returned when no function block exists."""
        from topsailai.ai_base.llm_control.message import _parse_xml_function_call

        assert _parse_xml_function_call("just some text") is None
        assert _parse_xml_function_call("{\"step_name\": \"action\"}") is None

    def test_parse_xml_function_call_unclosed_tag(self):
        """Verify None is returned for unclosed function tags."""
        from topsailai.ai_base.llm_control.message import _parse_xml_function_call

        assert _parse_xml_function_call("<function=foo>\n<parameter=a>1</parameter>") is None

    def test_parse_xml_function_call_non_dict_parameter(self):
        """Verify non-JSON-dict parameter values are stored under their key."""
        from topsailai.ai_base.llm_control.message import _parse_xml_function_call

        text = (
            "<function=echo>\n"
            "<parameter=message>hello world</parameter>\n"
            "</function>"
        )
        result = _parse_xml_function_call(text)
        assert result == [
            {
                "step_name": "action",
                "tool_call": "echo",
                "tool_args": {"message": "hello world"},
            },
        ]


class TestFormatResponseXmlFunctionCall:
    """Test suite for format_response XML function-call handling."""

    def test_format_response_xml_function_call_with_nested_json(self):
        """Verify reported LLM output is parsed into thought + action."""
        from topsailai.ai_base.llm_control.message import format_response

        text = (
            "The subagent response was truncated/errored. Let me directly read the file using shell command since I need to see its contents.\n"
            "<function=subagent_tool-call_assistant>\n"
            '<parameter=task>{"task": "Execute the following shell command and return the full output:\\n\\n'
            "cat /work/2026/qrew/sop/sop-update-qguard-proxy-in-qrew-test.md\\n\\n"
            'If the file does not exist, report that clearly.", "role": "km1-tester"}</parameter>\n'
            "</function>"
        )
        result = format_response(text)
        assert len(result) == 2
        assert result[0]["step_name"] == "thought"
        assert "truncated/errored" in result[0]["raw_text"]
        assert result[1]["step_name"] == "action"
        assert result[1]["tool_call"] == "subagent_tool-call_assistant"
        assert result[1]["tool_args"]["role"] == "km1-tester"
        assert "cat /work/2026/qrew/sop" in result[1]["tool_args"]["task"]

    def test_format_response_plain_text_unchanged(self):
        """Verify plain text without function block still falls back to thought."""
        from topsailai.ai_base.llm_control.message import format_response

        result = format_response("just a thought")
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"
        assert "just a thought" in result[0]["raw_text"]


class TestFormatResponseActionWithFinalAnswer:
    """Test suite for action_with_final_answer fixer in topsailai. format."""

    def test_format_response_topsailai_action_and_final_answer(self):
        """Verify final_answer is converted to thought when action exists."""
        from topsailai.ai_base.llm_control.message import format_response

        text = (
            "topsailai.action\n"
            "{\"tool_call\": \"file_tool-read_file\", \"tool_args\": {\"files\": [\"/tmp/1.txt\"]}}\n"
            "topsailai.final_answer\n"
            "I will read the file first."
        )
        result = format_response(text)
        assert len(result) == 2
        assert result[0]["step_name"] == "action"
        assert '"tool_call": "file_tool-read_file"' in result[0]["raw_text"]
        assert '"tool_args": {"files": [\"/tmp/1.txt\"]}' in result[0]["raw_text"]
        assert result[1]["step_name"] == "thought"
        assert "read the file first" in result[1]["raw_text"]

    def test_format_response_topsailai_thought_action_and_final_answer(self):
        """Verify final text is merged into existing thought when action exists."""
        from topsailai.ai_base.llm_control.message import format_response

        text = (
            "topsailai.thought\n"
            "Let me check the file.\n"
            "topsailai.action\n"
            "{\"tool_call\": \"file_tool-read_file\", \"tool_args\": {\"files\": [\"/tmp/1.txt\"]}}\n"
            "topsailai.final_answer\n"
            "I will read the file first."
        )
        result = format_response(text)
        assert len(result) == 2
        assert result[0]["step_name"] == "thought"
        assert "check the file" in result[0]["raw_text"]
        assert "read the file first" in result[0]["raw_text"]
        assert result[1]["step_name"] == "action"
        assert '"tool_call": "file_tool-read_file"' in result[1]["raw_text"]
        assert '"tool_args": {"files": [\"/tmp/1.txt\"]}' in result[1]["raw_text"]


class TestFormatResponseDuplicateConsecutiveSteps:
    """Test suite for duplicate_consecutive_steps fixer in format_response."""

    def test_format_response_topsailai_duplicate_actions_collapsed_by_parser(self):
        """Verify topsailai format parser collapses duplicate action keys.

        The ``topsailai.`` format is parsed into an ``OrderedDict`` keyed by
        ``step_name``, so duplicate ``action`` steps are already collapsed
        before any fixer runs. The deduplication fixer therefore cannot (and
        does not need to) handle this format.
        """
        from topsailai.ai_base.llm_control.message import format_response

        text = (
            "topsailai.thought\n"
            "Let me read the file.\n"
            "topsailai.action\n"
            '{"tool_call": "file_tool-read_file", "tool_args": {"files": ["/tmp/1.txt"]}}\n'
            "topsailai.action\n"
            '{"tool_call": "file_tool-read_file", "tool_args": {"files": ["/tmp/2.txt"]}}'
        )
        result = format_response(text)
        assert len(result) == 2
        assert result[0]["step_name"] == "thought"
        assert result[1]["step_name"] == "action"
        assert '"files": ["/tmp/2.txt"]' in result[1]["raw_text"]

    def test_format_response_duplicate_action_fixer_failure_is_safe(self):
        """Verify an exception in the duplicate fixer does not break format_response_finally."""
        from topsailai.ai_base.llm_control.message import format_response_finally

        response = [
            {"step_name": "action", "tool_call": "file_tool-read_file", "tool_args": {"files": ["/tmp/1.txt"]}},
            {"step_name": "action", "tool_call": "file_tool-read_file", "tool_args": {"files": ["/tmp/1.txt"]}},
        ]
        with patch(
            "topsailai.ai_base.llm_control.llm_mistakes.duplicate_consecutive_steps._remove_consecutive_duplicate_actions",
            side_effect=RuntimeError("boom"),
        ):
            result = format_response_finally(response)

        assert len(result) == 2
        assert result[0]["step_name"] == "action"
        assert result[1]["step_name"] == "action"

class TestDeepseekDsmlToolCalls:
    """Test suite for DeepSeek DSML tool-call parsing fixer."""

    DSML_SAMPLE_PATH = (
        Path(__file__).resolve().parent.parent / "mistakes" / "response" / "deepseek" / "dsml.txt"
    )

    def test_parse_dsml_single_invoke(self):
        """Verify a single invoke block is parsed into one action step."""
        from topsailai.ai_base.llm_control.llm_mistakes.deepseek import _parse_dsml_tool_calls

        text = (
            '<｜DSML｜tool_calls>\n'
            '<｜DSML｜invoke name="file_tool-read_file">\n'
            '<｜DSML｜parameter name="files" string="false">["/tmp/1.txt"]</｜DSML｜parameter>\n'
            '</｜DSML｜invoke>\n'
            '</｜DSML｜tool_calls>'
        )
        result = _parse_dsml_tool_calls(text)
        assert result == [
            {
                "step_name": "action",
                "tool_call": "file_tool-read_file",
                "tool_args": {"files": ["/tmp/1.txt"]},
            },
        ]

    def test_parse_dsml_multiple_invokes(self):
        """Verify multiple invoke blocks produce multiple action steps."""
        from topsailai.ai_base.llm_control.llm_mistakes.deepseek import _parse_dsml_tool_calls

        text = (
            '<｜DSML｜tool_calls>\n'
            '<｜DSML｜invoke name="cmd_tool-exec_cmd">\n'
            '<｜DSML｜parameter name="cmd" string="true">echo hello</｜DSML｜parameter>\n'
            '</｜DSML｜invoke>\n'
            '<｜DSML｜invoke name="file_tool-read_file">\n'
            '<｜DSML｜parameter name="files" string="false">["/tmp/1.txt"]</｜DSML｜parameter>\n'
            '</｜DSML｜invoke>\n'
            '</｜DSML｜tool_calls>'
        )
        result = _parse_dsml_tool_calls(text)
        assert len(result) == 2
        assert result[0]["tool_call"] == "cmd_tool-exec_cmd"
        assert result[0]["tool_args"]["cmd"] == "echo hello"
        assert result[1]["tool_call"] == "file_tool-read_file"
        assert result[1]["tool_args"]["files"] == ["/tmp/1.txt"]

    def test_parse_dsml_leading_text_as_thought(self):
        """Verify leading text before the DSML block is preserved as thought."""
        from topsailai.ai_base.llm_control.llm_mistakes.deepseek import _parse_dsml_tool_calls

        text = (
            'Let me check the logs.\n'
            '<｜DSML｜tool_calls>\n'
            '<｜DSML｜invoke name="cmd_tool-exec_cmd">\n'
            '<｜DSML｜parameter name="cmd" string="true">echo hello</｜DSML｜parameter>\n'
            '</｜DSML｜invoke>\n'
            '</｜DSML｜tool_calls>'
        )
        result = _parse_dsml_tool_calls(text)
        assert len(result) == 2
        assert result[0]["step_name"] == "thought"
        assert result[0]["raw_text"] == "Let me check the logs."
        assert result[1]["step_name"] == "action"

    def test_parse_dsml_string_true_keeps_string(self):
        """Verify string=\"true\" keeps the raw value as a string."""
        from topsailai.ai_base.llm_control.llm_mistakes.deepseek import _parse_dsml_tool_calls

        text = (
            '<｜DSML｜tool_calls>\n'
            '<｜DSML｜invoke name="cmd_tool-exec_cmd">\n'
            '<｜DSML｜parameter name="cmd" string="true">export FOO=bar && echo $FOO</｜DSML｜parameter>\n'
            '</｜DSML｜invoke>\n'
            '</｜DSML｜tool_calls>'
        )
        result = _parse_dsml_tool_calls(text)
        assert result[0]["tool_args"]["cmd"] == "export FOO=bar && echo $FOO"

    def test_parse_dsml_string_false_parses_json(self):
        """Verify string=\"false\" parses the value as JSON."""
        from topsailai.ai_base.llm_control.llm_mistakes.deepseek import _parse_dsml_tool_calls

        text = (
            '<｜DSML｜tool_calls>\n'
            '<｜DSML｜invoke name="cmd_tool-exec_cmd">\n'
            '<｜DSML｜parameter name="cmd" string="true">echo hello</｜DSML｜parameter>\n'
            '<｜DSML｜parameter name="timeout" string="false">30</｜DSML｜parameter>\n'
            '</｜DSML｜invoke>\n'
            '</｜DSML｜tool_calls>'
        )
        result = _parse_dsml_tool_calls(text)
        assert result[0]["tool_args"]["timeout"] == 30
        assert isinstance(result[0]["tool_args"]["timeout"], int)

    def test_parse_dsml_no_block_returns_none(self):
        """Verify None is returned when no DSML block exists."""
        from topsailai.ai_base.llm_control.llm_mistakes.deepseek import _parse_dsml_tool_calls

        assert _parse_dsml_tool_calls("just some text") is None
        assert _parse_dsml_tool_calls('{"step_name": "action"}') is None

    def test_parse_dsml_malformed_returns_none(self):
        """Verify None is returned for malformed DSML blocks."""
        from topsailai.ai_base.llm_control.llm_mistakes.deepseek import _parse_dsml_tool_calls

        assert _parse_dsml_tool_calls('<｜DSML｜tool_calls>') is None
        assert _parse_dsml_tool_calls(
            '<｜DSML｜tool_calls>\n'
            '<｜DSML｜invoke name="foo">\n'
            '<｜DSML｜parameter name="bar">baz</｜DSML｜parameter>\n'
        ) is None
        assert _parse_dsml_tool_calls(
            '<｜DSML｜tool_call>\n'
            '<｜DSML｜invoke name="foo">\n'
            '</｜DSML｜tool_call>'
        ) is None

    def test_format_response_deepseek_dsml_sample(self, monkeypatch):
        """Verify the real DeepSeek sample is parsed into action steps."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.setenv("OPENAI_MODEL", "deepseek-chat")

        text = self.DSML_SAMPLE_PATH.read_text(encoding="utf-8")
        result = format_response(text)

        assert isinstance(result, list)
        assert len(result) == 5
        for item in result:
            assert item["step_name"] == "action"
            assert item["tool_call"] == "cmd_tool-exec_cmd"
            assert "cmd" in item["tool_args"]
            assert isinstance(item["tool_args"]["cmd"], str)
            assert item["tool_args"]["timeout"] == 30


    def test_format_response_deepseek_malformed_dsml_sample(self, monkeypatch):
        """Verify malformed singular DSML wrapper is recovered into one action."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.setenv("OPENAI_MODEL", "deepseek-chat")

        text = self.DSML_SAMPLE_PATH.with_name("dsml-2.txt").read_text(encoding="utf-8")
        result = format_response(text)

        assert result == [{
            "step_name": "action",
            "tool_call": "file_tool-read_file",
            "tool_args": {"file_path": "/tmp/test.txt"},
        }]

    def test_format_response_deepseek_singular_invoke_wrapper(self, monkeypatch):
        """Verify a singular invoke wrapper is recovered into one action."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.setenv("OPENAI_MODEL", "deepseek-chat")

        text = self.DSML_SAMPLE_PATH.with_name("dsml-3.txt").read_text(encoding="utf-8")
        result = format_response(text)

        assert result == [{
            "step_name": "action",
            "tool_call": "cmd_tool-exec_cmd",
            "tool_args": {"cmd": "echo ok"},
        }]

    def test_format_response_deepseek_mixed_invoke_wrapper(self, monkeypatch):
        """Verify a singular-open plural-close invoke wrapper is recovered."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.setenv("OPENAI_MODEL", "deepseek-chat")

        text = self.DSML_SAMPLE_PATH.with_name("dsml-4.txt").read_text(encoding="utf-8")
        result = format_response(text)

        assert result == [{
            "step_name": "action",
            "tool_call": "cmd_tool-exec_cmd",
            "tool_args": {"cmd": "echo ok"},
        }]

    def test_format_response_deepseek_malformed_wrapper_with_leading_text(self, monkeypatch):
        """Verify text before a singular DSML wrapper is preserved as thought."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.setenv("OPENAI_MODEL", "deepseek-chat")

        text = self.DSML_SAMPLE_PATH.with_name("dsml-5.txt").read_text(encoding="utf-8")
        result = format_response(text)

        assert result == [
            {"step_name": "thought", "raw_text": "hello-raw-text"},
            {
                "step_name": "action",
                "tool_call": "cmd_tool-exec_cmd",
                "tool_args": {"cmd": "echo ok"},
            },
        ]

    def test_format_response_deepseek_requires_model(self, monkeypatch):
        """Verify DSML is not parsed when the model is not DeepSeek."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.setenv("OPENAI_MODEL", "kimi-k2.5")

        text = (
            '<｜DSML｜tool_calls>\n'
            '<｜DSML｜invoke name="cmd_tool-exec_cmd">\n'
            '<｜DSML｜parameter name="cmd" string="true">echo hello</｜DSML｜parameter>\n'
            '</｜DSML｜invoke>\n'
            '</｜DSML｜tool_calls>'
        )
        result = format_response(text)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"
        assert "DSML" in result[0]["raw_text"]


class TestFormatResponseSingleLineNoFinalAnswerConversion:
    """Test suite for the single-line guard on final-answer conversion.

    When the response raw content is a single line (no newline), the
    'change step to final answer due to found action count' conversion must
    NOT happen. Only multi-line responses are converted.
    """

    # ---- format_response_finally (list with single thought item) ----

    def test_finally_single_line_with_action_keeps_thought(self):
        """Single-line thought with existing action stays thought."""
        from topsailai.ai_base.llm_control.message import format_response_finally

        response = [{"step_name": "thought", "raw_text": "done"}]
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        result = format_response_finally(response, rsp_obj=None, messages=messages)
        assert result[0]["step_name"] == "thought"

    def test_finally_multi_line_with_action_converts_to_final(self, monkeypatch):
        """Multi-line thought with existing action converts to final_answer when enabled."""
        from topsailai.ai_base.llm_control.message import format_response_finally

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "1")
        response = [{"step_name": "thought", "raw_text": "first line\nsecond line"}]
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        result = format_response_finally(response, rsp_obj=None, messages=messages)
        assert result[0]["step_name"] == "final_answer"

    def test_finally_single_line_without_action_keeps_thought(self):
        """Single-line thought without action stays thought."""
        from topsailai.ai_base.llm_control.message import format_response_finally

        response = [{"step_name": "thought", "raw_text": "done"}]
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]
        result = format_response_finally(response, rsp_obj=None, messages=messages)
        assert result[0]["step_name"] == "thought"

    def test_finally_multi_line_without_action_keeps_thought(self):
        """Multi-line thought without action stays thought."""
        from topsailai.ai_base.llm_control.message import format_response_finally

        response = [{"step_name": "thought", "raw_text": "first line\nsecond line"}]
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]
        result = format_response_finally(response, rsp_obj=None, messages=messages)
        assert result[0]["step_name"] == "thought"

    # ---- format_response (plain text string) ----

    def test_format_single_line_with_action_keeps_thought(self):
        """Single-line plain text with existing action stays thought."""
        from topsailai.ai_base.llm_control.message import format_response

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        result = format_response("done", rsp_obj=None, messages=messages)
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"
        assert "done" in result[0]["raw_text"]

    def test_format_multi_line_with_action_converts_to_final(self, monkeypatch):
        """Multi-line plain text with existing action converts to final_answer when enabled."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "1")
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        result = format_response("first line\nsecond line", rsp_obj=None, messages=messages)
        assert len(result) == 1
        assert result[0]["step_name"] == "final_answer"

    def test_format_single_line_without_action_keeps_thought(self):
        """Single-line plain text without action stays thought."""
        from topsailai.ai_base.llm_control.message import format_response

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]
        result = format_response("done", rsp_obj=None, messages=messages)
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"

    def test_format_multi_line_without_action_keeps_thought(self):
        """Multi-line plain text without action stays thought."""
        from topsailai.ai_base.llm_control.message import format_response

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]
        result = format_response("first line\nsecond line", rsp_obj=None, messages=messages)
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"

    # ---- TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED switch ----

    def test_finally_env_disabled_keeps_thought(self, monkeypatch):
        """When the convert-thought-to-final switch is off, multi-line thought with action stays thought."""
        from topsailai.ai_base.llm_control.message import format_response_finally

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "0")
        response = [{"step_name": "thought", "raw_text": "first line\nsecond line"}]
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        result = format_response_finally(response, rsp_obj=None, messages=messages)
        assert result[0]["step_name"] == "thought"

    def test_finally_env_enabled_converts_to_final(self, monkeypatch):
        """When the convert-thought-to-final switch is on, multi-line thought with action converts to final_answer."""
        from topsailai.ai_base.llm_control.message import format_response_finally

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "1")
        response = [{"step_name": "thought", "raw_text": "first line\nsecond line"}]
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        result = format_response_finally(response, rsp_obj=None, messages=messages)
        assert result[0]["step_name"] == "final_answer"

    # ---- format_response (plain string path) switch coverage ----

    def test_format_env_disabled_keeps_thought(self, monkeypatch):
        """When the convert-thought-to-final switch is off, multi-line thought with action stays thought."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "0")
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        result = format_response("first line\nsecond line", rsp_obj=None, messages=messages)
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"

    def test_format_env_enabled_converts_to_final(self, monkeypatch):
        """When the convert-thought-to-final switch is on, multi-line thought with action converts to final_answer."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "1")
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        result = format_response("first line\nsecond line", rsp_obj=None, messages=messages)
        assert len(result) == 1
        assert result[0]["step_name"] == "final_answer"

    def test_format_unset_defaults_to_keep_thought(self, monkeypatch):
        """When the convert-thought-to-final switch is unset, it defaults to disabled and keeps thought."""
        from topsailai.ai_base.llm_control.message import format_response

        monkeypatch.delenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", raising=False)
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        result = format_response("first line\nsecond line", rsp_obj=None, messages=messages)
        assert len(result) == 1
        assert result[0]["step_name"] == "thought"


class TestMaybeConvertThoughtToFinal:
    """Unit tests for the standalone maybe_convert_thought_to_final helper."""

    def test_maybe_convert_disabled_keeps_thought(self, monkeypatch):
        from topsailai.ai_base.llm_control.message import maybe_convert_thought_to_final

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "0")
        item = {"step_name": "thought", "raw_text": "first line\nsecond line"}
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        changed = maybe_convert_thought_to_final(item, messages)
        assert changed is False
        assert item["step_name"] == "thought"

    def test_maybe_convert_enabled_converts_to_final(self, monkeypatch):
        from topsailai.ai_base.llm_control.message import maybe_convert_thought_to_final

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "1")
        item = {"step_name": "thought", "raw_text": "first line\nsecond line"}
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        changed = maybe_convert_thought_to_final(item, messages)
        assert changed is True
        assert item["step_name"] == "final_answer"

    def test_maybe_convert_unset_defaults_to_disabled(self, monkeypatch):
        from topsailai.ai_base.llm_control.message import maybe_convert_thought_to_final

        monkeypatch.delenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", raising=False)
        item = {"step_name": "thought", "raw_text": "first line\nsecond line"}
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        changed = maybe_convert_thought_to_final(item, messages)
        assert changed is False
        assert item["step_name"] == "thought"

    def test_maybe_convert_single_line_no_action_returns_false(self, monkeypatch):
        from topsailai.ai_base.llm_control.message import maybe_convert_thought_to_final

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "1")
        # single-line raw_text -> no newline -> not converted
        item = {"step_name": "thought", "raw_text": "single line"}
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        changed = maybe_convert_thought_to_final(item, messages)
        assert changed is False
        assert item["step_name"] == "thought"



class TestShouldConvertThoughtToFinal:
    """Unit tests for the shared should_convert_thought_to_final helper."""

    def test_disabled_env_returns_false(self, monkeypatch):
        from topsailai.ai_base.llm_control.message import should_convert_thought_to_final

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "0")
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        converted, reason = should_convert_thought_to_final("first line\nsecond line", messages)
        assert converted is False and reason == ""

    def test_enabled_with_multiline_and_action_returns_true(self, monkeypatch):
        from topsailai.ai_base.llm_control.message import should_convert_thought_to_final

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "1")
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        converted, reason = should_convert_thought_to_final("first line\nsecond line", messages)
        assert converted is True
        assert "found action count [1]" in reason

    def test_unset_defaults_to_false(self, monkeypatch):
        from topsailai.ai_base.llm_control.message import should_convert_thought_to_final

        monkeypatch.delenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", raising=False)
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        converted, reason = should_convert_thought_to_final("first line\nsecond line", messages)
        assert converted is False and reason == ""

    def test_enabled_single_line_returns_false(self, monkeypatch):
        from topsailai.ai_base.llm_control.message import should_convert_thought_to_final

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "1")
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]
        # single-line text -> no newline -> not converted
        converted, reason = should_convert_thought_to_final("single line", messages)
        assert converted is False and reason == ""

    def test_enabled_no_action_returns_false(self, monkeypatch):
        from topsailai.ai_base.llm_control.message import should_convert_thought_to_final

        monkeypatch.setenv("TOPSAILAI_CONVERT_THOUGHT_TO_FINAL_ENABLED", "1")
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]
        # no prior tool action -> not converted even with multi-line text
        converted, reason = should_convert_thought_to_final("first line\nsecond line", messages)
        assert converted is False and reason == ""
class TestLlmMistakeWarningSuppressionNativeToolCalls:
    """Verify no mistake warnings are logged when the response arrives via native tool_calls."""

    @staticmethod
    def _native_rsp():
        """Build a fake rsp object whose message carries native tool_calls."""
        from openai.types.chat import ChatCompletionMessage

        msg = MagicMock(spec=ChatCompletionMessage)
        msg.tool_calls = [MagicMock()]
        return msg

    def test_fix_llm_mistakes_native_no_step_name_warning(self):
        """fix_llm_mistakes must not warn 'missing step_name=action' for native tool_calls."""
        from topsailai.ai_base.llm_control.message import fix_llm_mistakes

        with patch("topsailai.ai_base.llm_control.message.print_warning") as mpw:
            out = fix_llm_mistakes(
                [{"step_name": "thought"}],
                rsp_obj=self._native_rsp(),
            )
        # behavioral contract preserved: missing action is still appended
        assert out[-1] == {"step_name": "action"}
        mpw.assert_not_called()

    def test_format_response_native_no_only_thought_warning(self):
        """format_response must not warn 'maybe only thought' for native tool_calls."""
        from topsailai.ai_base.llm_control.message import format_response

        with patch("topsailai.ai_base.llm_control.message.print_warning") as mpw, \
             patch("topsailai.ai_base.llm_control.message.hook_execute",
                   side_effect=lambda *a, **k: None), \
             patch("topsailai.ai_base.llm_control.message.should_convert_thought_to_final",
                   return_value=(False, "")):
            format_response("just some text", rsp_obj=self._native_rsp(), messages=[])
        mpw.assert_not_called()

    def test_format_response_non_native_still_warns_only_thought(self):
        """Non-native responses must still emit the 'maybe only thought' warning."""
        from topsailai.ai_base.llm_control.message import format_response

        with patch("topsailai.ai_base.llm_control.message.print_warning") as mpw, \
             patch("topsailai.ai_base.llm_control.message.hook_execute",
                   side_effect=lambda *a, **k: None), \
             patch("topsailai.ai_base.llm_control.message.should_convert_thought_to_final",
                   return_value=(False, "")):
            format_response("just some text", rsp_obj=None, messages=[])
        mpw.assert_called_once()