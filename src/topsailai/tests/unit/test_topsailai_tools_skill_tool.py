"""
Unit tests for tools/skill_tool.py

Author: mm-m25
Purpose: Test skill tool functionality including skill overview, file reading, and execution
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

# Add project root to path
sys.path.insert(0, '/root/ai/TopsailAI/src')


class TestGetCallSkillTimeout(unittest.TestCase):
    """Test get_call_skill_timeout function"""

    def test_default_timeout_when_no_env_var(self):
        """Test default timeout is returned when no env var is set"""
        from topsailai.tools.skill_tool import get_call_skill_timeout, DEFAULT_CALL_SKILL_TIMEOUT
        
        with patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get', return_value=None):
            result = get_call_skill_timeout('/some/skill/folder')
            self.assertEqual(result, DEFAULT_CALL_SKILL_TIMEOUT)

    def test_default_timeout_when_empty_env_var(self):
        """Test default timeout is returned when env var is empty string"""
        from topsailai.tools.skill_tool import get_call_skill_timeout, DEFAULT_CALL_SKILL_TIMEOUT
        
        with patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get', return_value=''):
            result = get_call_skill_timeout('/some/skill/folder')
            self.assertEqual(result, DEFAULT_CALL_SKILL_TIMEOUT)

    def test_custom_timeout_from_env_var(self):
        """Test custom timeout is returned when env var is set"""
        from topsailai.tools.skill_tool import get_call_skill_timeout
        
        with patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get', return_value='{"default": 300}'):
            with patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict', return_value={'default': '300'}):
                with patch('topsailai.tools.skill_tool.is_matched_skill', return_value=False):
                    result = get_call_skill_timeout('/some/skill/folder')
                    self.assertEqual(result, 300)

    def test_matched_skill_timeout(self):
        """Test timeout is returned for matched skill"""
        from topsailai.tools.skill_tool import get_call_skill_timeout
        
        with patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get', return_value='{"python": 500, "default": 300}'):
            with patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict', return_value={'python': '500', 'default': '300'}):
                with patch('topsailai.tools.skill_tool.is_matched_skill', side_effect=[True, False]):
                    result = get_call_skill_timeout('/some/python/skill')
                    self.assertEqual(result, 500)


class TestCallSkill(unittest.TestCase):
    """Test call_skill function"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_folder = '/test/skill/folder'
        self.test_script = 'test_script.py'

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_basic_execution(
        self, mock_env_get, mock_parse_dict, mock_timeout, 
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
    ):
        """Test basic skill script execution"""
        from topsailai.tools.skill_tool import call_skill
        
        mock_env_get.return_value = None
        mock_parse_dict.return_value = {}
        mock_timeout.return_value = 120
        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'output', '')
        
        result = call_skill(self.test_folder, self.test_script, 'arg1 arg2')
        
        self.assertIsNotNone(result)
        mock_exec_cmd.assert_called_once()

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_list_parameters(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
    ):
        """Test skill execution with list parameters"""
        from topsailai.tools.skill_tool import call_skill
        
        mock_env_get.return_value = None
        mock_parse_dict.return_value = {}
        mock_timeout.return_value = 120
        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'output', '')
        
        result = call_skill(self.test_folder, self.test_script, ['arg1', 'arg2'])
        
        self.assertIsNotNone(result)
        call_args = mock_exec_cmd.call_args[0][0]
        self.assertIsInstance(call_args, list)

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_output_file(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
    ):
        """Test skill execution with output file"""
        from topsailai.tools.skill_tool import call_skill
        
        mock_env_get.return_value = None
        mock_parse_dict.return_value = {}
        mock_timeout.return_value = 120
        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'test output', '')
        
        output_file = '/tmp/test_output.txt'
        if os.path.exists(output_file):
            os.remove(output_file)
        
        try:
            result = call_skill(self.test_folder, self.test_script, '', output_file=output_file)
            self.assertTrue(os.path.exists(output_file))
            with open(output_file, 'r') as f:
                self.assertEqual(f.read(), 'test output')
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)

    def test_call_skill_output_file_must_be_absolute_path(self):
        """Test that output_file must be an absolute path"""
        from topsailai.tools.skill_tool import call_skill
        
        with self.assertRaises(AssertionError) as context:
            call_skill(self.test_folder, self.test_script, '', output_file='relative/path.txt')
        
        self.assertIn('absolute path', str(context.exception))

    def test_call_skill_output_file_must_not_exist(self):
        """Test that output_file must not already exist"""
        from topsailai.tools.skill_tool import call_skill
        
        test_file = '/tmp/existing_output.txt'
        with open(test_file, 'w') as f:
            f.write('existing')
        
        try:
            with self.assertRaises(AssertionError) as context:
                call_skill(self.test_folder, self.test_script, '', output_file=test_file)
            
            self.assertIn('already exists', str(context.exception))
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_no_need_stderr(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
    ):
        """Test skill execution with no_need_stderr flag"""
        from topsailai.tools.skill_tool import call_skill
        
        mock_env_get.return_value = None
        mock_parse_dict.return_value = {}
        mock_timeout.return_value = 120
        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'output', '')
        
        result = call_skill(self.test_folder, self.test_script, '', no_need_stderr=1)
        
        self.assertIsNotNone(result)
        call_kwargs = mock_exec_cmd.call_args[1]
        self.assertTrue(call_kwargs.get('no_need_stderr'))

    def test_call_skill_empty_cmd_raises_exception(self):
        """Test that empty command raises exception"""
        from topsailai.tools.skill_tool import call_skill
        
        with patch('topsailai.tools.skill_tool.get_skills_from_cache', return_value=[]):
            with self.assertRaises(Exception):
                call_skill(self.test_folder, '', '')


class TestOverviewSkill(unittest.TestCase):
    """Test overview_skill function"""

    @patch('topsailai.tools.skill_tool.overview_skill_native')
    def test_overview_skill_returns_native_result(self, mock_native):
        """Test that overview_skill delegates to native function"""
        from topsailai.tools.skill_tool import overview_skill
        
        expected_result = {'name': 'test_skill', 'description': 'A test skill'}
        mock_native.return_value = expected_result
        
        result = overview_skill('/test/skill/folder')
        
        self.assertEqual(result, expected_result)
        mock_native.assert_called_once_with('/test/skill/folder')


class TestReadSkillFile(unittest.TestCase):
    """Test read_skill_file function"""

    def test_read_skill_file_success(self):
        """Test successful file reading"""
        from topsailai.tools.skill_tool import read_skill_file
        
        test_content = 'Test file content'
        test_file = '/tmp/test_skill_file.txt'
        
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(test_content)
        
        try:
            with patch('topsailai.tools.skill_tool.exists_skill', return_value=True):
                with patch('topsailai.tools.skill_tool.get_skill_file', return_value=test_file):
                    result = read_skill_file('/test/folder', 'test_file.txt')
                    self.assertEqual(result, test_content)
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

    def test_read_skill_file_skill_not_exists(self):
        """Test error when skill folder doesn't exist"""
        from topsailai.tools.skill_tool import read_skill_file
        
        with patch('topsailai.tools.skill_tool.exists_skill', return_value=False):
            with self.assertRaises(AssertionError) as context:
                read_skill_file('/nonexistent/folder', 'test_file.txt')
            
            self.assertIn('no found this skill folder', str(context.exception))

    def test_read_skill_file_file_not_exists(self):
        """Test error when file doesn't exist"""
        from topsailai.tools.skill_tool import read_skill_file
        
        with patch('topsailai.tools.skill_tool.exists_skill', return_value=True):
            with patch('topsailai.tools.skill_tool.get_skill_file', return_value=None):
                with self.assertRaises(AssertionError) as context:
                    read_skill_file('/test/folder', 'nonexistent.txt')
                
                self.assertIn('no found this skill file', str(context.exception))


class TestModuleConstants(unittest.TestCase):
    """Test module constants"""

    def test_tools_contains_required_functions(self):
        """Test TOOLS dictionary contains all required functions"""
        from topsailai.tools.skill_tool import TOOLS
        
        self.assertIn('call_skill', TOOLS)
        self.assertIn('overview_skill', TOOLS)
        self.assertIn('read_skill_file', TOOLS)
        
        self.assertTrue(callable(TOOLS['call_skill']))
        self.assertTrue(callable(TOOLS['overview_skill']))
        self.assertTrue(callable(TOOLS['read_skill_file']))

    def test_prompt_skill_tool_rule_contains_mandatory_inspection(self):
        """Test PROMPT_SKILL_TOOL_RULE contains mandatory inspection text"""
        from topsailai.tools.skill_tool import PROMPT_SKILL_TOOL_RULE
        
        self.assertIn('Mandatory Skill Inspection', PROMPT_SKILL_TOOL_RULE)
        self.assertIn('overview_skill', PROMPT_SKILL_TOOL_RULE)
        self.assertIn('full, up-to-date details', PROMPT_SKILL_TOOL_RULE)

    def test_flag_tool_enabled_is_boolean(self):
        """Test FLAG_TOOL_ENABLED is a boolean"""
        from topsailai.tools.skill_tool import FLAG_TOOL_ENABLED
        
        self.assertIsInstance(FLAG_TOOL_ENABLED, bool)


class TestReload(unittest.TestCase):
    """Test reload function"""

    @patch('topsailai.tools.skill_tool.get_skill_markdown')
    @patch('topsailai.tools.skill_tool.prompt_tool.read_prompt')
    def test_reload_updates_prompt_and_flag(self, mock_read_prompt, mock_get_markdown):
        """Test reload function updates global variables"""
        import topsailai.tools.skill_tool as skill_tool_module
        
        mock_read_prompt.return_value = 'Base prompt content'
        mock_get_markdown.return_value = '## Skills\n- Skill 1\n- Skill 2'
        
        original_prompt_plugin_skills = skill_tool_module.PROMPT_PLUGIN_SKILLS
        original_prompt = skill_tool_module.PROMPT
        
        skill_tool_module.reload()
        
        # Verify reload updated the global variables
        self.assertTrue(skill_tool_module.FLAG_TOOL_ENABLED)
        self.assertIn('Skill 1', skill_tool_module.PROMPT_PLUGIN_SKILLS)
        self.assertIn('Skill 1', skill_tool_module.PROMPT)
        
        # Restore original values
        skill_tool_module.PROMPT_PLUGIN_SKILLS = original_prompt_plugin_skills
        skill_tool_module.PROMPT = original_prompt

    @patch('topsailai.tools.skill_tool.get_skill_markdown')
    @patch('topsailai.tools.skill_tool.prompt_tool.read_prompt')
    def test_reload_with_no_skills_disables_tool(self, mock_read_prompt, mock_get_markdown):
        """Test reload disables tool when no skills available"""
        import topsailai.tools.skill_tool as skill_tool_module
        
        mock_read_prompt.return_value = 'Base prompt content'
        mock_get_markdown.return_value = ''
        
        skill_tool_module.reload()
        
        self.assertFalse(skill_tool_module.FLAG_TOOL_ENABLED)
        self.assertEqual(skill_tool_module.PROMPT_PLUGIN_SKILLS, '')


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_folder = '/test/skill/folder'
        self.test_script = 'test_script.py'

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_unicode_parameters(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
    ):
        """Test skill execution with unicode parameters"""
        from topsailai.tools.skill_tool import call_skill
        
        mock_env_get.return_value = None
        mock_parse_dict.return_value = {}
        mock_timeout.return_value = 120
        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'unicode output: 你好世界', '')
        
        result = call_skill('/test/folder', 'test.py', '参数 --name 中文')
        
        self.assertIsNotNone(result)

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_special_characters_in_path(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
    ):
        """Test skill execution with special characters in path"""
        from topsailai.tools.skill_tool import call_skill
        
        mock_env_get.return_value = None
        mock_parse_dict.return_value = {}
        mock_timeout.return_value = 120
        special_folder = '/test/skill-folder_v1.2.3'
        mock_get_skills.return_value = [SimpleNamespace(folder=special_folder)]
        mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'output', '')
        
        result = call_skill(special_folder, 'test_script.sh', '--flag value')
        
        self.assertIsNotNone(result)

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_long_timeout(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
    ):
        """Test skill execution with long timeout"""
        from topsailai.tools.skill_tool import call_skill
        
        mock_env_get.return_value = None
        mock_parse_dict.return_value = {}
        mock_timeout.return_value = 3600
        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'output', '')
        
        result = call_skill(self.test_folder, self.test_script, '', timeout=3600)
        
        self.assertIsNotNone(result)
        mock_exec_cmd.assert_called_once()


if __name__ == '__main__':
    unittest.main()
