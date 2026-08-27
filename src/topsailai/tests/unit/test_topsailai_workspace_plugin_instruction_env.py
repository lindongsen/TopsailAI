"""
Unit tests for workspace/plugin_instruction/env.py

Author: DawsonLin
Test Engineer: mm-m25
Purpose: Test environment variable instruction handlers
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock


class TestGetEnv(unittest.TestCase):
    """Test get_env() function"""

    def setUp(self):
        """Import module for each test"""
        if 'topsailai.workspace.plugin_instruction.env' in sys.modules:
            del sys.modules['topsailai.workspace.plugin_instruction.env']

    def test_get_env_success(self):
        """Test get_env returns value when key exists"""
        from topsailai.workspace.plugin_instruction.env import get_env
        
        with patch('topsailai.workspace.plugin_instruction.env.os.getenv', return_value='test_value'):
            result = get_env('TEST_KEY')
            self.assertEqual(result, 'test_value')

    def test_get_env_not_found(self):
        """Test get_env returns None when key does not exist"""
        from topsailai.workspace.plugin_instruction.env import get_env
        
        with patch('topsailai.workspace.plugin_instruction.env.os.getenv', return_value=None):
            result = get_env('NONEXISTENT_KEY')
            self.assertIsNone(result)

    def test_get_env_converts_to_string(self):
        """Test get_env converts key to string"""
        from topsailai.workspace.plugin_instruction.env import get_env
        
        with patch('topsailai.workspace.plugin_instruction.env.os.getenv', return_value='value'):
            result = get_env(123)
            self.assertEqual(result, 'value')


class TestSetEnv(unittest.TestCase):
    """Test set_env() function"""

    def setUp(self):
        """Import module for each test"""
        if 'topsailai.workspace.plugin_instruction.env' in sys.modules:
            del sys.modules['topsailai.workspace.plugin_instruction.env']

    def test_set_env_success(self):
        """Test set_env sets environment variable"""
        from topsailai.workspace.plugin_instruction.env import set_env
        
        with patch('topsailai.workspace.plugin_instruction.env.os.getenv', return_value=None):
            with patch('topsailai.workspace.plugin_instruction.env.os.environ', {}):
                with patch('builtins.print') as mock_print:
                    set_env('NEW_KEY', 'new_value')
                    mock_print.assert_called_once()
                    call_args = mock_print.call_args[0][0]
                    self.assertIn('set environment ok', call_args)
                    self.assertIn('old=None', call_args)
                    self.assertIn('new=new_value', call_args)

    def test_set_env_overwrites_existing(self):
        """Test set_env overwrites existing environment variable"""
        from topsailai.workspace.plugin_instruction.env import set_env
        
        with patch('topsailai.workspace.plugin_instruction.env.os.getenv', return_value='old_value'):
            with patch('topsailai.workspace.plugin_instruction.env.os.environ', {}):
                with patch('builtins.print') as mock_print:
                    set_env('EXISTING_KEY', 'new_value')
                    call_args = mock_print.call_args[0][0]
                    self.assertIn('old=old_value', call_args)

    def test_set_env_converts_to_string(self):
        """Test set_env converts key and value to string"""
        from topsailai.workspace.plugin_instruction.env import set_env
        
        with patch('topsailai.workspace.plugin_instruction.env.os.getenv', return_value=None):
            with patch('topsailai.workspace.plugin_instruction.env.os.environ', {}):
                with patch('builtins.print'):
                    set_env(123, 456)
                    # Should not raise, conversion works

    def test_set_env_empty_key(self):
        """Test set_env handles empty key"""
        from topsailai.workspace.plugin_instruction.env import set_env
        
        with patch('topsailai.workspace.plugin_instruction.env.os.getenv', return_value=None):
            with patch('topsailai.workspace.plugin_instruction.env.os.environ', {}):
                with patch('builtins.print') as mock_print:
                    set_env('', 'value')
                    # Empty key should still work (str('') = '')


class TestInstructions(unittest.TestCase):
    """Test INSTRUCTIONS dictionary"""

    def setUp(self):
        """Import module for each test"""
        if 'topsailai.workspace.plugin_instruction.env' in sys.modules:
            del sys.modules['topsailai.workspace.plugin_instruction.env']

    def test_instructions_has_all_keys(self):
        """Test INSTRUCTIONS has required keys"""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS
        
        self.assertIn('set', INSTRUCTIONS)
        self.assertIn('get', INSTRUCTIONS)
        self.assertIn('print_step_mode', INSTRUCTIONS)

    def test_instructions_correct_count(self):
        """Test INSTRUCTIONS has exactly 3 entries"""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS
        
        self.assertEqual(len(INSTRUCTIONS), 3)

    def test_instructions_callable_values(self):
        """Test INSTRUCTIONS values are callable"""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS
        
        self.assertTrue(callable(INSTRUCTIONS['set']))
        self.assertTrue(callable(INSTRUCTIONS['get']))
        self.assertTrue(callable(INSTRUCTIONS['print_step_mode']))

    def test_instructions_set_is_set_env(self):
        """Test INSTRUCTIONS['set'] is set_env function"""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS, set_env
        
        self.assertEqual(INSTRUCTIONS['set'], set_env)

    def test_instructions_get_is_get_env(self):
        """Test INSTRUCTIONS['get'] is get_env function"""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS, get_env
        
        self.assertEqual(INSTRUCTIONS['get'], get_env)


class TestPrintStepMode(unittest.TestCase):
    """Test print_step_mode() instruction"""

    ENV_KEY = 'TOPSAILAI_PRINT_STEP_MODE'

    def setUp(self):
        """Save and clear the step-mode environment variable"""
        self.original_mode = os.environ.pop(self.ENV_KEY, None)

    def tearDown(self):
        """Restore the step-mode environment variable"""
        os.environ.pop(self.ENV_KEY, None)
        if self.original_mode is not None:
            os.environ[self.ENV_KEY] = self.original_mode

    def test_list_marks_current_with_asterisk(self):
        """Listing modes marks the current mode with '*' and numbers every choice"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        os.environ[self.ENV_KEY] = 'simple'
        output = print_step_mode()

        self.assertIn('TOPSAILAI_PRINT_STEP_MODE', output)
        self.assertIn('current: simple', output)
        self.assertIn('1.', output)
        self.assertIn('2.', output)
        self.assertIn('* simple', output)
        self.assertNotIn('* normal', output)

    def test_list_marks_default_when_unset(self):
        """Listing modes marks 'normal' when the variable is unset"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        output = print_step_mode()

        self.assertIn('current: normal', output)
        self.assertIn('* normal', output)

    def test_select_by_index(self):
        """Selecting by 1-based index sets the environment variable"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        os.environ[self.ENV_KEY] = 'normal'
        result = print_step_mode('2')

        self.assertIn('set environment ok', result)
        self.assertIn('new=simple', result)
        self.assertEqual(os.environ[self.ENV_KEY], 'simple')

    def test_select_by_name(self):
        """Selecting by mode name sets the environment variable"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        result = print_step_mode('simple')

        self.assertIn('new=simple', result)
        self.assertEqual(os.environ[self.ENV_KEY], 'simple')

    def test_select_by_name_is_case_insensitive(self):
        """Mode names are matched case-insensitively and stored lowercased"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        result = print_step_mode('SIMPLE')

        self.assertIn('new=simple', result)
        self.assertEqual(os.environ[self.ENV_KEY], 'simple')

    def test_invalid_index_is_rejected(self):
        """An out-of-range index reports the valid range and keeps the value"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        os.environ[self.ENV_KEY] = 'normal'
        result = print_step_mode('9')

        self.assertIn('Invalid index: 9', result)
        self.assertIn('Valid range: 1-2', result)
        self.assertEqual(os.environ[self.ENV_KEY], 'normal')

    def test_invalid_mode_is_rejected(self):
        """An unknown mode name reports valid values and keeps the value"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        os.environ[self.ENV_KEY] = 'normal'
        result = print_step_mode('bogus')

        self.assertIn('Invalid mode: bogus', result)
        self.assertIn('normal', result)
        self.assertIn('simple', result)
        self.assertEqual(os.environ[self.ENV_KEY], 'normal')

    def test_empty_argument_returns_usage(self):
        """A blank argument returns usage without changing the value"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        os.environ[self.ENV_KEY] = 'simple'
        result = print_step_mode('   ')

        self.assertIn('Usage: /print_step_mode', result)
        self.assertEqual(os.environ[self.ENV_KEY], 'simple')

    def test_invalid_current_value_falls_back_to_default_marker(self):
        """An invalid current value shows the effective fallback mode as current"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        os.environ[self.ENV_KEY] = 'verbose'
        output = print_step_mode()

        self.assertIn('current: normal', output)
        self.assertIn('* normal', output)
        self.assertNotIn('verbose', output)

    def test_index_beyond_supported_values_is_rejected(self):
        """Only supported values are selectable, so extra indexes are invalid"""
        from topsailai.workspace.plugin_instruction.env import print_step_mode

        os.environ[self.ENV_KEY] = 'verbose'
        result = print_step_mode('3')

        self.assertIn('Invalid index: 3', result)
        self.assertEqual(os.environ[self.ENV_KEY], 'verbose')


if __name__ == '__main__':
    unittest.main()
