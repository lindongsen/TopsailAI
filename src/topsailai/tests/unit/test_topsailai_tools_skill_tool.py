import os
import sys
import tempfile
import unittest
import shutil
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
# Add project root to path
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai.tools.skill_tool import SkillToolError

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

    def test_invalid_timeout_value_raises_skill_tool_error(self):
        """Test non-integer timeout value raises SkillToolError with guidance."""
        from topsailai.tools.skill_tool import get_call_skill_timeout

        with patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get', return_value='{"python": "not_a_number", "default": "300"}'):
            with patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict', return_value={'python': 'not_a_number', 'default': '300'}):
                with patch('topsailai.tools.skill_tool.is_matched_skill', return_value=True):
                    with self.assertRaises(SkillToolError) as context:
                        get_call_skill_timeout('/some/python/skill')

                    self.assertIn('python', str(context.exception))
                    self.assertIn('not_a_number', str(context.exception))

    def test_non_positive_timeout_value_raises_skill_tool_error(self):
        """Test zero or negative timeout value raises SkillToolError."""
        from topsailai.tools.skill_tool import get_call_skill_timeout

        with patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get', return_value='{"python": "-10", "default": "300"}'):
            with patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict', return_value={'python': '-10', 'default': '300'}):
                with patch('topsailai.tools.skill_tool.is_matched_skill', return_value=True):
                    with self.assertRaises(SkillToolError) as context:
                        get_call_skill_timeout('/some/python/skill')

                    self.assertIn('positive', str(context.exception))


class TestCallSkill(unittest.TestCase):
    """Test call_skill function"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_folder = '/test/skill/folder'
        self.test_script = 'test_script.py'

        self._isdir_patcher = patch('topsailai.tools.skill_tool.os.path.isdir', return_value=True)
        self._isdir_patcher.start()

    def tearDown(self):
        self._isdir_patcher.stop()

    def _patch_call_skill(self, mock_env_get, mock_parse_dict, mock_timeout,
                          mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd,
                          folder=None, script=None):
        """Helper to configure common mocks for successful call_skill tests."""
        mock_env_get.return_value = None
        mock_parse_dict.return_value = {}
        mock_timeout.return_value = 120
        mock_get_skills.return_value = [SimpleNamespace(folder=folder or self.test_folder)]
        mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'output', '')
        # Default os.access to True so executable check passes
        import topsailai.tools.skill_tool as st
        st.os.access = MagicMock(return_value=True)

    def _mock_realpath_for_test_folder(self, mock_realpath, mock_isfile, folder=None, script=None):
        """Make realpath and isfile behave as if test_script exists under test_folder."""
        target_folder = folder if folder is not None else self.test_folder
        target_script = script if script is not None else self.test_script
        def fake_realpath(path):
            if isinstance(path, str):
                if path == target_folder:
                    return target_folder
                if path.startswith(target_folder):
                    return path
                if path == target_script or path.endswith('/' + target_script):
                    return os.path.join(target_folder, target_script)
                return os.path.join(target_folder, os.path.basename(path))
            return path
        mock_realpath.side_effect = fake_realpath
        mock_isfile.return_value = True

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_basic_execution(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd,
        mock_realpath, mock_isfile
    ):
        """Test basic skill script execution"""
        from topsailai.tools.skill_tool import call_skill

        self._patch_call_skill(
            mock_env_get, mock_parse_dict, mock_timeout,
            mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
        )
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

        result = call_skill(self.test_folder, self.test_script, 'arg1 arg2')

        self.assertIsNotNone(result)
        mock_exec_cmd.assert_called_once()

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_list_parameters(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd,
        mock_realpath, mock_isfile
    ):
        """Test skill execution with list parameters"""
        from topsailai.tools.skill_tool import call_skill

        self._patch_call_skill(
            mock_env_get, mock_parse_dict, mock_timeout,
            mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
        )
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

        result = call_skill(self.test_folder, self.test_script, ['arg1', 'arg2'])

        self.assertIsNotNone(result)
        call_args = mock_exec_cmd.call_args[0][0]
        self.assertIsInstance(call_args, list)

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_output_file(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd,
        mock_realpath, mock_isfile
    ):
        """Test skill execution with output file"""
        from topsailai.tools.skill_tool import call_skill

        self._patch_call_skill(
            mock_env_get, mock_parse_dict, mock_timeout,
            mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
        )
        mock_exec_cmd.return_value = (0, 'test output', '')
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

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

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_stdin_text(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd,
        mock_realpath, mock_isfile
    ):
        """Test skill execution with stdin_text forwarded to subprocess input"""
        from topsailai.tools.skill_tool import call_skill

        self._patch_call_skill(
            mock_env_get, mock_parse_dict, mock_timeout,
            mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
        )
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

        result = call_skill(
            self.test_folder,
            self.test_script,
            '',
            stdin_text='hello from stdin',
        )

        self.assertIsNotNone(result)
        call_kwargs = mock_exec_cmd.call_args[1]
        self.assertIn('input', call_kwargs)
        self.assertEqual(call_kwargs['input'], b'hello from stdin')

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_output_file_must_be_absolute_path(self, mock_get_skills, mock_realpath, mock_isfile):
        """Test that output_file must be an absolute path"""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

        with self.assertRaises((SkillToolError, ValueError)) as context:
            call_skill(self.test_folder, self.test_script, '', output_file='relative/path.txt')

        self.assertIn('absolute path', str(context.exception))

    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_rejects_absolute_path_outside_skill_folder(self, mock_get_skills):
        """Test that absolute script_path outside the skill folder is rejected."""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]

        with self.assertRaises(ValueError) as context:
            call_skill(self.test_folder, '/bin/sh', '')

        msg = str(context.exception)
        self.assertIn('A skill can only run scripts that exist inside its own folder', msg)
        self.assertIn("'/bin/sh'", msg)
        self.assertIn('outside', msg)

    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_rejects_tilde_path(self, mock_get_skills):
        """Test that tilde-prefixed script_path is rejected"""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]

        with self.assertRaises(ValueError) as context:
            call_skill(self.test_folder, '~/.bashrc', '')

        msg = str(context.exception)
        self.assertIn('A skill can only run scripts that exist inside its own folder', msg)
        self.assertIn("'~/.bashrc'", msg)

    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_rejects_backslash_path(self, mock_get_skills):
        """Test that backslash-prefixed script_path is rejected"""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]

        with self.assertRaises(ValueError) as context:
            call_skill(self.test_folder, r'\\windows\script.bat', '')

        msg = str(context.exception)
        self.assertIn('A skill can only run scripts that exist inside its own folder', msg)
        self.assertIn(r"'\\\\windows\\script.bat'", msg)

    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_rejects_path_traversal(self, mock_get_skills, mock_realpath):
        """Test that script_path escaping skill folder is rejected"""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_realpath.side_effect = lambda p: p

        with self.assertRaises(ValueError) as context:
            call_skill(self.test_folder, '../escape.sh', '')

        msg = str(context.exception)
        self.assertIn('A skill can only run scripts that exist inside its own folder', msg)
        self.assertIn('outside the skill folder', msg)

    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_rejects_missing_relative_script(self, mock_get_skills):
        """Test that non-existent relative script_path is rejected"""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]

        with self.assertRaises(ValueError) as context:
            call_skill(self.test_folder, 'missing_script.py', '')

        msg = str(context.exception)
        self.assertIn('A skill can only run scripts that exist inside its own folder', msg)
        self.assertIn("'missing_script.py'", msg)
        self.assertIn('requested script', msg)
        self.assertIn('was not found', msg)

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_accepts_absolute_path_inside_skill_folder(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
    ):
        """An absolute script path inside the skill folder is accepted."""
        from topsailai.tools.skill_tool import call_skill

        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "skill")
            scripts_dir = os.path.join(skill_dir, "scripts")
            os.makedirs(scripts_dir)
            script_file = os.path.join(scripts_dir, "run.sh")
            with open(script_file, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\necho ok")
            os.chmod(script_file, 0o755)

            mock_env_get.return_value = None
            mock_parse_dict.return_value = {}
            mock_timeout.return_value = 120
            mock_get_skills.return_value = [SimpleNamespace(folder=skill_dir)]
            mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
            mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
            mock_hook_instance = MagicMock()
            mock_hook_instance.need_lock_session = False
            mock_hook_instance.need_refresh_session = False
            mock_hook.return_value = mock_hook_instance
            mock_exec_cmd.return_value = (0, 'ok', '')

            result = call_skill(skill_dir, script_file, '')

            self.assertEqual(result[0], 0)
            mock_exec_cmd.assert_called_once()
            called_cmd = mock_exec_cmd.call_args[0][0]
            self.assertEqual(called_cmd[0], script_file)

    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_rejects_invalid_environ_string(self, mock_get_skills):
        """Test that non-JSON environ string is rejected"""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]


        with self.assertRaises(ValueError) as context:
            call_skill(self.test_folder, self.test_script, '', environ='not-json')

        msg = str(context.exception)
        self.assertIn('A skill accepts environment variables only as a JSON object', msg)
        self.assertIn("'not-json'", msg)
        self.assertIn('not a valid object', msg)

    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_rejects_non_object_environ(self, mock_get_skills):
        """Test that JSON array environ is rejected"""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]

        with self.assertRaises(ValueError) as context:
            call_skill(self.test_folder, self.test_script, '', environ='[1,2,3]')

        msg = str(context.exception)
        self.assertIn('A skill accepts environment variables only as a JSON object', msg)
        self.assertIn("'[1,2,3]'", msg)
        self.assertIn('not a valid object', msg)

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_accepts_valid_environ_dict(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd,
        mock_realpath, mock_isfile
    ):
        """Test that valid dict environ is accepted and passed to exec_cmd"""
        from topsailai.tools.skill_tool import call_skill

        self._patch_call_skill(
            mock_env_get, mock_parse_dict, mock_timeout,
            mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
        )
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

        result = call_skill(self.test_folder, self.test_script, '', environ={'KEY': 'value'})

        self.assertIsNotNone(result)
        mock_exec_cmd.assert_called_once()
        call_kwargs = mock_exec_cmd.call_args[1]
        self.assertEqual(call_kwargs.get('env_info'), {'KEY': 'value'})


class TestOverviewSkill(unittest.TestCase):
    @patch('topsailai.tools.skill_tool.os.path.isdir')
    @patch('topsailai.tools.skill_tool.overview_skill_native')
    def test_overview_skill_returns_native_result(self, mock_native, mock_isdir):
        """Test that overview_skill delegates to native function"""
        from topsailai.tools.skill_tool import overview_skill

        mock_isdir.return_value = True
        expected_result = {'name': 'test_skill', 'description': 'A test skill'}
        mock_native.return_value = expected_result

        result = overview_skill('/test/skill/folder')

        self.assertEqual(result, expected_result)
        mock_native.assert_called_once_with('/test/skill/folder')

    def test_overview_skill_missing_folder_raises_skill_tool_error(self):
        """Test overview_skill raises SkillToolError when folder does not exist."""
        from topsailai.tools.skill_tool import overview_skill

        with self.assertRaises(SkillToolError) as context:
            overview_skill('/nonexistent/skill/folder')

        self.assertIn('does not exist', str(context.exception))


class TestReadSkillFile(unittest.TestCase):
    """Test read_skill_file function"""

    @patch('topsailai.tools.skill_tool.os.path.isdir')
    def test_read_skill_file_success(self, mock_isdir):
        """Test successful file reading"""
        from topsailai.tools.skill_tool import read_skill_file
        
        mock_isdir.return_value = True
        test_content = 'Test file content'
        test_file = '/test/folder/test_file.txt'
        
        with patch('topsailai.tools.skill_tool.exists_skill', return_value=True):
            with patch('topsailai.tools.skill_tool.get_skill_file', return_value=test_file):
                with patch('topsailai.tools.skill_tool.open', unittest.mock.mock_open(read_data=test_content)) as mock_file:
                    result = read_skill_file('/test/folder', 'test_file.txt')
                    self.assertEqual(result, test_content)
                    mock_file.assert_called_once_with(test_file, encoding='utf-8')

    @patch('topsailai.tools.skill_tool.os.path.isdir')
    def test_read_skill_file_skill_not_exists(self, mock_isdir):
        """Test error when skill is not loaded"""
        from topsailai.tools.skill_tool import read_skill_file
        
        mock_isdir.return_value = True
        with patch('topsailai.tools.skill_tool.exists_skill', return_value=False):
            with self.assertRaises(SkillToolError) as context:
                read_skill_file('/nonexistent/folder', 'test_file.txt')
            
            self.assertIn('not loaded', str(context.exception))

    @patch('topsailai.tools.skill_tool.os.path.isdir')
    def test_read_skill_file_file_not_exists(self, mock_isdir):
        """Test error when file doesn't exist"""
        from topsailai.tools.skill_tool import read_skill_file
        
        mock_isdir.return_value = True
        with patch('topsailai.tools.skill_tool.exists_skill', return_value=True):
            with patch('topsailai.tools.skill_tool.get_skill_file', return_value=None):
                with self.assertRaises(SkillToolError) as context:
                    read_skill_file('/test/folder', 'nonexistent.txt')
                
                self.assertIn('not found', str(context.exception))


class TestReadSkillFilePathSecurity(unittest.TestCase):
    """Real-filesystem tests for read_skill_file path containment."""

    def setUp(self):
        from topsailai.skill_hub.skill_tool import g_skills
        self.tmpdir = tempfile.mkdtemp()
        self.skill_folder = os.path.join(self.tmpdir, 'skill')
        os.makedirs(self.skill_folder)
        with open(os.path.join(self.skill_folder, 'SKILL.md'), 'w', encoding='utf-8') as f:
            f.write('---\nname: PathSecSkill\ndescription: test\n---\n')
        g_skills[self.skill_folder] = SimpleNamespace(folder=self.skill_folder)

    def tearDown(self):
        from topsailai.skill_hub.skill_tool import g_skills
        g_skills.pop(self.skill_folder, None)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_skill_file_accepts_absolute_path_inside_skill_folder(self):
        """An absolute file path inside the skill folder is accepted."""
        from topsailai.tools.skill_tool import read_skill_file

        target = os.path.join(self.skill_folder, 'note.txt')
        with open(target, 'w', encoding='utf-8') as f:
            f.write('inside')

        result = read_skill_file(self.skill_folder, target)
        self.assertEqual(result, 'inside')

    def test_read_skill_file_rejects_absolute_path_outside_skill_folder(self):
        """An absolute file path outside the skill folder is rejected."""
        from topsailai.tools.skill_tool import read_skill_file, SkillToolError

        outside = os.path.join(self.tmpdir, 'outside.txt')
        with open(outside, 'w', encoding='utf-8') as f:
            f.write('outside')

        with self.assertRaises(SkillToolError) as context:
            read_skill_file(self.skill_folder, outside)

        self.assertIn('inside the skill folder', str(context.exception))

    def test_read_skill_file_rejects_relative_path_traversal(self):
        """A relative path that escapes the skill folder is rejected."""
        from topsailai.tools.skill_tool import read_skill_file, SkillToolError

        outside = os.path.join(self.tmpdir, 'outside.txt')
        with open(outside, 'w', encoding='utf-8') as f:
            f.write('outside')

        with self.assertRaises(SkillToolError) as context:
            read_skill_file(self.skill_folder, '../outside.txt')

        self.assertIn('inside the skill folder', str(context.exception))

    def test_read_skill_file_relative_path_inside_skill_folder_still_works(self):
        """A normal relative path inside the skill folder still works."""
        from topsailai.tools.skill_tool import read_skill_file

        target = os.path.join(self.skill_folder, 'subdir', 'note.txt')
        os.makedirs(os.path.dirname(target))
        with open(target, 'w', encoding='utf-8') as f:
            f.write('relative inside')

        result = read_skill_file(self.skill_folder, 'subdir/note.txt')
        self.assertEqual(result, 'relative inside')

class TestLoadSkill(unittest.TestCase):
    """Test load_skill function"""

    def setUp(self):
        """Clear global skills cache before each test."""
        from topsailai.skill_hub.skill_tool import g_skills
        g_skills.clear()

    def test_load_skill_success(self):
        """Test successful skill loading returns markdown."""
        from topsailai.tools.skill_tool import load_skill

        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = os.path.join(tmpdir, "SKILL.md")
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write("---\nname: LoadedSkill\ndescription: A loaded skill\n---\n")

            result = load_skill(tmpdir)

            self.assertIn("LoadedSkill", result)
            self.assertIn(tmpdir, result)

    def test_load_skill_missing_name_raises_skill_tool_error(self):
        """Test load_skill raises SkillToolError when SKILL.md has no name."""
        from topsailai.tools.skill_tool import load_skill, SkillToolError

        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = os.path.join(tmpdir, "SKILL.md")
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write("---\ndescription: no name\n---\n")

            with self.assertRaises(SkillToolError) as context:
                load_skill(tmpdir)

            self.assertIn("load skill failed", str(context.exception))
            self.assertIn("no valid SKILL.md", str(context.exception))

    def test_load_skill_duplicate_basename_identical_content_returns_markdown(self):
        """Test load_skill succeeds when an identical-content duplicate basename is already loaded."""
        from topsailai.tools.skill_tool import load_skill
        from topsailai.skill_hub.skill_tool import g_skills

        content = "---\nname: DupSkill\ndescription: duplicate\n---\n"
        with tempfile.TemporaryDirectory() as parent:
            folder1 = os.path.join(parent, "a", "dup")
            folder2 = os.path.join(parent, "b", "dup")
            os.makedirs(folder1)
            os.makedirs(folder2)

            for folder in (folder1, folder2):
                with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
                    f.write(content)

            result1 = load_skill(folder1)
            self.assertIn("DupSkill", result1)
            self.assertIn(folder1, g_skills)

            result2 = load_skill(folder2)
            self.assertIn("DupSkill", result2)

    def test_load_skill_duplicate_basename_different_content_raises_skill_tool_error(self):
        """Test load_skill fails when a conflicting duplicate basename is already loaded."""
        from topsailai.tools.skill_tool import load_skill, SkillToolError
        from topsailai.skill_hub.skill_tool import g_skills

        with tempfile.TemporaryDirectory() as parent:
            folder1 = os.path.join(parent, "a", "dup")
            folder2 = os.path.join(parent, "b", "dup")
            os.makedirs(folder1)
            os.makedirs(folder2)

            with open(os.path.join(folder1, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: DupSkill\ndescription: first\n---\n")
            with open(os.path.join(folder2, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: DupSkill\ndescription: second\n---\n")

            load_skill(folder1)
            self.assertIn(folder1, g_skills)

            with self.assertRaises(SkillToolError) as context:
                load_skill(folder2)
            self.assertIn("load skill failed", str(context.exception))

class TestModuleConstants(unittest.TestCase):
    """Test module constants"""

    def test_tools_contains_required_functions(self):
        """Test TOOLS dictionary contains all required functions"""
        from topsailai.tools.skill_tool import TOOLS
        
        self.assertIn('call_skill', TOOLS)
        self.assertIn('overview_skill', TOOLS)
        self.assertIn('read_skill_file', TOOLS)
        self.assertIn('load_skill', TOOLS)
        
        self.assertTrue(callable(TOOLS['call_skill']))
        self.assertTrue(callable(TOOLS['overview_skill']))
        self.assertTrue(callable(TOOLS['read_skill_file']))
        self.assertTrue(callable(TOOLS['load_skill']))

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

        self._isdir_patcher = patch('topsailai.tools.skill_tool.os.path.isdir', return_value=True)
        self._isdir_patcher.start()

    def tearDown(self):
        self._isdir_patcher.stop()

    def _mock_realpath_for_test_folder(self, mock_realpath, mock_isfile, folder=None, script=None):
        """Make realpath and isfile behave as if test_script exists under test_folder."""
        target_folder = folder if folder is not None else self.test_folder
        target_script = script if script is not None else self.test_script
        def fake_realpath(path):
            if isinstance(path, str):
                if path == target_folder:
                    return target_folder
                if path.startswith(target_folder):
                    return path
                if path == target_script or path.endswith('/' + target_script):
                    return os.path.join(target_folder, target_script)
                return os.path.join(target_folder, os.path.basename(path))
            return path
        mock_realpath.side_effect = fake_realpath
        mock_isfile.return_value = True

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_unicode_parameters(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd,
        mock_realpath, mock_isfile
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
        mock_exec_cmd.return_value = (0, 'unicode output: \u4f60\u597d\u4e16\u754c', '')
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

        result = call_skill('/test/skill/folder', 'test.py', '\u53c2\u6570 --name \u4e2d\u6587')

        self.assertIsNotNone(result)

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_special_characters_in_path(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd,
        mock_realpath, mock_isfile
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
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile, folder=special_folder)

        result = call_skill(special_folder, 'test_script.sh', '--flag value')

        self.assertIsNotNone(result)

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_with_long_timeout(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd,
        mock_realpath, mock_isfile
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
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

        result = call_skill(self.test_folder, self.test_script, '', timeout=3600)

        self.assertIsNotNone(result)
        mock_exec_cmd.assert_called_once()


class TestErrorHandlingImprovements(unittest.TestCase):
    """Test improved error handling and actionable guidance in call_skill."""

    def setUp(self):
        self.test_folder = '/tmp/test_skill'
        self.test_script = 'scripts/test.sh'

        self._isdir_patcher = patch('topsailai.tools.skill_tool.os.path.isdir', return_value=True)
        self._isdir_patcher.start()

    def tearDown(self):
        self._isdir_patcher.stop()

    def _mock_realpath_for_test_folder(self, mock_realpath, mock_isfile, folder=None, script=None):
        """Make realpath and isfile behave as if script exists under folder."""
        target_folder = folder if folder is not None else self.test_folder
        target_script = script if script is not None else self.test_script
        def fake_realpath(path):
            if isinstance(path, str):
                if path == target_folder:
                    return target_folder
                if path.startswith(target_folder):
                    return path
                if path == target_script or path.endswith('/' + target_script):
                    return os.path.join(target_folder, target_script)
                return os.path.join(target_folder, os.path.basename(path))
            return path
        mock_realpath.side_effect = fake_realpath
        mock_isfile.return_value = True

    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_missing_skill_folder(self, mock_get_skills, mock_realpath, mock_isfile):
        """Missing skill folder should raise SkillToolError with guidance."""
        from topsailai.tools.skill_tool import call_skill

        self._isdir_patcher.stop()
        mock_get_skills.return_value = []
        mock_realpath.return_value = '/nonexistent/skill'
        mock_isfile.return_value = True

        with patch('topsailai.tools.skill_tool.os.path.isdir', return_value=False):
            with self.assertRaises(SkillToolError) as context:
                call_skill('/nonexistent/skill', self.test_script, '')

        self.assertIn('does not exist', str(context.exception))

    @patch('topsailai.tools.skill_tool.os.access')
    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_non_executable_script(self, mock_get_skills, mock_realpath, mock_isfile, mock_access):
        """Non-executable script should raise SkillToolError with chmod guidance."""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_access.return_value = False
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

        with self.assertRaises(SkillToolError) as context:
            call_skill(self.test_folder, self.test_script, '')

        self.assertIn('not executable', str(context.exception))
        self.assertIn('chmod +x', str(context.exception))

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_try_session_lock')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_session_lock_failure_returns_tuple(
        self, mock_get_skills, mock_realpath, mock_isfile,
        mock_hook, mock_ctxm, mock_exec_cmd
    ):
        """Session lock failure should return a tuple, not a string."""
        from topsailai.tools.skill_tool import call_skill
        from topsailai.workspace import lock_tool

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)
        mock_ctxm.return_value.__enter__ = MagicMock(return_value=lock_tool.YieldData(
            session_id='s1',
            fp=None,
            msg='another process holds the lock'
        ))
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = True
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'output', '')

        result = call_skill(self.test_folder, self.test_script, '')

        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0], 1)
        self.assertIn('call_skill failed', result[2])
        self.assertIn('another process holds the lock', result[2])

    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.os.access')
    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_timeout_returns_guidance(
        self, mock_get_skills, mock_realpath, mock_isfile,
        mock_access, mock_hook, mock_exec_cmd, mock_get_timeout
    ):
        """Timeout should return a tuple with actionable guidance."""
        import subprocess
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_access.return_value = True
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_get_timeout.return_value = 10
        mock_exec_cmd.side_effect = subprocess.TimeoutExpired(cmd='test', timeout=10)

        result = call_skill(self.test_folder, self.test_script, '', timeout=10)

        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0], 1)
        self.assertIn('timed out', result[2])
        self.assertIn('10', result[2])

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.os.access')
    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_permission_error_returns_guidance(
        self, mock_get_skills, mock_realpath, mock_isfile,
        mock_access, mock_hook, mock_exec_cmd
    ):
        """PermissionError should return a tuple with actionable guidance."""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_access.return_value = True
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.side_effect = PermissionError(13, 'Permission denied')

        result = call_skill(self.test_folder, self.test_script, '')

        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0], 1)
        self.assertIn('Permission denied', result[2])

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.os.access')
    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_output_file_parent_dir_created(
        self, mock_get_skills, mock_realpath, mock_isfile,
        mock_access, mock_hook, mock_exec_cmd
    ):
        """output_file parent directory should be auto-created."""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_access.return_value = True
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'output', '')

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, 'nested', 'dir', 'out.txt')
            self.assertFalse(os.path.exists(os.path.dirname(output_file)))

            result = call_skill(self.test_folder, self.test_script, '', output_file=output_file)

            self.assertEqual(result[0], 0)
            self.assertTrue(os.path.exists(output_file))
            with open(output_file, 'r') as f:
                self.assertEqual(f.read(), 'output')

    @patch('topsailai.tools.skill_tool.os.access')
    @patch('topsailai.tools.skill_tool.os.path.isfile')
    @patch('topsailai.tools.skill_tool.os.path.realpath')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    def test_call_skill_stdin_text_not_string(self, mock_get_skills, mock_realpath, mock_isfile, mock_access):
        """stdin_text must be a string."""
        from topsailai.tools.skill_tool import call_skill

        mock_get_skills.return_value = [SimpleNamespace(folder=self.test_folder)]
        mock_access.return_value = True
        self._mock_realpath_for_test_folder(mock_realpath, mock_isfile)

        with self.assertRaises(SkillToolError) as context:
            call_skill(self.test_folder, self.test_script, '', stdin_text=12345)

        self.assertIn('stdin_text', str(context.exception))
        self.assertIn('string', str(context.exception))

class TestSymlinkPathHandling(unittest.TestCase):
    """Test symlink-aware path validation in skill_tool."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.skill_folder = os.path.join(self.tmpdir, 'skill')
        self.real_scripts = os.path.join(self.tmpdir, 'real_scripts')
        os.makedirs(self.skill_folder)
        os.makedirs(self.real_scripts)

        real_script = os.path.join(self.real_scripts, 'hello.sh')
        with open(real_script, 'w', encoding='utf-8') as f:
            f.write('#!/bin/sh\necho hello')
        os.chmod(real_script, 0o755)

        # Symlink the scripts directory into the skill folder
        os.symlink(self.real_scripts, os.path.join(self.skill_folder, 'scripts'))

        # Also create a direct script inside the skill folder
        direct_script = os.path.join(self.skill_folder, 'direct.sh')
        with open(direct_script, 'w', encoding='utf-8') as f:
            f.write('#!/bin/sh\necho direct')
        os.chmod(direct_script, 0o755)

        # Create a SKILL.md so load_skill/cache checks pass
        with open(os.path.join(self.skill_folder, 'SKILL.md'), 'w', encoding='utf-8') as f:
            f.write('---\nname: SymlinkSkill\ndescription: test\n---\n')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch('topsailai.tools.skill_tool.exec_cmd')
    @patch('topsailai.tools.skill_tool.skill_hook.SkillHookHandler')
    @patch('topsailai.tools.skill_tool.lock_tool.ctxm_void')
    @patch('topsailai.tools.skill_tool.get_skills_from_cache')
    @patch('topsailai.tools.skill_tool.get_call_skill_timeout')
    @patch('topsailai.tools.skill_tool.format_tool.parse_str_to_dict')
    @patch('topsailai.tools.skill_tool.env_tool.EnvReaderInstance.get')
    def test_call_skill_accepts_script_inside_symlinked_subdir(
        self, mock_env_get, mock_parse_dict, mock_timeout,
        mock_get_skills, mock_ctxm, mock_hook, mock_exec_cmd
    ):
        """A script reached through a symlink inside the skill folder is accepted."""
        from topsailai.tools.skill_tool import call_skill

        mock_env_get.return_value = None
        mock_parse_dict.return_value = {}
        mock_timeout.return_value = 120
        mock_get_skills.return_value = [SimpleNamespace(folder=self.skill_folder)]
        mock_ctxm.return_value.__enter__ = MagicMock(return_value={})
        mock_ctxm.return_value.__exit__ = MagicMock(return_value=False)
        mock_hook_instance = MagicMock()
        mock_hook_instance.need_lock_session = False
        mock_hook_instance.need_refresh_session = False
        mock_hook.return_value = mock_hook_instance
        mock_exec_cmd.return_value = (0, 'hello', '')

        result = call_skill(self.skill_folder, 'scripts/hello.sh', '')
        self.assertEqual(result[0], 0)
        mock_exec_cmd.assert_called_once()

    def test_call_skill_rejects_traversal_through_symlink(self):
        """A relative path that escapes the skill folder is still rejected."""
        from topsailai.tools.skill_tool import call_skill, SkillToolError

        with self.assertRaises((SkillToolError, ValueError)) as context:
            call_skill(self.skill_folder, 'scripts/../../escape.sh', '')

        self.assertIn('outside the skill folder', str(context.exception))

    def test_read_skill_file_accepts_file_inside_symlinked_subdir(self):
        """read_skill_file accepts files reached through an in-skill symlink."""
        from topsailai.tools.skill_tool import read_skill_file
        from topsailai.skill_hub.skill_tool import g_skills

        real_file = os.path.join(self.real_scripts, 'note.txt')
        with open(real_file, 'w', encoding='utf-8') as f:
            f.write('symlinked note')

        g_skills[self.skill_folder] = SimpleNamespace(folder=self.skill_folder)
        try:
            result = read_skill_file(self.skill_folder, 'scripts/note.txt')
            self.assertEqual(result, 'symlinked note')
        finally:
            g_skills.pop(self.skill_folder, None)

    def test_read_skill_file_rejects_traversal_through_symlink(self):
        """read_skill_file still rejects paths that escape the skill folder."""
        from topsailai.tools.skill_tool import read_skill_file, SkillToolError
        from topsailai.skill_hub.skill_tool import g_skills

        g_skills[self.skill_folder] = SimpleNamespace(folder=self.skill_folder)
        try:
            with self.assertRaises(SkillToolError) as context:
                read_skill_file(self.skill_folder, 'scripts/../../escape.txt')

            self.assertIn('inside the skill folder', str(context.exception))
        finally:
            g_skills.pop(self.skill_folder, None)
if __name__ == '__main__':
    unittest.main()
