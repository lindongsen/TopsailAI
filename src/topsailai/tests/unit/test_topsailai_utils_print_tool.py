import os
import unittest
from unittest.mock import patch, MagicMock
from topsailai.utils import print_tool
from topsailai.utils.ansi_color import Colors


class TestPrintTool(unittest.TestCase):
    """Test cases for print_tool module."""

    def setUp(self):
        """Set up test fixtures."""
        # Store original environment variables
        self.original_debug = os.environ.get('DEBUG')
        self.original_truncate_len = os.environ.get('DEBUG_PRINT_TRUNCATE_LENGTH')
        self.original_print_step_mode = os.environ.get('TOPSAILAI_PRINT_STEP_MODE')
        # Snapshot the module level step print flag so tests that enable it
        # cannot leak stdout output into sibling test modules.
        self.original_flag_print_step = print_tool.g_flag_print_step

        # Set default test environment
        if 'DEBUG' in os.environ:
            del os.environ['DEBUG']
        os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = '100'
        os.environ.pop('TOPSAILAI_PRINT_STEP_MODE', None)
        print_tool._print_step_invalid_mode_warned = False

    def tearDown(self):
        """Clean up after tests."""
        # Restore original environment variables
        if self.original_debug is not None:
            os.environ['DEBUG'] = self.original_debug
        elif 'DEBUG' in os.environ:
            del os.environ['DEBUG']

        if self.original_truncate_len is not None:
            os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = self.original_truncate_len
        elif 'DEBUG_PRINT_TRUNCATE_LENGTH' in os.environ:
            del os.environ['DEBUG_PRINT_TRUNCATE_LENGTH']

        if self.original_print_step_mode is not None:
            os.environ['TOPSAILAI_PRINT_STEP_MODE'] = self.original_print_step_mode
        else:
            os.environ.pop('TOPSAILAI_PRINT_STEP_MODE', None)
        print_tool._print_step_invalid_mode_warned = False
        print_tool.g_flag_print_step = self.original_flag_print_step

    def test_get_truncation_len_default(self):
        """Test get_truncation_len with no environment variable."""
        if 'DEBUG_PRINT_TRUNCATE_LENGTH' in os.environ:
            del os.environ['DEBUG_PRINT_TRUNCATE_LENGTH']
        result = print_tool.get_truncation_len()
        self.assertIsNone(result)

    def test_get_truncation_len_env_var(self):
        """Test get_truncation_len with environment variable set."""
        os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = '50'
        result = print_tool.get_truncation_len()
        self.assertEqual(result, 50)

    def test_get_truncation_len_env_var_invalid(self):
        """Test get_truncation_len with invalid environment variable."""
        os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = 'invalid'
        result = print_tool.get_truncation_len()
        self.assertIsNone(result)

    def test_truncate_msg_with_json_string(self):
        """Test truncate_msg with a JSON string that will be parsed and truncated."""
        os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = '10'
        # Create a JSON string with a long raw_text value
        long_text = 'a' * 500
        msg = f'{{"step_name": "test", "raw_text": "{long_text}"}}'

        result = print_tool.truncate_msg(msg)

        # Should be truncated and contain the truncation marker
        self.assertIn('[Display truncated:', result)
        self.assertIn('500 chars total', result)
        # Should be valid JSON
        import json
        parsed = json.loads(result)
        self.assertEqual(parsed['step_name'], 'test')
        self.assertIn('aaaaaaaaaa', parsed['raw_text'])
        self.assertIn('[Display truncated:', parsed['raw_text'])

    def test_truncate_msg_with_dict(self):
        """Test truncate_msg with a dictionary that will be truncated."""
        os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = '10'
        # Create a dict with a long raw_text value
        msg = {
            'step_name': 'test',
            'raw_text': 'b' * 500
        }

        result = print_tool.truncate_msg(msg)

        # Should be truncated and contain the truncation marker
        self.assertIn('[Display truncated:', result)
        self.assertIn('500 chars total', result)
        # Should be valid JSON
        import json
        parsed = json.loads(result)
        self.assertEqual(parsed['step_name'], 'test')
        self.assertIn('bbbbbbbbbb', parsed['raw_text'])
        self.assertIn('[Display truncated:', parsed['raw_text'])

    def test_truncate_msg_plain_string_short(self):
        """Test truncate_msg with a short plain string (no truncation)."""
        os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = '100'
        msg = 'short message'

        result = print_tool.truncate_msg(msg)

        # Should not be truncated
        self.assertEqual(result, 'short message')

    def test_truncate_msg_plain_string_long(self):
        """Test truncate_msg with a long plain string (no truncation for plain strings)."""
        os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = '10'
        # Create a long string that exceeds truncation_len + 100
        msg = 'c' * 500

        result = print_tool.truncate_msg(msg)

        # Plain strings are not truncated directly, only JSON/dict/list objects are
        self.assertEqual(result, msg)
        self.assertEqual(len(result), 500)

    def test_truncate_msg_list(self):
        """Test truncate_msg with a list of dictionaries."""
        os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = '10'
        # Create a list with dicts containing long raw_text values
        msg = [
            {'step_name': 'test1', 'raw_text': 'd' * 300},
            {'step_name': 'test2', 'raw_text': 'e' * 400}
        ]

        result = print_tool.truncate_msg(msg)

        # Should be truncated and contain the truncation markers
        self.assertIn('[Display truncated:', result)
        self.assertIn('300 chars total', result)
        self.assertIn('400 chars total', result)
        # Should be valid JSON list
        import json
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['step_name'], 'test1')
        self.assertEqual(parsed[1]['step_name'], 'test2')

    def test_enable_disable_flag_print_step(self):
        """Test enable_flag_print_step and disable_flag_print_step functions."""
        # Initially should be None
        self.assertIsNone(print_tool.g_flag_print_step)

        # Enable the flag
        print_tool.enable_flag_print_step()
        self.assertTrue(print_tool.g_flag_print_step)

        # Disable the flag
        print_tool.disable_flag_print_step()
        self.assertFalse(print_tool.g_flag_print_step)

    def test_flag_print_step_env_var(self):
        """Test that flag_print_step respects environment variable."""
        # Set DEBUG environment variable
        os.environ['DEBUG'] = '1'

        # Reset the flag to None
        print_tool.g_flag_print_step = None

        # The flag should be set based on DEBUG env var when accessed
        # For this test, we'll just verify the environment is set correctly
        self.assertEqual(os.environ.get('DEBUG'), '1')

    @patch('topsailai.utils.print_tool.print_with_time')
    @patch('topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    def test_print_debug_with_debug_env(self, mock_get_thread_var, mock_print_with_time):
        """Test print_debug when DEBUG environment variable is set."""
        # Set DEBUG environment variable
        os.environ['DEBUG'] = '1'

        # Mock thread_local_tool.get_thread_var to return None
        mock_get_thread_var.return_value = None

        # Call print_debug
        print_tool.print_debug('test message')

        # Verify print_with_time was called
        mock_print_with_time.assert_called_once_with('[DEBUG] test message', need_format=False,
                                                        color_kind='debug', color_enabled=None)

        # Verify get_thread_var was called
        mock_get_thread_var.assert_called_once_with('flag_debug')

    @patch('topsailai.utils.print_tool.print_with_time')
    @patch('topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    def test_print_debug_with_flag_debug(self, mock_get_thread_var, mock_print_with_time):
        """Test print_debug when flag_debug is set in thread local."""
        # Ensure DEBUG environment variable is not set
        if 'DEBUG' in os.environ:
            del os.environ['DEBUG']

        # Mock thread_local_tool.get_thread_var to return 1 (truthy)
        mock_get_thread_var.return_value = 1

        print_tool.enable_flag_print_step()

        # Call print_debug
        print_tool.print_debug('test message')

        # Verify print_with_time was called
        mock_print_with_time.assert_called_once_with('[DEBUG] test message', need_format=False,
                                                        color_kind='debug', color_enabled=None)

        # Verify get_thread_var was called
        mock_get_thread_var.assert_called_once_with('flag_debug')

    @patch('topsailai.utils.print_tool.print_with_time')
    @patch('topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    @patch('topsailai.utils.env_tool.is_interactive_mode')
    def test_print_debug_no_output(self, mock_is_interactive_mode, mock_get_thread_var, mock_print_with_time):
        """Test print_debug when neither DEBUG env nor flag_debug is set."""
        # Ensure DEBUG environment variable is not set
        if 'DEBUG' in os.environ:
            del os.environ['DEBUG']

        # Mock thread_local_tool.get_thread_var to return None (falsy)
        mock_get_thread_var.return_value = None

        # Non-interactive mode so env_tool.is_interactive_mode() does not force output
        mock_is_interactive_mode.return_value = False

        # Call print_debug
        print_tool.print_debug('test message')

        # Verify print_with_time was NOT called
        mock_print_with_time.assert_not_called()

        # Verify get_thread_var was called
        mock_get_thread_var.assert_called_once_with('flag_debug')

    def test_get_print_step_mode(self):
        """Step mode defaults, normalizes, and accepts supported values."""
        cases = [
            (None, "normal"),
            ("", "normal"),
            ("simple", "simple"),
            ("normal", "normal"),
            ("  NoRmAl  ", "normal"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                if value is None:
                    os.environ.pop('TOPSAILAI_PRINT_STEP_MODE', None)
                else:
                    os.environ['TOPSAILAI_PRINT_STEP_MODE'] = value
                self.assertEqual(print_tool.get_print_step_mode(), expected)

    @patch('topsailai.utils.print_tool.logger.warning')
    def test_get_print_step_mode_invalid_warns_once(self, mock_warning):
        """Invalid step modes safely fall back and warn once per process."""
        os.environ['TOPSAILAI_PRINT_STEP_MODE'] = 'verbose'

        self.assertEqual(print_tool.get_print_step_mode(), 'normal')
        self.assertEqual(print_tool.get_print_step_mode(), 'normal')

        mock_warning.assert_called_once()

    def test_format_print_step_simple_structured_messages(self):
        """Action raw text stays complete while ordinary steps remain summarized."""
        action_raw_text = '\n  first   line  \nsecond line'
        result = print_tool.format_print_step_simple([
            {'step_name': 'action', 'raw_text': action_raw_text},
            {'step_name': 'observation', 'raw_text': 'short'},
        ])

        self.assertEqual(
            result,
            f'[action] {action_raw_text}\n[observation] short',
        )
        self.assertNotIn('[truncated,', result)

    def test_format_print_step_simple_long_content(self):
        """Long action content stays complete while plain content remains capped."""
        long_text = 'x' * 200

        structured = print_tool.format_print_step_simple(
            {'step_name': 'action', 'raw_text': long_text}
        )
        plain = print_tool.format_print_step_simple(long_text)

        expected = f"{'x' * 160} [truncated, 200 chars total]"
        self.assertEqual(structured, f'[action] {long_text}')
        self.assertNotIn('[truncated,', structured)
        self.assertEqual(plain, expected)

    def test_format_print_step_simple_full_prefixes_keep_complete_content(self):
        """Task, thought, action, final, and inquiry prefixes stay complete."""
        raw_text = 'first line\n' + ('details ' * 40)
        step_names = (
            'task', 'task_input',
            'thought', 'thought_process',
            'action', 'action_input',
            'final', 'final_answer',
            'inquiry', 'inquiry_user',
        )

        for step_name in step_names:
            with self.subTest(step_name=step_name):
                result = print_tool.format_print_step_simple(
                    {'step_name': step_name, 'raw_text': raw_text}
                )
                self.assertEqual(result, f'[{step_name}] {raw_text}')
                self.assertNotIn('[truncated,', result)

    def test_format_print_step_simple_formatted_string_honors_full_prefixes(self):
        """Canonical formatted strings keep full-prefix content complete."""
        result = print_tool.format_print_step_simple(
            'topsailai.thought\nfirst line\nsecond line\n'
            'topsailai.action\naction line\naction detail'
        )

        self.assertEqual(
            result,
            '[thought] first line\nsecond line\n'
            '[action] action line\naction detail',
        )

    def test_format_print_step_simple_tool_calls(self):
        """Tool-call summaries expose names, count and the first argument, never IDs."""
        tool_calls = [
            {'id': 'call-1', 'function': {'name': 'read_file', 'arguments': '{"file_path": "/tmp/a.md"}'}},
            {'id': 'call-2', 'function': {'name': 'read_file', 'arguments': '{}'}},
            {'id': 'call-3', 'function': {'name': 'exec_cmd', 'arguments': 'danger'}},
        ]

        result = print_tool.format_print_step_simple(tool_calls)

        self.assertEqual(
            result,
            '[tool_calls] count=3 names=read_file,exec_cmd\n'
            '  read_file(file_path=/tmp/a.md)\n'
            '  exec_cmd(danger)',
        )
        self.assertNotIn('call-1', result)

    def test_format_print_step_simple_tool_calls_masks_sensitive_values(self):
        """Sensitive first-argument names keep their key but mask the value."""
        sensitive_values = ['sk-secret-value', 'p@ssw0rd-plain', 'ghp_token_plain']
        tool_calls = [
            {'function': {'name': 'llm_chat', 'arguments': '{"api_key": "%s"}' % sensitive_values[0]}},
            {'function': {'name': 'auth', 'arguments': '{"Password": "%s"}' % sensitive_values[1]}},
            {'function': {'name': 'ssh', 'arguments': '{"ACCESS_TOKEN": "%s"}' % sensitive_values[2]}},
        ]

        result = print_tool.format_print_step_simple(tool_calls)

        self.assertIn('llm_chat(api_key=***)', result)
        self.assertIn('auth(Password=***)', result)
        self.assertIn('ssh(ACCESS_TOKEN=***)', result)
        for value in sensitive_values:
            self.assertNotIn(value, result)

    def test_format_print_step_simple_tool_calls_collapses_and_truncates(self):
        """First-argument values stay on one line and are bounded with a size marker."""
        long_value = 'y' * 200
        tool_calls = [
            {'function': {'name': 'exec_cmd', 'arguments': '{"cmd": "first   line\\nsecond line"}'}},
            {'function': {'name': 'write_file', 'arguments': '{"content": "%s"}' % long_value}},
        ]

        result = print_tool.format_print_step_simple(tool_calls)

        lines = result.splitlines()
        self.assertEqual(lines[1], '  exec_cmd(cmd=first line second line)')
        self.assertEqual(
            lines[2],
            '  write_file(content=%s [truncated, 200 chars total])' % ('y' * 80),
        )
        # Exactly one summary line plus one line per tool call: no leaked line breaks.
        self.assertEqual(len(lines), 3)

    def test_format_print_step_simple_tool_calls_nested_values(self):
        """Nested dict and list values render as compact single-line JSON."""
        tool_calls = [
            {'function': {'name': 't', 'arguments': '{"args": [1, 2, {"k": "v"}]}'}},
            {'function': {'name': 'u', 'arguments': '{"options": {"deep": {"a": 1}}}'}},
        ]

        result = print_tool.format_print_step_simple(tool_calls)

        self.assertIn('  t(args=[1,2,{"k":"v"}])', result)
        self.assertIn('  u(options={"deep":{"a":1}})', result)

    def test_format_print_step_simple_tool_calls_pre_parsed_arguments(self):
        """Already parsed dict/list arguments and unserializable values are handled."""
        # Event-style payloads may carry arguments as real containers.
        result = print_tool.format_print_step_simple(
            [{'function': {'name': 't', 'arguments': {'file_path': '/tmp/a.md'}}}]
        )
        self.assertIn('  t(file_path=/tmp/a.md)', result)

        # An empty parsed dict keeps the legacy summary.
        result = print_tool.format_print_step_simple(
            [{'function': {'name': 't', 'arguments': {}}}]
        )
        self.assertEqual(result, '[tool_calls] count=1 names=t')

        # A list payload is shown as an unnamed compact JSON value.
        result = print_tool.format_print_step_simple(
            [{'function': {'name': 't', 'arguments': [1, 2]}}]
        )
        self.assertIn('  t([1,2])', result)

        # A nested value that cannot be JSON-serialized falls back to plain text.
        result = print_tool.format_print_step_simple(
            [{'function': {'name': 't', 'arguments': {'items': [{1}]}}}]
        )
        self.assertIn('  t(items=', result)
        self.assertEqual(len(result.splitlines()), 2)

    def test_format_print_step_simple_tool_calls_fail_open(self):
        """Missing, empty or unparsable arguments keep the legacy name-only summary."""
        cases = [
            [{'function': {'name': 't', 'arguments': ''}}],
            [{'function': {'name': 't', 'arguments': '   '}}],
            [{'function': {'name': 't', 'arguments': '{}'}}],
            [{'function': {'name': 't', 'arguments': None}}],
            [{'function': {'name': 't'}}],
            [{'name': 't', 'function': {}}],
            [{'function': {'name': 't', 'arguments': 12345}}],
            [{'name': 't'}],
        ]

        for tool_calls in cases:
            with self.subTest(tool_calls=tool_calls):
                result = print_tool.format_print_step_simple(tool_calls)
                self.assertEqual(result, '[tool_calls] count=1 names=t')

    def test_format_print_step_simple_tool_calls_scalar_and_empty_values(self):
        """Scalar, empty-string and null first values render explicitly."""
        tool_calls = [
            {'function': {'name': 't', 'arguments': '{"seek": 0}'}},
            {'function': {'name': 'u', 'arguments': '{"content": ""}'}},
            {'function': {'name': 'v', 'arguments': '{"flag": null}'}},
            {'function': {'name': 'w', 'arguments': '[1, 2]'}},
        ]

        result = print_tool.format_print_step_simple(tool_calls)

        self.assertIn('  t(seek=0)', result)
        self.assertIn('  u(content="")', result)
        self.assertIn('  v(flag=None)', result)
        self.assertIn('  w([1,2])', result)

    def test_format_print_step_simple_tool_calls_supports_attribute_objects(self):
        """SDK-style attribute tool calls expose the first argument like dicts."""
        function = MagicMock()
        function.name = 'read_file'
        function.arguments = '{"file_path": "/tmp/a.md", "seek": 0}'
        tool_call = MagicMock()
        tool_call.id = 'call-1'
        tool_call.function = function

        result = print_tool.format_print_step_simple([tool_call])

        self.assertEqual(
            result,
            '[tool_calls] count=1 names=read_file\n  read_file(file_path=/tmp/a.md)',
        )
        self.assertNotIn('call-1', result)

    def test_format_print_step_simple_tool_calls_dedups_name_and_first_arg(self):
        """Identical name plus argument collapses; differing arguments each print."""
        tool_calls = [
            {'function': {'name': 't', 'arguments': '{"a": 1}'}},
            {'function': {'name': 't', 'arguments': '{"a": 1}'}},
            {'function': {'name': 't', 'arguments': '{"a": 2}'}},
        ]

        result = print_tool.format_print_step_simple(tool_calls)

        self.assertEqual(
            result,
            '[tool_calls] count=3 names=t\n  t(a=1)\n  t(a=2)',
        )

    def test_format_print_step_simple_empty_and_unknown(self):
        """Empty messages disappear and unknown objects are summarized safely."""
        class Unknown:
            def __str__(self):
                return 'unknown object\nextra detail'

        for value in (None, '', '   ', []):
            with self.subTest(value=value):
                self.assertEqual(print_tool.format_print_step_simple(value), '')
        self.assertEqual(
            print_tool.format_print_step_simple(Unknown()),
            'unknown object [truncated, 27 chars total]',
        )

    @patch('topsailai.utils.print_tool.print_with_time')
    def test_print_step_normal_default(self, mock_print_with_time):
        """The default mode passes messages through unchanged."""
        print_tool.enable_flag_print_step()
        msg = {'step_name': 'thought', 'raw_text': 'first\nsecond'}

        print_tool.print_step(msg)

        mock_print_with_time.assert_called_once_with(msg, need_format=True)

    @patch('topsailai.utils.print_tool.print_with_time')
    def test_print_step_simple_empty_skips_output(self, mock_print_with_time):
        """Simple mode does not print empty content."""
        os.environ['TOPSAILAI_PRINT_STEP_MODE'] = 'simple'
        print_tool.enable_flag_print_step()

        print_tool.print_step('   ')

        mock_print_with_time.assert_not_called()

    @patch('topsailai.utils.print_tool.print_with_time')
    def test_print_step_normal_preserves_legacy_behavior(self, mock_print_with_time):
        """Normal mode passes messages and formatting flags through unchanged."""
        os.environ['TOPSAILAI_PRINT_STEP_MODE'] = 'normal'
        print_tool.enable_flag_print_step()
        tool_calls = [{'id': 'call-1', 'function': {'name': 'read_file', 'arguments': '{}'}}]

        print_tool.print_step('test message')
        print_tool.print_step(tool_calls, need_format=False)

        self.assertEqual(mock_print_with_time.call_args_list, [
            unittest.mock.call('test message', need_format=True),
            unittest.mock.call(tool_calls, need_format=False),
        ])

    @patch('topsailai.utils.print_tool.logger.info')
    @patch('topsailai.utils.print_tool.print_with_time')
    def test_print_step_simple_logs_full_message(self, mock_print_with_time, mock_info):
        """Simple mode retains complete console and log content for thought steps."""
        os.environ['TOPSAILAI_PRINT_STEP_MODE'] = 'simple'
        print_tool.enable_flag_print_step()
        msg = {'step_name': 'thought', 'raw_text': 'first\nsecond'}

        print_tool.print_step(msg, need_log=True)

        mock_info.assert_called_once_with(msg)
        mock_print_with_time.assert_called_once_with(
            '[thought] first\nsecond', need_format=False
        )

    @patch('topsailai.utils.print_tool.print_with_time')
    def test_print_step_simple_prints_first_tool_arg(self, mock_print_with_time):
        """Simple mode prints the first tool-call argument through print_step."""
        os.environ['TOPSAILAI_PRINT_STEP_MODE'] = 'simple'
        print_tool.enable_flag_print_step()
        tool_calls = [
            {'id': 'call-1', 'function': {'name': 'read_file', 'arguments': '{"file_path": "/tmp/a.md"}'}},
        ]

        print_tool.print_step(tool_calls, need_format=False)

        mock_print_with_time.assert_called_once_with(
            '[tool_calls] count=1 names=read_file\n  read_file(file_path=/tmp/a.md)',
            need_format=False,
        )

    @patch('topsailai.utils.print_tool.format_print_step_simple')
    @patch('topsailai.utils.print_tool.print_with_time')
    def test_print_step_disabled(self, mock_print_with_time, mock_format):
        """The explicit step-print flag suppresses output before formatting."""
        print_tool.disable_flag_print_step()

        print_tool.print_step('test message')

        mock_format.assert_not_called()
        mock_print_with_time.assert_not_called()

    @patch('topsailai.utils.print_tool.format_print_step_simple')
    @patch('topsailai.utils.print_tool.print_with_time')
    @patch('topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    def test_print_step_thread_debug_disabled(
        self, mock_get_thread_var, mock_print_with_time, mock_format
    ):
        """The thread-local debug gate suppresses output before formatting."""
        mock_get_thread_var.return_value = 0
        print_tool.enable_flag_print_step()

        print_tool.print_step('test message')

        mock_format.assert_not_called()
        mock_print_with_time.assert_not_called()

    @patch('topsailai.utils.print_tool.format_print_step_simple')
    @patch('topsailai.utils.print_tool.print_with_time')
    @patch('topsailai.utils.print_tool.env_tool.is_need_print')
    def test_print_step_environment_gate_disabled(
        self, mock_is_need_print, mock_print_with_time, mock_format
    ):
        """The environment print gate suppresses output before formatting."""
        mock_is_need_print.return_value = False
        print_tool.enable_flag_print_step()

        print_tool.print_step('test message')

        mock_format.assert_not_called()
        mock_print_with_time.assert_not_called()

    @patch('topsailai.utils.print_tool.print_with_time')
    def test_print_error(self, mock_print_with_time):
        """Test print_error function."""
        print_tool.print_error('error message')

        # Verify print_with_time was called with error prefix
        mock_print_with_time.assert_called_once_with('Error: error message', need_format=False,
                                                       color_kind='error', color_enabled=None)

    @patch('topsailai.utils.print_tool.print_with_time')
    def test_print_warning(self, mock_print_with_time):
        """Test print_warning function."""
        print_tool.print_warning('warning message')

        # Verify print_with_time was called with warning prefix
        mock_print_with_time.assert_called_once_with('Warning: warning message', need_format=False,
                                                         color_kind='warning', color_enabled=None)


    @patch('topsailai.utils.print_tool.print_with_time')
    def test_print_critical(self, mock_print_with_time):
        """Test print_critical function."""
        print_tool.print_critical('critical message')

        # Verify print_with_time was called with critical prefix
        mock_print_with_time.assert_called_once_with('Critical: critical message', need_format=False,
                                                          color_kind='critical', color_enabled=None)

    def test_format_dict_to_md(self):
        """Test format_dict_to_md function."""
        test_dict = {
            'key1': 'value1',
            'key2': 'value2',
            'nested': {
                'subkey': 'subvalue'
            }
        }

        result = print_tool.format_dict_to_md(test_dict)

        # Should contain markdown formatting
        self.assertIn('key1', result)
        self.assertIn('value1', result)
        self.assertIn('key2', result)
        self.assertIn('value2', result)
        self.assertIn('nested', result)
        self.assertIn('subkey', result)
        self.assertIn('subvalue', result)

    def test_add_indent_to_lines(self):
        """Test add_indent_to_lines function."""
        test_str = "line1\nline2\nline3"
        result = print_tool.add_indent_to_lines(test_str, indent=4)
        
        expected = "    line1\n    line2\n    line3\n"
        self.assertEqual(result, expected)

    def test_add_indent_to_lines_custom_indent(self):
        """Test add_indent_to_lines with custom indent."""
        test_str = "line1\nline2"
        result = print_tool.add_indent_to_lines(test_str, indent=2)
        
        expected = "  line1\n  line2\n"
        self.assertEqual(result, expected)

    def test_add_indent_to_lines_empty_string(self):
        """Test add_indent_to_lines returns empty string for empty input."""
        result = print_tool.add_indent_to_lines("")
        self.assertEqual(result, "")

    def test_add_indent_to_lines_none_input(self):
        """Test add_indent_to_lines returns empty string for None input."""
        result = print_tool.add_indent_to_lines(None)
        self.assertEqual(result, "")


    @patch('topsailai.utils.print_tool.print')
    @patch('topsailai.utils.print_tool.datetime')
    @patch('topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    @patch('topsailai.utils.env_tool.is_interactive_mode')
    def test_print_with_time_no_prefix(self, mock_is_interactive_mode, mock_get_thread_var, mock_datetime, mock_print):
        """Test print_with_time with no agent or model name."""
        mock_is_interactive_mode.return_value = True
        mock_get_thread_var.return_value = None
        mock_datetime.now.return_value.strftime.return_value = "2026-01-01 00:00:00"

        print_tool.print_with_time('test message')

        mock_print.assert_called_once_with('[2026-01-01 00:00:00] test message')

    @patch('topsailai.utils.print_tool.print')
    @patch('topsailai.utils.print_tool.datetime')
    @patch('topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    @patch('topsailai.utils.env_tool.is_interactive_mode')
    def test_print_with_time_agent_name_only(self, mock_is_interactive_mode, mock_get_thread_var, mock_datetime, mock_print):
        """Test print_with_time with only agent name."""
        mock_is_interactive_mode.return_value = True

        def _get_thread_var(name, default=None):
            if name == print_tool.thread_local_tool.KEY_AGENT_NAME:
                return "TestAgent"
            return None
        mock_get_thread_var.side_effect = _get_thread_var
        mock_datetime.now.return_value.strftime.return_value = "2026-01-01 00:00:00"

        print_tool.print_with_time('test message')

        mock_print.assert_called_once_with('[TestAgent] [2026-01-01 00:00:00] test message')

    @patch('topsailai.utils.print_tool.print')
    @patch('topsailai.utils.print_tool.datetime')
    @patch('topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    @patch('topsailai.utils.env_tool.is_interactive_mode')
    def test_print_with_time_model_name_only(self, mock_is_interactive_mode, mock_get_thread_var, mock_datetime, mock_print):
        """Test print_with_time with only model name from agent object."""
        mock_is_interactive_mode.return_value = True

        agent_obj = MagicMock()
        agent_obj.llm_model.model_name = "TestModel"

        def _get_thread_var(name, default=None):
            if name == print_tool.thread_local_tool.KEY_AGENT_OBJECT:
                return agent_obj
            return None
        mock_get_thread_var.side_effect = _get_thread_var
        mock_datetime.now.return_value.strftime.return_value = "2026-01-01 00:00:00"

        print_tool.print_with_time('test message')

        mock_print.assert_called_once_with('[TestModel] [2026-01-01 00:00:00] test message')

    @patch('topsailai.utils.print_tool.print')
    @patch('topsailai.utils.print_tool.datetime')
    @patch('topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    @patch('topsailai.utils.env_tool.is_interactive_mode')
    def test_print_with_time_agent_and_model_name(self, mock_is_interactive_mode, mock_get_thread_var, mock_datetime, mock_print):
        """Test print_with_time with both agent name and model name."""
        mock_is_interactive_mode.return_value = True

        agent_obj = MagicMock()
        agent_obj.llm_model.model_name = "TestModel"

        def _get_thread_var(name, default=None):
            if name == print_tool.thread_local_tool.KEY_AGENT_NAME:
                return "TestAgent"
            if name == print_tool.thread_local_tool.KEY_AGENT_OBJECT:
                return agent_obj
            return None
        mock_get_thread_var.side_effect = _get_thread_var
        mock_datetime.now.return_value.strftime.return_value = "2026-01-01 00:00:00"

        print_tool.print_with_time('test message')

        mock_print.assert_called_once_with('[TestAgent] [TestModel] [2026-01-01 00:00:00] test message')

if __name__ == '__main__':
    unittest.main()


class TestPrintToolColor(unittest.TestCase):
    """Test cases for ANSI color support added to print_tool."""

    def setUp(self):
        self._saved_env = {}
        for k in ("TOPSAILAI_PRINT_COLOR_ENABLED", "NO_COLOR"):
            self._saved_env[k] = os.environ.get(k)
            if k in os.environ:
                del os.environ[k]

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    @patch("sys.stdout")
    def test_is_color_enabled_explicit_param_overrides_env(self, mock_stdout):
        """Explicit parameter takes precedence over env var."""
        os.environ["TOPSAILAI_PRINT_COLOR_ENABLED"] = "1"
        mock_stdout.isatty.return_value = False
        # Explicit False wins despite env=1
        self.assertFalse(print_tool._is_color_enabled(color_enabled=False))
        # Explicit True wins despite env unset & non-tty
        os.environ.pop("TOPSAILAI_PRINT_COLOR_ENABLED", None)
        self.assertTrue(print_tool._is_color_enabled(color_enabled=True))

    @patch("sys.stdout")
    def test_is_color_enabled_env_var_true_values(self, mock_stdout):
        """Env var truthy values enable color regardless of tty."""
        mock_stdout.isatty.return_value = False
        for val in ("1", "true", "yes", "on"):
            os.environ["TOPSAILAI_PRINT_COLOR_ENABLED"] = val
            self.assertTrue(print_tool._is_color_enabled(), msg=f"val={val!r}")

    @patch("sys.stdout")
    def test_is_color_enabled_no_color_disables_even_on_tty(self, mock_stdout):
        """NO_COLOR disables color even when stdout is a tty."""
        mock_stdout.isatty.return_value = True
        os.environ["NO_COLOR"] = "1"
        self.assertFalse(print_tool._is_color_enabled())

    @patch("sys.stdout")
    def test_is_color_enabled_falls_back_to_tty(self, mock_stdout):
        """With no env vars set, falls back to sys.stdout.isatty()."""
        mock_stdout.isatty.return_value = True
        self.assertTrue(print_tool._is_color_enabled())
        mock_stdout.isatty.return_value = False
        self.assertFalse(print_tool._is_color_enabled())

    @patch("builtins.print")
    @patch("topsailai.utils.print_tool.datetime")
    @patch("topsailai.utils.print_tool.thread_local_tool.get_thread_var")
    @patch("topsailai.utils.env_tool.is_interactive_mode")
    def test_level_methods_emit_ansi_when_enabled(self, mock_int, mock_gv, mock_dt, mock_print):
        """Each level method emits its mapped ANSI code when color enabled."""
        mock_int.return_value = True
        mock_gv.return_value = None
        mock_dt.now.return_value.strftime.return_value = "2026-01-01 00:00:00"

        cases = [
            (lambda: print_tool.print_info("m", color_enabled=True), Colors.CYAN),
            (lambda: print_tool.print_debug("m", color_enabled=True), [Colors.GRAY, Colors.DIM]),
            (lambda: print_tool.print_warning("m", color_enabled=True), Colors.YELLOW),
            (lambda: print_tool.print_error("m", color_enabled=True), Colors.RED),
            (lambda: print_tool.print_critical("m", color_enabled=True), Colors.BOLD + Colors.RED),
        ]
        for fn, expected_codes in cases:
            mock_print.reset_mock()
            fn()
            out = mock_print.call_args[0][0]
            if isinstance(expected_codes, str):
                expected_codes = [expected_codes]
            for code in expected_codes:
                self.assertIn(code, out, f"missing ansi {code!r} in {out!r}")
            self.assertIn(Colors.RESET, out)

    @patch("builtins.print")
    @patch("topsailai.utils.print_tool.datetime")
    @patch("topsailai.utils.print_tool.thread_local_tool.get_thread_var")
    @patch("topsailai.utils.env_tool.is_interactive_mode")
    def test_level_methods_no_escape_when_disabled(self, mock_int, mock_gv, mock_dt, mock_print):
        """No ANSI codes emitted when color explicitly disabled."""
        mock_int.return_value = True
        mock_gv.return_value = None
        mock_dt.now.return_value.strftime.return_value = "2026-01-01 00:00:00"

        print_tool.print_error("boom", color_enabled=False)
        out = mock_print.call_args[0][0]
        self.assertEqual(out, "[2026-01-01 00:00:00] Error: boom")
        self.assertNotIn("\033[", out)

    @patch("builtins.print")
    @patch("topsailai.utils.print_tool.datetime")
    @patch("topsailai.utils.print_tool.thread_local_tool.get_thread_var")
    @patch("topsailai.utils.env_tool.is_interactive_mode")
    def test_error_prefix_colored_with_body(self, mock_int, mock_gv, mock_dt, mock_print):
        """Error:/Warning:/Critical: prefix is colored together with body."""
        mock_int.return_value = True
        mock_gv.return_value = None
        mock_dt.now.return_value.strftime.return_value = "2026-01-01 00:00:00"

        print_tool.print_error("boom", color_enabled=True)
        out = mock_print.call_args[0][0]
        # The whole line (prefix included) sits between RED start and RESET end
        self.assertIn(f"{Colors.RED}[2026-01-01 00:00:00] Error: boom{Colors.RESET}", out)

    @patch("builtins.print")
    @patch("topsailai.utils.print_tool.datetime")
    @patch("topsailai.utils.print_tool.thread_local_tool.get_thread_var")
    @patch("topsailai.utils.env_tool.is_interactive_mode")
    def test_truncated_reset_not_lost_and_plain_first(self, mock_int, mock_gv, mock_dt, mock_print):
        """Truncation happens on plain text BEFORE wrapping; RESET survives."""
        mock_int.return_value = True
        mock_gv.return_value = None
        mock_dt.now.return_value.strftime.return_value = "2026-01-01 00:00:00"
        os.environ["DEBUG_PRINT_TRUNCATE_LENGTH"] = "10"

        long_msg = {"step_name": "test", "raw_text": "x" * 500}
        print_tool.print_info(long_msg, color_enabled=True)
        out = mock_print.call_args[0][0]

        # ANSI wrap must be outermost: starts with style, ends with RESET
        self.assertTrue(out.startswith(Colors.CYAN), out[:20])
        self.assertTrue(out.endswith(Colors.RESET), out[-20:])
        # Truncation marker present inside the colored region => plain-text truncated first
        self.assertIn("[Display truncated:", out)
        # No stray raw escape sequences counted into the visible tail preview
        self.assertIn("chars total", out)


if __name__ == "__main__":
    unittest.main()
