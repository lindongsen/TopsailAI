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

    def test_tools_info_defines_native_argument_types(self):
        """TOOLS_INFO must constrain native ask_decision arguments."""
        parameters = human_tool.TOOLS_INFO['ask_decision']['function']['parameters']
        properties = parameters['properties']
        self.assertEqual(parameters['required'], ['question'])
        self.assertEqual(properties['question']['type'], 'string')
        self.assertEqual(properties['options']['type'], ['array', 'null'])
        self.assertEqual(properties['options']['items']['type'], 'string')
        self.assertEqual(properties['allow_free_text']['type'], ['integer', 'null'])
        self.assertNotIn('boolean', properties['allow_free_text']['type'])
        self.assertNotIn('string', properties['allow_free_text']['type'])
        self.assertEqual(properties['timeout_seconds']['type'], ['number', 'null'])

    def test_flag_tool_enabled_is_true(self):
        """FLAG_TOOL_ENABLED must be boolean True."""
        self.assertIsInstance(human_tool.FLAG_TOOL_ENABLED, bool)
        self.assertTrue(human_tool.FLAG_TOOL_ENABLED)

    def test_prompt_describes_blocked_task_usage(self):
        """PROMPT must describe blocked-task decision usage."""
        self.assertIsInstance(human_tool.PROMPT, str)
        self.assertIn('blocked', human_tool.PROMPT.lower())
        self.assertIn('invalid_request', human_tool.PROMPT)

class TestConfigHelpers(unittest.TestCase):
    """Test environment-variable-driven configuration helpers."""

    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_TIMEOUT': '15'}, clear=False)
    def test_default_timeout_from_env(self):
        """Positive env timeout is returned as float."""
        self.assertEqual(human_tool._get_default_timeout(), 15.0)

    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_TIMEOUT': '0'}, clear=False)
    def test_default_timeout_zero_means_infinite(self):
        """Zero or unset means infinite (None)."""
        self.assertIsNone(human_tool._get_default_timeout())

    @patch.dict(os.environ, {}, clear=True)
    def test_default_timeout_unset_returns_none(self):
        """Missing variable yields None (infinite)."""
        self.assertIsNone(human_tool._get_default_timeout())

    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_ALLOW_FREE_TEXT': '0'}, clear=False)
    def test_allow_free_text_disabled_by_env(self):
        """Env flag 0 disables free text by default."""
        self.assertFalse(human_tool._get_allow_free_text_default())

    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_ALLOW_FREE_TEXT': '1'}, clear=False)
    def test_allow_free_text_enabled_by_env(self):
        """Env flag 1 enables free text by default."""
        self.assertTrue(human_tool._get_allow_free_text_default())

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
        ans, idx = human_tool._validate_and_resolve('   ', ['a'], True, 'fallback')
        self.assertEqual(ans, 'fallback')
        self.assertEqual(idx, -1)

    def test_validate_and_resolve_valid_option(self):
        """Valid option selection resolves to its text and index."""
        ans, idx = human_tool._validate_and_resolve('2', ['x', 'y', 'z'], False, None)
        self.assertEqual(ans, 'z')
        self.assertEqual(idx, 2)

    def test_validate_and_resolve_invalid_when_free_text_disabled_raises(self):
        """Invalid option with free-text disabled raises ValueError."""
        with self.assertRaises(ValueError):
            human_tool._validate_and_resolve('bogus', ['x', 'y'], False, None)

    def test_validate_and_resolve_free_text_allowed(self):
        """Free-text answer accepted even when options exist."""
        ans, idx = human_tool._validate_and_resolve('custom', ['x', 'y'], True, None)
        self.assertEqual(ans, 'custom')
        self.assertEqual(idx, -1)


class TestPromptRendering(unittest.TestCase):
    """Test option-menu rendering."""

    @patch('topsailai.tools.human_tool._get_prompt_template', return_value='')
    def test_free_text_prompt_accepts_direct_opinion(self, _mock_template):
        """Free-text mode advertises direct opinion input without an extra option."""
        prompt = human_tool._build_prompt('q', ['a', 'b'], True, None)
        self.assertNotIn('Other (enter your own opinion)', prompt)
        self.assertIn('[0..1] or your own opinion', prompt)
        self.assertIn("'/cancel'", prompt)

    @patch('topsailai.tools.human_tool._get_prompt_template', return_value='')
    def test_strict_option_prompt_omits_own_opinion_hint(self, _mock_template):
        """Strict option mode only advertises predefined choices."""
        prompt = human_tool._build_prompt('q', ['a', 'b'], False, None)
        self.assertNotIn('own opinion', prompt)
        self.assertIn('[0..1]', prompt)
        self.assertIn("'/cancel'", prompt)

    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_ALLOW_FREE_TEXT': '0'}, clear=False)
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: '0', None))
    def test_omitted_free_text_parameter_uses_environment(self, _mock_resolve):
        """Omitted free-text setting honors the environment configuration."""
        with patch('topsailai.tools.human_tool._build_prompt', wraps=human_tool._build_prompt) as mock_build:
            result = human_tool.ask_decision('q', options=['Alpha'])
        self.assertEqual(result['answer'], 'Alpha')
        self.assertFalse(mock_build.call_args.args[2])


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
    """Test strict reprompt loop when free-text is disabled."""

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    def test_reprompts_until_valid_option(self, mock_build):
        """Invalid option with allow_free_text=False reprompts until valid or cancel."""
        answers = iter(['bogus', '1'])
        fake_input = lambda p, t: next(answers)
        with patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(fake_input, None)):
            result = human_tool.ask_decision('q', options=['x', 'y'], allow_free_text=False)
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'y')
        self.assertEqual(result['option_index'], 1)

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    def test_cancel_during_reprompt_is_cancelled(self, mock_build):
        """The '/cancel' command during strict reprompt yields cancelled status."""
        answers = iter(['bad', '/cancel'])
        fake_input = lambda p, t: next(answers)
        with patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(fake_input, None)):
            result = human_tool.ask_decision('q', options=['x', 'y'], allow_free_text=False, default='dflt')
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['answer'], 'dflt')

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

    def test_integer_allow_free_text_values_are_normalized(self):
        """Integer flags resolve using Python truthiness."""
        for value in (1, 2, '1', '0', ' 1 ', '00'):
            expected = int(str(value).strip()) != 0
            self.assertEqual(human_tool._resolve_allow_free_text(value), (expected, None))
        self.assertEqual(human_tool._resolve_allow_free_text(0), (False, None))
        self.assertEqual(human_tool._resolve_allow_free_text('1'), (True, None))
        self.assertEqual(human_tool._resolve_allow_free_text('0'), (False, None))
        self.assertEqual(human_tool._resolve_allow_free_text(' 1 '), (True, None))

    @patch.dict(os.environ, {'TOPSAILAI_HUMAN_DECISION_ALLOW_FREE_TEXT': '0'}, clear=False)
    def test_empty_allow_free_text_uses_environment_default(self):
        """Empty, whitespace, and omitted values use the environment default."""
        for value in ('', '   ', None):
            self.assertEqual(human_tool._resolve_allow_free_text(value), (False, None))

    def test_python_boolean_allow_free_text_remains_supported(self):
        """Python booleans remain accepted for existing callers."""
        self.assertEqual(human_tool._resolve_allow_free_text(True), (True, None))
        self.assertEqual(human_tool._resolve_allow_free_text(False), (False, None))

    def test_non_integer_allow_free_text_returns_invalid_request(self):
        """Non-integer strings and floats return a structured validation failure."""
        for value in ('maybe', 'true', 'yes', '1.3', 1.0, 0.0, []):
            result = human_tool.ask_decision('q', allow_free_text=value)
            self.assertEqual(result['status'], 'invalid_request')
            self.assertEqual(result['reason'], 'invalid_allow_free_text')

    @patch('topsailai.tools.human_tool._resolve_input_funcs')
    def test_string_allow_free_text_reaches_prompt_as_bool(self, mock_resolve):
        """A numeric string flag is applied to prompt rendering as a bool."""
        observed = []
        mock_resolve.return_value = (lambda p, t: observed.append(p) or 'yes', None)
        result = human_tool.ask_decision(
            'q', options=['a', 'b'], allow_free_text='1', default='dflt'
        )
        self.assertEqual(result['status'], 'answered')
        self.assertIn('or your own opinion', observed[0])

    def test_numeric_timeout_strings_are_normalized(self):
        """Finite numeric timeout strings are parsed to floats."""
        for value, expected in (('1.3', 1.3), ('300', 300.0), (' 42 ', 42.0), ('1e2', 100.0)):
            self.assertEqual(human_tool._resolve_timeout_seconds(value), (expected, None))

    def test_non_positive_timeout_values_mean_infinite_wait(self):
        """Zero and negative numeric values normalize to an infinite wait."""
        for value in (0, -1, '0', '-1.5'):
            self.assertEqual(human_tool._resolve_timeout_seconds(value), (None, None))

    def test_invalid_timeout_values_return_invalid_request(self):
        """Empty, nonnumeric, non-finite, and boolean timeouts are rejected."""
        for value in ('abc', '', 'NaN', 'inf', '-inf', True, False):
            result = human_tool.ask_decision('q', timeout_seconds=value)
            self.assertEqual(result['status'], 'invalid_request')
            self.assertEqual(result['reason'], 'invalid_timeout_seconds')

    @patch('topsailai.tools.human_tool._resolve_input_funcs')
    def test_string_timeout_reaches_input_as_parsed_float(self, mock_resolve):
        """ask_decision passes a parsed numeric string to the runtime callback."""
        observed = []
        mock_resolve.return_value = (lambda _prompt, timeout: observed.append(timeout) or 'yes', None)
        result = human_tool.ask_decision('q', timeout_seconds='1.3')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(observed, [1.3])

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

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    def test_plain_branch_enforces_positive_timeout(self, mock_build):
        """Plain thread-local input must honor a positive effective timeout."""
        import time

        def slow_reader(_prompt):
            time.sleep(30)
            return 'too late'

        with patch('topsailai.tools.human_tool._resolve_input_funcs',
                   return_value=(None, slow_reader)):
            result = human_tool.ask_decision(
                'q', default='dflt', timeout_seconds=0.002
            )
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['answer'], 'dflt')

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    @patch('topsailai.tools.human_tool._has_usable_input_source', return_value=True)
    def test_input_fallback_enforces_positive_timeout(self, mock_src, mock_build):
        """Builtin input() fallback must honor a positive effective timeout."""
        import time

        def blocking_input(*_args):
            time.sleep(60)
            return 'late'

        with patch('builtins.input', blocking_input):
            with patch('topsailai.tools.human_tool._resolve_input_funcs',
                       return_value=(None, None)):
                result = human_tool.ask_decision(
                    'q', default='dflt', timeout_seconds=0.004
                )
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['answer'], 'dflt')


class TestRepromptRobustness(unittest.TestCase):
    """Cover retry budget exhaustion and consistent timeout mapping."""

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    def test_reprompt_exhaustion_degrades_to_current_input(self, mock_build):
        """After max_retries invalid inputs, accept current input instead of looping forever."""
        answers = iter(['bad'] * 80)

        def fake_input(_p, _t):
            return next(answers)

        with patch('topsailai.tools.human_tool._resolve_input_funcs',
                   return_value=(fake_input, None)):
            result = human_tool.ask_decision(
                'q', options=['x', 'y'], allow_free_text=False
            )
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], 'bad')
        self.assertEqual(result['option_index'], -1)

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    def test_reprompt_timeouterror_maps_to_timeout(self, mock_build):
        """A TimeoutError raised during reprompt yields status 'timeout' (consistent)."""
        state = {'count': 0}

        def flaky(_p, _t):
            state['count'] += 1
            if state['count'] == 1:
                return 'bad'
            raise TimeoutError()

        with patch('topsailai.tools.human_tool._resolve_input_funcs',
                   return_value=(flaky, None)):
            result = human_tool.ask_decision(
                'q', options=['x', 'y'], allow_free_text=False, default='dflt'
            )
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['answer'], 'dflt')

    @patch('topsailai.tools.human_tool._build_prompt', return_value='prompt')
    def test_reprompt_keyboard_interrupt_maps_to_cancelled(self, mock_build):
        """A KeyboardInterrupt raised during reprompt yields status 'cancelled'."""
        state = {'count': 0}

        def flaky(_p, _t):
            state['count'] += 1
            if state['count'] == 1:
                return 'bad'
            raise KeyboardInterrupt()

        with patch('topsailai.tools.human_tool._resolve_input_funcs',
                   return_value=(flaky, None)):
            result = human_tool.ask_decision(
                'q', options=['x', 'y'], allow_free_text=False, default='dflt'
            )
        self.assertEqual(result['status'], 'cancelled')
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
