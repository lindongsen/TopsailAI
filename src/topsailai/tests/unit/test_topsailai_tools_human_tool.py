"""
Unit tests for tools/human_tool.py

Author: DawsonLin
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, '/TopsailAI/src/topsailai')

from topsailai.tools import human_tool


class TestModuleConstants(unittest.TestCase):
    """Test module-level constants and registration."""

    def test_tools_dict_registers_ask_decision(self):
        """TOOLS must register ask_decision under its tool name."""
        self.assertIn('ask_decision', human_tool.TOOLS)
        self.assertEqual(human_tool.TOOLS['ask_decision'], human_tool.ask_decision)

    def test_no_hand_written_tools_info(self):
        """ask_decision must not declare a hand-written TOOLS_INFO schema."""
        self.assertFalse(hasattr(human_tool, 'TOOLS_INFO'))

    def test_flag_tool_enabled_is_true(self):
        """FLAG_TOOL_ENABLED must be boolean True."""
        self.assertIsInstance(human_tool.FLAG_TOOL_ENABLED, bool)
        self.assertTrue(human_tool.FLAG_TOOL_ENABLED)

    def test_prompt_describes_blocked_task_usage(self):
        """PROMPT must describe blocked-task decision usage."""
        self.assertIsInstance(human_tool.PROMPT, str)
        self.assertIn('blocked', human_tool.PROMPT.lower())
        self.assertIn('invalid_request', human_tool.PROMPT)

    def test_registered_contract_documents_always_free_text(self):
        """The tool contract documents always-accepted free-text answers."""
        self.assertIn('always accepted', human_tool.ask_decision.__doc__)
        self.assertIn('always accepted', human_tool.PROMPT)
        self.assertNotIn('invalid_answer', human_tool.ask_decision.__doc__)
        self.assertNotIn('invalid_answer', human_tool.PROMPT)


class TestConfigHelpers(unittest.TestCase):
    """Test environment-variable-driven configuration helpers."""

    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_TIMEOUT': '15'}, clear=False)
    def test_default_timeout_from_env(self):
        """Positive env timeout is returned as an integer."""
        self.assertEqual(human_tool._get_default_timeout(), 15)

    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_TIMEOUT': '0'}, clear=False)
    def test_default_timeout_zero_means_infinite(self):
        """Zero or unset means infinite (None)."""
        self.assertIsNone(human_tool._get_default_timeout())

    @patch.dict(os.environ, {}, clear=True)
    def test_default_timeout_unset_returns_none(self):
        """Missing variable yields None (infinite)."""
        self.assertIsNone(human_tool._get_default_timeout())

    def test_default_timeout_accepts_integer_valued_text(self):
        """Integer-valued decimal text is normalized to integer seconds."""
        with patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_TIMEOUT': '5.0'}, clear=False):
            self.assertEqual(human_tool._get_default_timeout(), 5)

    def test_default_timeout_invalid_values_fall_back_to_infinite(self):
        """Fractional, nonnumeric, and non-finite env values fall back to zero semantics."""
        for value in ('0.5', 'abc', 'NaN', '+inf', 'inf', '-inf'):
            with self.subTest(value=value):
                with patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_TIMEOUT': value}, clear=False):
                    self.assertIsNone(human_tool._get_default_timeout())


    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_MAX_ANSWER_LENGTH': '12345'}, clear=False)
    def test_max_answer_length_from_env(self):
        """Max answer length parsed from env."""
        self.assertEqual(human_tool._get_max_answer_length(), 12345)

    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_PROMPT_TEMPLATE': '{question} :: {options}'}, clear=False)
    def test_prompt_template_read_from_env(self):
        """Prompt template read and stripped from env."""
        self.assertEqual(human_tool._get_prompt_template(), '{question} :: {options}')


class TestAnswerNormalization(unittest.TestCase):
    """Test answer normalization and option matching helpers."""

    def test_normalize_answer_strips_whitespace(self):
        """Whitespace is stripped from raw answers."""
        self.assertEqual(human_tool._normalize_answer('  hello  '), 'hello')

    def test_match_option_by_index(self):
        """Numeric index selects the corresponding option."""
        opts = ['alpha', 'beta', 'gamma']
        self.assertEqual(human_tool._match_option('1', opts), 1)
        self.assertEqual(human_tool._match_option('0', opts), 0)

    def test_match_option_out_of_range_returns_minus_one(self):
        """Out-of-range index yields -1."""
        opts = ['alpha', 'beta']
        self.assertEqual(human_tool._match_option('5', opts), -1)

    def test_match_option_by_text_case_insensitive(self):
        """Verbatim text match is case-insensitive."""
        opts = ['Alpha', 'Beta']
        self.assertEqual(human_tool._match_option('alpha', opts), 0)
        self.assertEqual(human_tool._match_option('BETA', opts), 1)

    def test_match_option_no_options_returns_minus_one(self):
        """No options always returns -1."""
        self.assertEqual(human_tool._match_option('anything', None), -1)

    def test_validate_and_resolve_default_fallback_on_empty(self):
        """Empty answer falls back to default when provided."""
        ans, idx = human_tool._validate_and_resolve('   ', ['a'], 'fallback')
        self.assertEqual(ans, 'fallback')
        self.assertEqual(idx, -1)

    def test_validate_and_resolve_valid_option(self):
        """Valid option selection resolves to its text and index."""
        ans, idx = human_tool._validate_and_resolve('2', ['x', 'y', 'z'], None)
        self.assertEqual(ans, 'z')
        self.assertEqual(idx, 2)

    def test_validate_and_resolve_unlisted_text_is_accepted(self):
        """Unlisted text is always accepted as a custom answer."""
        ans, idx = human_tool._validate_and_resolve('bogus', ['x', 'y'], None)
        self.assertEqual(ans, 'bogus')
        self.assertEqual(idx, -1)


    def test_validate_and_resolve_free_text_allowed(self):
        """Free-text answer accepted even when options exist."""
        ans, idx = human_tool._validate_and_resolve('custom', ['x', 'y'], None)
        self.assertEqual(ans, 'custom')
        self.assertEqual(idx, -1)


class TestPromptRendering(unittest.TestCase):
    """Test option-menu rendering."""

    @patch('topsailai.tools.human_tool._get_prompt_template', return_value='')
    def test_options_prompt_always_offers_own_opinion(self, _mock_template):
        """An options prompt always advertises free-text input."""
        prompt = human_tool._build_prompt('q', ['a', 'b'], None)
        self.assertIn('own opinion', prompt)
        self.assertIn('[0..1]', prompt)
        self.assertIn("'/cancel'", prompt)


    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: 'custom', None))
    def test_removed_environment_setting_has_no_effect(self, _mock_resolve):
        """The removed environment setting cannot disable free-text answers."""
        with patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_ALLOW_FREE_TEXT': '0'}, clear=False):
            result = human_tool.ask_decision('q', options=['Alpha'])
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'custom')
        self.assertEqual(result['option_index'], -1)



class TestAskDecisionDegradation(unittest.TestCase):
    """Test unavailable/cancelled/timeout paths and default fallback."""

    @patch('topsailai.tools.human_tool._is_sub_agent_context', return_value=True)
    def test_sub_agent_context_returns_unavailable(self, mock_sub):
        """Sub-agent context must not prompt; returns unavailable with default."""
        result = human_tool.ask_decision('question?', default='fallback')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['answer'], 'fallback')
        self.assertEqual(result['option_index'], -1)

    @patch('topsailai.tools.human_tool._has_usable_input_source', return_value=False)
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(None, None))
    def test_no_input_source_returns_unavailable(self, mock_resolve, mock_src):
        """No usable input source yields unavailable immediately."""
        result = human_tool.ask_decision('question?')
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['answer'])

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: None, None))
    def test_timeout_when_input_returns_none(self, mock_resolve, mock_build):
        """Input returning None is treated as timeout with default fallback."""
        result = human_tool.ask_decision('q', default='dflt')
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['answer'], 'dflt')

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(MagicMock(side_effect=KeyboardInterrupt), None))
    def test_keyboard_interrupt_is_cancelled(self, mock_resolve, mock_build):
        """Ctrl+C maps to cancelled status with default fallback."""
        result = human_tool.ask_decision('q', default='dflt')
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['answer'], 'dflt')

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(MagicMock(side_effect=EOFError), None))
    def test_eof_is_cancelled(self, mock_resolve, mock_build):
        """EOF maps to cancelled status with default fallback."""
        result = human_tool.ask_decision('q', default='dflt')
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['answer'], 'dflt')

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: '/cancel', None))
    def test_slash_cancel_is_cancelled(self, mock_resolve, mock_build):
        """The explicit '/cancel' command maps to cancelled status."""
        result = human_tool.ask_decision('q', default='dflt')
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['answer'], 'dflt')


class TestAskDecisionAnswered(unittest.TestCase):
    """Test successful answered paths."""

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: 'my answer', None))
    def test_free_text_answer(self, mock_resolve, mock_build):
        """Free-text input yields answered status with the text."""
        result = human_tool.ask_decision('q')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'my answer')
        self.assertEqual(result['option_index'], -1)
        self.assertIsInstance(result['asked_at'], str)
        self.assertIsInstance(result['elapsed'], int)
        self.assertNotIn('asked_at_ms', result)
        self.assertNotIn('elapsed_ms', result)

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: '   ', None))
    def test_blank_answer_without_default_is_answered_empty(self, _mock_resolve, _mock_build):
        """A blank reply without a default remains an answered empty string."""
        result = human_tool.ask_decision('q')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], '')
        self.assertEqual(result['option_index'], -1)

    @patch('topsailai.tools.human_tool.datetime')
    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: 'answer', None))
    @patch('topsailai.tools.human_tool.time.time', side_effect=[1700000000.9, 1700000002.8])
    def test_result_timing_uses_local_iso_seconds(
        self, _mock_time, _mock_resolve, _mock_build, mock_datetime
    ):
        """Decision timing uses local ISO time and integer elapsed seconds."""
        mock_local_time = mock_datetime.fromtimestamp.return_value
        mock_local_time.isoformat.return_value = '2026-08-14T16:52:00'
        result = human_tool.ask_decision('q')
        mock_datetime.fromtimestamp.assert_called_once_with(1700000000.9)
        mock_local_time.isoformat.assert_called_once_with(timespec='seconds')
        self.assertEqual(result['asked_at'], '2026-08-14T16:52:00')
        self.assertEqual(result['elapsed'], 1)

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(None, lambda p: 'plain answer'))
    def test_plain_thread_local_input_fallback(self, mock_resolve, mock_build):
        """Plain thread-local input is used when no timeout variant exists."""
        result = human_tool.ask_decision('q')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'plain answer')

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: '2', None))
    def test_option_selection_by_index(self, mock_resolve, mock_build):
        """Selecting an option by index returns its text and index."""
        result = human_tool.ask_decision('q', options=['a', 'b', 'c'])
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'c')
        self.assertEqual(result['option_index'], 2)

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: 'beta', None))
    def test_option_selection_by_text(self, mock_resolve, mock_build):
        """Selecting an option by verbatim text works case-insensitively."""
        result = human_tool.ask_decision('q', options=['Alpha', 'Beta'])
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'Beta')
        self.assertEqual(result['option_index'], 1)

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs',
           return_value=(lambda p, t: 'Use a staged rollout', None))
    def test_non_option_input_is_direct_custom_opinion(self, _mock_resolve, _mock_build):
        """Any non-option input is returned directly as the user's opinion."""
        result = human_tool.ask_decision('q', options=['Alpha', 'Beta'])
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'Use a staged rollout')
        self.assertEqual(result['option_index'], -1)

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs',
           return_value=(lambda p, t: 'cancel', None))
    def test_plain_cancel_is_custom_content(self, _mock_resolve, _mock_build):
        """Plain 'cancel' is content because only '/cancel' cancels."""
        result = human_tool.ask_decision('q', options=['Alpha', 'Beta'])
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'cancel')
        self.assertEqual(result['option_index'], -1)



class TestOptionValidationLoop(unittest.TestCase):
    """Test option shortcuts and the removed compatibility input."""

    def test_removed_integer_zero_argument_raises_type_error(self):
        """The removed parameter is not accepted for an integer zero value."""
        with self.assertRaisesRegex(TypeError, "allow_free_text"):
            human_tool.ask_decision('q', options=['x', 'y'], allow_free_text=0)

    def test_removed_string_zero_argument_raises_type_error(self):
        """The removed parameter is not accepted for a string zero value."""
        with self.assertRaisesRegex(TypeError, "allow_free_text"):
            human_tool.ask_decision('q', options=['x', 'y'], allow_free_text='0')

    def test_removed_arbitrary_argument_raises_type_error(self):
        """The removed parameter is not accepted for an arbitrary legacy value."""
        with self.assertRaisesRegex(TypeError, "allow_free_text"):
            human_tool.ask_decision('q', options=['x'], allow_free_text={'old': True})

    @patch('topsailai.tools.human_tool._get_max_answer_length', return_value=5)
    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: 'a very long answer here', None))
    def test_long_answer_truncated(self, mock_resolve, mock_build, mock_len):
        """Answers exceeding max length are truncated via truncate_text."""
        result = human_tool.ask_decision('q')
        self.assertEqual(result['status'], 'answered')
        self.assertNotEqual(result['answer'], 'a very long answer here')
        self.assertIn('truncate', result['answer'].lower())

    def test_invalid_question_returns_invalid_request(self):
        """Empty question returns invalid_request with a reason."""
        result = human_tool.ask_decision('   ', default='dflt')
        self.assertEqual(result['status'], 'invalid_request')
        self.assertEqual(result['reason'], 'invalid_question')
        self.assertEqual(result['answer'], 'dflt')
        self.assertEqual(result['option_index'], -1)

    def test_non_list_options_returns_invalid_request(self):
        """Non-list options return invalid_request with a reason."""
        result = human_tool.ask_decision('q', options='not-a-list', default='dflt')
        self.assertEqual(result['status'], 'invalid_request')
        self.assertEqual(result['reason'], 'invalid_options')
        self.assertEqual(result['answer'], 'dflt')

    def test_non_string_option_returns_invalid_request(self):
        """Every option must be a string."""
        result = human_tool.ask_decision('q', options=['valid', 2])
        self.assertEqual(result['status'], 'invalid_request')
        self.assertEqual(result['reason'], 'invalid_options')

    def test_json_array_string_options_are_parsed(self):
        """A stringified options array is parsed instead of rejected."""
        self.assertEqual(human_tool._resolve_options('["a", "b"]'), (['a', 'b'], None))

    def test_json_array_string_options_drive_option_selection(self):
        """Stringified options still allow index selection without unavailable."""
        with patch('topsailai.tools.human_tool._build_prompt', return_value='prompt'), \
             patch('topsailai.tools.human_tool._resolve_input_funcs',
                   return_value=(lambda p, t: '1', None)):
            result = human_tool.ask_decision(
                'q', options='["a", "b"]', timeout_seconds='60'
            )
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'b')
        self.assertEqual(result['option_index'], 1)

    def test_json_array_string_options_are_rendered_in_prompt(self):
        """Parsed stringified options are rendered into the prompt."""
        observed = []
        with patch('topsailai.tools.human_tool._resolve_input_funcs',
                   return_value=(lambda p, t: observed.append(p) or 'a', None)):
            result = human_tool.ask_decision('q', options='["Alpha", "Beta"]')
        self.assertEqual(result['status'], 'answered')
        self.assertIn('Alpha', observed[0])
        self.assertIn('Beta', observed[0])

    def test_malformed_options_string_returns_invalid_request(self):
        """A non-JSON options string yields invalid_request, never unavailable."""
        for value in ('not-a-list', '["a"', '{"a":1}', '[1, 2]'):
            result = human_tool.ask_decision('q', options=value, default='dflt')
            self.assertEqual(result['status'], 'invalid_request')
            self.assertEqual(result['reason'], 'invalid_options')
            self.assertEqual(result['answer'], 'dflt')

    def test_empty_options_string_means_not_provided(self):
        """Empty or blank options string means no options were provided."""
        for value in (None, '', '   '):
            self.assertEqual(human_tool._resolve_options(value), (None, None))

    def test_non_string_container_options_returns_invalid_request(self):
        """Non-list containers are rejected with a machine-readable reason."""
        for value in ({'a': 1}, ('a', 'b'), 3):
            self.assertEqual(human_tool._resolve_options(value), (None, 'invalid_options'))

    def test_timeout_reaches_input_safely(self):
        """Timeout coercion remains active while custom free text is accepted."""
        observed = []
        with patch('topsailai.tools.human_tool._resolve_input_funcs',
                   return_value=(lambda p, t: observed.append((p, t)) or 'free text', None)):
            result = human_tool.ask_decision(
                'q', options=['a', 'b'], timeout_seconds='60'
            )
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'free text')
        self.assertIn('or your own opinion', observed[0][0])
        self.assertEqual(observed[0][1], 60)


    def test_integer_timeout_values_are_normalized(self):
        """Native integers and integer-valued text or floats become integers."""
        for value, expected in ((5, 5), ('5', 5), (' 5 ', 5), (5.0, 5), ('5.0', 5), ('1e2', 100)):
            self.assertEqual(human_tool._resolve_timeout_seconds(value), (expected, None))

    def test_non_positive_timeout_values_mean_infinite_wait(self):
        """Zero and negative integer values normalize to an infinite wait."""
        for value in (0, -1, '0', '-1', -1.0):
            self.assertEqual(human_tool._resolve_timeout_seconds(value), (None, None))

    def test_invalid_timeout_values_return_invalid_request(self):
        """Fractional, empty, nonnumeric, non-finite, and boolean timeouts are rejected."""
        for value in (0.5, '0.5', 'abc', '', 'NaN', '+inf', 'inf', '-inf', True, False):
            result = human_tool.ask_decision('q', timeout_seconds=value)
            self.assertEqual(result['status'], 'invalid_request')
            self.assertEqual(result['reason'], 'invalid_timeout_seconds')

    @patch('topsailai.tools.human_tool._resolve_input_funcs')
    def test_string_timeout_reaches_input_as_parsed_integer(self, mock_resolve):
        """ask_decision passes parsed integer text to the runtime callback."""
        observed = []
        mock_resolve.return_value = (lambda _prompt, timeout: observed.append(timeout) or 'yes', None)
        result = human_tool.ask_decision('q', timeout_seconds='5.0')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(observed, [5])

    @patch('topsailai.tools.human_tool.sys.stdin')
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: 'yes', None))
    def test_runtime_input_is_used_without_tty(self, _mock_resolve, mock_stdin):
        """A runtime input callback remains usable when stdin is not a TTY."""
        mock_stdin.isatty.return_value = False
        result = human_tool.ask_decision('q')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'yes')

    def test_non_string_default_returns_invalid_request(self):
        """Default fallback must be a string when provided."""
        result = human_tool.ask_decision('q', default=3)
        self.assertEqual(result['status'], 'invalid_request')
        self.assertEqual(result['reason'], 'invalid_default')
        self.assertEqual(result['answer'], 3)


class TestTimeoutEnforcement(unittest.TestCase):
    """Verify positive effective_timeout is enforced on non-with_timeout branches."""

    @patch('topsailai.tools.human_tool._read_with_timeout', return_value=None)
    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    def test_plain_branch_passes_positive_integer_timeout(self, mock_build, mock_read):
        """Plain thread-local input passes the integer deadline to the wait helper."""
        reader = MagicMock()
        with patch('topsailai.tools.human_tool._resolve_input_funcs',
                   return_value=(None, reader)):
            result = human_tool.ask_decision('q', default='dflt', timeout_seconds=1)
        mock_read.assert_called_once_with(reader, 1, 'prompt')
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['answer'], 'dflt')

    @patch('topsailai.tools.human_tool._read_with_timeout', return_value=None)
    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._has_usable_input_source', return_value=True)
    def test_input_fallback_passes_positive_integer_timeout(self, mock_src, mock_build, mock_read):
        """Builtin input fallback passes the integer deadline to the wait helper."""
        with patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(None, None)):
            result = human_tool.ask_decision('q', default='dflt', timeout_seconds=1)
        mock_read.assert_called_once_with(input, 1, 'prompt')
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['answer'], 'dflt')




if __name__ == '__main__':
    unittest.main()


class TestDocumentedInputHelpers(unittest.TestCase):
    """Direct tests for documented input and option-rendering helpers."""

    def test_read_with_timeout_reads_synchronously_without_deadline(self):
        """Falsy deadlines call the reader directly with its arguments."""
        reader = MagicMock(return_value="answer")
        self.assertEqual(human_tool._read_with_timeout(reader, None, "prompt"), "answer")
        reader.assert_called_once_with("prompt")

    def test_read_with_timeout_returns_completed_thread_result(self):
        """A reader that completes before its deadline returns its value."""
        self.assertEqual(human_tool._read_with_timeout(lambda: "answer", 1), "answer")

    def test_read_with_timeout_returns_none_when_deadline_expires(self):
        """A blocked daemon reader yields None when its deadline expires."""
        import threading

        blocker = threading.Event()
        self.assertIsNone(human_tool._read_with_timeout(blocker.wait, 0.01))

    def test_read_with_timeout_propagates_reader_exception(self):
        """Exceptions raised by a completed reader reach the caller."""
        def fail():
            raise RuntimeError("reader failed")

        with self.assertRaisesRegex(RuntimeError, "reader failed"):
            human_tool._read_with_timeout(fail, 1)

    def test_render_options_numbers_entries_and_handles_empty_list(self):
        """Options use zero-based menu labels and empty input renders empty text."""
        self.assertEqual(human_tool._render_options(["yes", "no"]), "  0) yes\n  1) no")
        self.assertEqual(human_tool._render_options([]), "")
