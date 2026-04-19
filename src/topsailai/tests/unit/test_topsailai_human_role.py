"""
Unit tests for topsailai.human.role module.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-18
Purpose: Test human role name resolution logic
"""

import os
import pytest
from unittest.mock import patch

from src.topsailai.human.role import (
    get_human_name,
    HUMAN_STARTSWITH
)


class TestHumanStartsWith:
    """Test HUMAN_STARTSWITH constant"""
    
    def test_human_startswith_value(self):
        """Test HUMAN_STARTSWITH constant value is 'Human.'"""
        assert HUMAN_STARTSWITH == "Human."


class TestGetHumanNameWithParameter:
    """Test get_human_name function with explicit parameter"""
    
    def test_with_explicit_name_no_prefix(self):
        """Test get_human_name with explicit name without prefix"""
        result = get_human_name("Alice")
        assert result == "Human.Alice"
    
    def test_with_explicit_name_with_prefix(self):
        """Test get_human_name with explicit name that already has prefix"""
        result = get_human_name("Human.Bob")
        assert result == "Human.Bob"
    
    def test_with_explicit_name_empty_string(self):
        """Test get_human_name with empty string parameter"""
        result = get_human_name("")
        # Empty string is falsy, should fall back to env var or default
        assert result == "Human.DawsonLin"
    
    def test_with_explicit_name_none(self):
        """Test get_human_name with None parameter"""
        result = get_human_name(None)
        # None is falsy, should fall back to env var or default
        assert result == "Human.DawsonLin"


class TestGetHumanNameWithEnvVar:
    """Test get_human_name function with environment variable"""
    
    def test_with_env_var_no_prefix(self):
        """Test get_human_name reads from env var without prefix"""
        with patch.dict(os.environ, {"TOPSAILAI_HUMAN_NAME": "Charlie"}):
            result = get_human_name()
            assert result == "Human.Charlie"
    
    def test_with_env_var_with_prefix(self):
        """Test get_human_name reads from env var with existing prefix"""
        with patch.dict(os.environ, {"TOPSAILAI_HUMAN_NAME": "Human.Dave"}):
            result = get_human_name()
            assert result == "Human.Dave"
    
    def test_with_env_var_empty_string(self):
        """Test get_human_name with empty env var falls back to default"""
        with patch.dict(os.environ, {"TOPSAILAI_HUMAN_NAME": ""}):
            result = get_human_name()
            assert result == "Human.DawsonLin"
    
    def test_with_env_var_not_set(self):
        """Test get_human_name when env var is not set"""
        with patch.dict(os.environ, {}, clear=True):
            result = get_human_name()
            assert result == "Human.DawsonLin"


class TestGetHumanNameDefaultValue:
    """Test get_human_name function default value behavior"""
    
    def test_default_value(self):
        """Test default value is 'Human.DawsonLin' when no input provided"""
        with patch.dict(os.environ, {}, clear=True):
            result = get_human_name()
            assert result == "Human.DawsonLin"
    
    def test_default_value_with_empty_env(self):
        """Test default value when env var is empty string"""
        with patch.dict(os.environ, {"TOPSAILAI_HUMAN_NAME": ""}):
            result = get_human_name()
            assert result == "Human.DawsonLin"


class TestGetHumanNamePrefixHandling:
    """Test get_human_name function prefix handling logic"""
    
    def test_prefix_added_when_missing(self):
        """Test 'Human.' prefix is added when not present"""
        result = get_human_name("Eve")
        assert result.startswith(HUMAN_STARTSWITH)
        assert result == "Human.Eve"
    
    def test_prefix_not_duplicated(self):
        """Test 'Human.' prefix is not duplicated if already present"""
        result = get_human_name("Human.Frank")
        assert result.count("Human.") == 1
        assert result == "Human.Frank"
    
    def test_prefix_case_sensitive(self):
        """Test prefix matching is case sensitive"""
        result = get_human_name("human.Gina")
        # Should add prefix because 'human.' != 'Human.'
        assert result == "Human.human.Gina"


class TestGetHumanNameEdgeCases:
    """Test get_human_name function edge cases"""
    
    def test_special_characters_in_name(self):
        """Test get_human_name with special characters in name"""
        result = get_human_name("John_Doe-123")
        assert result == "Human.John_Doe-123"
    
    def test_unicode_characters(self):
        """Test get_human_name with unicode characters"""
        result = get_human_name("张三")
        assert result == "Human.张三"
    
    def test_long_name(self):
        """Test get_human_name with long name"""
        long_name = "A" * 100
        result = get_human_name(long_name)
        assert result == "Human." + long_name
    
    def test_numeric_name(self):
        """Test get_human_name with numeric string"""
        result = get_human_name("12345")
        assert result == "Human.12345"
    
    def test_whitespace_name(self):
        """Test get_human_name with whitespace in name"""
        result = get_human_name("  Space  ")
        assert result == "Human.  Space  "
    
    def test_parameter_overrides_env_var(self):
        """Test explicit parameter takes precedence over env var"""
        with patch.dict(os.environ, {"TOPSAILAI_HUMAN_NAME": "EnvName"}):
            result = get_human_name("ExplicitName")
            assert result == "Human.ExplicitName"


class TestGetHumanNameIntegration:
    """Integration tests for get_human_name function"""
    
    def test_full_workflow_no_input(self):
        """Test complete workflow with no input provided"""
        with patch.dict(os.environ, {}, clear=True):
            result = get_human_name()
            assert result == "Human.DawsonLin"
    
    def test_full_workflow_with_env(self):
        """Test complete workflow with env var set"""
        with patch.dict(os.environ, {"TOPSAILAI_HUMAN_NAME": "TestUser"}):
            result = get_human_name()
            assert result == "Human.TestUser"
    
    def test_full_workflow_with_param(self):
        """Test complete workflow with explicit parameter"""
        result = get_human_name("CustomUser")
        assert result == "Human.CustomUser"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
