#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for topsailai.context.prompt_env module.

Tests environment prompt generation including system info,
current date, and custom environment prompts.
"""

import os
import pytest
from unittest.mock import patch, mock_open, MagicMock

from topsailai.context.prompt_env import (
    get_system_info,
    _Base,
    CurrentDate,
    CurrentSystem,
    generate_prompt_for_env,
)


class TestGetSystemInfo:
    """Tests for get_system_info function."""

    def test_get_system_info_success(self):
        """Test successful system info retrieval."""
        with patch('topsailai.context.prompt_env.cmd_tool') as mock_cmd:
            mock_cmd.exec_cmd.return_value = (0, "Linux ai-dev 5.14.0 x86_64 GNU/Linux")
            
            with patch('os.path.exists', return_value=True):
                with patch('builtins.open', mock_open(read_data="Debian GNU/Linux 13")):
                    result = get_system_info()
                    
                    assert 'uname' in result
                    assert 'issue' in result
                    assert result['uname'] == "Linux ai-dev 5.14.0 x86_64 GNU/Linux"
                    assert result['issue'] == "Debian GNU/Linux 13"

    def test_get_system_info_cmd_failure(self):
        """Test system info retrieval when cmd_tool fails."""
        with patch('topsailai.context.prompt_env.cmd_tool') as mock_cmd:
            mock_cmd.exec_cmd.return_value = (1, "")
            
            with patch('os.path.exists', return_value=False):
                result = get_system_info()
                
                assert 'uname' not in result
                assert 'issue' not in result

    def test_get_system_info_no_issue_file(self):
        """Test system info retrieval when /etc/issue doesn't exist."""
        with patch('topsailai.context.prompt_env.cmd_tool') as mock_cmd:
            mock_cmd.exec_cmd.return_value = (0, "Linux test")
            
            with patch('os.path.exists', return_value=False):
                result = get_system_info()
                
                assert 'uname' in result
                assert 'issue' not in result

    def test_get_system_info_empty_issue(self):
        """Test system info with empty issue file."""
        with patch('topsailai.context.prompt_env.cmd_tool') as mock_cmd:
            mock_cmd.exec_cmd.return_value = (0, "Linux test")
            
            with patch('os.path.exists', return_value=True):
                with patch('builtins.open', mock_open(read_data="")):
                    result = get_system_info()
                    
                    assert 'issue' in result
                    assert result['issue'] == ""


class TestBaseClass:
    """Tests for _Base class."""

    def test_base_str_representation(self):
        """Test string representation of _Base class."""
        from topsailai.context.prompt_env import _Base
        
        class TestPrompt(_Base):
            @property
            def prompt(self):
                return "Test prompt content"
        
        base = TestPrompt()
        assert str(base) == "Test prompt content"

    def test_base_prompt_property_raises(self):
        """Test that base prompt property raises NotImplementedError."""
        from topsailai.context.prompt_env import _Base
        
        base = _Base()
        with pytest.raises(NotImplementedError):
            _ = base.prompt


class TestCurrentDate:
    """Tests for CurrentDate class."""

    def test_current_date_prompt_format(self):
        """Test that CurrentDate generates properly formatted prompt."""
        from topsailai.context.prompt_env import CurrentDate
        
        with patch('topsailai.context.prompt_env.time_tool') as mock_time:
            mock_time.get_current_date.return_value = "2025-01-15T10:30:00"
            
            current_date = CurrentDate()
            result = current_date.prompt
            
            assert "CurrentDate:" in result
            assert "2025-01-15T10:30:00" in result

    def test_current_date_str_representation(self):
        """Test string representation of CurrentDate."""
        from topsailai.context.prompt_env import CurrentDate
        
        with patch('topsailai.context.prompt_env.time_tool') as mock_time:
            mock_time.get_current_date.return_value = "2025-01-15"
            
            current_date = CurrentDate()
            assert str(current_date) == "CurrentDate: 2025-01-15"

    def test_current_date_iso_format(self):
        """Test that date is in ISO 8601 format."""
        from topsailai.context.prompt_env import CurrentDate
        
        with patch('topsailai.context.prompt_env.time_tool') as mock_time:
            mock_time.get_current_date.return_value = "2025-12-31T23:59:59"
            
            current_date = CurrentDate()
            result = current_date.prompt
            
            # Verify ISO format with T separator
            assert "T" in result


class TestCurrentSystem:
    """Tests for CurrentSystem class."""

    def test_current_system_prompt_format(self):
        """Test that CurrentSystem generates properly formatted prompt."""
        from topsailai.context.prompt_env import CurrentSystem
        
        # Mock the class-level system_info
        with patch.object(CurrentSystem, 'system_info', {'uname': 'Linux test', 'issue': 'Test OS'}):
            system = CurrentSystem()
            result = system.prompt
            
            assert "System Info:" in result
            assert "- uname:Linux test" in result
            assert "- issue:Test OS" in result

    def test_current_system_str_representation(self):
        """Test string representation of CurrentSystem."""
        from topsailai.context.prompt_env import CurrentSystem
        
        with patch.object(CurrentSystem, 'system_info', {'uname': 'Linux'}):
            system = CurrentSystem()
            assert "System Info:" in str(system)

    def test_current_system_handles_none_values(self):
        """Test that CurrentSystem handles None values in system_info."""
        from topsailai.context.prompt_env import CurrentSystem
        
        with patch.object(CurrentSystem, 'system_info', {'uname': None, 'issue': 'Test'}):
            system = CurrentSystem()
            result = system.prompt
            
            # None values should not be included
            assert "- uname:None" not in result
            assert "- issue:Test" in result

    def test_current_system_empty_system_info(self):
        """Test CurrentSystem with empty system_info."""
        from topsailai.context.prompt_env import CurrentSystem
        
        with patch.object(CurrentSystem, 'system_info', {}):
            system = CurrentSystem()
            result = system.prompt
            
            assert "System Info:" in result
            # Should not have any bullet points


class TestGeneratePromptForEnv:
    """Tests for generate_prompt_for_env function."""

    def test_generate_prompt_basic_structure(self):
        """Test basic structure of generated prompt."""
        with patch('topsailai.context.prompt_env.os') as mock_os:
            mock_os.getenv.return_value = None
            
            with patch('topsailai.context.prompt_env.CurrentDate') as mock_date:
                with patch('topsailai.context.prompt_env.CurrentSystem') as mock_system:
                    mock_date.return_value.prompt = "CurrentDate: 2025-01-15"
                    mock_system.return_value.prompt = "System Info:\n- uname:Linux"
                    
                    result = generate_prompt_for_env()
                    
                    assert "# Environment" in result
                    assert "CurrentDate: 2025-01-15" in result
                    assert "System Info:" in result

    def test_generate_prompt_with_env_var_text(self, monkeypatch):
        """Test prompt generation with ENV_PROMPT as direct text."""
        monkeypatch.setenv("ENV_PROMPT", "Custom environment info")
        
        with patch('topsailai.context.prompt_env.CurrentDate') as mock_date:
            with patch('topsailai.context.prompt_env.CurrentSystem') as mock_system:
                mock_date.return_value.prompt = "CurrentDate: 2025-01-15"
                mock_system.return_value.prompt = "System Info:"
                
                result = generate_prompt_for_env()
                
                assert "Custom environment info" in result

    def test_generate_prompt_with_env_var_file_path(self, monkeypatch, tmp_path):
        """Test prompt generation with ENV_PROMPT as file path."""
        # Create a temporary file with content
        env_file = tmp_path / "env_prompt.txt"
        env_file.write_text("Content from file")
        
        monkeypatch.setenv("ENV_PROMPT", str(env_file))
        
        with patch('topsailai.context.prompt_env.CurrentDate') as mock_date:
            with patch('topsailai.context.prompt_env.CurrentSystem') as mock_system:
                mock_date.return_value.prompt = "CurrentDate: 2025-01-15"
                mock_system.return_value.prompt = "System Info:"
                
                result = generate_prompt_for_env()
                
                assert "Content from file" in result

    def test_generate_prompt_with_slash_path(self, monkeypatch):
        """Test prompt generation with ENV_PROMPT starting with slash."""
        monkeypatch.setenv("ENV_PROMPT", "/etc/custom_env")
        
        with patch('topsailai.context.prompt_env.os') as mock_os:
            mock_os.getenv.return_value = "/etc/custom_env"
            
            with patch('builtins.open', mock_open(read_data="Slash path content")):
                with patch('topsailai.context.prompt_env.CurrentDate') as mock_date:
                    with patch('topsailai.context.prompt_env.CurrentSystem') as mock_system:
                        mock_date.return_value.prompt = "CurrentDate: 2025-01-15"
                        mock_system.return_value.prompt = "System Info:"
                        
                        result = generate_prompt_for_env()
                        
                        assert "Slash path content" in result

    def test_generate_prompt_empty_env_var(self, monkeypatch):
        """Test prompt generation with empty ENV_PROMPT."""
        monkeypatch.setenv("ENV_PROMPT", "")
        
        with patch('topsailai.context.prompt_env.CurrentDate') as mock_date:
            with patch('topsailai.context.prompt_env.CurrentSystem') as mock_system:
                mock_date.return_value.prompt = "CurrentDate: 2025-01-15"
                mock_system.return_value.prompt = "System Info:"
                
                result = generate_prompt_for_env()
                
                # Should still have basic structure
                assert "# Environment" in result
                assert "CurrentDate:" in result

    def test_generate_prompt_no_env_var(self, monkeypatch):
        """Test prompt generation when ENV_PROMPT is not set."""
        monkeypatch.delenv("ENV_PROMPT", raising=False)
        
        with patch('topsailai.context.prompt_env.CurrentDate') as mock_date:
            with patch('topsailai.context.prompt_env.CurrentSystem') as mock_system:
                mock_date.return_value.prompt = "CurrentDate: 2025-01-15"
                mock_system.return_value.prompt = "System Info:"
                
                result = generate_prompt_for_env()
                
                # Should still have basic structure
                assert "# Environment" in result

    def test_generate_prompt_multiline_env_content(self, monkeypatch, tmp_path):
        """Test prompt generation with multiline ENV_PROMPT content."""
        env_file = tmp_path / "multiline.txt"
        env_file.write_text("Line 1\nLine 2\nLine 3")
        
        monkeypatch.setenv("ENV_PROMPT", str(env_file))
        
        with patch('topsailai.context.prompt_env.CurrentDate') as mock_date:
            with patch('topsailai.context.prompt_env.CurrentSystem') as mock_system:
                mock_date.return_value.prompt = "CurrentDate: 2025-01-15"
                mock_system.return_value.prompt = "System Info:"
                
                result = generate_prompt_for_env()
                
                assert "Line 1" in result
                assert "Line 2" in result
                assert "Line 3" in result


class TestIntegration:
    """Integration tests for prompt_env module."""

    def test_full_prompt_generation_workflow(self, monkeypatch):
        """Test complete prompt generation workflow."""
        monkeypatch.setenv("ENV_PROMPT", "Custom environment setup")
        
        with patch('topsailai.context.prompt_env.os') as mock_os:
            mock_os.getenv.return_value = "Custom environment setup"
            
            with patch('topsailai.context.prompt_env.CurrentDate') as mock_date:
                with patch('topsailai.context.prompt_env.CurrentSystem') as mock_system:
                    mock_date.return_value.prompt = "CurrentDate: 2025-01-15T10:00:00"
                    mock_system.return_value.prompt = "System Info:\n- uname:Linux x86_64"
                    
                    result = generate_prompt_for_env()
                    
                    # Verify complete structure
                    assert result.startswith("# Environment")
                    assert "CurrentDate:" in result
                    assert "System Info:" in result
                    assert "Custom environment setup" in result

    def test_prompt_generation_without_custom_env(self, monkeypatch):
        """Test prompt generation without custom environment."""
        monkeypatch.delenv("ENV_PROMPT", raising=False)
        
        with patch('topsailai.context.prompt_env.os') as mock_os:
            mock_os.getenv.return_value = None
            
            with patch('topsailai.context.prompt_env.CurrentDate') as mock_date:
                with patch('topsailai.context.prompt_env.CurrentSystem') as mock_system:
                    mock_date.return_value.prompt = "CurrentDate: 2025-01-15"
                    mock_system.return_value.prompt = "System Info:\n- uname:Linux"
                    
                    result = generate_prompt_for_env()
                    
                    # Verify structure without custom env
                    assert result.startswith("# Environment")
                    assert "CurrentDate:" in result
                    assert "System Info:" in result

    def test_current_date_and_system_together(self):
        """Test that CurrentDate and CurrentSystem work together in prompt."""
        from topsailai.context.prompt_env import CurrentDate, CurrentSystem
        
        with patch('topsailai.context.prompt_env.time_tool') as mock_time:
            mock_time.get_current_date.return_value = "2025-01-15"
            
            with patch.object(CurrentSystem, 'system_info', {'uname': 'Linux', 'issue': 'Debian'}):
                date_prompt = CurrentDate().prompt
                system_prompt = CurrentSystem().prompt
                
                combined = f"{date_prompt}\n{system_prompt}"
                
                assert "CurrentDate:" in combined
                assert "System Info:" in combined
                assert "uname:Linux" in combined
