"""
Unit tests for hook_tool module.

Test coverage for:
- get_hook_scripts_info()
- build_cmd_parameters()
- call_hook_scripts()

Author: mm-m25
"""

import pytest
from unittest.mock import patch, MagicMock


class TestGetHookScriptsInfo:
    """Tests for get_hook_scripts_info() function."""

    @patch('topsailai.utils.hook_tool.env_tool.EnvReaderInstance')
    def test_get_hook_scripts_info_single_script(self, mock_env_reader):
        """Test parsing a single script with options."""
        from src.topsailai.utils.hook_tool import get_hook_scripts_info

        mock_env_reader.get_list_str.return_value = ['script.py timeout=30']

        result = get_hook_scripts_info('TEST_KEY')

        assert result == {'script.py': {'timeout': '30'}}
        mock_env_reader.get_list_str.assert_called_once_with('TEST_KEY', separator=';')

    @patch('topsailai.utils.hook_tool.env_tool.EnvReaderInstance')
    def test_get_hook_scripts_info_multiple_scripts(self, mock_env_reader):
        """Test parsing multiple scripts with options."""
        from src.topsailai.utils.hook_tool import get_hook_scripts_info

        mock_env_reader.get_list_str.return_value = [
            'script1.py timeout=30',
            'script2.py timeout=60 env_keys=KEY1,KEY2'
        ]

        result = get_hook_scripts_info('TEST_KEY')

        assert result == {
            'script1.py': {'timeout': '30'},
            'script2.py': {'timeout': '60', 'env_keys': ['KEY1', 'KEY2']}
        }

    @patch('topsailai.utils.hook_tool.env_tool.EnvReaderInstance')
    def test_get_hook_scripts_info_empty_env(self, mock_env_reader):
        """Test when environment variable is not set."""
        from src.topsailai.utils.hook_tool import get_hook_scripts_info

        mock_env_reader.get_list_str.return_value = []

        result = get_hook_scripts_info('EMPTY_KEY')

        assert result == {}

    @patch('topsailai.utils.hook_tool.env_tool.EnvReaderInstance')
    def test_get_hook_scripts_info_no_separator(self, mock_env_reader):
        """Test script without semicolon separator."""
        from src.topsailai.utils.hook_tool import get_hook_scripts_info

        mock_env_reader.get_list_str.return_value = ['script.py']

        result = get_hook_scripts_info('TEST_KEY')

        assert result == {'script.py': {}}


class TestBuildCmdParameters:
    """Tests for build_cmd_parameters() function."""

    def test_build_cmd_parameters_default_timeout(self):
        """Test building parameters with default timeout."""
        from src.topsailai.utils.hook_tool import build_cmd_parameters, DEFAULT_CMD_TIMEOUT

        result = build_cmd_parameters('script.py', {})

        assert result['cmd'] == 'script.py'
        assert result['timeout'] == DEFAULT_CMD_TIMEOUT
        assert 'SESSION_ID' in result['env_keys']
        assert 'TOPSAILAI_SESSION_ID' in result['env_keys']
        assert 'TOPSAILAI_TASK_ID' in result['env_keys']

    def test_build_cmd_parameters_custom_timeout(self):
        """Test building parameters with custom timeout."""
        from src.topsailai.utils.hook_tool import build_cmd_parameters

        result = build_cmd_parameters('script.py', {'timeout': '60'})

        # Note: timeout is returned as string from cmd_options.get()
        assert result['timeout'] == '60'

    def test_build_cmd_parameters_with_env_keys(self):
        """Test building parameters with additional env keys."""
        from src.topsailai.utils.hook_tool import build_cmd_parameters

        result = build_cmd_parameters('script.py', {'env_keys': 'CUSTOM_KEY'})

        # env_keys are appended as a list element
        assert 'CUSTOM_KEY' in result['env_keys']

    def test_build_cmd_parameters_with_multiple_env_keys(self):
        """Test building parameters with comma-separated env keys string."""
        from src.topsailai.utils.hook_tool import build_cmd_parameters

        result = build_cmd_parameters('script.py', {'env_keys': 'KEY1,KEY2,KEY3'})

        # format_tool.to_list returns the string as a single list element
        assert 'KEY1,KEY2,KEY3' in result['env_keys']


class TestCallHookScripts:
    """Tests for call_hook_scripts() function."""

    def test_call_hook_scripts_no_scripts(self):
        """Test when no scripts are configured."""
        from src.topsailai.utils import hook_tool

        with patch.object(hook_tool, 'get_hook_scripts_info') as mock_get_info:
            mock_get_info.return_value = {}
            result = hook_tool.call_hook_scripts('EMPTY_KEY', {})
            assert result == {}

    def test_call_hook_scripts_single_script_success(self):
        """Test executing a single script successfully."""
        from src.topsailai.utils import hook_tool

        with patch.object(hook_tool, 'get_hook_scripts_info') as mock_get_info, \
             patch.object(hook_tool, 'build_cmd_parameters') as mock_build_params, \
             patch.object(hook_tool.cmd_tool, 'exec_cmd') as mock_exec_cmd:

            mock_get_info.return_value = {'script.py': {'timeout': '30'}}
            mock_build_params.return_value = {'cmd': 'script.py', 'timeout': 30, 'env_keys': []}
            mock_exec_cmd.return_value = (0, 'output', '')

            result = hook_tool.call_hook_scripts('TEST_KEY', {})

            assert result == {'script.py': (0, 'output', '')}
            mock_exec_cmd.assert_called_once()

    def test_call_hook_scripts_multiple_scripts(self):
        """Test executing multiple scripts sequentially."""
        from src.topsailai.utils import hook_tool

        with patch.object(hook_tool, 'get_hook_scripts_info') as mock_get_info, \
             patch.object(hook_tool, 'build_cmd_parameters') as mock_build_params, \
             patch.object(hook_tool.cmd_tool, 'exec_cmd') as mock_exec_cmd:

            mock_get_info.return_value = {
                'script1.py': {'timeout': '30'},
                'script2.py': {'timeout': '60'}
            }
            mock_build_params.side_effect = [
                {'cmd': 'script1.py', 'timeout': 30, 'env_keys': []},
                {'cmd': 'script2.py', 'timeout': 60, 'env_keys': []}
            ]
            mock_exec_cmd.side_effect = [
                (0, 'output1', ''),
                (0, 'output2', '')
            ]

            result = hook_tool.call_hook_scripts('TEST_KEY', {})

            assert result == {
                'script1.py': (0, 'output1', ''),
                'script2.py': (0, 'output2', '')
            }
            assert mock_exec_cmd.call_count == 2

    def test_call_hook_scripts_with_env_info(self):
        """Test executing script with env_info passed."""
        from src.topsailai.utils import hook_tool

        with patch.object(hook_tool, 'get_hook_scripts_info') as mock_get_info, \
             patch.object(hook_tool, 'build_cmd_parameters') as mock_build_params, \
             patch.object(hook_tool.cmd_tool, 'exec_cmd') as mock_exec_cmd:

            mock_get_info.return_value = {'script.py': {}}
            mock_build_params.return_value = {'cmd': 'script.py', 'timeout': 300, 'env_keys': []}
            mock_exec_cmd.return_value = (0, 'output', '')

            env_info = {'CUSTOM_VAR': 'value'}
            hook_tool.call_hook_scripts('TEST_KEY', env_info)

            # Verify env_info was added to cmd_parameters
            call_kwargs = mock_exec_cmd.call_args[1]
            assert 'env_info' in call_kwargs
            assert call_kwargs['env_info']['CUSTOM_VAR'] == 'value'

    def test_call_hook_scripts_script_failure(self):
        """Test handling script execution failure."""
        from src.topsailai.utils import hook_tool

        with patch.object(hook_tool, 'get_hook_scripts_info') as mock_get_info, \
             patch.object(hook_tool, 'build_cmd_parameters') as mock_build_params, \
             patch.object(hook_tool.cmd_tool, 'exec_cmd') as mock_exec_cmd:

            mock_get_info.return_value = {'script.py': {}}
            mock_build_params.return_value = {'cmd': 'script.py', 'timeout': 300, 'env_keys': []}
            mock_exec_cmd.side_effect = Exception('Command failed')

            result = hook_tool.call_hook_scripts('TEST_KEY', {})

            # Should return None for failed script
            assert result == {'script.py': None}


class TestDefaultCmdTimeout:
    """Tests for DEFAULT_CMD_TIMEOUT constant."""

    def test_default_cmd_timeout_is_integer(self):
        """Test that DEFAULT_CMD_TIMEOUT is a positive integer."""
        from src.topsailai.utils.hook_tool import DEFAULT_CMD_TIMEOUT

        assert isinstance(DEFAULT_CMD_TIMEOUT, int)
        assert DEFAULT_CMD_TIMEOUT > 0

    def test_default_cmd_timeout_value(self):
        """Test DEFAULT_CMD_TIMEOUT value is reasonable."""
        from src.topsailai.utils.hook_tool import DEFAULT_CMD_TIMEOUT

        # Should be at least 1 second and not more than 1 hour
        assert 1 <= DEFAULT_CMD_TIMEOUT <= 3600
