"""
Unit tests for tools/story_tool.py

Author: DawsonLin
Email: lin_dongsen@126.com
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, mock_open

# Add project root to path
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai.tools import story_tool


class TestBuildStoryId(unittest.TestCase):
    """Test cases for build_story_id function."""

    def test_build_story_id_empty_string(self):
        """Test build_story_id with empty string returns date-based filename."""
        with patch.object(story_tool.time_tool, 'get_current_date', return_value='2025-01-15T10-30-00'):
            result = story_tool.build_story_id("")
            self.assertEqual(result, '2025-01-15T10-30-00.md')

    def test_build_story_id_with_title(self):
        """Test build_story_id with a title string."""
        with patch.object(story_tool.time_tool, 'get_current_date', return_value='2025-01-15T10-30-00'):
            result = story_tool.build_story_id("My Story Title")
            self.assertEqual(result, '2025-01-15T10-30-00.My_Story_Title.md')

    def test_build_story_id_with_special_chars(self):
        """Test build_story_id with special characters."""
        with patch.object(story_tool.time_tool, 'get_current_date', return_value='2025-01-15T10-30-00'):
            result = story_tool.build_story_id("Test!@#$%^&*()")
            self.assertEqual(result, '2025-01-15T10-30-00.Test_____.md')

    def test_build_story_id_with_spaces(self):
        """Test build_story_id with whitespace characters."""
        with patch.object(story_tool.time_tool, 'get_current_date', return_value='2025-01-15T10-30-00'):
            result = story_tool.build_story_id("Hello   World")
            self.assertEqual(result, '2025-01-15T10-30-00.Hello__World.md')

    def test_build_story_id_already_has_md_extension(self):
        """Test build_story_id when title already ends with .md."""
        with patch.object(story_tool.time_tool, 'get_current_date', return_value='2025-01-15T10-30-00'):
            result = story_tool.build_story_id("story.md")
            self.assertEqual(result, '2025-01-15T10-30-00.story_md.md')

    def test_build_story_id_unicode(self):
        """Test build_story_id with unicode characters."""
        with patch.object(story_tool.time_tool, 'get_current_date', return_value='2025-01-15T10-30-00'):
            result = story_tool.build_story_id("故事标题")
            self.assertEqual(result, '2025-01-15T10-30-00.故事标题.md')

    def test_build_story_id_whitespace_only(self):
        """Test build_story_id with only whitespace."""
        with patch.object(story_tool.time_tool, 'get_current_date', return_value='2025-01-15T10-30-00'):
            result = story_tool.build_story_id("   ")
            self.assertEqual(result, '2025-01-15T10-30-00.md')


class TestStoryBase(unittest.TestCase):
    """Test cases for StoryBase abstract class."""

    def test_story_base_name(self):
        """Test StoryBase name attribute."""
        self.assertEqual(story_tool.StoryBase.name, "story_tool")

    def test_assert_workspace_valid(self):
        """Test assert_workspace with valid workspace."""
        instance = story_tool.StoryBase()
        result = instance.assert_workspace("/valid/workspace")
        self.assertIsNone(result)

    def test_assert_workspace_none(self):
        """Test assert_workspace with None workspace."""
        instance = story_tool.StoryBase()
        with self.assertRaises(Exception) as context:
            instance.assert_workspace(None)
        self.assertIn("illegal workspace", str(context.exception))

    def test_assert_workspace_root(self):
        """Test assert_workspace with root path."""
        instance = story_tool.StoryBase()
        with self.assertRaises(Exception) as context:
            instance.assert_workspace("/")
        self.assertIn("illegal workspace", str(context.exception))

    def test_assert_workspace_relative_path(self):
        """Test assert_workspace with relative path."""
        instance = story_tool.StoryBase()
        with self.assertRaises(Exception) as context:
            instance.assert_workspace("relative/path")
        self.assertIn("illegal workspace", str(context.exception))

    def test_write_story_not_implemented(self):
        """Test write_story raises NotImplementedError."""
        instance = story_tool.StoryBase()
        with self.assertRaises(NotImplementedError):
            instance.write_story("/workspace", "story_id", "content")

    def test_read_story_not_implemented(self):
        """Test read_story raises NotImplementedError."""
        instance = story_tool.StoryBase()
        with self.assertRaises(NotImplementedError):
            instance.read_story("/workspace", "story_id")

    def test_delete_story_not_implemented(self):
        """Test delete_story raises NotImplementedError."""
        instance = story_tool.StoryBase()
        with self.assertRaises(NotImplementedError):
            instance.delete_story("/workspace", "story_id")

    def test_list_stories_not_implemented(self):
        """Test list_stories raises NotImplementedError."""
        instance = story_tool.StoryBase()
        with self.assertRaises(NotImplementedError):
            instance.list_stories("/workspace")

    def test_retrieve_stories_not_implemented(self):
        """Test retrieve_stories raises NotImplementedError."""
        instance = story_tool.StoryBase()
        with self.assertRaises(NotImplementedError):
            instance.retrieve_stories("/workspace", "keywords")


class TestStoryFile(unittest.TestCase):
    """Test cases for StoryFile concrete implementation."""

    def setUp(self):
        """Set up test fixtures."""
        self.story_file = story_tool.StoryFile()

    def test_story_file_name(self):
        """Test StoryFile name attribute."""
        self.assertEqual(self.story_file.name, "story_tool")

    @patch('topsailai.tools.story_tool.file_tool.find_files_by_name')
    def test_get_story_file_found(self, mock_find_files):
        """Test get_story_file when file is found."""
        mock_find_files.return_value = ['/workspace/story/test.md']
        result = self.story_file.get_story_file('/workspace', 'test.md')
        self.assertEqual(result, '/workspace/story/test.md')
        mock_find_files.assert_called_once_with('/workspace/story', 'test.md')

    @patch('topsailai.tools.story_tool.file_tool.find_files_by_name')
    def test_get_story_file_not_found(self, mock_find_files):
        """Test get_story_file when file is not found."""
        mock_find_files.return_value = []
        result = self.story_file.get_story_file('/workspace', 'nonexistent.md')
        self.assertIsNone(result)

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch('topsailai.tools.story_tool.os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    @patch.object(story_tool.time_tool, 'get_current_day', return_value='2025-01-15')
    def test_write_story(self, mock_get_day, mock_file, mock_makedirs, mock_lock):
        """Test write_story creates file correctly."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)

        result = self.story_file.write_story('/workspace', 'test_story.md', 'Test content')

        mock_makedirs.assert_called_once()
        mock_file.assert_called()
        self.assertIn('test_story.md', result)

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch.object(story_tool.StoryFile, 'get_story_file')
    def test_read_story_found(self, mock_get_file, mock_lock):
        """Test read_story when story is found."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_file.return_value = '/workspace/story/test.md'

        with patch('builtins.open', mock_open(read_data='Test story content')):
            result = self.story_file.read_story('/workspace', 'test.md')
            self.assertEqual(result, 'Test story content')

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch.object(story_tool.StoryFile, 'get_story_file')
    def test_read_story_not_found(self, mock_get_file, mock_lock):
        """Test read_story when story is not found."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_file.return_value = None

        result = self.story_file.read_story('/workspace', 'nonexistent.md')
        self.assertIsNone(result)

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch('topsailai.tools.story_tool.file_tool.list_files')
    def test_list_stories(self, mock_list_files, mock_lock):
        """Test list_stories returns list of story filenames."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        mock_list_files.return_value = ['/workspace/story1.md', '/workspace/story2.md']

        result = self.story_file.list_stories('/workspace')
        self.assertEqual(result, ['story1.md', 'story2.md'])

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch('topsailai.tools.story_tool.file_tool.list_files')
    def test_list_stories_empty(self, mock_list_files, mock_lock):
        """Test list_stories returns empty list when no stories."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        mock_list_files.return_value = []

        result = self.story_file.list_stories('/workspace')
        self.assertEqual(result, [])

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch('topsailai.tools.story_tool.file_tool.list_files')
    def test_retrieve_stories(self, mock_list_files, mock_lock):
        """Test retrieve_stories returns stories with content."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        mock_list_files.return_value = ['/workspace/story1.md', '/workspace/story2.md']

        # Use mock_open to provide proper file-like objects with read() method
        mock_file = mock_open(read_data='{"content": "Content 1"}')
        mock_file.return_value.read.side_effect = ['{"content": "Content 1"}', '{"content": "Content 2"}']

        with patch('builtins.open', mock_file):
            result = self.story_file.retrieve_stories('/workspace', 'story1|story2')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['title'], 'story1.md')
        self.assertEqual(result[1]['title'], 'story2.md')

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch('topsailai.tools.story_tool.file_tool.list_files')
    def test_retrieve_stories_no_results(self, mock_list_files, mock_lock):
        """Test retrieve_stories returns None when no matches."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        mock_list_files.return_value = []

        result = self.story_file.retrieve_stories('/workspace', 'nonexistent')
        self.assertIsNone(result)

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch.object(story_tool.StoryFile, 'get_story_file')
    @patch('topsailai.tools.story_tool.file_tool.delete_file')
    def test_delete_story(self, mock_delete, mock_get_file, mock_lock):
        """Test delete_story deletes file correctly."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_file.return_value = '/workspace/story/test.md'

        result = self.story_file.delete_story('/workspace', 'test.md')

        mock_delete.assert_called_once_with('/workspace/story/test.md')
        self.assertTrue(result)

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch.object(story_tool.StoryFile, 'get_story_file')
    @patch('topsailai.tools.story_tool.file_tool.delete_file')
    def test_delete_story_not_found(self, mock_delete, mock_get_file, mock_lock):
        """Test delete_story when story doesn't exist."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_file.return_value = None

        result = self.story_file.delete_story('/workspace', 'nonexistent.md')

        mock_delete.assert_not_called()
        self.assertTrue(result)


class TestModuleConstants(unittest.TestCase):
    """Test cases for module-level constants."""

    def test_tools_has_required_keys(self):
        """Test TOOLS dict has required function keys."""
        self.assertIn('write_story', story_tool.TOOLS)
        self.assertIn('read_story', story_tool.TOOLS)
        self.assertEqual(len(story_tool.TOOLS), 2)

    def test_story_file_rwlr_tools_has_required_keys(self):
        """Test STORY_FILE_RWLR_TOOLS dict has required function keys."""
        self.assertIn('write_story', story_tool.STORY_FILE_RWLR_TOOLS)
        self.assertIn('read_story', story_tool.STORY_FILE_RWLR_TOOLS)
        self.assertIn('list_stories', story_tool.STORY_FILE_RWLR_TOOLS)
        self.assertIn('retrieve_stories', story_tool.STORY_FILE_RWLR_TOOLS)
        self.assertEqual(len(story_tool.STORY_FILE_RWLR_TOOLS), 4)

    def test_story_file_all_tools_has_required_keys(self):
        """Test STORY_FILE_ALL_TOOLS dict has all function keys."""
        self.assertIn('write_story', story_tool.STORY_FILE_ALL_TOOLS)
        self.assertIn('read_story', story_tool.STORY_FILE_ALL_TOOLS)
        self.assertIn('list_stories', story_tool.STORY_FILE_ALL_TOOLS)
        self.assertIn('retrieve_stories', story_tool.STORY_FILE_ALL_TOOLS)
        self.assertIn('delete_story', story_tool.STORY_FILE_ALL_TOOLS)
        self.assertEqual(len(story_tool.STORY_FILE_ALL_TOOLS), 5)

    def test_flag_tool_enabled_is_false(self):
        """Test FLAG_TOOL_ENABLED is False."""
        self.assertFalse(story_tool.FLAG_TOOL_ENABLED)

    def test_story_file_instance_exists(self):
        """Test StoryFileInstance is properly initialized."""
        self.assertIsInstance(story_tool.StoryFileInstance, story_tool.StoryFile)
        self.assertEqual(story_tool.StoryFileInstance.name, "story_tool")


class TestKeyStoryConstant(unittest.TestCase):
    """Test cases for KEY_STORY constant."""

    def test_key_story_value(self):
        """Test KEY_STORY constant value."""
        self.assertEqual(story_tool.KEY_STORY, "story")


class TestIntegration(unittest.TestCase):
    """Integration tests for story_tool functionality."""

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch.object(story_tool.StoryFile, 'get_story_file')
    @patch('topsailai.tools.story_tool.file_tool.delete_file')
    @patch('topsailai.tools.story_tool.file_tool.list_files')
    @patch('topsailai.tools.story_tool.os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    @patch.object(story_tool.time_tool, 'get_current_day', return_value='2025-01-15')
    def test_write_read_delete_workflow(
        self, mock_get_day, mock_file, mock_makedirs, 
        mock_list_files, mock_delete, mock_get_file, mock_lock
    ):
        """Test complete workflow: write -> read -> delete."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)

        story_file = story_tool.StoryFile()
        
        # Write story
        file_path = story_file.write_story('/workspace', 'test.md', 'Test content')
        self.assertIn('test.md', file_path)

        # Read story
        mock_get_file.return_value = file_path
        with patch('builtins.open', mock_open(read_data='Test content')):
            content = story_file.read_story('/workspace', 'test.md')
            self.assertEqual(content, 'Test content')

        # Delete story
        result = story_file.delete_story('/workspace', 'test.md')
        self.assertTrue(result)

    @patch('topsailai.tools.story_tool.lock_tool.FileLock')
    @patch('topsailai.tools.story_tool.file_tool.list_files')
    def test_list_and_retrieve_workflow(self, mock_list_files, mock_lock):
        """Test workflow: list stories -> retrieve stories."""
        mock_lock_instance = MagicMock()
        mock_lock.return_value.__enter__ = MagicMock(return_value=mock_lock_instance)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        mock_list_files.return_value = ['/workspace/story1.md', '/workspace/story2.md']

        story_file = story_tool.StoryFile()
        
        # List stories
        stories = story_file.list_stories('/workspace')
        self.assertEqual(len(stories), 2)

        # Retrieve stories - use mock_open with proper read() method
        mock_file = mock_open(read_data='{"content": "Content 1"}')
        mock_file.return_value.read.side_effect = ['{"content": "Content 1"}', '{"content": "Content 2"}']

        with patch('builtins.open', mock_file):
            results = story_file.retrieve_stories('/workspace', 'story1|story2')
            self.assertEqual(len(results), 2)


if __name__ == '__main__':
    unittest.main()
