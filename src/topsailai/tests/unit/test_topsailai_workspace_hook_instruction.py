"""
Unit tests for workspace/hook_instruction module.

This module tests the HookFunc and HookInstruction classes which provide
a flexible hook system for managing and executing instruction-based hooks.

Author: AI
"""

import unittest
from unittest.mock import patch, MagicMock


# Mock the imports before importing the module under test
with patch.dict('sys.modules', {
    'topsailai.utils': MagicMock(),
    'topsailai.utils.json_tool': MagicMock(),
    'topsailai.utils.print_tool': MagicMock(),
    'topsailai.utils.format_tool': MagicMock(),
    'topsailai.workspace.plugin_instruction': MagicMock(),
    'topsailai.workspace.plugin_instruction.base': MagicMock(),
    'topsailai.workspace.plugin_instruction.base.init': MagicMock(),
}):
    from topsailai.workspace.hook_instruction import (
        HookFunc,
        HookBaseUtils,
        HookInstruction,
        TRIGGER_CHARS,
        SPLIT_LINE,
    )


class TestHookFunc(unittest.TestCase):
    """Test cases for HookFunc class."""

    def test_init_with_description(self):
        """Test HookFunc initialization with description."""
        def dummy_func():
            pass
        hook = HookFunc("test description", dummy_func)
        self.assertEqual(hook.description, "test description")
        self.assertEqual(hook.func, dummy_func)
        self.assertIsNone(hook.args)
        self.assertIsNone(hook.kwargs)

    def test_init_without_description(self):
        """Test HookFunc initialization without description uses func docstring."""
        def dummy_func():
            """This is docstring."""
            pass
        hook = HookFunc("", dummy_func)
        # When description is empty, it uses print_tool.add_indent_to_lines(func.__doc__)
        # With mocking, this returns a MagicMock, so we just verify description is set
        self.assertTrue(hook.description is not None)

    def test_init_with_args_and_kwargs(self):
        """Test HookFunc initialization with args and kwargs."""
        def dummy_func(a, b, c=None):
            pass
        hook = HookFunc("test", dummy_func, args=(1, 2), kwargs={'c': 3})
        self.assertEqual(hook.args, (1, 2))
        self.assertEqual(hook.kwargs, {'c': 3})

    def test_call_with_no_args_uses_default(self):
        """Test __call__ uses default args when none provided."""
        def dummy_func(a, b):
            return a + b
        hook = HookFunc("test", dummy_func, args=(1, 2))
        result = hook()
        self.assertEqual(result, 3)

    def test_call_with_provided_args(self):
        """Test __call__ uses provided args over defaults."""
        def dummy_func(a, b):
            return a * b
        hook = HookFunc("test", dummy_func, args=(1, 2))
        result = hook(3, 4)
        self.assertEqual(result, 12)

    def test_call_with_no_args_no_defaults(self):
        """Test __call__ with no args and no defaults."""
        def dummy_func():
            return "called"
        hook = HookFunc("test", dummy_func)
        result = hook()
        self.assertEqual(result, "called")

    def test_call_with_kwargs(self):
        """Test __call__ with keyword arguments."""
        def dummy_func(a, b, c=0):
            return a + b + c
        hook = HookFunc("test", dummy_func, kwargs={'c': 10})
        result = hook(1, 2)
        self.assertEqual(result, 13)


class TestHookBaseUtils(unittest.TestCase):
    """Test cases for HookBaseUtils class."""

    def test_class_exists(self):
        """Test HookBaseUtils class can be instantiated."""
        utils = HookBaseUtils()
        self.assertIsInstance(utils, HookBaseUtils)


class TestHookInstruction(unittest.TestCase):
    """Test cases for HookInstruction class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_instructions = {
            'test_cmd': MagicMock(),
            '/existing': MagicMock(),
        }
        # Patch INSTRUCTIONS to control what hooks are loaded
        self.instruction_patcher = patch(
            'topsailai.workspace.hook_instruction.INSTRUCTIONS',
            self.mock_instructions
        )
        self.instruction_patcher.start()

    def tearDown(self):
        """Clean up after tests."""
        self.instruction_patcher.stop()

    def test_init_creates_default_help_hook(self):
        """Test __init__ creates default /help hook."""
        with patch.object(HookInstruction, 'load_instructions'):
            hook_inst = HookInstruction()
            self.assertIn('/help', hook_inst.hook_map)
            self.assertTrue(len(hook_inst.hook_map['/help']) > 0)

    def test_load_instructions_adds_hooks(self):
        """Test load_instructions adds instructions to hook_map."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            instructions = {
                'clear': MagicMock(),
                'story': MagicMock(),
            }
            hook_inst.load_instructions(instructions)
            self.assertIn('/clear', hook_inst.hook_map)
            self.assertIn('/story', hook_inst.hook_map)

    def test_load_instructions_preserves_existing_trigger(self):
        """Test load_instructions preserves existing trigger char."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            instructions = {
                '/custom': MagicMock(),
            }
            hook_inst.load_instructions(instructions)
            self.assertIn('/custom', hook_inst.hook_map)

    def test_add_hook_creates_new_hook(self):
        """Test add_hook creates new hook entry."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            def dummy_func():
                pass
            hook_inst.add_hook('/new', dummy_func, "new hook")
            self.assertIn('/new', hook_inst.hook_map)
            self.assertEqual(len(hook_inst.hook_map['/new']), 1)

    def test_add_hook_appends_to_existing(self):
        """Test add_hook appends to existing hook entry."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {'/test': []}
            def dummy_func():
                pass
            hook_inst.add_hook('/test', dummy_func)
            self.assertEqual(len(hook_inst.hook_map['/test']), 1)

    def test_add_hook_adds_trigger_char(self):
        """Test add_hook adds trigger char if missing."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            def dummy_func():
                pass
            hook_inst.add_hook('clear', dummy_func)
            self.assertIn('/clear', hook_inst.hook_map)

    def test_add_hook_wraps_callable(self):
        """Test add_hook wraps callable in HookFunc."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            def dummy_func():
                pass
            hook_inst.add_hook('/test', dummy_func, "description")
            hook_func = hook_inst.hook_map['/test'][0]
            self.assertIsInstance(hook_func, HookFunc)

    def test_add_hook_raises_on_non_callable(self):
        """Test add_hook raises AssertionError for non-callable."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            with self.assertRaises(AssertionError):
                hook_inst.add_hook('/test', "not callable")

    def test_del_hook_removes_function(self):
        """Test del_hook removes hook function."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {'/test': []}
            hook_func = HookFunc("test", MagicMock())
            hook_inst.hook_map['/test'].append(hook_func)
            hook_inst.del_hook('/test', hook_func)
            self.assertEqual(len(hook_inst.hook_map['/test']), 0)

    def test_del_hook_nonexistent_hook(self):
        """Test del_hook handles nonexistent hook gracefully."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            hook_func = HookFunc("test", MagicMock())
            # Should not raise
            hook_inst.del_hook('/nonexistent', hook_func)

    def test_del_hook_nonexistent_func(self):
        """Test del_hook handles nonexistent function gracefully."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {'/test': []}
            hook_func1 = HookFunc("test1", MagicMock())
            hook_func2 = HookFunc("test2", MagicMock())
            hook_inst.hook_map['/test'].append(hook_func1)
            # Should not raise
            hook_inst.del_hook('/test', hook_func2)

    def test_is_help_various_formats(self):
        """Test __is_help recognizes help variations."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            help_formats = ["help", "--help", "-h", "/help", "@help"]
            for fmt in help_formats:
                self.assertTrue(hook_inst._HookInstruction__is_help(fmt))

    def test_is_help_non_help_strings(self):
        """Test __is_help returns False for non-help strings."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            non_help = ["helper", "helpme", "h", "hELP", 123, None]
            for val in non_help:
                self.assertFalse(hook_inst._HookInstruction__is_help(val))

    def test_exist_hook_with_valid_hook(self):
        """Test exist_hook returns True for existing hook."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {'/test': []}
            self.assertTrue(hook_inst.exist_hook('/test'))

    def test_exist_hook_with_hook_and_kwargs(self):
        """Test exist_hook returns True for hook with kwargs."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {'/test': []}
            self.assertTrue(hook_inst.exist_hook('/test arg1'))

    def test_exist_hook_without_trigger_char(self):
        """Test exist_hook returns False without trigger char."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {'/test': []}
            self.assertFalse(hook_inst.exist_hook('test'))

    def test_exist_hook_nonexistent(self):
        """Test exist_hook returns False for nonexistent hook."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            self.assertFalse(hook_inst.exist_hook('/nonexistent'))

    @patch('topsailai.workspace.hook_instruction.json_tool')
    @patch('topsailai.workspace.hook_instruction.format_tool')
    def test_call_hook_with_help_string(self, mock_format, mock_json):
        """Test call_hook shows help for help strings."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {'/test': []}
            with patch.object(hook_inst, 'show_help') as mock_help:
                hook_inst.call_hook('/test', 'help')
                mock_help.assert_called_once_with('/test')

    @patch('topsailai.workspace.hook_instruction.json_tool')
    @patch('topsailai.workspace.hook_instruction.format_tool')
    def test_call_hook_with_json_kwargs(self, mock_format, mock_json):
        """Test call_hook parses JSON kwargs."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            mock_func = MagicMock(return_value=None)
            hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
            mock_json.safe_json_load.return_value = {'key': 'value'}
            hook_inst.call_hook('/test', '{"key": "value"}')
            mock_func.assert_called_once()

    @patch('topsailai.workspace.hook_instruction.json_tool')
    @patch('topsailai.workspace.hook_instruction.format_tool')
    def test_call_hook_with_key_value_kwargs(self, mock_format, mock_json):
        """Test call_hook parses key=value kwargs."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            mock_func = MagicMock(return_value=None)
            hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
            mock_json.safe_json_load.return_value = None
            hook_inst.call_hook('/test', 'key=value')
            mock_func.assert_called_once()

    @patch('topsailai.workspace.hook_instruction.json_tool')
    @patch('topsailai.workspace.hook_instruction.format_tool')
    def test_call_hook_with_space_separated_args(self, mock_format, mock_json):
        """Test call_hook parses space-separated args."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            mock_func = MagicMock(return_value=None)
            hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
            mock_json.safe_json_load.return_value = None
            hook_inst.call_hook('/test', 'arg1 arg2')
            mock_func.assert_called_once()

    @patch('topsailai.workspace.hook_instruction.json_tool')
    @patch('topsailai.workspace.hook_instruction.format_tool')
    def test_call_hook_nonexistent_shows_help(self, mock_format, mock_json):
        """Test call_hook shows help for nonexistent hook."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            with patch.object(hook_inst, 'show_help') as mock_help:
                hook_inst.call_hook('/nonexistent')
                mock_help.assert_called_once_with('/nonexistent')

    @patch('topsailai.workspace.hook_instruction.json_tool')
    @patch('topsailai.workspace.hook_instruction.format_tool')
    def test_call_hook_empty_hook_name(self, mock_format, mock_json):
        """Test call_hook handles empty hook name."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            hook_inst.hook_map = {}
            # Should not raise
            hook_inst.call_hook('')

    @patch('topsailai.workspace.hook_instruction.json_tool')
    @patch('topsailai.workspace.hook_instruction.format_tool')
    def test_call_hook_exception_handling(self, mock_format, mock_json):
        """Test call_hook handles exceptions in hook functions."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            mock_func = MagicMock(side_effect=Exception("test error"))
            hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
            # Should not raise
            hook_inst.call_hook('/test')

    @patch('topsailai.workspace.hook_instruction.json_tool')
    @patch('topsailai.workspace.hook_instruction.format_tool')
    def test_call_hook_with_return_value(self, mock_format, mock_json):
        """Test call_hook prints return value if truthy."""
        with patch.object(HookInstruction, '__init__', lambda x: None):
            hook_inst = HookInstruction()
            mock_func = MagicMock(return_value="result value")
            hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
            with patch('builtins.print') as mock_print:
                hook_inst.call_hook('/test')
                mock_print.assert_called_with("result value")


class TestConstants(unittest.TestCase):
    """Test cases for module constants."""

    def test_trigger_chars_contains_slash(self):
        """Test TRIGGER_CHARS contains forward slash."""
        self.assertIn('/', TRIGGER_CHARS)

    def test_split_line_is_string(self):
        """Test SPLIT_LINE is a non-empty string."""
        self.assertIsInstance(SPLIT_LINE, str)
        self.assertTrue(len(SPLIT_LINE) > 0)


if __name__ == '__main__':
    unittest.main()
