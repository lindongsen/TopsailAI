"""
Test for topsailai/tools/cmd_tool.py

Author: Dawsonlin
Email: lin_dongsen@126.com
Created: 2025-12-10
"""

import pytest
from unittest.mock import patch, MagicMock


class TestExecCmd:
    """Test exec_cmd function"""
    
    def test_exec_cmd_with_list_command(self):
        """Test exec_cmd with list command"""
        with patch('topsailai.tools.cmd_tool.exec_command') as mock_exec:
            mock_exec.return_value = (0, "hello\n", "")
            with patch('topsailai.tools.cmd_tool.format_return') as mock_format:
                mock_format.return_value = (0, "hello\n", "")
                from topsailai.tools.cmd_tool import exec_cmd
                result = exec_cmd(["echo", "hello"])
                assert result == (0, "hello\n", "")
                mock_exec.assert_called_once()
                mock_format.assert_called_once()
    
    def test_exec_cmd_with_string_command(self):
        """Test exec_cmd with string command"""
        with patch('topsailai.tools.cmd_tool.exec_command') as mock_exec:
            mock_exec.return_value = (0, "world\n", "")
            with patch('topsailai.tools.cmd_tool.format_return') as mock_format:
                mock_format.return_value = (0, "world\n", "")
                from topsailai.tools.cmd_tool import exec_cmd
                result = exec_cmd("echo world")
                assert result == (0, "world\n", "")
    
    def test_exec_cmd_with_json_string(self):
        """Test exec_cmd with JSON string command"""
        with patch('topsailai.tools.cmd_tool.exec_command') as mock_exec:
            mock_exec.return_value = (0, "test\n", "")
            with patch('topsailai.tools.cmd_tool.format_return') as mock_format:
                mock_format.return_value = (0, "test\n", "")
                from topsailai.tools.cmd_tool import exec_cmd
                result = exec_cmd('["echo", "test"]')
                assert result == (0, "test\n", "")
    
    def test_exec_cmd_with_illegal_cmd(self):
        """Test exec_cmd with illegal command type"""
        from topsailai.tools.cmd_tool import exec_cmd
        result = exec_cmd(123)
        assert result == "illegal cmd"
    
    def test_exec_cmd_with_timeout(self):
        """Test exec_cmd with custom timeout"""
        with patch('topsailai.tools.cmd_tool.exec_command') as mock_exec:
            mock_exec.return_value = (0, "done\n", "")
            with patch('topsailai.tools.cmd_tool.format_return') as mock_format:
                mock_format.return_value = (0, "done\n", "")
                from topsailai.tools.cmd_tool import exec_cmd
                result = exec_cmd(["echo", "done"], timeout=60)
                mock_exec.assert_called_once()
                call_kwargs = mock_exec.call_args[1]
                assert call_kwargs['timeout'] == 60
    
    def test_exec_cmd_with_cwd(self):
        """Test exec_cmd with custom cwd"""
        with patch('topsailai.tools.cmd_tool.exec_command') as mock_exec:
            mock_exec.return_value = (0, "done\n", "")
            with patch('topsailai.tools.cmd_tool.format_return') as mock_format:
                mock_format.return_value = (0, "done\n", "")
                from topsailai.tools.cmd_tool import exec_cmd
                result = exec_cmd(["ls"], cwd="/home")
                mock_exec.assert_called_once()
                call_kwargs = mock_exec.call_args[1]
                assert call_kwargs['cwd'] == "/home"


class TestFormatReturn:
    """Test format_return function"""
    
    def test_format_return_with_list_cmd(self):
        """Test format_return with list command"""
        with patch('topsailai.tools.cmd_tool.format_text') as mock_text:
            mock_text.side_effect = lambda x, **k: x
            from topsailai.tools.cmd_tool import format_return
            result = format_return(["echo", "hello"], (0, "output", "error"))
            assert result == (0, "output", "error")
    
    def test_format_return_with_string_cmd(self):
        """Test format_return with string command"""
        with patch('topsailai.tools.cmd_tool.format_text') as mock_text:
            mock_text.side_effect = lambda x, **k: x
            from topsailai.tools.cmd_tool import format_return
            result = format_return("echo hello", (0, "output", "error"))
            assert result == (0, "output", "error")
    
    def test_format_return_with_curl_wikipedia(self):
        """Test format_return with curl wikipedia - no stderr truncation"""
        from topsailai.tools.cmd_tool import format_return, _need_whole_stdout
        # Verify curl wikipedia needs whole stdout
        assert _need_whole_stdout("curl https://wikipedia.org") is True
        result = format_return("curl https://wikipedia.org", (0, "output", "error"))
        assert result[0] == 0


class TestFormatText:
    """Test format_text function"""
    
    def test_format_text_with_string(self):
        """Test format_text with string input"""
        with patch('topsailai.tools.cmd_tool.safe_decode') as mock_decode:
            with patch('topsailai.tools.cmd_tool.ctx_safe') as mock_ctx:
                mock_decode.return_value = "  hello  "
                mock_ctx.truncate_message.return_value = "hello"
                from topsailai.tools.cmd_tool import format_text
                result = format_text("  hello  ")
                assert result == "hello"
    
    def test_format_text_with_bytes(self):
        """Test format_text with bytes input"""
        with patch('topsailai.tools.cmd_tool.safe_decode') as mock_decode:
            with patch('topsailai.tools.cmd_tool.ctx_safe') as mock_ctx:
                mock_decode.return_value = "  test  "
                mock_ctx.truncate_message.return_value = "test"
                from topsailai.tools.cmd_tool import format_text
                result = format_text(b"  test  ")
                assert result == "test"
    
    def test_format_text_no_truncate(self):
        """Test format_text without truncation"""
        with patch('topsailai.tools.cmd_tool.safe_decode') as mock_decode:
            mock_decode.return_value = "  no_truncate  "
            from topsailai.tools.cmd_tool import format_text
            result = format_text("  no_truncate  ", need_truncate=False)
            assert result == "no_truncate"


class TestNeedWholeStdout:
    """Test _need_whole_stdout function"""
    
    def test_need_whole_stdout_curl_wikipedia(self):
        """Test _need_whole_stdout with curl wikipedia"""
        from topsailai.tools.cmd_tool import _need_whole_stdout
        assert _need_whole_stdout("curl https://wikipedia.org") is True
    
    def test_need_whole_stdout_curl_other(self):
        """Test _need_whole_stdout with curl other domain"""
        from topsailai.tools.cmd_tool import _need_whole_stdout
        assert _need_whole_stdout("curl https://example.com") is False
    
    def test_need_whole_stdout_non_curl(self):
        """Test _need_whole_stdout with non-curl command"""
        from topsailai.tools.cmd_tool import _need_whole_stdout
        assert _need_whole_stdout("ls -la") is False


class TestToolsConstant:
    """Test TOOLS constant"""
    
    def test_tools_contains_exec_cmd(self):
        """Test TOOLS contains exec_cmd"""
        from topsailai.tools.cmd_tool import TOOLS
        assert "exec_cmd" in TOOLS
        assert callable(TOOLS["exec_cmd"])


class TestModuleImports:
    """Test module imports"""
    
    def test_import_format_text(self):
        """Test format_text can be imported"""
        from topsailai.tools.cmd_tool import format_text
        assert callable(format_text)
    
    def test_import_exec_cmd(self):
        """Test exec_cmd can be imported"""
        from topsailai.tools.cmd_tool import exec_cmd
        assert callable(exec_cmd)
    
    def test_import_format_return(self):
        """Test format_return can be imported"""
        from topsailai.tools.cmd_tool import format_return
        assert callable(format_return)
    
    def test_import_need_whole_stdout(self):
        """Test _need_whole_stdout can be imported"""
        from topsailai.tools.cmd_tool import _need_whole_stdout
        assert callable(_need_whole_stdout)
