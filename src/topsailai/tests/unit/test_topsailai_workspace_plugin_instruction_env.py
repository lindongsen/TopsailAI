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

    def test_instructions_correct_count(self):
        """Test INSTRUCTIONS has exactly 2 entries"""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS
        
        self.assertEqual(len(INSTRUCTIONS), 2)

    def test_instructions_callable_values(self):
        """Test INSTRUCTIONS values are callable"""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS
        
        self.assertTrue(callable(INSTRUCTIONS['set']))
        self.assertTrue(callable(INSTRUCTIONS['get']))

    def test_instructions_set_is_set_env(self):
        """Test INSTRUCTIONS['set'] is set_env function"""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS, set_env
        
        self.assertEqual(INSTRUCTIONS['set'], set_env)

    def test_instructions_get_is_get_env(self):
        """Test INSTRUCTIONS['get'] is get_env function"""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS, get_env
        
        self.assertEqual(INSTRUCTIONS['get'], get_env)


if __name__ == '__main__':
    unittest.main()
