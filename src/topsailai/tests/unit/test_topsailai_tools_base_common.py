"""
Unit tests for topsailai.tools.base.common module.

Tests tool management functions including add_tool, get_tools_by_module,
get_tool_prompt, expand_plugin_tools, generate_tool_info, get_tools_for_chat,
and format_tools_map.
"""

import unittest
from unittest.mock import patch, MagicMock


class TestAddTool(unittest.TestCase):
    """Tests for add_tool() function."""

    @patch('topsailai.tools.base.common.TOOLS', {})
    @patch('topsailai.tools.base.common.CONN_CHAR', '.')
    def test_add_tool_with_name(self):
        """Test adding a tool with explicit name."""
        from topsailai.tools.base.common import add_tool
        
        def sample_func():
            """Sample function docstring."""
            pass
        
        add_tool("custom_tool", sample_func)
        from topsailai.tools.base.common import TOOLS
        self.assertIn("custom_tool", TOOLS)
        self.assertEqual(TOOLS["custom_tool"], sample_func)

    @patch('topsailai.tools.base.common.TOOLS', {})
    @patch('topsailai.tools.base.common.CONN_CHAR', '.')
    def test_add_tool_without_name(self):
        """Test adding a tool without name uses function name."""
        from topsailai.tools.base.common import add_tool
        
        def my_sample_function():
            """Sample function docstring."""
            pass
        
        add_tool("", my_sample_function)
        from topsailai.tools.base.common import TOOLS
        self.assertIn("aiagent.my_sample_function", TOOLS)
        self.assertEqual(TOOLS["aiagent.my_sample_function"], my_sample_function)

    @patch('topsailai.tools.base.common.TOOLS', {})
    def test_add_tool_invalid_not_callable(self):
        """Test that adding non-callable raises assertion error."""
        from topsailai.tools.base.common import add_tool
        
        with self.assertRaises(AssertionError) as context:
            add_tool("invalid_tool", "not_a_function")
        self.assertIn("invalid function", str(context.exception))

    @patch('topsailai.tools.base.common.TOOLS', {})
    @patch('topsailai.tools.base.common.CONN_CHAR', '.')
    def test_add_tool_updates_tools_dict(self):
        """Test that TOOLS dict is updated correctly."""
        from topsailai.tools.base.common import add_tool
        
        def tool_func():
            pass
        
        initial_count = len([k for k in ['test_tool'] if k in ['test_tool']])
        add_tool("test_tool", tool_func)
        from topsailai.tools.base.common import TOOLS
        self.assertEqual(TOOLS.get("test_tool"), tool_func)


class TestGetToolsByModule(unittest.TestCase):
    """Tests for get_tools_by_module() function."""

    @patch('topsailai.tools.base.common.module_tool')
    def test_get_tools_by_module_success(self, mock_module_tool):
        """Test successfully getting tools from a module."""
        from topsailai.tools.base.common import get_tools_by_module, CONN_CHAR
        
        mock_module = MagicMock()
        mock_module.TOOLS = {"func1": lambda: None, "func2": lambda: None}
        mock_module_tool.get_mod.return_value = mock_module
        
        result = get_tools_by_module("topsailai.tools.example")
        
        self.assertEqual(len(result), 2)
        self.assertIn("example.func1", result)
        self.assertIn("example.func2", result)

    @patch('topsailai.tools.base.common.module_tool')
    def test_get_tools_by_module_with_prefix(self):
        """Test that tool names are prefixed correctly."""
        from topsailai.tools.base.common import get_tools_by_module
        
        mock_module = MagicMock()
        mock_module.TOOLS = {"tool_a": lambda: None}
        mock_module_tool.get_mod.return_value = mock_module
        
        result = get_tools_by_module("topsailai.tools.mytools")
        
        tool_name = list(result.keys())[0]
        self.assertTrue(tool_name.startswith("mytools."))

    @patch('topsailai.tools.base.common.module_tool')
    def test_get_tools_by_module_empty(self):
        """Test handling module with no tools."""
        from topsailai.tools.base.common import get_tools_by_module
        
        mock_module = MagicMock()
        mock_module.TOOLS = {}
        mock_module_tool.get_mod.return_value = mock_module
        
        result = get_tools_by_module("topsailai.tools.empty")
        
        self.assertEqual(result, {})

    @patch('topsailai.tools.base.common.module_tool')
    def test_get_tools_by_module_custom_key(self):
        """Test using custom key parameter."""
        from topsailai.tools.base.common import get_tools_by_module
        
        mock_module = MagicMock()
        mock_module.CUSTOM_KEY = {"custom_func": lambda: None}
        mock_module_tool.get_mod.return_value = mock_module
        
        result = get_tools_by_module("topsailai.tools.custom", key="CUSTOM_KEY")
        
        self.assertIn("custom.custom_func", result)


class TestGetToolPrompt(unittest.TestCase):
    """Tests for get_tool_prompt() function."""

    @patch('topsailai.tools.base.common.TOOLS', {"tool1": MagicMock(__doc__="Tool 1 doc")})
    @patch('topsailai.tools.base.common.format_tool')
    @patch('topsailai.tools.base.common.print_tool')
    @patch('topsailai.tools.base.common.TOOL_PROMPT', "Tools:\n{__TOOLS__}")
    def test_get_tool_prompt_with_tools_name(self, mock_print, mock_format):
        """Test generating prompt from tool names."""
        from topsailai.tools.base.common import get_tool_prompt, TOOLS
        
        mock_format.to_list.return_value = ["tool1"]
        mock_print.format_dict_to_md.return_value = "formatted_tools"
        
        result = get_tool_prompt(tools_name=["tool1"])
        
        self.assertIn("formatted_tools", result)

    @patch('topsailai.tools.base.common.format_tool')
    @patch('topsailai.tools.base.common.print_tool')
    @patch('topsailai.tools.base.common.TOOL_PROMPT', "Tools:\n{__TOOLS__}")
    def test_get_tool_prompt_with_tools_map(self, mock_print, mock_format):
        """Test generating prompt from tools map."""
        from topsailai.tools.base.common import get_tool_prompt, TOOLS
        
        mock_func = MagicMock(__doc__="Map tool doc")
        mock_format.to_list.return_value = []
        
        result = get_tool_prompt(tools_map={"map_tool": mock_func})
        
        self.assertIn("Map tool doc", result)

    @patch('topsailai.tools.base.common.TOOLS', {"tool1": MagicMock(__doc__="Tool 1 doc")})
    @patch('topsailai.tools.base.common.format_tool')
    @patch('topsailai.tools.base.common.print_tool')
    @patch('topsailai.tools.base.common.TOOL_PROMPT', "Tools:\n{__TOOLS__}")
    def test_get_tool_prompt_both_params(self, mock_print, mock_format):
        """Test combining both tools_name and tools_map parameters."""
        from topsailai.tools.base.common import get_tool_prompt, TOOLS
        
        mock_format.to_list.return_value = ["tool1"]
        mock_func = MagicMock(__doc__="Map tool doc")
        
        result = get_tool_prompt(tools_name=["tool1"], tools_map={"map_tool": mock_func})
        
        self.assertIn("formatted_tools", result)

    @patch('topsailai.tools.base.common.TOOLS', {})
    @patch('topsailai.tools.base.common.format_tool')
    def test_get_tool_prompt_empty(self, mock_format):
        """Test returning empty string when no tools provided."""
        from topsailai.tools.base.common import get_tool_prompt, TOOLS
        
        mock_format.to_list.return_value = []
        
        result = get_tool_prompt()
        
        self.assertEqual(result, "")


class TestExpandPluginTools(unittest.TestCase):
    """Tests for expand_plugin_tools() function."""

    @patch('topsailai.tools.base.common.TOOLS', {})
    @patch('topsailai.tools.base.common.TOOLS_INFO', {})
    @patch('topsailai.tools.base.common.module_tool')
    @patch('topsailai.tools.base.common.env_tool.EnvReaderInstance')
    def test_expand_plugin_tools_with_env_var(self, mock_env, mock_module_tool, mock_tools_info, mock_tools):
        """Test loading tools from environment variable."""
        from topsailai.tools.base.common import expand_plugin_tools
        
        mock_env.get_list_str.return_value = ["plugin.path.to.tools"]
        mock_module_tool.get_external_function_map.return_value = {"plugin_tool": lambda: None}
        
        expand_plugin_tools()
        
        mock_module_tool.get_external_function_map.assert_called()

    @patch('topsailai.tools.base.common.TOOLS', {})
    @patch('topsailai.tools.base.common.TOOLS_INFO', {})
    @patch('topsailai.tools.base.common.module_tool')
    @patch('topsailai.tools.base.common.env_tool.EnvReaderInstance')
    def test_expand_plugin_tools_no_env_var(self, mock_env, mock_module_tool, mock_tools_info, mock_tools):
        """Test that nothing happens when no env var is set."""
        from topsailai.tools.base.common import expand_plugin_tools
        
        mock_env.get_list_str.return_value = None
        
        expand_plugin_tools()
        
        mock_module_tool.get_external_function_map.assert_not_called()

    @patch('topsailai.tools.base.common.TOOLS', {})
    @patch('topsailai.tools.base.common.TOOLS_INFO', {})
    @patch('topsailai.tools.base.common.module_tool')
    @patch('topsailai.tools.base.common.env_tool.EnvReaderInstance')
    def test_expand_plugin_tools_updates_tools(self, mock_env, mock_module_tool, mock_tools_info, mock_tools):
        """Test that TOOLS dict is updated with plugin tools."""
        from topsailai.tools.base.common import expand_plugin_tools
        
        mock_env.get_list_str.return_value = ["plugin.path"]
        mock_module_tool.get_external_function_map.side_effect = [
            {"new_tool": lambda: None},  # TOOLS
            {}  # TOOLS_INFO
        ]
        
        expand_plugin_tools()
        
        self.assertIn("new_tool", mock_tools)

    @patch('topsailai.tools.base.common.TOOLS', {})
    @patch('topsailai.tools.base.common.TOOLS_INFO', {})
    @patch('topsailai.tools.base.common.module_tool')
    @patch('topsailai.tools.base.common.env_tool.EnvReaderInstance')
    def test_expand_plugin_tools_updates_tools_info(self, mock_env, mock_module_tool, mock_tools_info, mock_tools):
        """Test that TOOLS_INFO dict is updated with plugin tools info."""
        from topsailai.tools.base.common import expand_plugin_tools
        
        mock_env.get_list_str.return_value = ["plugin.path"]
        mock_module_tool.get_external_function_map.side_effect = [
            {},  # TOOLS
            {"new_tool_info": {"name": "test"}}  # TOOLS_INFO
        ]
        
        expand_plugin_tools()
        
        self.assertIn("new_tool_info", mock_tools_info)


class TestGenerateToolInfo(unittest.TestCase):
    """Tests for generate_tool_info() function."""

    def test_generate_tool_info_structure(self):
        """Test correct JSON structure is generated."""
        from topsailai.tools.base.common import generate_tool_info
        
        result = generate_tool_info("test_tool", "Test description")
        
        self.assertEqual(result["type"], "function")
        self.assertIn("function", result)
        self.assertIn("name", result["function"])
        self.assertIn("description", result["function"])
        self.assertIn("parameters", result["function"])

    def test_generate_tool_info_values(self):
        """Test correct name and description values."""
        from topsailai.tools.base.common import generate_tool_info
        
        result = generate_tool_info("my_tool", "My tool description")
        
        self.assertEqual(result["function"]["name"], "my_tool")
        self.assertEqual(result["function"]["description"], "My tool description")

    def test_generate_tool_info_parameters(self):
        """Test parameters object is present with correct structure."""
        from topsailai.tools.base.common import generate_tool_info
        
        result = generate_tool_info("param_tool", "Tool with params")
        
        self.assertEqual(result["function"]["parameters"]["type"], "object")


class TestGetToolsForChat(unittest.TestCase):
    """Tests for get_tools_for_chat() function."""

    @patch('topsailai.tools.base.common.TOOLS_INFO', {"info_tool": {"function": {"name": "info_tool"}}})
    @patch('topsailai.tools.base.common.TOOLS', {})
    def test_get_tools_for_chat_with_tools_info(self):
        """Test using TOOLS_INFO when available."""
        from topsailai.tools.base.common import get_tools_for_chat
        
        result = get_tools_for_chat({"info_tool": MagicMock()})
        
        self.assertIn("info_tool", result)
        self.assertEqual(result["info_tool"]["function"]["name"], "info_tool")

    @patch('topsailai.tools.base.common.TOOLS_INFO', {})
    @patch('topsailai.tools.base.common.TOOLS', {"fallback_tool": MagicMock(__doc__="Fallback doc")})
    def test_get_tools_for_chat_fallback_to_tools(self):
        """Test fallback to TOOLS docstring when TOOLS_INFO not available."""
        from topsailai.tools.base.common import get_tools_for_chat
        
        result = get_tools_for_chat({"fallback_tool": MagicMock()})
        
        self.assertIn("fallback_tool", result)
        self.assertEqual(result["fallback_tool"]["function"]["description"], "Fallback doc")

    @patch('topsailai.tools.base.common.TOOLS_INFO', {"info_tool": {"function": {"name": "original"}}})
    @patch('topsailai.tools.base.common.TOOLS', {})
    def test_get_tools_for_chat_name_override(self):
        """Test that function name is overridden in result."""
        from topsailai.tools.base.common import get_tools_for_chat
        
        result = get_tools_for_chat({"info_tool": MagicMock()})
        
        self.assertEqual(result["info_tool"]["function"]["name"], "info_tool")

    @patch('topsailai.tools.base.common.TOOLS_INFO', {})
    @patch('topsailai.tools.base.common.TOOLS', {})
    def test_get_tools_for_chat_empty(self):
        """Test handling empty tools map."""
        from topsailai.tools.base.common import get_tools_for_chat
        
        result = get_tools_for_chat({})
        
        self.assertEqual(result, {})


class TestFormatToolsMap(unittest.TestCase):
    """Tests for format_tools_map() function."""

    def test_format_tools_map_adds_prefix(self):
        """Test adding prefix to tool names."""
        from topsailai.tools.base.common import format_tools_map
        
        result = format_tools_map({"tool1": MagicMock()}, "prefix")
        
        self.assertIn("prefix.tool1", result)

    def test_format_tools_map_existing_prefix(self):
        """Test that prefix is not duplicated if already exists."""
        from topsailai.tools.base.common import format_tools_map
        
        result = format_tools_map({"prefix.tool1": MagicMock()}, "prefix")
        
        self.assertIn("prefix.tool1", result)
        self.assertEqual(len(result), 1)

    def test_format_tools_map_adds_dot(self):
        """Test that dot is added to prefix if missing."""
        from topsailai.tools.base.common import format_tools_map
        
        result = format_tools_map({"tool1": MagicMock()}, "prefix")
        
        # Should add dot if prefix doesn't end with one
        self.assertTrue(result.get("prefix.tool1") or "prefix.tool1" in result)


if __name__ == '__main__':
    unittest.main()
