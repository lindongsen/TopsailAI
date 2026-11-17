"""
Unit tests for tools/base module.

Test coverage:
- CONN_CHAR constant
- is_tool_enabled function
- TOOLS and TOOLS_INFO dictionaries
- TOOL_PROMPT template
- add_tool function
- get_tools_by_module function
- get_tool_prompt function
- expand_plugin_tools function
- generate_tool_info function
- get_tools_for_chat function
- format_tools_map function

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock


class TestConnChar(unittest.TestCase):
    """Test cases for CONN_CHAR constant."""

    def test_conn_char_default_value(self):
        """Test CONN_CHAR has default value of '-'."""
        from topsailai.tools.base.init import CONN_CHAR
        self.assertEqual(CONN_CHAR, "-")

    def test_conn_char_is_string(self):
        """Test CONN_CHAR is a string type."""
        from topsailai.tools.base.init import CONN_CHAR
        self.assertIsInstance(CONN_CHAR, str)


class TestIsToolEnabled(unittest.TestCase):
    """Test cases for is_tool_enabled function."""

    def test_tool_enabled_no_config(self):
        """Test tool is enabled when no ENABLED_TOOLS or DISABLED_TOOLS configured."""
        with patch('topsailai.tools.base.init.ENABLED_TOOLS', None), \
             patch('topsailai.tools.base.init.DISABLED_TOOLS', None):
            from topsailai.tools.base.init import is_tool_enabled
            
            mock_tool = MagicMock()
            mock_tool.__name__ = "test_tool"
            mock_tool.FLAG_TOOL_ENABLED = True
            
            self.assertTrue(is_tool_enabled(mock_tool))

    def test_tool_disabled_explicit(self):
        """Test tool is disabled when in DISABLED_TOOLS list."""
        with patch('topsailai.tools.base.init.ENABLED_TOOLS', None), \
             patch('topsailai.tools.base.init.DISABLED_TOOLS', ['test_tool']):
            from topsailai.tools.base.init import is_tool_enabled
            
            mock_tool = MagicMock()
            mock_tool.__name__ = "test_tool"
            
            self.assertFalse(is_tool_enabled(mock_tool))

    def test_tool_disabled_by_prefix(self):
        """Test tool is disabled when its prefix matches a disabled tool."""
        with patch('topsailai.tools.base.init.ENABLED_TOOLS', None), \
             patch('topsailai.tools.base.init.DISABLED_TOOLS', ['ai_team']):
            from topsailai.tools.base.init import is_tool_enabled
            
            mock_tool = MagicMock()
            mock_tool.__name__ = "ai_team_tool"
            
            self.assertFalse(is_tool_enabled(mock_tool))

    def test_tool_enabled_explicit(self):
        """Test tool is enabled when in ENABLED_TOOLS list."""
        with patch('topsailai.tools.base.init.ENABLED_TOOLS', ['test_tool']), \
             patch('topsailai.tools.base.init.DISABLED_TOOLS', None):
            from topsailai.tools.base.init import is_tool_enabled
            
            mock_tool = MagicMock()
            mock_tool.__name__ = "test_tool"
            
            self.assertTrue(is_tool_enabled(mock_tool))

    def test_tool_enabled_by_prefix(self):
        """Test tool is enabled when its prefix matches an enabled tool."""
        with patch('topsailai.tools.base.init.ENABLED_TOOLS', ['ai_team']), \
             patch('topsailai.tools.base.init.DISABLED_TOOLS', None):
            from topsailai.tools.base.init import is_tool_enabled
            
            mock_tool = MagicMock()
            mock_tool.__name__ = "ai_team_tool"
            
            self.assertTrue(is_tool_enabled(mock_tool))

    def test_tool_enabled_wildcard(self):
        """Test all tools are enabled when '*' is in ENABLED_TOOLS."""
        with patch('topsailai.tools.base.init.ENABLED_TOOLS', ['*']), \
             patch('topsailai.tools.base.init.DISABLED_TOOLS', None):
            from topsailai.tools.base.init import is_tool_enabled
            
            mock_tool = MagicMock()
            mock_tool.__name__ = "any_tool"
            
            self.assertTrue(is_tool_enabled(mock_tool))

    def test_tool_disabled_flag(self):
        """Test tool is disabled when FLAG_TOOL_ENABLED is False and no ENABLED_TOOLS."""
        with patch('topsailai.tools.base.init.ENABLED_TOOLS', None), \
             patch('topsailai.tools.base.init.DISABLED_TOOLS', None):
            from topsailai.tools.base.init import is_tool_enabled
            
            mock_tool = MagicMock()
            mock_tool.__name__ = "disabled_tool"
            mock_tool.FLAG_TOOL_ENABLED = False
            
            self.assertFalse(is_tool_enabled(mock_tool))

    def test_tool_disabled_flag_with_enabled_list(self):
        """Test tool is enabled when FLAG_TOOL_ENABLED is False but tool is in ENABLED_TOOLS."""
        with patch('topsailai.tools.base.init.ENABLED_TOOLS', ['disabled_tool']), \
             patch('topsailai.tools.base.init.DISABLED_TOOLS', None):
            from topsailai.tools.base.init import is_tool_enabled
            
            mock_tool = MagicMock()
            mock_tool.__name__ = "disabled_tool"
            mock_tool.FLAG_TOOL_ENABLED = False
            
            self.assertTrue(is_tool_enabled(mock_tool))


class TestToolsAndToolsInfo(unittest.TestCase):
    """Test cases for TOOLS and TOOLS_INFO dictionaries."""

    def test_tools_is_dict(self):
        """Test TOOLS is a dictionary."""
        from topsailai.tools.base.init import TOOLS
        self.assertIsInstance(TOOLS, dict)

    def test_tools_info_is_dict(self):
        """Test TOOLS_INFO is a dictionary."""
        from topsailai.tools.base.init import TOOLS_INFO
        self.assertIsInstance(TOOLS_INFO, dict)

    def test_tools_not_empty(self):
        """Test TOOLS is not empty (at least some tools registered)."""
        from topsailai.tools.base.init import TOOLS
        self.assertGreater(len(TOOLS), 0)

    def test_tools_values_are_callable(self):
        """Test all values in TOOLS are callable functions."""
        from topsailai.tools.base.init import TOOLS
        for name, func in TOOLS.items():
            self.assertTrue(callable(func), f"Tool {name} is not callable")


class TestCollectPackageToolsInfo(unittest.TestCase):
    """Test cases for adopting TOOLS_INFO declared inside tool packages."""

    def _make_tool(self, module_name, func_name):
        """Build a callable whose __module__ and __name__ are controlled."""
        def _tool():
            """probe tool"""
            return None
        _tool.__module__ = module_name
        _tool.__name__ = func_name
        return _tool

    def test_package_schema_is_adopted_under_registered_key(self):
        """A schema declared in a package module is adopted under the registry key."""
        from topsailai.tools.base import init as base_init
        from topsailai.tools.file_tool_utils import file_read_line

        spec = {
            "type": "function",
            "function": {
                "name": "",
                "description": "probe",
                "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
        }
        original = getattr(file_read_line, "TOOLS_INFO", None)
        file_read_line.TOOLS_INFO = {"read_file_with_context": spec}
        try:
            tools = {"file_tool-read_file_with_context": self._make_tool(
                "topsailai.tools.file_tool_utils.file_read_line", "read_file_with_context")}
            result = base_init._collect_package_tools_info(tools, {}, base_init.CONN_CHAR)
        finally:
            if original is None:
                del file_read_line.TOOLS_INFO
            else:
                file_read_line.TOOLS_INFO = original

        self.assertIn("file_tool-read_file_with_context", result)
        self.assertEqual(result["file_tool-read_file_with_context"], spec)

    def test_package_module_prefix_is_not_introduced(self):
        """Adoption must not create a key prefixed by the package module name."""
        from topsailai.tools.base import init as base_init
        from topsailai.tools.file_tool_utils import file_read_line

        original = getattr(file_read_line, "TOOLS_INFO", None)
        file_read_line.TOOLS_INFO = {
            "read_file_lines": {"type": "function", "function": {"name": "", "description": "p", "parameters": {"type": "object"}}}
        }
        try:
            tools = {"file_tool-read_file_lines": self._make_tool(
                "topsailai.tools.file_tool_utils.file_read_line", "read_file_lines")}
            result = base_init._collect_package_tools_info(tools, {}, base_init.CONN_CHAR)
        finally:
            if original is None:
                del file_read_line.TOOLS_INFO
            else:
                file_read_line.TOOLS_INFO = original

        self.assertIn("file_tool-read_file_lines", result)
        self.assertEqual([k for k in result if k.startswith("file_read_line-")], [])

    def test_alias_key_is_resolved_before_function_name(self):
        """A registered key that differs from __name__ still resolves its schema."""
        from topsailai.tools.base import init as base_init
        from topsailai.tools.file_tool_utils import file_write_code_block

        spec = {"type": "function", "function": {"name": "", "description": "alias", "parameters": {"type": "object"}}}
        original = getattr(file_write_code_block, "TOOLS_INFO", None)
        file_write_code_block.TOOLS_INFO = {"overwrite_lines_in_file": spec}
        try:
            tools = {"file_tool-overwrite_lines_in_file": self._make_tool(
                "topsailai.tools.file_tool_utils.file_write_code_block", "overwrite_code_block")}
            result = base_init._collect_package_tools_info(tools, {}, base_init.CONN_CHAR)
        finally:
            if original is None:
                del file_write_code_block.TOOLS_INFO
            else:
                file_write_code_block.TOOLS_INFO = original

        self.assertIn("file_tool-overwrite_lines_in_file", result)
        self.assertEqual(result["file_tool-overwrite_lines_in_file"], spec)

    def test_existing_entry_is_not_overwritten(self):
        """An already collected schema wins over a package declaration."""
        from topsailai.tools.base import init as base_init
        from topsailai.tools.file_tool_utils import file_read_line

        original = getattr(file_read_line, "TOOLS_INFO", None)
        file_read_line.TOOLS_INFO = {"read_file_lines": {"type": "function", "function": {"name": "", "description": "pkg", "parameters": {"type": "object"}}}}
        existing = {"type": "function", "function": {"name": "", "description": "existing", "parameters": {"type": "object"}}}
        try:
            tools = {"file_tool-read_file_lines": self._make_tool(
                "topsailai.tools.file_tool_utils.file_read_line", "read_file_lines")}
            result = base_init._collect_package_tools_info(tools, {"file_tool-read_file_lines": existing}, base_init.CONN_CHAR)
        finally:
            if original is None:
                del file_read_line.TOOLS_INFO
            else:
                file_read_line.TOOLS_INFO = original

        self.assertEqual(result["file_tool-read_file_lines"], existing)

    def test_module_without_tools_info_is_ignored(self):
        """A module that declares no TOOLS_INFO contributes nothing."""
        from topsailai.tools.base import init as base_init

        tools = {"file_tool-read_file": self._make_tool("topsailai.tools.file_tool", "read_file")}
        result = base_init._collect_package_tools_info(tools, {}, base_init.CONN_CHAR)
        self.assertEqual(result, {})

    def test_unresolvable_module_is_skipped(self):
        """A tool whose module cannot be imported is skipped without raising."""
        from topsailai.tools.base import init as base_init

        tools = {"ghost_tool-ghost": self._make_tool("topsailai.tools.not_a_real_module", "ghost")}
        result = base_init._collect_package_tools_info(tools, {}, base_init.CONN_CHAR)
        self.assertEqual(result, {})

    def test_production_registry_keeps_cmd_tool_schema(self):
        """The only real TOOLS_INFO in the tree survives adoption."""
        from topsailai.tools.base.init import TOOLS_INFO
        self.assertIn("cmd_tool-exec_cmd", TOOLS_INFO)

    def test_module_level_wiring_adopts_package_schema(self):
        """Re-importing the registry module adopts a package-declared schema."""
        import os
        import subprocess
        import sys

        script = (
            "import sys\n"
            "sys.path.insert(0, '/TopsailAI/src')\n"
            "sys.path.insert(0, '/TopsailAI/src/topsailai')\n"
            "from topsailai.tools.file_tool_utils import file_read_line\n"
            "file_read_line.TOOLS_INFO = {'read_file_with_context': {'type': 'function', 'function': {'name': '', 'description': 'wired', 'parameters': {'type': 'object'}}}}\n"
            "sys.modules.pop('topsailai.tools.base.init', None)\n"
            "sys.modules.pop('topsailai.tools.base', None)\n"
            "from topsailai.tools.base import init as base_init\n"
            "print('WIRED' if 'file_tool-read_file_with_context' in base_init.TOOLS_INFO else 'MISSING')\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = "/TopsailAI/src/topsailai:/TopsailAI/src"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=env, timeout=120,
        )
        self.assertIn("WIRED", completed.stdout, completed.stderr)


class TestToolPrompt(unittest.TestCase):
    """Test cases for TOOL_PROMPT template."""

    def test_tool_prompt_is_string(self):
        """Test TOOL_PROMPT is a string."""
        from topsailai.tools.base.init import TOOL_PROMPT
        self.assertIsInstance(TOOL_PROMPT, str)

    def test_tool_prompt_contains_tools_marker(self):
        """Test TOOL_PROMPT contains __TOOLS__ placeholder."""
        from topsailai.tools.base.init import TOOL_PROMPT
        self.assertIn("__TOOLS__", TOOL_PROMPT)

    def test_tool_prompt_contains_conn_char(self):
        """Test TOOL_PROMPT contains CONN_CHAR."""
        from topsailai.tools.base.init import TOOL_PROMPT, CONN_CHAR
        self.assertIn(CONN_CHAR, TOOL_PROMPT)


class TestAddTool(unittest.TestCase):
    """Test cases for add_tool function."""

    def test_add_tool_with_name(self):
        """Test adding a tool with explicit name."""
        from topsailai.tools.base import common
        from topsailai.tools.base.init import TOOLS
        
        def test_func():
            pass
        
        common.add_tool("test_custom_tool", test_func)
        
        try:
            self.assertIn("test_custom_tool", TOOLS)
            self.assertEqual(TOOLS["test_custom_tool"], test_func)
        finally:
            # Cleanup
            if "test_custom_tool" in TOOLS:
                del TOOLS["test_custom_tool"]

    def test_add_tool_without_name(self):
        """Test adding a tool without name uses function name."""
        from topsailai.tools.base import common
        from topsailai.tools.base.init import TOOLS, CONN_CHAR
        
        def my_test_function():
            pass
        
        common.add_tool("", my_test_function)
        
        try:
            # Source code uses "aiagent_tool" prefix
            expected_name = f"aiagent_tool{CONN_CHAR}my_test_function"
            self.assertIn(expected_name, TOOLS)
            self.assertEqual(TOOLS[expected_name], my_test_function)
        finally:
            # Cleanup
            expected_name = f"aiagent_tool{CONN_CHAR}my_test_function"
            if expected_name in TOOLS:
                del TOOLS[expected_name]

    def test_add_tool_invalid_function(self):
        """Test adding an invalid (non-callable) tool raises assertion error."""
        from topsailai.tools.base import common
        
        with self.assertRaises(AssertionError):
            common.add_tool("invalid_tool", "not_a_function")


class TestGetToolsByModule(unittest.TestCase):
    """Test cases for get_tools_by_module function."""

    def test_get_tools_by_module_returns_dict(self):
        """Test get_tools_by_module returns a dictionary."""
        from topsailai.tools.base.common import get_tools_by_module
        
        result = get_tools_by_module("topsailai.tools.base.init", "TOOLS")
        
        self.assertIsInstance(result, dict)

    def test_get_tools_by_module_keys_have_prefix(self):
        """Test returned tool names have module prefix."""
        from topsailai.tools.base.common import get_tools_by_module
        
        result = get_tools_by_module("topsailai.tools.base.init", "TOOLS")
        
        for tool_name in result.keys():
            self.assertTrue(tool_name.startswith("init-"))


class TestGetToolPrompt(unittest.TestCase):
    """Test cases for get_tool_prompt function."""

    def test_get_tool_prompt_empty_when_no_tools(self):
        """Test get_tool_prompt returns empty string when no tools specified."""
        from topsailai.tools.base.common import get_tool_prompt
        
        result = get_tool_prompt(tools_name=None, tools_map=None)
        
        self.assertEqual(result, "")

    def test_get_tool_prompt_with_tools_name(self):
        """Test get_tool_prompt returns formatted prompt with tool names."""
        from topsailai.tools.base.common import get_tool_prompt
        from topsailai.tools.base.init import TOOLS
        
        if TOOLS:
            first_tool_name = list(TOOLS.keys())[0]
            result = get_tool_prompt(tools_name=[first_tool_name])
            
            self.assertIsInstance(result, str)
            # __TOOLS__ is replaced with actual tool content
            self.assertIn(first_tool_name, result)


class TestGenerateToolInfo(unittest.TestCase):
    """Test cases for generate_tool_info function."""

    def test_generate_tool_info_returns_dict(self):
        """Test generate_tool_info returns a dictionary."""
        from topsailai.tools.base.common import generate_tool_info
        
        result = generate_tool_info("test_tool", "Test description")
        
        self.assertIsInstance(result, dict)

    def test_generate_tool_info_structure(self):
        """Test generate_tool_info returns correct structure."""
        from topsailai.tools.base.common import generate_tool_info
        
        result = generate_tool_info("test_tool", "Test description")
        
        self.assertIn("type", result)
        self.assertIn("function", result)
        self.assertEqual(result["type"], "function")
        self.assertEqual(result["function"]["name"], "test_tool")
        self.assertEqual(result["function"]["description"], "Test description")
        self.assertIn("parameters", result["function"])

    def test_generate_tool_info_parameters_type(self):
        """Test generate_tool_info parameters has correct type."""
        from topsailai.tools.base.common import generate_tool_info
        
        result = generate_tool_info("test_tool", "Test description")
        
        self.assertEqual(result["function"]["parameters"]["type"], "object")


class TestGetToolsForChat(unittest.TestCase):
    """Test cases for get_tools_for_chat function."""

    def test_get_tools_for_chat_returns_dict(self):
        """Test get_tools_for_chat returns a dictionary."""
        from topsailai.tools.base.common import get_tools_for_chat
        
        result = get_tools_for_chat({})
        
        self.assertIsInstance(result, dict)

    def test_get_tools_for_chat_with_tools_info(self):
        """Test get_tools_for_chat uses TOOLS_INFO when available."""
        from topsailai.tools.base.common import get_tools_for_chat
        from topsailai.tools.base.init import TOOLS_INFO
        
        if TOOLS_INFO:
            first_tool = list(TOOLS_INFO.keys())[0]
            result = get_tools_for_chat({first_tool: None})
            
            self.assertIn(first_tool, result)

    def test_get_tools_for_chat_generates_info(self):
        """Test get_tools_for_chat generates info for tools not in TOOLS_INFO."""
        from topsailai.tools.base.common import get_tools_for_chat
        from topsailai.tools.base.init import TOOLS, TOOLS_INFO
        
        for tool_name, tool_func in TOOLS.items():
            if tool_name not in TOOLS_INFO:
                result = get_tools_for_chat({tool_name: tool_func})
                
                self.assertIn(tool_name, result)
                self.assertEqual(result[tool_name]["function"]["name"], tool_name)
                break
        else:
            # All tools are in TOOLS_INFO, skip test
            self.skipTest("All tools in TOOLS_INFO, nothing to test")


class TestFormatToolsMap(unittest.TestCase):
    """Test cases for format_tools_map function."""

    def test_format_tools_map_returns_dict(self):
        """Test format_tools_map returns a dictionary."""
        from topsailai.tools.base.common import format_tools_map
        
        result = format_tools_map({}, "prefix")
        
        self.assertIsInstance(result, dict)

    def test_format_tools_map_adds_prefix(self):
        """Test format_tools_map adds prefix to tool names."""
        from topsailai.tools.base.common import format_tools_map
        
        result = format_tools_map({"tool1": "func1"}, "prefix")
        
        self.assertIn("prefix.tool1", result)

    def test_format_tools_map_without_dot(self):
        """Test format_tools_map adds dot if prefix doesn't end with one."""
        from topsailai.tools.base.common import format_tools_map
        
        result = format_tools_map({"tool1": "func1"}, "prefix")
        
        self.assertIn("prefix.tool1", result)

    def test_format_tools_map_already_has_prefix(self):
        """Test format_tools_map doesn't duplicate prefix."""
        from topsailai.tools.base.common import format_tools_map
        
        result = format_tools_map({"prefix.tool1": "func1"}, "prefix")
        
        self.assertIn("prefix.tool1", result)
        self.assertNotIn("prefix.prefix.tool1", result)

    def test_format_tools_map_preserves_values(self):
        """Test format_tools_map preserves tool function references."""
        from topsailai.tools.base.common import format_tools_map
        
        func = lambda: None
        result = format_tools_map({"tool1": func}, "prefix")
        
        self.assertEqual(result["prefix.tool1"], func)


class TestExpandPluginTools(unittest.TestCase):
    """Test cases for expand_plugin_tools function."""

    def test_expand_plugin_tools_no_plugins(self):
        """Test expand_plugin_tools handles no plugins gracefully."""
        from topsailai.tools.base.common import expand_plugin_tools
        
        # Should not raise any exception
        expand_plugin_tools()

    def test_expand_plugin_tools_with_env_var(self):
        """Test expand_plugin_tools reads from environment variable."""
        from topsailai.tools.base.common import expand_plugin_tools
        
        with patch('topsailai.tools.base.common.env_tool.EnvReaderInstance.get_list_str', 
                   return_value=None):
            # Should not raise any exception
            expand_plugin_tools()


if __name__ == "__main__":
    unittest.main()
