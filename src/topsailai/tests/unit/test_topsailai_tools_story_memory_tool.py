"""
Unit tests for tools/story_memory_tool.py

Author: mm-m25
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, mock_open

# Add project root to path
sys.path.insert(0, '/root/ai/TopsailAI/src/topsailai')


class TestModuleConstants(unittest.TestCase):
    """Test module constants are properly defined."""
    
    def test_tools_dict_contains_required_functions(self):
        """Test TOOLS dict contains all required memory functions."""
        from topsailai.tools import story_memory_tool
        self.assertIn('write_memory', story_memory_tool.TOOLS)
        self.assertIn('read_memory', story_memory_tool.TOOLS)
        self.assertIn('list_memories', story_memory_tool.TOOLS)
        self.assertIn('delete_memory', story_memory_tool.TOOLS)
    
    def test_flag_tool_enabled_is_boolean(self):
        """Test FLAG_TOOL_ENABLED is a boolean value."""
        from topsailai.tools import story_memory_tool
        self.assertIsInstance(story_memory_tool.FLAG_TOOL_ENABLED, bool)
    
    def test_prompt_is_string(self):
        """Test PROMPT is a non-empty string."""
        from topsailai.tools import story_memory_tool
        self.assertIsInstance(story_memory_tool.PROMPT, str)
        self.assertIn('story_memory_tool', story_memory_tool.PROMPT)


class TestWriteMemory(unittest.TestCase):
    """Test write_memory function."""
    
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    def test_write_memory_basic(self, mock_build_id, mock_story_instance):
        """Test basic write_memory call."""
        from topsailai.tools import story_memory_tool
        
        mock_build_id.return_value = "2026-04-19.story_title.md"
        mock_story_instance.write_story.return_value = "/path/to/memory.md"
        
        result = story_memory_tool.write_memory("story_title", "test content")
        
        mock_build_id.assert_called_once_with("story_title")
        mock_story_instance.write_story.assert_called_once()
        call_kwargs = mock_story_instance.write_story.call_args[1]
        self.assertEqual(call_kwargs['story_content'], "test content")
        self.assertEqual(result, "/path/to/memory.md")
    
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    def test_write_memory_unicode_content(self, mock_build_id, mock_story_instance):
        """Test write_memory with unicode content."""
        from topsailai.tools import story_memory_tool
        
        mock_build_id.return_value = "2026-04-19.unicode_test.md"
        mock_story_instance.write_story.return_value = "/path/to/memory.md"
        
        unicode_content = "测试内容 🎉 émojis & special <chars>"
        result = story_memory_tool.write_memory("unicode_test", unicode_content)
        
        call_kwargs = mock_story_instance.write_story.call_args[1]
        self.assertEqual(call_kwargs['story_content'], unicode_content)
    
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    def test_write_memory_empty_content(self, mock_build_id, mock_story_instance):
        """Test write_memory with empty content."""
        from topsailai.tools import story_memory_tool
        
        mock_build_id.return_value = "2026-04-19.empty.md"
        mock_story_instance.write_story.return_value = "/path/to/memory.md"
        
        result = story_memory_tool.write_memory("empty", "")
        
        call_kwargs = mock_story_instance.write_story.call_args[1]
        self.assertEqual(call_kwargs['story_content'], "")


class TestReadMemory(unittest.TestCase):
    """Test read_memory function."""
    
    @patch('topsailai.tools.story_memory_tool.os.path.exists')
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_read_memory_with_extension(self, mock_story_instance, mock_exists):
        """Test read_memory when file has .md extension."""
        from topsailai.tools import story_memory_tool
        
        mock_exists.return_value = True
        mock_story_instance.read_story.return_value = "memory content"
        
        result = story_memory_tool.read_memory("test_memory.md")
        
        mock_story_instance.read_story.assert_called_once()
        call_kwargs = mock_story_instance.read_story.call_args[1]
        self.assertEqual(call_kwargs['story_id'], "test_memory.md")
        self.assertEqual(result, "memory content")
    
    @patch('topsailai.tools.story_memory_tool.os.path.exists')
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_read_memory_without_extension(self, mock_story_instance, mock_exists):
        """Test read_memory when file doesn't have .md extension."""
        from topsailai.tools import story_memory_tool
        
        # First call (without extension) returns False, second call (with extension) returns True
        mock_exists.side_effect = [False, True]
        mock_story_instance.read_story.return_value = "memory content"
        
        result = story_memory_tool.read_memory("test_memory")
        
        mock_story_instance.read_story.assert_called_once()
        call_kwargs = mock_story_instance.read_story.call_args[1]
        self.assertEqual(call_kwargs['story_id'], "test_memory.md")
        self.assertEqual(result, "memory content")
    
    @patch('topsailai.tools.story_memory_tool.os.path.exists')
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_read_memory_not_found(self, mock_story_instance, mock_exists):
        """Test read_memory when memory doesn't exist."""
        from topsailai.tools import story_memory_tool
        
        mock_exists.return_value = False
        mock_story_instance.read_story.return_value = None
        
        result = story_memory_tool.read_memory("nonexistent")
        
        self.assertIsNone(result)
    
    @patch('topsailai.tools.story_memory_tool.os.path.exists')
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_read_memory_unicode_title(self, mock_story_instance, mock_exists):
        """Test read_memory with unicode title."""
        from topsailai.tools import story_memory_tool
        
        mock_exists.return_value = True
        mock_story_instance.read_story.return_value = "unicode content"
        
        result = story_memory_tool.read_memory("测试_标题.md")
        
        self.assertEqual(result, "unicode content")


class TestListMemories(unittest.TestCase):
    """Test list_memories function."""
    
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_list_memories_returns_list(self, mock_story_instance):
        """Test list_memories returns a list of titles."""
        from topsailai.tools import story_memory_tool
        
        mock_story_instance.list_stories.return_value = ["memory1.md", "memory2.md"]
        
        result = story_memory_tool.list_memories()
        
        mock_story_instance.list_stories.assert_called_once()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
    
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_list_memories_empty(self, mock_story_instance):
        """Test list_memories when no memories exist."""
        from topsailai.tools import story_memory_tool
        
        mock_story_instance.list_stories.return_value = None
        
        result = story_memory_tool.list_memories()
        
        self.assertIsNone(result)


class TestDeleteMemory(unittest.TestCase):
    """Test delete_memory function."""
    
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_delete_memory_success(self, mock_story_instance):
        """Test delete_memory returns True on success."""
        from topsailai.tools import story_memory_tool
        
        mock_story_instance.delete_story.return_value = True
        
        result = story_memory_tool.delete_memory("test_memory")
        
        mock_story_instance.delete_story.assert_called_once()
        call_kwargs = mock_story_instance.delete_story.call_args[1]
        self.assertEqual(call_kwargs['story_id'], "test_memory")
        self.assertTrue(result)
    
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_delete_memory_unicode_title(self, mock_story_instance):
        """Test delete_memory with unicode title."""
        from topsailai.tools import story_memory_tool
        
        mock_story_instance.delete_story.return_value = True
        
        result = story_memory_tool.delete_memory("测试_标题")
        
        self.assertTrue(result)


class TestBuildStoryId(unittest.TestCase):
    """Test build_story_id function from story_tool."""
    
    def test_build_story_id_empty_string(self):
        """Test build_story_id with empty string."""
        from topsailai.tools.story_tool import build_story_id
        
        result = build_story_id("")
        
        self.assertTrue(result.endswith(".md"))
        self.assertIn(".", result)
    
    def test_build_story_id_with_special_chars(self):
        """Test build_story_id with special characters."""
        from topsailai.tools.story_tool import build_story_id
        
        result = build_story_id("test!@#$%title")
        
        # Special chars should be replaced with underscores
        self.assertNotIn("!", result)
        self.assertNotIn("@", result)
        self.assertTrue(result.endswith(".md"))
    
    def test_build_story_id_with_spaces(self):
        """Test build_story_id with spaces."""
        from topsailai.tools.story_tool import build_story_id
        
        result = build_story_id("test title with spaces")
        
        # Spaces should be replaced with underscores
        self.assertNotIn(" ", result)
        self.assertTrue(result.endswith(".md"))
    
    def test_build_story_id_already_has_extension(self):
        """Test build_story_id when title already has .md extension."""
        from topsailai.tools.story_tool import build_story_id
        
        result = build_story_id("test_title.md")
        
        # Should not double the extension
        self.assertTrue(result.endswith(".md"))
        self.assertEqual(result.count(".md"), 1)
    
    def test_build_story_id_unicode(self):
        """Test build_story_id with unicode characters."""
        from topsailai.tools.story_tool import build_story_id
        
        result = build_story_id("测试标题")
        
        self.assertTrue(result.endswith(".md"))
        # Unicode chars should be preserved or converted appropriately


class TestWorkspaceConfiguration(unittest.TestCase):
    """Test workspace configuration."""
    
    @patch.dict(os.environ, {'TOPSAILAI_STORY_WORKSPACE': '/test/workspace'})
    def test_workspace_from_env_story(self):
        """Test workspace is read from TOPSAILAI_STORY_WORKSPACE env var."""
        # Need to reimport to pick up the env var
        import importlib
        from topsailai.tools import story_memory_tool
        importlib.reload(story_memory_tool)
        
        self.assertEqual(story_memory_tool.WORKSPACE, '/test/workspace')
    
    @patch.dict(os.environ, {'TOPSAILAI_MEMORY_WORKSPACE': '/memory/workspace'}, clear=True)
    def test_workspace_from_env_memory(self):
        """Test workspace is read from TOPSAILAI_MEMORY_WORKSPACE env var."""
        import importlib
        from topsailai.tools import story_memory_tool
        importlib.reload(story_memory_tool)
        
        self.assertEqual(story_memory_tool.WORKSPACE, '/memory/workspace')


class TestIntegration(unittest.TestCase):
    """Integration tests for memory operations."""
    
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    @patch('topsailai.tools.story_memory_tool.os.path.exists')
    def test_write_then_read_workflow(self, mock_exists, mock_build_id, mock_story_instance):
        """Test complete write then read workflow."""
        from topsailai.tools import story_memory_tool
        
        # Setup mocks
        mock_build_id.return_value = "2026-04-19.integration_test.md"
        mock_story_instance.write_story.return_value = "/path/to/memory.md"
        mock_exists.return_value = True
        mock_story_instance.read_story.return_value = "test content"
        
        # Write memory
        write_result = story_memory_tool.write_memory("integration_test", "test content")
        self.assertEqual(write_result, "/path/to/memory.md")
        
        # Read memory
        read_result = story_memory_tool.read_memory("integration_test")
        self.assertEqual(read_result, "test content")
    
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    @patch('topsailai.tools.story_memory_tool.os.path.exists')
    def test_write_list_delete_workflow(self, mock_exists, mock_build_id, mock_story_instance):
        """Test write, list, delete workflow."""
        from topsailai.tools import story_memory_tool
        
        # Setup mocks
        mock_build_id.return_value = "2026-04-19.workflow_test.md"
        mock_story_instance.write_story.return_value = "/path/to/memory.md"
        mock_story_instance.list_stories.return_value = ["workflow_test.md"]
        mock_story_instance.delete_story.return_value = True
        
        # Write memory
        story_memory_tool.write_memory("workflow_test", "test content")
        
        # List memories
        list_result = story_memory_tool.list_memories()
        self.assertIn("workflow_test.md", list_result)
        
        # Delete memory
        delete_result = story_memory_tool.delete_memory("workflow_test")
        self.assertTrue(delete_result)


if __name__ == '__main__':
    unittest.main()
