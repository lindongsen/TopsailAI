"""
Unit tests for topsailai.tools.base.init module.

Tests cover:
- CONN_CHAR default and env override
- ENABLED_TOOLS / DISABLED_TOOLS parsing
- is_tool_enabled logic (disabled list, enabled list, FLAG_TOOL_ENABLED, wildcard, plus)
- TOOLS / TOOLS_INFO / TOOL_PROMPT creation
"""

import pytest
from unittest.mock import MagicMock, patch


class FakeModule:
    """Fake module object for testing is_tool_enabled."""
    def __init__(self, name, flag_enabled=None):
        self.__name__ = name
        if flag_enabled is not None:
            self.FLAG_TOOL_ENABLED = flag_enabled


class TestIsToolEnabled:
    """Tests for is_tool_enabled function."""

    def test_no_config_tool_enabled_by_default(self, monkeypatch):
        """When no ENABLED_TOOLS or DISABLED_TOOLS, tool is enabled by default."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is True

    def test_disabled_tools_exact_match(self, monkeypatch):
        """Tool is disabled when its exact name is in DISABLED_TOOLS."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", ["file_tool"])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is False

    def test_disabled_tools_prefix_match(self, monkeypatch):
        """Tool is disabled when its name starts with a disabled prefix."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", ["file"])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is False

    def test_disabled_tools_no_match(self, monkeypatch):
        """Tool is enabled when not in DISABLED_TOOLS and no ENABLED_TOOLS."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", ["other_tool"])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is True

    def test_enabled_tools_exact_match(self, monkeypatch):
        """Tool is enabled when its exact name is in ENABLED_TOOLS."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", ["file_tool"])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is True

    def test_enabled_tools_prefix_match(self, monkeypatch):
        """Tool is enabled when its name starts with an enabled prefix."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", ["file"])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is True

    def test_enabled_tools_wildcard(self, monkeypatch):
        """All tools enabled when '*' is in ENABLED_TOOLS."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", ["*"])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.any_tool")
        assert is_tool_enabled(mod) is True

    def test_enabled_tools_plus_with_flag_false(self, monkeypatch):
        """With '+' in ENABLED_TOOLS, tool with FLAG_TOOL_ENABLED=False is NOT enabled
        because '+' is checked after FLAG_TOOL_ENABLED, and FLAG_TOOL_ENABLED=False
        returns False when ENABLED_TOOLS is non-empty and tool not in list."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", ["+"])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool", flag_enabled=False)
        assert is_tool_enabled(mod) is False

    def test_enabled_tools_plus_no_flag(self, monkeypatch):
        """With '+' in ENABLED_TOOLS, tool without FLAG_TOOL_ENABLED is enabled."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", ["+"])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is True

    def test_flag_false_no_enabled_tools(self, monkeypatch):
        """Tool with FLAG_TOOL_ENABLED=False is disabled when no ENABLED_TOOLS."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool", flag_enabled=False)
        assert is_tool_enabled(mod) is False

    def test_flag_true_no_enabled_tools(self, monkeypatch):
        """Tool with FLAG_TOOL_ENABLED=True is enabled when no ENABLED_TOOLS."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool", flag_enabled=True)
        assert is_tool_enabled(mod) is True

    def test_disabled_overrides_enabled(self, monkeypatch):
        """DISABLED_TOOLS takes precedence over ENABLED_TOOLS."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", ["file_tool"])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", ["file_tool"])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is False

    def test_enabled_tools_no_match(self, monkeypatch):
        """Tool is disabled when ENABLED_TOOLS is set but tool not in list."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", ["other_tool"])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is False

    def test_no_flag_attribute_no_enabled_tools(self, monkeypatch):
        """Tool without FLAG_TOOL_ENABLED is enabled by default."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is True

    def test_no_flag_attribute_with_enabled_tools(self, monkeypatch):
        """Tool without FLAG_TOOL_ENABLED is disabled when ENABLED_TOOLS set but no match."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", ["other_tool"])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is False

    def test_flag_false_but_in_enabled_list(self, monkeypatch):
        """Tool with FLAG_TOOL_ENABLED=False is enabled if explicitly in ENABLED_TOOLS."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", ["file_tool"])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool", flag_enabled=False)
        assert is_tool_enabled(mod) is True


class TestModuleVariables:
    """Tests for module-level variables created at import time."""

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_conn_char_default(self, mock_env, mock_get_map):
        """CONN_CHAR defaults to '-' when env var not set."""
        mock_env.get.return_value = None
        mock_env.get_list_str.return_value = None
        mock_get_map.return_value = {}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import CONN_CHAR
        assert CONN_CHAR == "-"

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_conn_char_from_env(self, mock_env, mock_get_map):
        """CONN_CHAR reads from TOPSAILAI_TOOL_CONN_CHAR env var."""
        mock_env.get.return_value = "."
        mock_env.get_list_str.return_value = None
        mock_get_map.return_value = {}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import CONN_CHAR
        assert CONN_CHAR == "."

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_tools_created(self, mock_env, mock_get_map):
        """TOOLS dict is populated from get_function_map."""
        mock_env.get.return_value = None
        mock_env.get_list_str.return_value = None
        mock_get_map.return_value = {"cmd_tool.exec_cmd": lambda x: x}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import TOOLS
        assert "cmd_tool.exec_cmd" in TOOLS

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_tools_info_created(self, mock_env, mock_get_map):
        """TOOLS_INFO dict is populated from get_function_map."""
        mock_env.get.return_value = None
        mock_env.get_list_str.return_value = None
        tool_info = {"type": "function", "function": {"name": "test"}}
        mock_get_map.return_value = {"cmd_tool.exec_cmd": tool_info}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import TOOLS_INFO
        assert "cmd_tool.exec_cmd" in TOOLS_INFO
        assert TOOLS_INFO["cmd_tool.exec_cmd"]["type"] == "function"

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_tool_prompt_contains_tools(self, mock_env, mock_get_map):
        """TOOL_PROMPT contains the __TOOLS__ placeholder."""
        mock_env.get.return_value = None
        mock_env.get_list_str.return_value = None
        mock_get_map.return_value = {}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import TOOL_PROMPT
        assert "{__TOOLS__}" in TOOL_PROMPT

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_tool_prompt_uses_conn_char(self, mock_env, mock_get_map):
        """TOOL_PROMPT uses CONN_CHAR in the attention note."""
        mock_env.get.return_value = "."
        mock_env.get_list_str.return_value = None
        mock_get_map.return_value = {}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import TOOL_PROMPT, CONN_CHAR
        assert CONN_CHAR in TOOL_PROMPT

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_enabled_tools_from_env(self, mock_env, mock_get_map):
        """ENABLED_TOOLS reads from TOPSAILAI_ENABLED_TOOLS env var."""
        mock_env.get.return_value = None
        mock_env.get_list_str.side_effect = lambda key, separator=None: ["file_tool", "cmd_tool"] if "TOPSAILAI_ENABLED_TOOLS" in key else None
        mock_get_map.return_value = {}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import ENABLED_TOOLS
        assert ENABLED_TOOLS == ["file_tool", "cmd_tool"]

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_disabled_tools_from_env(self, mock_env, mock_get_map):
        """DISABLED_TOOLS reads from TOPSAILAI_DISABLED_TOOLS env var."""
        mock_env.get.return_value = None
        mock_env.get_list_str.side_effect = lambda key, separator=None: ["ai_team"] if "TOPSAILAI_DISABLED_TOOLS" in key else None
        mock_get_map.return_value = {}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import DISABLED_TOOLS
        assert DISABLED_TOOLS == ["ai_team"]

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_fallback_enabled_tools_env(self, mock_env, mock_get_map):
        """ENABLED_TOOLS falls back to ENABLED_TOOLS env var."""
        mock_env.get.return_value = None
        def side_effect(key, separator=None):
            if key == "TOPSAILAI_ENABLED_TOOLS":
                return None
            if key == "ENABLED_TOOLS":
                return ["cmd_tool"]
            return None
        mock_env.get_list_str.side_effect = side_effect
        mock_get_map.return_value = {}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import ENABLED_TOOLS
        assert ENABLED_TOOLS == ["cmd_tool"]

    @patch("topsailai.tools.base.init.module_tool.get_function_map")
    @patch("topsailai.tools.base.init.env_tool.EnvReaderInstance")
    def test_fallback_disabled_tools_env(self, mock_env, mock_get_map):
        """DISABLED_TOOLS falls back to DISABLED_TOOLS env var."""
        mock_env.get.return_value = None
        def side_effect(key, separator=None):
            if key == "TOPSAILAI_DISABLED_TOOLS":
                return None
            if key == "DISABLED_TOOLS":
                return ["ai_team"]
            return None
        mock_env.get_list_str.side_effect = side_effect
        mock_get_map.return_value = {}

        import importlib
        from topsailai.tools import base
        importlib.reload(base.init)
        from topsailai.tools.base.init import DISABLED_TOOLS
        assert DISABLED_TOOLS == ["ai_team"]


class TestIsToolEnabledEdgeCases:
    """Edge case tests for is_tool_enabled."""

    def test_disabled_tools_empty_list(self, monkeypatch):
        """Empty DISABLED_TOOLS list does not disable any tool."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is True

    def test_enabled_tools_empty_list(self, monkeypatch):
        """Empty ENABLED_TOOLS list means default behavior."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        assert is_tool_enabled(mod) is True

    def test_module_name_with_multiple_dots(self, monkeypatch):
        """is_tool_enabled extracts last part of dotted module name."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", ["subagent"])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.subagent.subagent_tool")
        assert is_tool_enabled(mod) is False

    def test_flag_attribute_exception_handled(self, monkeypatch):
        """Exception when accessing FLAG_TOOL_ENABLED is handled gracefully."""
        monkeypatch.setattr("topsailai.tools.base.init.ENABLED_TOOLS", [])
        monkeypatch.setattr("topsailai.tools.base.init.DISABLED_TOOLS", [])
        from topsailai.tools.base.init import is_tool_enabled
        mod = FakeModule("topsailai.tools.file_tool")
        # Delete FLAG_TOOL_ENABLED if it exists
        if hasattr(mod, "FLAG_TOOL_ENABLED"):
            delattr(mod, "FLAG_TOOL_ENABLED")
        assert is_tool_enabled(mod) is True
