"""
Unit tests for ai_base/agent_types/tool.py module.

Test coverage for get_tool_func function which handles tool name resolution
with compatibility for dot/hyphen connection characters.

Author: mm-m25
"""

import unittest
from topsailai.ai_base.agent_types.tool import get_tool_func


class TestGetToolFunc(unittest.TestCase):
    """Test suite for get_tool_func function."""

    def test_get_tool_func_empty_map(self):
        """Test that empty map returns None."""
        result = get_tool_func({}, "agent.tool")
        self.assertIsNone(result)

    def test_get_tool_func_none_map(self):
        """Test that None map returns None."""
        result = get_tool_func(None, "agent.tool")
        self.assertIsNone(result)

    def test_get_tool_func_empty_name(self):
        """Test that empty string name returns None."""
        result = get_tool_func({"agent.tool": lambda: None}, "")
        self.assertIsNone(result)

    def test_get_tool_func_none_name(self):
        """Test that None name returns None."""
        result = get_tool_func({"agent.tool": lambda: None}, None)
        self.assertIsNone(result)

    def test_get_tool_func_exact_match(self):
        """Test exact match returns the correct function."""
        test_func = lambda: None
        tool_map = {"agent.tool": test_func}
        result = get_tool_func(tool_map, "agent.tool")
        self.assertIs(result, test_func)

    def test_get_tool_func_dot_to_hyphen_match(self):
        """Test that dot in name matches hyphen in map."""
        test_func = lambda: None
        tool_map = {"agent-tool": test_func}
        result = get_tool_func(tool_map, "agent.tool")
        self.assertIs(result, test_func)

    def test_get_tool_func_hyphen_to_dot_match(self):
        """Test that hyphen in name matches dot in map."""
        test_func = lambda: None
        tool_map = {"agent.tool": test_func}
        result = get_tool_func(tool_map, "agent-tool")
        self.assertIs(result, test_func)

    def test_get_tool_func_no_match(self):
        """Test that non-existent tool name returns None."""
        tool_map = {"other.tool": lambda: None}
        result = get_tool_func(tool_map, "agent.tool")
        self.assertIsNone(result)

    def test_get_tool_func_whitespace_name(self):
        """Test that whitespace in name is stripped before matching."""
        test_func = lambda: None
        tool_map = {"agent.tool": test_func}
        result = get_tool_func(tool_map, "  agent.tool  ")
        self.assertIs(result, test_func)

    def test_get_tool_func_multiple_dots(self):
        """Test that multiple dots in name match multiple hyphens in map."""
        test_func = lambda: None
        tool_map = {"module-sub-tool": test_func}
        result = get_tool_func(tool_map, "module.sub.tool")
        self.assertIs(result, test_func)


if __name__ == "__main__":
    unittest.main()
