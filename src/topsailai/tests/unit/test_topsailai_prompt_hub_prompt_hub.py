"""
Unit tests for prompt_hub/prompt_tool.py

Author: mm-m25
Purpose: Test prompt_hub module functions
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, mock_open

# Add project root to path
sys.path.insert(0, '/root/ai/TopsailAI/src')


class TestGetExtraPrompt(unittest.TestCase):
    """Test get_extra_prompt function"""

    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    def test_get_extra_prompt_with_files(self, mock_read_prompt, mock_env_instance):
        """Test get_extra_prompt returns content from files"""
        from topsailai.prompt_hub.prompt_tool import get_extra_prompt
        
        mock_env_instance.get_list_str.return_value = ['file1.md', 'file2.md']
        mock_read_prompt.side_effect = ['content1\n', 'content2\n']
        
        result = get_extra_prompt()
        
        self.assertEqual(result, 'content1\ncontent2\n')
        mock_read_prompt.assert_any_call('file1.md')
        mock_read_prompt.assert_any_call('file2.md')

    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    def test_get_extra_prompt_empty(self, mock_env_instance):
        """Test get_extra_prompt returns empty string when no files"""
        from topsailai.prompt_hub.prompt_tool import get_extra_prompt
        
        mock_env_instance.get_list_str.return_value = ''
        
        result = get_extra_prompt()
        
        self.assertEqual(result, '')

    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    def test_get_extra_prompt_none(self, mock_env_instance):
        """Test get_extra_prompt returns empty string when None"""
        from topsailai.prompt_hub.prompt_tool import get_extra_prompt
        
        mock_env_instance.get_list_str.return_value = None
        
        result = get_extra_prompt()
        
        self.assertEqual(result, '')


class TestGetExtraTools(unittest.TestCase):
    """Test get_extra_tools function"""

    @patch('topsailai.prompt_hub.prompt_tool.os.path.exists')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    def test_get_extra_tools_with_tools(self, mock_env_instance, mock_read_prompt, mock_exists):
        """Test get_extra_tools returns formatted tools content"""
        from topsailai.prompt_hub.prompt_tool import get_extra_tools
        
        mock_env_instance.get_list_str.side_effect = ['tool1.md;tool2.md', None]
        mock_exists.return_value = True
        mock_read_prompt.return_value = 'tool content'
        
        result = get_extra_tools()
        
        self.assertIn('# Extra Tools Start', result)
        self.assertIn('tool content', result)
        self.assertIn('# Extra Tools End', result)

    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    def test_get_extra_tools_empty(self, mock_env_instance):
        """Test get_extra_tools returns empty string when no tools"""
        from topsailai.prompt_hub.prompt_tool import get_extra_tools
        
        mock_env_instance.get_list_str.side_effect = [None, None]
        
        result = get_extra_tools()
        
        self.assertEqual(result, '')

    @patch('topsailai.prompt_hub.prompt_tool.os.path.exists')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    def test_get_extra_tools_file_not_exists(self, mock_env_instance, mock_read_prompt, mock_exists):
        """Test get_extra_tools skips non-existent files"""
        from topsailai.prompt_hub.prompt_tool import get_extra_tools
        
        mock_env_instance.get_list_str.side_effect = ['tool1.md', None]
        mock_exists.return_value = False
        
        result = get_extra_tools()
        
        self.assertEqual(result, '')


class TestGetPromptFilePath(unittest.TestCase):
    """Test get_prompt_file_path function"""

    @patch('topsailai.prompt_hub.prompt_tool.os.path.exists')
    @patch('topsailai.prompt_hub.prompt_tool.os.path.join')
    def test_get_prompt_file_path_exists(self, mock_join, mock_exists):
        """Test get_prompt_file_path returns original path if exists"""
        from topsailai.prompt_hub.prompt_tool import get_prompt_file_path
        
        mock_exists.return_value = True
        
        result = get_prompt_file_path('test.md')
        
        self.assertEqual(result, 'test.md')
        mock_join.assert_not_called()

    @patch('topsailai.prompt_hub.prompt_tool.os.path.exists')
    @patch('topsailai.prompt_hub.prompt_tool.os.path.join')
    @patch('topsailai.prompt_hub.prompt_tool.os.path.dirname')
    def test_get_prompt_file_path_with_dirname(self, mock_dirname, mock_join, mock_exists):
        """Test get_prompt_file_path joins with dirname when not exists"""
        from topsailai.prompt_hub.prompt_tool import get_prompt_file_path
        
        mock_exists.side_effect = [False, True]
        mock_dirname.return_value = '/root/ai/TopsailAI/src/topsailai/prompt_hub'
        mock_join.return_value = '/root/ai/TopsailAI/src/topsailai/prompt_hub/test.md'
        
        result = get_prompt_file_path('test.md')
        
        self.assertEqual(result, '/root/ai/TopsailAI/src/topsailai/prompt_hub/test.md')


class TestExistsPromptFile(unittest.TestCase):
    """Test exists_prompt_file function"""

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    @patch('topsailai.prompt_hub.prompt_tool.os.path.exists')
    def test_exists_prompt_file_true(self, mock_exists, mock_get_path):
        """Test exists_prompt_file returns True when file exists"""
        from topsailai.prompt_hub.prompt_tool import exists_prompt_file
        
        mock_get_path.return_value = '/path/to/file.md'
        mock_exists.return_value = True
        
        result = exists_prompt_file('file.md')
        
        self.assertTrue(result)

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    @patch('topsailai.prompt_hub.prompt_tool.os.path.exists')
    def test_exists_prompt_file_false(self, mock_exists, mock_get_path):
        """Test exists_prompt_file returns False when file not exists"""
        from topsailai.prompt_hub.prompt_tool import exists_prompt_file
        
        mock_get_path.return_value = '/path/to/file.md'
        mock_exists.return_value = False
        
        result = exists_prompt_file('file.md')
        
        self.assertFalse(result)


class TestReadPrompt(unittest.TestCase):
    """Test read_prompt function"""

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    def test_read_prompt_with_content(self, mock_get_path):
        """Test read_prompt returns content with separator"""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        
        mock_get_path.return_value = '/path/to/file.md'
        
        with patch('builtins.open', mock_open(read_data='test content')):
            result = read_prompt('file.md')
        
        self.assertEqual(result, 'test content\n---\n\n')

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    def test_read_prompt_ends_with_dash(self, mock_get_path):
        """Test read_prompt adds newline when content ends with ---"""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        
        mock_get_path.return_value = '/path/to/file.md'
        
        with patch('builtins.open', mock_open(read_data='test content---')):
            result = read_prompt('file.md')
        
        self.assertEqual(result, 'test content---\n')

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    def test_read_prompt_ends_with_equals(self, mock_get_path):
        """Test read_prompt adds newline when content ends with ==="""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        
        mock_get_path.return_value = '/path/to/file.md'
        
        with patch('builtins.open', mock_open(read_data='test content===')):
            result = read_prompt('file.md')
        
        self.assertEqual(result, 'test content===\n')

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    def test_read_prompt_empty_content(self, mock_get_path):
        """Test read_prompt returns empty string for empty content"""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        
        mock_get_path.return_value = '/path/to/file.md'
        
        with patch('builtins.open', mock_open(read_data='')):
            result = read_prompt('file.md')
        
        self.assertEqual(result, '')


class TestIsOnlyPureSystemPrompt(unittest.TestCase):
    """Test is_only_pure_system_prompt function"""

    @patch.dict(os.environ, {'PURE_SYSTEM_PROMPT': '1'})
    def test_is_only_pure_system_prompt_true(self):
        """Test is_only_pure_system_prompt returns True when set to 1"""
        from topsailai.prompt_hub.prompt_tool import is_only_pure_system_prompt
        
        result = is_only_pure_system_prompt()
        
        self.assertTrue(result)

    @patch.dict(os.environ, {'PURE_SYSTEM_PROMPT': '0'})
    def test_is_only_pure_system_prompt_false(self):
        """Test is_only_pure_system_prompt returns False when set to 0"""
        from topsailai.prompt_hub.prompt_tool import is_only_pure_system_prompt
        
        result = is_only_pure_system_prompt()
        
        self.assertFalse(result)

    @patch.dict(os.environ, {})
    def test_is_only_pure_system_prompt_default(self):
        """Test is_only_pure_system_prompt returns False when not set"""
        from topsailai.prompt_hub.prompt_tool import is_only_pure_system_prompt
        
        result = is_only_pure_system_prompt()
        
        self.assertFalse(result)


class TestDisableTools(unittest.TestCase):
    """Test disable_tools function"""

    def test_disable_tools_basic(self):
        """Test disable_tools removes matching tools"""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        
        raw_tools = ['agent_tool.Write', 'agent_tool.Read', 'cmd_tool.Exec']
        target_tools = ['agent_tool']
        
        result = disable_tools(raw_tools, target_tools)
        
        self.assertEqual(result, ['cmd_tool.Exec'])

    def test_disable_tools_empty_raw(self):
        """Test disable_tools returns empty list when raw_tools is empty"""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        
        result = disable_tools([], ['agent_tool'])
        
        self.assertEqual(result, [])

    def test_disable_tools_none_raw(self):
        """Test disable_tools returns None when raw_tools is None"""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        
        result = disable_tools(None, ['agent_tool'])
        
        self.assertIsNone(result)

    def test_disable_tools_no_match(self):
        """Test disable_tools returns all tools when no match"""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        
        raw_tools = ['agent_tool.Write', 'cmd_tool.Exec']
        target_tools = ['other_tool']
        
        result = disable_tools(raw_tools, target_tools)
        
        self.assertEqual(result, raw_tools)


class TestDisableToolsByEnv(unittest.TestCase):
    """Test disable_tools_by_env function"""

    @patch('topsailai.tools.base.init.DISABLED_TOOLS', ['agent_tool'])
    def test_disable_tools_by_env_with_disabled(self):
        """Test disable_tools_by_env uses DISABLED_TOOLS from env"""
        from topsailai.prompt_hub.prompt_tool import disable_tools_by_env
        
        raw_tools = ['agent_tool.Write', 'cmd_tool.Exec']
        
        result = disable_tools_by_env(raw_tools)
        
        self.assertEqual(result, ['cmd_tool.Exec'])

    @patch('topsailai.tools.base.init.DISABLED_TOOLS', [])
    def test_disable_tools_by_env_no_disabled(self):
        """Test disable_tools_by_env returns all tools when no disabled"""
        from topsailai.prompt_hub.prompt_tool import disable_tools_by_env
        
        raw_tools = ['agent_tool.Write', 'cmd_tool.Exec']
        
        result = disable_tools_by_env(raw_tools)
        
        self.assertEqual(result, raw_tools)


class TestEnableTools(unittest.TestCase):
    """Test enable_tools function"""

    def test_enable_tools_basic(self):
        """Test enable_tools returns only matching tools"""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        
        raw_tools = ['agent_tool.Write', 'agent_tool.Read', 'cmd_tool.Exec']
        target_tools = ['agent_tool']
        
        result = enable_tools(raw_tools, target_tools)
        
        self.assertEqual(set(result), {'agent_tool.Write', 'agent_tool.Read'})

    def test_enable_tools_with_wildcard(self):
        """Test enable_tools returns all when wildcard in target"""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        
        raw_tools = ['agent_tool.Write', 'cmd_tool.Exec']
        target_tools = ['*']
        
        result = enable_tools(raw_tools, target_tools)
        
        self.assertEqual(result, raw_tools)

    def test_enable_tools_empty_raw(self):
        """Test enable_tools returns empty list when raw_tools is empty"""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        
        result = enable_tools([], ['agent_tool'])
        
        self.assertEqual(result, [])

    def test_enable_tools_no_match(self):
        """Test enable_tools returns empty when no match"""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        
        raw_tools = ['agent_tool.Write']
        target_tools = ['cmd_tool']
        
        result = enable_tools(raw_tools, target_tools)
        
        self.assertEqual(result, [])


class TestEnableToolsByEnv(unittest.TestCase):
    """Test enable_tools_by_env function"""

    @patch('topsailai.tools.base.init.ENABLED_TOOLS', ['agent_tool'])
    def test_enable_tools_by_env_with_enabled(self):
        """Test enable_tools_by_env uses ENABLED_TOOLS from env"""
        from topsailai.prompt_hub.prompt_tool import enable_tools_by_env
        
        raw_tools = ['agent_tool.Write', 'cmd_tool.Exec']
        
        result = enable_tools_by_env(raw_tools)
        
        self.assertEqual(set(result), {'agent_tool.Write'})

    @patch('topsailai.tools.base.init.ENABLED_TOOLS', [])
    def test_enable_tools_by_env_no_enabled(self):
        """Test enable_tools_by_env returns all tools when no enabled"""
        from topsailai.prompt_hub.prompt_tool import enable_tools_by_env
        
        raw_tools = ['agent_tool.Write', 'cmd_tool.Exec']
        
        result = enable_tools_by_env(raw_tools)
        
        self.assertEqual(result, raw_tools)


class TestGetToolsByEnv(unittest.TestCase):
    """Test get_tools_by_env function"""

    @patch('topsailai.prompt_hub.prompt_tool.enable_tools_by_env')
    @patch('topsailai.prompt_hub.prompt_tool.disable_tools_by_env')
    def test_get_tools_by_env_enable_first(self, mock_disable, mock_enable):
        """Test get_tools_by_env enables first, then disables"""
        from topsailai.prompt_hub.prompt_tool import get_tools_by_env
        
        mock_enable.return_value = ['agent_tool.Write', 'cmd_tool.Exec']
        mock_disable.return_value = ['cmd_tool.Exec']
        
        result = get_tools_by_env(['agent_tool.Write', 'cmd_tool.Exec'])
        
        self.assertEqual(result, ['cmd_tool.Exec'])
        mock_enable.assert_called_once()
        mock_disable.assert_called_once_with(['agent_tool.Write', 'cmd_tool.Exec'])

    def test_get_tools_by_env_empty(self):
        """Test get_tools_by_env returns empty list for empty input"""
        from topsailai.prompt_hub.prompt_tool import get_tools_by_env
        
        result = get_tools_by_env([])
        
        self.assertEqual(result, [])


class TestGetPromptFromModule(unittest.TestCase):
    """Test get_prompt_from_module function"""

    @patch('topsailai.prompt_hub.prompt_tool.__import__')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_from_module_success(self, mock_logger, mock_import):
        """Test get_prompt_from_module returns prompt from module"""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        
        mock_module = MagicMock()
        mock_module.PROMPT = 'test prompt content'
        mock_import.return_value = mock_module
        
        result = get_prompt_from_module('agent_tool')
        
        self.assertEqual(result, 'test prompt content')

    @patch('topsailai.prompt_hub.prompt_tool.__import__')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_from_module_not_found(self, mock_logger, mock_import):
        """Test get_prompt_from_module returns empty when module not found"""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        
        mock_import.side_effect = ModuleNotFoundError()
        
        result = get_prompt_from_module('nonexistent')
        
        self.assertEqual(result, '')

    @patch('topsailai.prompt_hub.prompt_tool.__import__')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_from_module_no_attr(self, mock_logger, mock_import):
        """Test get_prompt_from_module returns empty when attr not found"""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        
        mock_module = MagicMock(spec=[])
        mock_import.return_value = mock_module
        
        result = get_prompt_from_module('agent_tool')
        
        self.assertEqual(result, '')


class TestReloadPromptOnModule(unittest.TestCase):
    """Test reload_prompt_on_module function"""

    @patch('topsailai.prompt_hub.prompt_tool.__import__')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_reload_prompt_on_module_success(self, mock_logger, mock_import):
        """Test reload_prompt_on_module calls reload function"""
        from topsailai.prompt_hub.prompt_tool import reload_prompt_on_module
        
        mock_module = MagicMock()
        mock_import.return_value = mock_module
        
        reload_prompt_on_module('agent_tool')
        
        mock_module.reload.assert_called_once()
        mock_logger.info.assert_called()

    @patch('topsailai.prompt_hub.prompt_tool.__import__')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_reload_prompt_on_module_not_found(self, mock_logger, mock_import):
        """Test reload_prompt_on_module handles module not found"""
        from topsailai.prompt_hub.prompt_tool import reload_prompt_on_module
        
        mock_import.side_effect = ModuleNotFoundError()
        
        reload_prompt_on_module('nonexistent')
        
        mock_logger.info.assert_not_called()


class TestGetPromptByTools(unittest.TestCase):
    """Test get_prompt_by_tools function"""

    @patch('topsailai.tools.base.init.CONN_CHAR', '.')
    @patch('topsailai.prompt_hub.prompt_tool.exists_prompt_file')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_from_module')
    @patch('topsailai.prompt_hub.prompt_tool.reload_prompt_on_module')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_by_tools_with_modules(self, mock_logger, mock_reload, mock_get_prompt, mock_read, mock_exists, mock_char):
        """Test get_prompt_by_tools returns prompts from modules"""
        from topsailai.prompt_hub.prompt_tool import get_prompt_by_tools
        
        mock_exists.return_value = True
        mock_read.return_value = 'prompt content'
        mock_get_prompt.return_value = 'module prompt'
        
        result = get_prompt_by_tools(['agent_tool.Write', 'cmd_tool.Exec'])
        
        self.assertIn('module prompt', result)
        self.assertIn('prompt content', result)

    @patch('topsailai.tools.base.init.CONN_CHAR', '.')
    @patch('topsailai.prompt_hub.prompt_tool.exists_prompt_file')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_from_module')
    @patch('topsailai.prompt_hub.prompt_tool.reload_prompt_on_module')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_by_tools_no_reload(self, mock_logger, mock_reload, mock_get_prompt, mock_read, mock_exists, mock_char):
        """Test get_prompt_by_tools does not reload when need_reload=False"""
        from topsailai.prompt_hub.prompt_tool import get_prompt_by_tools
        
        mock_exists.return_value = False
        mock_get_prompt.return_value = ''
        
        result = get_prompt_by_tools(['agent_tool.Write'], need_reload=False)
        
        mock_reload.assert_not_called()


class TestGeneratePromptByTools(unittest.TestCase):
    """Test generate_prompt_by_tools function"""

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_by_tools')
    @patch('topsailai.prompt_hub.prompt_tool.get_extra_tools')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool.is_use_tool_calls')
    def test_generate_prompt_by_tools_with_list(self, mock_is_tool_calls, mock_get_extra, mock_get_by_tools):
        """Test generate_prompt_by_tools works with list input"""
        from topsailai.prompt_hub.prompt_tool import generate_prompt_by_tools
        
        mock_is_tool_calls.return_value = True
        mock_get_by_tools.return_value = 'tools prompt'
        mock_get_extra.return_value = 'extra tools'
        
        result = generate_prompt_by_tools(['agent_tool.Write'])
        
        self.assertIn('tools prompt', result)
        self.assertIn('extra tools', result)

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_by_tools')
    @patch('topsailai.prompt_hub.prompt_tool.get_extra_tools')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool.is_use_tool_calls')
    def test_generate_prompt_by_tools_with_dict(self, mock_is_tool_calls, mock_get_extra, mock_get_by_tools):
        """Test generate_prompt_by_tools works with dict input"""
        from topsailai.prompt_hub.prompt_tool import generate_prompt_by_tools
        
        mock_is_tool_calls.return_value = True
        mock_get_by_tools.return_value = 'tools prompt'
        mock_get_extra.return_value = ''
        
        result = generate_prompt_by_tools({'agent_tool.Write': {}})
        
        self.assertIn('tools prompt', result)


if __name__ == '__main__':
    unittest.main()
