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
        """Test basic write_memory call enables the compact timestamp prefix."""
        from topsailai.tools import story_memory_tool

        mock_build_id.return_value = "20260821135200.story_title.md"
        mock_story_instance.write_story.return_value = "/path/to/memory.md"

        result = story_memory_tool.write_memory("story_title", "test content")

        mock_build_id.assert_called_once_with("story_title", compact_prefix=True)
        mock_story_instance.write_story.assert_called_once()
        call_kwargs = mock_story_instance.write_story.call_args[1]
        self.assertEqual(call_kwargs['story_id'], "20260821135200.story_title.md")
        self.assertEqual(call_kwargs['story_content'], "test content")
        self.assertIn("/path/to/memory.md", result)

    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    def test_write_memory_unicode_content(self, mock_build_id, mock_story_instance):
        """Test write_memory with unicode content."""
        from topsailai.tools import story_memory_tool
        
        mock_build_id.return_value = "2026-04-19.unicode_test.md"
        mock_story_instance.write_story.return_value = "/path/to/memory.md"
        
        unicode_content = "æµ‹è¯•å†…å®¹ ðŸŽ‰ Ã©mojis & special <chars>"
        result = story_memory_tool.write_memory("unicode_test", unicode_content)
        
        call_kwargs = mock_story_instance.write_story.call_args[1]
        self.assertEqual(call_kwargs['story_content'], unicode_content)
        self.assertIn("/path/to/memory.md", result)
    
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
        self.assertIn("/path/to/memory.md", result)


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
        
        result = story_memory_tool.read_memory("æµ‹è¯•_æ ‡é¢˜.md")
        
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
        
        result = story_memory_tool.delete_memory("æµ‹è¯•_æ ‡é¢˜")
        
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
        
        result = build_story_id("æµ‹è¯•æ ‡é¢˜")
        
        self.assertTrue(result.endswith(".md"))
        # Unicode chars should be preserved or converted appropriately

    @patch(
        'topsailai.tools.story_tool.time_tool.get_current_compact_datetime',
        return_value='20260821135200',
    )
    def test_build_story_id_with_compact_prefix(self, _mock_current_datetime):
        """Test compact timestamp prefixes use YYYYMMDDHHMMSS."""
        from topsailai.tools.story_tool import build_story_id

        result = build_story_id("memory title", compact_prefix=True)

        self.assertEqual(result, "20260821135200.memory_title.md")


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
        self.assertIn("/path/to/memory.md", write_result)
        
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


class TestGetAllMemoriesOrdering(unittest.TestCase):
    """Tests verifying deterministic ordering in memory retrieval."""

    @patch('topsailai.tools.story_memory_tool.list_memories')
    @patch('topsailai.tools.story_memory_tool.read_memory_without_count')
    def test_get_all_memories_sorts_by_title(self, mock_read_memory, mock_list_memories):
        """Verify get_all_memories returns memories sorted by title."""
        from topsailai.tools import story_memory_tool

        mock_list_memories.return_value = ["z_memory.md", "a_memory.md", "m_memory.md"]
        mock_read_memory.side_effect = lambda title: f"content of {title}"

        result = story_memory_tool.get_all_memories()

        self.assertEqual(list(result.keys()), ["a_memory.md", "m_memory.md", "z_memory.md"])

    @patch('topsailai.tools.story_memory_tool.list_memories')
    @patch('topsailai.tools.story_memory_tool.read_memory_without_count')
    def test_get_all_memories_markdown_sorts_by_title(self, mock_read_memory, mock_list_memories):
        """Verify get_all_memories_markdown emits titles in sorted order."""
        from topsailai.tools import story_memory_tool

        mock_list_memories.return_value = ["z_memory.md", "a_memory.md", "m_memory.md"]
        mock_read_memory.side_effect = lambda title: f"content of {title}"

        result = story_memory_tool.get_all_memories_markdown()

        # Extract headings in order of appearance
        import re
        headings = re.findall(r"## ([^\n]+)", result)
        self.assertEqual(headings, ["a_memory.md", "m_memory.md", "z_memory.md"])


class TestMemoryStatLifecycle(unittest.TestCase):
    """Test memory API integration with stat callbacks."""

    @patch('topsailai.tools.story_memory_tool.memory_stat.record_memory_event')
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_counting_read_records_resolved_canonical_memory(
        self, mock_story_instance, mock_record_event
    ):
        from topsailai.tools import story_memory_tool

        def read_story(**kwargs):
            kwargs['after_read']('/workspace/story/2026-08-23/canonical.md')
            return 'content'

        mock_story_instance.read_story.side_effect = read_story

        result = story_memory_tool.read_memory('query')

        self.assertEqual(result, 'content')
        mock_record_event.assert_called_once_with(
            story_memory_tool.WORKSPACE, 'canonical.md', 'read'
        )

    @patch('topsailai.tools.story_memory_tool.memory_stat.record_memory_event')
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_not_found_read_does_not_record_event(
        self, mock_story_instance, mock_record_event
    ):
        from topsailai.tools import story_memory_tool

        mock_story_instance.read_story.return_value = None

        self.assertIsNone(story_memory_tool.read_memory('missing'))
        mock_record_event.assert_not_called()

    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_non_counting_read_passes_no_callback(self, mock_story_instance):
        from topsailai.tools import story_memory_tool

        mock_story_instance.read_story.return_value = 'content'

        result = story_memory_tool.read_memory_without_count('memory.md')

        self.assertEqual(result, 'content')
        self.assertIsNone(mock_story_instance.read_story.call_args.kwargs['after_read'])

    @patch('topsailai.tools.story_memory_tool.memory_stat.ensure_memory_stat')
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    def test_write_creates_zero_stat_inside_story_callback(
        self, mock_build_id, mock_story_instance, mock_ensure_stat
    ):
        from topsailai.tools import story_memory_tool

        mock_build_id.return_value = 'canonical.md'
        mock_story_instance.get_story_file.return_value = None

        def write_story(**kwargs):
            kwargs['after_write']('/workspace/story/2026-08-23/canonical.md')
            return '/workspace/story/2026-08-23/canonical.md'

        mock_story_instance.write_story.side_effect = write_story

        story_memory_tool.write_memory('title', 'content')

        mock_ensure_stat.assert_called_once_with(story_memory_tool.WORKSPACE, 'canonical.md')

    @patch('topsailai.tools.story_memory_tool.memory_stat.delete_memory_stat')
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_delete_stat_error_propagates(self, mock_story_instance, mock_delete_stat):
        from topsailai.tools import story_memory_tool

        mock_delete_stat.side_effect = PermissionError('denied')

        def delete_story(**kwargs):
            kwargs['before_delete']('/workspace/story/2026-08-23/canonical.md')
            self.fail('Markdown deletion must not continue after stat deletion fails')

        mock_story_instance.delete_story.side_effect = delete_story

        with self.assertRaises(PermissionError):
            story_memory_tool.delete_memory('canonical.md')

    @patch('topsailai.tools.story_memory_tool.list_memories')
    @patch('topsailai.tools.story_memory_tool.read_memory_without_count')
    @patch('topsailai.tools.story_memory_tool.read_memory')
    def test_prompt_bulk_loading_never_uses_counting_reader(
        self, mock_read_memory, mock_read_without_count, mock_list_memories
    ):
        from topsailai.tools import story_memory_tool

        mock_list_memories.return_value = ['memory.md']
        mock_read_without_count.return_value = 'content'

        prompt = story_memory_tool.get_prompt_memory()

        self.assertIn('content', prompt)
        self.assertIn('## Citing Memories', prompt)
        self.assertIn('@memory[<TITLE>]', prompt)
        self.assertIn('at most once per\nresponse', prompt)
        self.assertIn('Only cite memories that are actually listed above.', prompt)
        mock_read_without_count.assert_called_once_with('memory.md')
        mock_read_memory.assert_not_called()

    @patch(
        'topsailai.tools.story_memory_tool.memory_evict.maybe_evict_memory_stats'
    )
    @patch.dict(
        os.environ, {'TOPSAILAI_MEMORY_STAT_MAX_COUNT': '7'}, clear=False
    )
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    def test_write_triggers_live_eviction_after_stat_callback(
        self, mock_build_id, mock_story_instance, mock_evict
    ):
        """Verify a successful write runs configured eviction after stat creation."""
        from topsailai.tools import story_memory_tool

        mock_build_id.return_value = 'canonical.md'
        events = []

        def write_story(**kwargs):
            kwargs['after_write']('/workspace/story/canonical.md')
            events.append('stat')
            return '/workspace/story/canonical.md'

        mock_story_instance.write_story.side_effect = write_story
        mock_evict.side_effect = lambda *args, **kwargs: events.append('evict')

        story_memory_tool.write_memory('title', 'content')

        self.assertEqual(events, ['stat', 'evict'])
        mock_evict.assert_called_once_with(
            story_memory_tool.WORKSPACE, 7, dry_run=False
        )

    @patch(
        'topsailai.tools.story_memory_tool.memory_evict.maybe_evict_memory_stats'
    )
    @patch.dict(
        os.environ, {'TOPSAILAI_MEMORY_STAT_MAX_COUNT': '9'}, clear=False
    )
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_counting_read_triggers_live_eviction_after_event(
        self, mock_story_instance, mock_evict
    ):
        """Verify a counted read runs configured eviction after its stat event."""
        from topsailai.tools import story_memory_tool

        events = []

        def read_story(**kwargs):
            kwargs['after_read']('/workspace/story/canonical.md')
            events.append('stat')
            return 'content'

        mock_story_instance.read_story.side_effect = read_story
        mock_evict.side_effect = lambda *args, **kwargs: events.append('evict')

        self.assertEqual(story_memory_tool.read_memory('canonical.md'), 'content')

        self.assertEqual(events, ['stat', 'evict'])
        mock_evict.assert_called_once_with(
            story_memory_tool.WORKSPACE, 9, dry_run=False
        )

    @patch(
        'topsailai.tools.story_memory_tool.memory_evict.maybe_evict_memory_stats'
    )
    @patch.dict(
        os.environ, {'TOPSAILAI_MEMORY_STAT_MAX_COUNT': '0'}, clear=False
    )
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    def test_zero_limit_disables_write_eviction(
        self, mock_build_id, mock_story_instance, mock_evict
    ):
        """Verify a zero limit avoids calling the eviction engine."""
        from topsailai.tools import story_memory_tool

        mock_build_id.return_value = 'canonical.md'
        mock_story_instance.write_story.return_value = '/workspace/story/canonical.md'

        story_memory_tool.write_memory('title', 'content')

        mock_evict.assert_not_called()

    @patch(
        'topsailai.tools.story_memory_tool.memory_evict.maybe_evict_memory_stats'
    )
    @patch.dict(
        os.environ, {'TOPSAILAI_MEMORY_STAT_MAX_COUNT': '-4'}, clear=False
    )
    def test_negative_limit_is_clamped_and_disables_eviction(self, mock_evict):
        """Verify a negative configured limit is clamped to the disabled value."""
        from topsailai.tools import story_memory_tool

        story_memory_tool._maybe_evict_memories()

        mock_evict.assert_not_called()

    @patch(
        'topsailai.tools.story_memory_tool.memory_evict.maybe_evict_memory_stats',
        side_effect=RuntimeError('eviction failed'),
    )
    @patch.dict(
        os.environ, {'TOPSAILAI_MEMORY_STAT_MAX_COUNT': '1'}, clear=False
    )
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    @patch('topsailai.tools.story_memory_tool.build_story_id')
    def test_eviction_failure_does_not_break_write(
        self, mock_build_id, mock_story_instance, _mock_evict
    ):
        """Verify eviction failures are contained after a successful write."""
        from topsailai.tools import story_memory_tool

        mock_build_id.return_value = 'canonical.md'
        mock_story_instance.write_story.return_value = '/workspace/story/canonical.md'

        result = story_memory_tool.write_memory('title', 'content')

        self.assertIn('/workspace/story/canonical.md', result)

    @patch(
        'topsailai.tools.story_memory_tool.memory_evict.maybe_evict_memory_stats',
        side_effect=RuntimeError('eviction failed'),
    )
    @patch.dict(
        os.environ, {'TOPSAILAI_MEMORY_STAT_MAX_COUNT': '1'}, clear=False
    )
    @patch('topsailai.tools.story_memory_tool.StoryFileInstance')
    def test_eviction_failure_does_not_break_counting_read(
        self, mock_story_instance, _mock_evict
    ):
        """Verify eviction failures are contained after a successful counted read."""
        from topsailai.tools import story_memory_tool

        mock_story_instance.read_story.return_value = 'content'

        self.assertEqual(story_memory_tool.read_memory('canonical.md'), 'content')


    @patch(
        'topsailai.tools.story_memory_tool.memory_reconcile.reconcile_memory_stats'
    )
    def test_reconcile_memories_forwards_default_retention(self, mock_reconcile):
        """Verify the facade forwards approved retention and sync defaults."""
        from topsailai.tools import story_memory_tool
        from topsailai.tools.memory_tool_utils.memory_reconcile import ReconSummary

        mock_reconcile.return_value = ReconSummary(healthy=2, dry_run=False)

        result = story_memory_tool.reconcile_memories(dry_run=False)

        mock_reconcile.assert_called_once_with(
            story_memory_tool.WORKSPACE,
            dry_run=False,
            quarantine_max_age_days=30,
            quarantine_max_count=100,
            sync_batch_limit=100,
        )
        self.assertEqual(result, mock_reconcile.return_value.to_dict())

    @patch(
        'topsailai.tools.story_memory_tool.memory_reconcile.reconcile_memory_stats'
    )
    @patch.dict(
        os.environ,
        {
            'TOPSAILAI_MEMORY_STAT_QUARANTINE_MAX_AGE_DAYS': '7',
            'TOPSAILAI_MEMORY_STAT_QUARANTINE_MAX_COUNT': '12',
        },
    )
    def test_reconcile_memories_forwards_env_retention(self, mock_reconcile):
        """Verify configured retention values are resolved at the facade."""
        from topsailai.tools import story_memory_tool
        from topsailai.tools.memory_tool_utils.memory_reconcile import ReconSummary

        mock_reconcile.return_value = ReconSummary()

        story_memory_tool.reconcile_memories(sync_batch_limit=8)

        mock_reconcile.assert_called_once_with(
            story_memory_tool.WORKSPACE,
            dry_run=True,
            quarantine_max_age_days=7,
            quarantine_max_count=12,
            sync_batch_limit=8,
        )

    @patch(
        'topsailai.tools.story_memory_tool.memory_reconcile.reconcile_memory_stats'
    )
    @patch.dict(
        os.environ,
        {
            'TOPSAILAI_MEMORY_STAT_QUARANTINE_MAX_AGE_DAYS': '-1',
            'TOPSAILAI_MEMORY_STAT_QUARANTINE_MAX_COUNT': '-2',
        },
    )
    def test_reconcile_memories_clamps_negative_limits(self, mock_reconcile):
        """Verify negative retention and batch values safely disable actions."""
        from topsailai.tools import story_memory_tool
        from topsailai.tools.memory_tool_utils.memory_reconcile import ReconSummary

        mock_reconcile.return_value = ReconSummary()

        story_memory_tool.reconcile_memories(sync_batch_limit=-3)

        mock_reconcile.assert_called_once_with(
            story_memory_tool.WORKSPACE,
            dry_run=True,
            quarantine_max_age_days=0,
            quarantine_max_count=0,
            sync_batch_limit=0,
        )


if __name__ == '__main__':
    unittest.main()
