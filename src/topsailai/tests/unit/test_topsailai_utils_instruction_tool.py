"""
Unit tests for utils/instruction_tool module.

This module tests the base HookInstruction implementation that was extracted
from workspace/hook_instruction.py.

Author: AI
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from topsailai.utils.instruction_tool import (
    HookFunc,
    HookBaseUtils,
    HookInstruction,
    TRIGGER_CHARS,
    SPLIT_LINE,
)


def _make_dummy_func(doc="Dummy function doc.", aliases=None):
    """Create a real function with optional docstring and aliases attribute."""
    def dummy_func():
        if doc:
            return doc
        pass
    if doc:
        dummy_func.__doc__ = doc
    if aliases is not None:
        dummy_func.aliases = aliases
    return dummy_func


def _make_mock_callable(doc="Mock doc.", aliases=None):
    """Create a MagicMock callable with a non-None __doc__."""
    mock = MagicMock(return_value=None)
    mock.__doc__ = doc
    if aliases is not None:
        mock.aliases = aliases
    return mock


class TestHookFunc(unittest.TestCase):
    """Test cases for HookFunc class."""

    def test_init_with_description(self):
        """Test HookFunc initialization with description."""
        dummy_func = _make_dummy_func()
        hook = HookFunc("test description", dummy_func)
        self.assertEqual(hook.description, "test description")
        self.assertEqual(hook.func, dummy_func)
        self.assertIsNone(hook.args)
        self.assertIsNone(hook.kwargs)

    def test_init_without_description(self):
        """Test HookFunc initialization without description uses docstring."""
        dummy_func = _make_dummy_func("This is a docstring.")
        hook = HookFunc("", dummy_func)
        self.assertIn("This is a docstring.", hook.description)
        self.assertEqual(hook.func, dummy_func)

    def test_init_with_args_and_kwargs(self):
        """Test HookFunc initialization with args and kwargs."""
        dummy_func = _make_dummy_func()
        hook = HookFunc("desc", dummy_func, args=("arg1",), kwargs={"key": "value"})
        self.assertEqual(hook.args, ("arg1",))
        self.assertEqual(hook.kwargs, {"key": "value"})

    def test_call_with_no_args_no_defaults(self):
        """Test calling HookFunc with no extra args."""
        mock_func = _make_mock_callable()
        hook = HookFunc("", mock_func)
        result = hook()
        self.assertIsNone(result)
        mock_func.assert_called_once_with()

    def test_call_with_no_args_uses_default(self):
        """Test calling HookFunc uses stored args/kwargs."""
        mock_func = _make_mock_callable()
        hook = HookFunc("desc", mock_func, args=("arg1",), kwargs={"key": "value"})
        result = hook()
        self.assertIsNone(result)
        mock_func.assert_called_once_with("arg1", key="value")

    def test_call_with_provided_args(self):
        """Test calling HookFunc with provided args overrides defaults."""
        mock_func = _make_mock_callable()
        hook = HookFunc("desc", mock_func, args=("arg1",), kwargs={"key": "value"})
        result = hook("override", other="new")
        self.assertIsNone(result)
        mock_func.assert_called_once_with("override", other="new")

    def test_call_with_kwargs(self):
        """Test calling HookFunc with kwargs."""
        mock_func = _make_mock_callable()
        hook = HookFunc("", mock_func)
        result = hook(key="value")
        self.assertIsNone(result)
        mock_func.assert_called_once_with(key="value")


class TestHookBaseUtils(unittest.TestCase):
    """Test cases for HookBaseUtils class."""

    def test_class_exists(self):
        """Test HookBaseUtils class exists and can be instantiated."""
        utils = HookBaseUtils()
        self.assertIsInstance(utils, HookBaseUtils)


class TestConstants(unittest.TestCase):
    """Test cases for module constants."""

    def test_trigger_chars_contains_slash(self):
        """Test TRIGGER_CHARS contains '/'."""
        self.assertIn('/', TRIGGER_CHARS)

    def test_split_line_is_string(self):
        """Test SPLIT_LINE is a non-empty string."""
        self.assertIsInstance(SPLIT_LINE, str)
        self.assertTrue(len(SPLIT_LINE) > 0)


class TestHookInstructionBase(unittest.TestCase):
    """Test cases for base HookInstruction in utils/instruction_tool.py."""

    def _make_hook_instruction(self, completions_file=None):
        """Helper to create a HookInstruction with __init__ bypassed."""
        with patch.object(HookInstruction, '__init__', lambda x, **kwargs: None):
            hook_inst = HookInstruction()
        hook_inst.hook_map = {}
        hook_inst.file_input_completions = completions_file or ""
        return hook_inst

    def _write_completions_file(self, path, entries):
        """Helper to write a completions JSON file."""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({"completions": entries}, f)

    def test_init_sets_completions_path(self):
        """Test __init__ stores file_input_completions and loads instructions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "completions.json")
            instructions = {"/noop": _make_dummy_func()}
            inst = HookInstruction(file_input_completions=path, instructions=instructions)
            self.assertEqual(inst.file_input_completions, path)
            self.assertIn("/noop", inst.hook_map)
            self.assertIn("/help", inst.hook_map)

    def test_add_hook_creates_new_hook(self):
        """Test add_hook creates a new hook entry."""
        hook_inst = self._make_hook_instruction()
        dummy = _make_dummy_func()
        hook_inst.add_hook('/test', dummy)
        self.assertIn('/test', hook_inst.hook_map)
        self.assertEqual(len(hook_inst.hook_map['/test']), 1)
        self.assertEqual(hook_inst.hook_map['/test'][0].func, dummy)

    def test_add_hook_appends_to_existing(self):
        """Test add_hook appends to existing hook list."""
        hook_inst = self._make_hook_instruction()
        dummy1 = _make_dummy_func()
        dummy2 = _make_dummy_func()
        hook_inst.add_hook('/test', dummy1)
        hook_inst.add_hook('/test', dummy2)
        self.assertEqual(len(hook_inst.hook_map['/test']), 2)

    def test_add_hook_raises_on_non_callable(self):
        """Test add_hook raises on non-callable."""
        hook_inst = self._make_hook_instruction()
        with self.assertRaises(AssertionError):
            hook_inst.add_hook('/test', "not callable")

    def test_add_hook_wraps_callable(self):
        """Test add_hook wraps callable in HookFunc."""
        hook_inst = self._make_hook_instruction()
        dummy = _make_dummy_func()
        hook_inst.add_hook('/test', dummy)
        self.assertIsInstance(hook_inst.hook_map['/test'][0], HookFunc)

    def test_add_hook_calls_refresh_input_completions(self):
        """Test add_hook triggers refresh_input_completions."""
        hook_inst = self._make_hook_instruction()
        with patch.object(hook_inst, 'refresh_input_completions') as mock_refresh:
            dummy = _make_dummy_func()
            hook_inst.add_hook('/test', dummy)
            mock_refresh.assert_called_once()

    def test_del_hook_removes_function(self):
        """Test del_hook removes a specific function and its key when empty."""
        hook_inst = self._make_hook_instruction()
        dummy = _make_dummy_func()
        hook_inst.add_hook('/test', dummy)
        hook_func = hook_inst.hook_map['/test'][0]
        hook_inst.del_hook('/test', hook_func)
        # The implementation removes the HookFunc and deletes the empty key.
        self.assertNotIn('/test', hook_inst.hook_map)

    def test_del_hook_removes_empty_key_and_completion(self):
        """Test del_hook removes empty key and stale completion entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "completions.json")
            hook_inst = self._make_hook_instruction(path)

            def cmd1():
                """cmd1 doc."""
                pass

            hook_inst.add_hook('/cmd1', cmd1)
            assert '/cmd1' in hook_inst.hook_map
            assert hook_inst.hook_map['/cmd1']

            hook_func = hook_inst.hook_map['/cmd1'][0]
            hook_inst.del_hook('/cmd1', hook_func)

            # hook_map should no longer contain the empty key
            self.assertNotIn('/cmd1', hook_inst.hook_map)

            # completions file should no longer contain /cmd1
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            texts = [c['text'] for c in data.get('completions', [])]
            self.assertNotIn('/cmd1', texts)

    def test_del_hook_nonexistent_hook(self):
        """Test del_hook on nonexistent hook is safe."""
        hook_inst = self._make_hook_instruction()
        hook_inst.del_hook('/nonexistent', HookFunc("", _make_dummy_func()))
        self.assertEqual(hook_inst.hook_map, {})

    def test_del_hook_nonexistent_func(self):
        """Test del_hook with nonexistent func leaves key intact."""
        hook_inst = self._make_hook_instruction()
        dummy = _make_dummy_func()
        hook_inst.add_hook('/test', dummy)
        other_func = HookFunc("", _make_dummy_func())
        hook_inst.del_hook('/test', other_func)
        self.assertIn('/test', hook_inst.hook_map)

    def test_del_hook_calls_refresh_input_completions(self):
        """Test del_hook triggers refresh_input_completions."""
        hook_inst = self._make_hook_instruction()
        dummy = _make_dummy_func()
        hook_inst.add_hook('/test', dummy)
        hook_func = hook_inst.hook_map['/test'][0]
        with patch.object(hook_inst, 'refresh_input_completions') as mock_refresh:
            hook_inst.del_hook('/test', hook_func)
            mock_refresh.assert_called_once()

    def test_exist_hook_with_valid_hook(self):
        """Test exist_hook returns True for valid hook."""
        hook_inst = self._make_hook_instruction()
        dummy = _make_dummy_func()
        hook_inst.add_hook('/test', dummy)
        self.assertTrue(hook_inst.exist_hook('/test'))

    def test_exist_hook_nonexistent(self):
        """Test exist_hook returns False for nonexistent hook."""
        hook_inst = self._make_hook_instruction()
        self.assertFalse(hook_inst.exist_hook('/nonexistent'))

    def test_exist_hook_without_trigger_char(self):
        """Test exist_hook returns False for hook without trigger char."""
        hook_inst = self._make_hook_instruction()
        dummy = _make_dummy_func()
        hook_inst.add_hook('/test', dummy)
        self.assertFalse(hook_inst.exist_hook('test'))

    def test_exist_hook_with_hook_and_kwargs(self):
        """Test exist_hook checks kwargs requirement."""
        hook_inst = self._make_hook_instruction()
        dummy = _make_dummy_func()
        hook_inst.add_hook('/test', dummy)
        self.assertTrue(hook_inst.exist_hook('/test'))
        self.assertTrue(hook_inst.exist_hook('/test arg1'))

    def test_is_help_various_formats(self):
        """Test __is_help recognizes help strings."""
        hook_inst = self._make_hook_instruction()
        self.assertTrue(hook_inst._HookInstruction__is_help('help'))
        self.assertTrue(hook_inst._HookInstruction__is_help('--help'))
        self.assertTrue(hook_inst._HookInstruction__is_help('-h'))

    def test_is_help_non_help_strings(self):
        """Test __is_help rejects non-help strings."""
        hook_inst = self._make_hook_instruction()
        self.assertFalse(hook_inst._HookInstruction__is_help('arg'))
        self.assertFalse(hook_inst._HookInstruction__is_help(''))
        self.assertFalse(hook_inst._HookInstruction__is_help(123))

    @patch('topsailai.utils.instruction_tool.json_tool')
    @patch('topsailai.utils.instruction_tool.format_tool')
    def test_call_hook_with_help_string(self, mock_format, mock_json):
        """Test call_hook shows help for help strings."""
        hook_inst = self._make_hook_instruction()
        mock_func = _make_mock_callable()
        hook_inst.add_hook('/test', mock_func)
        with patch.object(hook_inst, 'show_help') as mock_help:
            hook_inst.call_hook('/test', 'help')
            mock_help.assert_called_once_with('/test')

    @patch('topsailai.utils.instruction_tool.json_tool')
    @patch('topsailai.utils.instruction_tool.format_tool')
    def test_call_hook_with_json_kwargs(self, mock_format, mock_json):
        """Test call_hook parses JSON kwargs."""
        hook_inst = self._make_hook_instruction()
        mock_func = _make_mock_callable()
        hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
        mock_json.safe_json_load.return_value = {'key': 'value'}
        hook_inst.call_hook('/test', '{"key": "value"}')
        mock_func.assert_called_once_with(key='value')

    @patch('topsailai.utils.instruction_tool.json_tool')
    @patch('topsailai.utils.instruction_tool.format_tool')
    def test_call_hook_with_key_value_kwargs(self, mock_format, mock_json):
        """Test call_hook parses key=value kwargs."""
        hook_inst = self._make_hook_instruction()
        mock_func = _make_mock_callable()
        hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
        mock_json.safe_json_load.return_value = None
        mock_format.parse_str_to_dict.return_value = {'key': 'value'}
        hook_inst.call_hook('/test', 'key=value')
        mock_func.assert_called_once_with(key='value')

    @patch('topsailai.utils.instruction_tool.json_tool')
    @patch('topsailai.utils.instruction_tool.format_tool')
    def test_call_hook_with_space_separated_args(self, mock_format, mock_json):
        """Test call_hook parses space-separated args."""
        hook_inst = self._make_hook_instruction()
        mock_func = _make_mock_callable()
        hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
        mock_json.safe_json_load.return_value = None
        hook_inst.call_hook('/test', 'arg1 arg2')
        mock_func.assert_called_once_with('arg1', 'arg2')

    @patch('topsailai.utils.instruction_tool.json_tool')
    @patch('topsailai.utils.instruction_tool.format_tool')
    def test_call_hook_nonexistent_shows_help(self, mock_format, mock_json):
        """Test call_hook shows help for nonexistent hook."""
        hook_inst = self._make_hook_instruction()
        with patch.object(hook_inst, 'show_help') as mock_help:
            hook_inst.call_hook('/nonexistent')
            mock_help.assert_called_once_with('/nonexistent')

    @patch('topsailai.utils.instruction_tool.json_tool')
    @patch('topsailai.utils.instruction_tool.format_tool')
    def test_call_hook_empty_hook_name(self, mock_format, mock_json):
        """Test call_hook handles empty hook name."""
        hook_inst = self._make_hook_instruction()
        result = hook_inst.call_hook('')
        self.assertIsNone(result)

    @patch('topsailai.utils.instruction_tool.json_tool')
    @patch('topsailai.utils.instruction_tool.format_tool')
    def test_call_hook_exception_handling(self, mock_format, mock_json):
        """Test call_hook handles exceptions in hook functions."""
        hook_inst = self._make_hook_instruction()
        mock_func = _make_mock_callable()
        mock_func.side_effect = Exception("test error")
        hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
        result = hook_inst.call_hook('/test')
        self.assertIsNone(result)

    @patch('topsailai.utils.instruction_tool.json_tool')
    @patch('topsailai.utils.instruction_tool.format_tool')
    def test_call_hook_with_return_value(self, mock_format, mock_json):
        """Test call_hook prints return value if truthy."""
        hook_inst = self._make_hook_instruction()
        mock_func = _make_mock_callable()
        mock_func.return_value = "result value"
        hook_inst.hook_map = {'/test': [HookFunc("test", mock_func)]}
        with patch('builtins.print') as mock_print:
            hook_inst.call_hook('/test')
            mock_print.assert_called_with("result value")

    def test_load_existing_completions_file_exists(self):
        """Test _load_existing_completions loads valid file."""
        hook_inst = self._make_hook_instruction()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"completions": [{"text": "/help", "aliases": ["/h"]}]}, f)
            path = f.name
        try:
            hook_inst.file_input_completions = path
            result = hook_inst._load_existing_completions()
            self.assertEqual(result, {"/help": ["/h"]})
        finally:
            os.unlink(path)

    def test_load_existing_completions_file_not_exists(self):
        """Test _load_existing_completions returns empty dict for missing file."""
        hook_inst = self._make_hook_instruction()
        hook_inst.file_input_completions = '/nonexistent/path.json'
        result = hook_inst._load_existing_completions()
        self.assertEqual(result, {})

    def test_load_existing_completions_malformed(self):
        """Test _load_existing_completions handles malformed JSON."""
        hook_inst = self._make_hook_instruction()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            hook_inst.file_input_completions = path
            result = hook_inst._load_existing_completions()
            self.assertEqual(result, {})
        finally:
            os.unlink(path)

    def test_extract_completion_doc_with_docstring(self):
        """Test _extract_completion_doc extracts docstring."""
        hook_inst = self._make_hook_instruction()

        def func_with_doc():
            """This is a help doc."""
            pass
        doc = hook_inst._extract_completion_doc(func_with_doc)
        self.assertEqual(doc, "This is a help doc.")

    def test_extract_completion_doc_without_docstring(self):
        """Test _extract_completion_doc returns empty for no docstring."""
        hook_inst = self._make_hook_instruction()
        doc = hook_inst._extract_completion_doc(_make_dummy_func(doc=None))
        self.assertEqual(doc, "")

    def test_generate_input_completions_basic(self):
        """Test generate_input_completions creates expected JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "completions.json")
            hook_inst = self._make_hook_instruction(path)
            dummy = _make_dummy_func("A dummy hook.")
            hook_inst.add_hook('/dummy', dummy)
            hook_inst.generate_input_completions()

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.assertIn('completions', data)
            self.assertEqual(len(data['completions']), 1)
            self.assertEqual(data['completions'][0]['text'], '/dummy')

    def test_generate_input_completions_preserves_existing_aliases(self):
        """Test generate_input_completions preserves aliases from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "completions.json")
            self._write_completions_file(path, [
                {"text": "/help", "aliases": ["/h", "/?"], "doc": "old doc"}
            ])
            hook_inst = self._make_hook_instruction(path)
            help_func = _make_dummy_func("Help command.", aliases=["/h"])
            hook_inst.add_hook('/help', help_func)
            hook_inst.generate_input_completions()

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            entry = data['completions'][0]
            self.assertEqual(set(entry['aliases']), {'/h', '/?'})

    def test_generate_input_completions_removes_stale_commands(self):
        """Test generate_input_completions removes stale commands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "completions.json")
            self._write_completions_file(path, [
                {"text": "/stale", "aliases": [], "doc": "stale"}
            ])
            hook_inst = self._make_hook_instruction(path)
            active_func = _make_dummy_func("Active command.")
            hook_inst.add_hook('/active', active_func)
            hook_inst.generate_input_completions()

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            texts = [c['text'] for c in data['completions']]
            self.assertNotIn('/stale', texts)
            self.assertIn('/active', texts)

    def test_generate_input_completions_includes_func_aliases(self):
        """Test generate_input_completions includes aliases from function attribute."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "completions.json")
            hook_inst = self._make_hook_instruction(path)
            func_with_aliases = _make_dummy_func("Command with aliases.", aliases=['/a', '/aa'])
            hook_inst.add_hook('/aliases', func_with_aliases)
            hook_inst.generate_input_completions()

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            entry = data['completions'][0]
            self.assertEqual(set(entry['aliases']), {'/a', '/aa'})

    def test_refresh_input_completions_writes_file(self):
        """Test refresh_input_completions writes completions file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "completions.json")
            hook_inst = self._make_hook_instruction(path)
            dummy = _make_dummy_func("Dummy.")
            hook_inst.add_hook('/dummy', dummy)
            hook_inst.refresh_input_completions()

            self.assertTrue(os.path.exists(path))

    def test_refresh_input_completions_swallows_exceptions(self):
        """Test refresh_input_completions does not raise on errors."""
        hook_inst = self._make_hook_instruction('/nonexistent_dir/completions.json')
        dummy = _make_dummy_func("Dummy.")
        hook_inst.add_hook('/dummy', dummy)
        # Should not raise
        hook_inst.refresh_input_completions()

    @patch('topsailai.utils.instruction_tool.readline')
    def test_setup_readline_completion(self, mock_readline):
        """Test setup_readline_completion registers completer."""
        hook_inst = self._make_hook_instruction()
        dummy = _make_dummy_func()
        # Avoid refresh side effects during add_hook.
        with patch.object(hook_inst, 'refresh_input_completions'):
            hook_inst.add_hook('/help', dummy)
        hook_inst.setup_readline_completion()
        mock_readline.set_completer.assert_called_once()
        mock_readline.parse_and_bind.assert_called_with('tab: complete')

if __name__ == '__main__':
    unittest.main()
