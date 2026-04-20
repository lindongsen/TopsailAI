"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-19
  Purpose: Unit tests for workspace/context/summary_tool.py
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from topsailai.workspace.context import summary_tool


class TestGetSummaryPromptExtraMap(unittest.TestCase):
    """Test suite for get_summary_prompt_extra_map() function."""

    def setUp(self):
        """Set up test fixtures."""
        # Clear global cache before each test
        summary_tool.g_summary_prompt_map.clear()

    def tearDown(self):
        """Tear down test fixtures."""
        # Clear global cache after each test
        summary_tool.g_summary_prompt_map.clear()

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    def test_returns_none_when_env_var_not_set(self, mock_env_reader):
        """
        Test that function returns None when environment variable is not set.
        
        Verifies:
        - EnvReaderInstance.get() returns None or empty string
        - Function returns None
        """
        mock_env_reader.get.return_value = None
        
        result = summary_tool.get_summary_prompt_extra_map()
        
        self.assertIsNone(result)
        mock_env_reader.get.assert_called_once_with("TOPSAILAI_SUMMARY_PROMPT_EXTRA_MAP")

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    def test_returns_none_when_env_var_empty(self, mock_env_reader):
        """
        Test that function returns None when environment variable is empty.
        
        Verifies:
        - EnvReaderInstance.get() returns empty string
        - Function returns None
        """
        mock_env_reader.get.return_value = ""
        
        result = summary_tool.get_summary_prompt_extra_map()
        
        self.assertIsNone(result)

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    @patch('topsailai.workspace.context.summary_tool.format_tool')
    def test_parses_simple_key_value(self, mock_format_tool, mock_env_reader):
        """
        Test parsing of simple key=value format.
        
        Verifies:
        - Env var is parsed correctly
        - Single value is converted to list
        - Result is cached in global map
        """
        mock_env_reader.get.return_value = "agent1=prompt1.txt"
        mock_format_tool.parse_str_to_dict.return_value = {"agent1": "prompt1.txt"}
        
        result = summary_tool.get_summary_prompt_extra_map()
        
        self.assertIsNotNone(result)
        self.assertIn("agent1", result)
        self.assertEqual(result["agent1"], ["prompt1.txt"])
        self.assertEqual(summary_tool.g_summary_prompt_map.get("agent1"), ["prompt1.txt"])

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    @patch('topsailai.workspace.context.summary_tool.format_tool')
    def test_parses_multiple_values_comma_separated(self, mock_format_tool, mock_env_reader):
        """
        Test parsing of multiple values (comma-separated) for single key.
        
        Verifies:
        - Multiple values are correctly split by comma
        - Each value becomes an item in the list
        """
        mock_env_reader.get.return_value = "agent1=prompt1.txt,prompt2.txt"
        mock_format_tool.parse_str_to_dict.return_value = {"agent1": "prompt1.txt,prompt2.txt"}
        
        result = summary_tool.get_summary_prompt_extra_map()
        
        self.assertIsNotNone(result)
        self.assertIn("agent1", result)
        self.assertEqual(len(result["agent1"]), 2)
        self.assertIn("prompt1.txt", result["agent1"])
        self.assertIn("prompt2.txt", result["agent1"])

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    @patch('topsailai.workspace.context.summary_tool.format_tool')
    def test_parses_multiple_key_value_pairs(self, mock_format_tool, mock_env_reader):
        """
        Test parsing of multiple key-value pairs (semicolon-separated).
        
        Verifies:
        - Multiple agents are parsed correctly
        - Each agent has its own list of values
        """
        mock_env_reader.get.return_value = "agent1=prompt1.txt;agent2=prompt2.txt,prompt3.txt"
        mock_format_tool.parse_str_to_dict.return_value = {
            "agent1": "prompt1.txt",
            "agent2": "prompt2.txt,prompt3.txt"
        }
        
        result = summary_tool.get_summary_prompt_extra_map()
        
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        self.assertEqual(result["agent1"], ["prompt1.txt"])
        self.assertEqual(result["agent2"], ["prompt2.txt", "prompt3.txt"])

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    @patch('topsailai.workspace.context.summary_tool.format_tool')
    def test_handles_whitespace_with_kv_strip(self, mock_format_tool, mock_env_reader):
        """
        Test that whitespace is handled with kv_strip=True.
        
        Verifies:
        - format_tool.parse_str_to_dict is called with kv_strip=True
        - Whitespace is stripped from keys and values
        """
        mock_env_reader.get.return_value = " agent1 = prompt1.txt "
        mock_format_tool.parse_str_to_dict.return_value = {"agent1": "prompt1.txt"}
        
        result = summary_tool.get_summary_prompt_extra_map()
        
        self.assertIsNotNone(result)
        mock_format_tool.parse_str_to_dict.assert_called_once_with(
            " agent1 = prompt1.txt ", 
            kv_strip=True
        )


class TestGetSummaryPromptExtraMapCache(unittest.TestCase):
    """Test suite for caching behavior of get_summary_prompt_extra_map()."""

    def setUp(self):
        """Set up test fixtures."""
        summary_tool.g_summary_prompt_map.clear()

    def tearDown(self):
        """Tear down test fixtures."""
        summary_tool.g_summary_prompt_map.clear()

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    @patch('topsailai.workspace.context.summary_tool.format_tool')
    def test_returns_cached_result_on_second_call(self, mock_format_tool, mock_env_reader):
        """
        Test that function returns cached result on second call.
        
        Verifies:
        - First call parses env var and caches result
        - Second call returns cached data without re-parsing
        - EnvReaderInstance.get() is only called once
        """
        mock_env_reader.get.return_value = "agent1=prompt1.txt"
        mock_format_tool.parse_str_to_dict.return_value = {"agent1": "prompt1.txt"}
        
        # First call
        result1 = summary_tool.get_summary_prompt_extra_map()
        
        # Second call
        result2 = summary_tool.get_summary_prompt_extra_map()
        
        self.assertEqual(result1, result2)
        self.assertEqual(result1["agent1"], ["prompt1.txt"])
        # Verify get was only called once (cache hit on second call)
        self.assertEqual(mock_env_reader.get.call_count, 1)

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    @patch('topsailai.workspace.context.summary_tool.format_tool')
    def test_cache_is_populated_after_first_call(self, mock_format_tool, mock_env_reader):
        """
        Test that cache is populated after first call.
        
        Verifies:
        - Global map is empty before first call
        - Global map is populated after first call
        """
        mock_env_reader.get.return_value = "agent1=prompt1.txt"
        mock_format_tool.parse_str_to_dict.return_value = {"agent1": "prompt1.txt"}
        
        # Before first call
        self.assertEqual(len(summary_tool.g_summary_prompt_map), 0)
        
        # First call
        summary_tool.get_summary_prompt_extra_map()
        
        # After first call
        self.assertEqual(len(summary_tool.g_summary_prompt_map), 1)
        self.assertIn("agent1", summary_tool.g_summary_prompt_map)


class TestGetSummaryPrompt(unittest.TestCase):
    """Test suite for get_summary_prompt() function."""

    def setUp(self):
        """Set up test fixtures."""
        summary_tool.g_summary_prompt_map.clear()

    def tearDown(self):
        """Tear down test fixtures."""
        summary_tool.g_summary_prompt_map.clear()

    @patch('topsailai.workspace.context.summary_tool.get_summary_prompt_extra_map')
    def test_returns_empty_string_when_no_summary_prompt_map(self, mock_get_map):
        """
        Test that function returns empty string when summary_prompt_map is None.
        
        Verifies:
        - get_summary_prompt_extra_map() returns None
        - Function returns empty string
        """
        mock_get_map.return_value = None
        
        result = summary_tool.get_summary_prompt("agent1")
        
        self.assertEqual(result, "")
        mock_get_map.assert_called_once()

    @patch('topsailai.workspace.context.summary_tool.get_summary_prompt_extra_map')
    def test_returns_empty_string_when_agent_type_not_in_map(self, mock_get_map):
        """
        Test that function returns empty string when agent_type not in map.
        
        Verifies:
        - get_summary_prompt_extra_map() returns valid dict
        - agent_type is not in the dict
        - Function returns empty string
        """
        mock_get_map.return_value = {"agent1": ["prompt1.txt"]}
        
        result = summary_tool.get_summary_prompt("agent2")
        
        self.assertEqual(result, "")

    @patch('topsailai.workspace.context.summary_tool.get_summary_prompt_extra_map')
    @patch('topsailai.workspace.context.summary_tool.prompt_tool')
    def test_returns_prompt_content_for_single_file(self, mock_prompt_tool, mock_get_map):
        """
        Test that function returns prompt content for single file.
        
        Verifies:
        - agent_type exists in map with single file
        - prompt_tool.read_prompt() is called once
        - Returned content matches read_prompt output
        """
        mock_get_map.return_value = {"agent1": ["prompt1.txt"]}
        mock_prompt_tool.read_prompt.return_value = "This is prompt content"
        
        result = summary_tool.get_summary_prompt("agent1")
        
        self.assertEqual(result, "This is prompt content")
        mock_prompt_tool.read_prompt.assert_called_once_with("prompt1.txt")

    @patch('topsailai.workspace.context.summary_tool.get_summary_prompt_extra_map')
    @patch('topsailai.workspace.context.summary_tool.prompt_tool')
    def test_returns_concatenated_prompt_content_for_multiple_files(self, mock_prompt_tool, mock_get_map):
        """
        Test that function returns concatenated prompt content for multiple files.
        
        Verifies:
        - agent_type exists in map with multiple files
        - prompt_tool.read_prompt() is called for each file
        - Returned content is concatenation of all prompts
        """
        mock_get_map.return_value = {"agent1": ["prompt1.txt", "prompt2.txt"]}
        mock_prompt_tool.read_prompt.side_effect = ["Content 1", "Content 2"]
        
        result = summary_tool.get_summary_prompt("agent1")
        
        self.assertEqual(result, "Content 1Content 2")
        self.assertEqual(mock_prompt_tool.read_prompt.call_count, 2)
        mock_prompt_tool.read_prompt.assert_any_call("prompt1.txt")
        mock_prompt_tool.read_prompt.assert_any_call("prompt2.txt")

    @patch('topsailai.workspace.context.summary_tool.get_summary_prompt_extra_map')
    @patch('topsailai.workspace.context.summary_tool.prompt_tool')
    def test_calls_read_prompt_for_each_file(self, mock_prompt_tool, mock_get_map):
        """
        Test that prompt_tool.read_prompt() is called for each file in the list.
        
        Verifies:
        - Three files result in three read_prompt calls
        - Each file is read exactly once
        """
        mock_get_map.return_value = {"agent1": ["file1.txt", "file2.txt", "file3.txt"]}
        mock_prompt_tool.read_prompt.side_effect = ["A", "B", "C"]
        
        result = summary_tool.get_summary_prompt("agent1")
        
        self.assertEqual(mock_prompt_tool.read_prompt.call_count, 3)
        self.assertEqual(result, "ABC")


class TestGlobalCacheBehavior(unittest.TestCase):
    """Test suite for global cache behavior."""

    def setUp(self):
        """Set up test fixtures."""
        summary_tool.g_summary_prompt_map.clear()

    def tearDown(self):
        """Tear down test fixtures."""
        summary_tool.g_summary_prompt_map.clear()

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    @patch('topsailai.workspace.context.summary_tool.format_tool')
    def test_cache_persists_across_function_calls(self, mock_format_tool, mock_env_reader):
        """
        Test that cache persists across multiple function calls.
        
        Verifies:
        - After first call, cache contains parsed data
        - Subsequent calls access cached data
        """
        mock_env_reader.get.return_value = "agent1=file1.txt"
        mock_format_tool.parse_str_to_dict.return_value = {"agent1": "file1.txt"}
        
        # First call
        summary_tool.get_summary_prompt_extra_map()
        
        # Verify cache is populated
        self.assertEqual(len(summary_tool.g_summary_prompt_map), 1)
        
        # Second call
        summary_tool.get_summary_prompt_extra_map()
        
        # Verify cache still populated (not re-parsed)
        self.assertEqual(len(summary_tool.g_summary_prompt_map), 1)
        self.assertEqual(mock_env_reader.get.call_count, 1)

    @patch('topsailai.workspace.context.summary_tool.env_tool.EnvReaderInstance')
    @patch('topsailai.workspace.context.summary_tool.format_tool')
    def test_cache_isolation_between_tests(self, mock_format_tool, mock_env_reader):
        """
        Test that cache can be cleared for test isolation.
        
        Verifies:
        - After clearing cache, function re-parses env var
        - New data is cached
        """
        # Use side_effect to return fresh dict each time (avoid mutation issues)
        def fresh_dict(*args, **kwargs):
            return {"agent1": "file1.txt"}
        
        mock_env_reader.get.return_value = "agent1=file1.txt"
        mock_format_tool.parse_str_to_dict.side_effect = fresh_dict
        
        # First call
        summary_tool.get_summary_prompt_extra_map()
        self.assertEqual(len(summary_tool.g_summary_prompt_map), 1)
        
        # Clear cache
        summary_tool.g_summary_prompt_map.clear()
        
        # Second call after clear
        summary_tool.get_summary_prompt_extra_map()
        
        # Verify cache was re-populated
        self.assertEqual(len(summary_tool.g_summary_prompt_map), 1)
        self.assertEqual(mock_env_reader.get.call_count, 2)


if __name__ == '__main__':
    unittest.main()
