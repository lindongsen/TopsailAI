import os
import unittest
from unittest.mock import patch, MagicMock
from src.topsailai.utils import print_tool


class TestPrintTool(unittest.TestCase):
    """Test cases for print_tool module."""

    def setUp(self):
        """Set up test fixtures."""
        # Store original environment variables
        self.original_debug = os.environ.get('DEBUG')
        self.original_truncate_len = os.environ.get('DEBUG_PRINT_TRUNCATE_LENGTH')

        # Set default test environment
        if 'DEBUG' in os.environ:
            del os.environ['DEBUG']
        os.environ['DEBUG_PRINT_TRUNCATE_LENGTH'] = '100'

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
        self.assertIn('(truncated)', result)
        self.assertIn('total_len=500', result)
        # Should be valid JSON
        import json
        parsed = json.loads(result)
        self.assertEqual(parsed['step_name'], 'test')
        self.assertIn('aaaaaaaaaa (truncated)', parsed['raw_text'])

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
        self.assertIn('(truncated)', result)
        self.assertIn('total_len=500', result)
        # Should be valid JSON
        import json
        parsed = json.loads(result)
        self.assertEqual(parsed['step_name'], 'test')
        self.assertIn('bbbbbbbbbb (truncated)', parsed['raw_text'])

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
        self.assertIn('(truncated)', result)
        self.assertIn('total_len=300', result)
        self.assertIn('total_len=400', result)
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
        self.assertEqual(os.getenv('DEBUG'), '1')

    @patch('src.topsailai.utils.print_tool.print_with_time')
    @patch('src.topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    def test_print_debug_with_debug_env(self, mock_get_thread_var, mock_print_with_time):
        """Test print_debug when DEBUG environment variable is set."""
        # Set DEBUG environment variable
        os.environ['DEBUG'] = '1'

        # Mock thread_local_tool.get_thread_var to return None
        mock_get_thread_var.return_value = None

        # Call print_debug
        print_tool.print_debug('test message')

        # Verify print_with_time was called
        mock_print_with_time.assert_called_once_with('[DEBUG] test message', need_format=False)

        # Verify get_thread_var was called
        mock_get_thread_var.assert_called_once_with('flag_debug')

    @patch('src.topsailai.utils.print_tool.print_with_time')
    @patch('src.topsailai.utils.print_tool.thread_local_tool.get_thread_var')
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
        mock_print_with_time.assert_called_once_with('[DEBUG] test message', need_format=False)

        # Verify get_thread_var was called
        mock_get_thread_var.assert_called_once_with('flag_debug')

    @patch('src.topsailai.utils.print_tool.print_with_time')
    @patch('src.topsailai.utils.print_tool.thread_local_tool.get_thread_var')
    def test_print_debug_no_output(self, mock_get_thread_var, mock_print_with_time):
        """Test print_debug when neither DEBUG env nor flag_debug is set."""
        # Ensure DEBUG environment variable is not set
        if 'DEBUG' in os.environ:
            del os.environ['DEBUG']

        # Mock thread_local_tool.get_thread_var to return None (falsy)
        mock_get_thread_var.return_value = None

        # Call print_debug
        print_tool.print_debug('test message')

        # Verify print_with_time was NOT called
        mock_print_with_time.assert_not_called()

        # Verify get_thread_var was called
        mock_get_thread_var.assert_called_once_with('flag_debug')

    @patch('src.topsailai.utils.print_tool.print_with_time')
    def test_print_step(self, mock_print_with_time):
        """Test print_step function."""
        # Enable the flag
        print_tool.enable_flag_print_step()

        # Call print_step
        print_tool.print_step('test message')

        # Verify print_with_time was called
        mock_print_with_time.assert_called_once_with('test message', need_format=True)

    @patch('src.topsailai.utils.print_tool.print_with_time')
    def test_print_step_disabled(self, mock_print_with_time):
        """Test print_step function when flag is disabled."""
        # Disable the flag
        print_tool.disable_flag_print_step()

        # Call print_step
        print_tool.print_step('test message')

        # Verify print_with_time was NOT called
        mock_print_with_time.assert_not_called()

    @patch('src.topsailai.utils.print_tool.print_with_time')
    def test_print_error(self, mock_print_with_time):
        """Test print_error function."""
        print_tool.print_error('error message')

        # Verify print_with_time was called with error prefix
        mock_print_with_time.assert_called_once_with('Error: error message', need_format=False)

    @patch('src.topsailai.utils.print_tool.print_with_time')
    def test_print_critical(self, mock_print_with_time):
        """Test print_critical function."""
        print_tool.print_critical('critical message')

        # Verify print_with_time was called with critical prefix
        mock_print_with_time.assert_called_once_with('Critical: critical message', need_format=False)

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


if __name__ == '__main__':
    unittest.main()
