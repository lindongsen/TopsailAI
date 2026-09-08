"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-09-08
Purpose: Unit tests for ai_base/llm_control/configuration.py
"""

from types import SimpleNamespace

import pytest

from topsailai.ai_base.llm_control.configuration import (
    get_first_byte_timeout_config,
)


class TestGetFirstByteTimeoutConfig:
    """Tests for get_first_byte_timeout_config function."""

    def test_defaults_when_unset(self):
        """Test default values when no environment variables are set."""
        reader = SimpleNamespace(
            get=lambda name, default=None, formatter=None: default,
            check_bool=lambda name, default=None: default,
        )
        timeout, raise_on_timeout = get_first_byte_timeout_config(reader)
        assert timeout == 180
        assert raise_on_timeout is False

    def test_float_value_parsed(self):
        """Test that a float timeout value is parsed and returned."""
        reader = SimpleNamespace(
            get=lambda name, default=None, formatter=None: formatter("0.05"),
            check_bool=lambda name, default=None: False,
        )
        timeout, raise_on_timeout = get_first_byte_timeout_config(reader)
        assert timeout == 0.05
        assert raise_on_timeout is False

    def test_none_timeout_falls_back_to_default(self):
        """Test that a None timeout falls back to the default 180."""
        reader = SimpleNamespace(
            get=lambda name, default=None, formatter=None: None,
            check_bool=lambda name, default=None: False,
        )
        timeout, raise_on_timeout = get_first_byte_timeout_config(reader)
        assert timeout == 180
        assert raise_on_timeout is False

    def test_raise_on_timeout_true(self):
        """Test that raise_on_timeout reflects the check_bool result."""
        reader = SimpleNamespace(
            get=lambda name, default=None, formatter=None: 180,
            check_bool=lambda name, default=None: True,
        )
        timeout, raise_on_timeout = get_first_byte_timeout_config(reader)
        assert timeout == 180
        assert raise_on_timeout is True

    def test_uses_default_env_reader_when_none(self, monkeypatch):
        """Test that the default EnvReaderInstance is used when env_reader is None."""
        monkeypatch.delenv("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT", raising=False)
        monkeypatch.delenv("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE", raising=False)
        timeout, raise_on_timeout = get_first_byte_timeout_config()
        assert timeout == 180
        assert raise_on_timeout is False

    def test_malformed_timeout_falls_back_to_default(self, monkeypatch):
        """Test that a malformed timeout falls back to the default 180."""
        monkeypatch.setenv("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT", "not-a-number")
        monkeypatch.setenv("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE", "yes")
        timeout, raise_on_timeout = get_first_byte_timeout_config()
        assert timeout == 180
        assert raise_on_timeout is True
