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

    def test_flag_tool_enabled_is_true(self):
        """FLAG_TOOL_ENABLED must be boolean True."""
        self.assertIsInstance(human_tool.FLAG_TOOL_ENABLED, bool)
        self.assertTrue(human_tool.FLAG_TOOL_ENABLED)

    def test_prompt_describes_blocked_task_usage(self):
        """PROMPT must describe blocked-task decision usage."""
        self.assertIsInstance(human_tool.PROMPT, str)
        self.assertIn('blocked', human_tool.PROMPT.lower())
        self.assertIn('status', human_tool.PROMPT)


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
    @patch('topsailai.tools.human_tool._resolve_input_funcs', return_value=(lambda p, t: 'cancel', None))
    def test_literal_cancel_word_is_cancelled(self, mock_resolve, mock_build):
        """Literal 'cancel' word maps to cancelled status."""
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
        self.assertIn('asked_at_ms', result)
        self.assertIn('elapsed_ms', result)

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
        """Cancelling during the reprompt loop yields cancelled status."""
        answers = iter(['bad', 'cancel'])
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

    def test_invalid_question_returns_unavailable(self):
        """Empty/non-string question returns unavailable immediately."""
        result = human_tool.ask_decision('   ', default='dflt')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['answer'], 'dflt')

    def test_non_list_options_returns_unavailable(self):
        """Non-list options argument returns unavailable."""
        result = human_tool.ask_decision('q', options='not-a-list', default='dflt')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['answer'], 'dflt')


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
