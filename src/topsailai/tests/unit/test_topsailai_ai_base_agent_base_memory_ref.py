"""Unit tests for raw-response story-memory reference accounting."""

import os
from unittest import TestCase
from tempfile import TemporaryDirectory
from unittest.mock import patch

from topsailai.tools import story_memory_tool
from topsailai.tools.memory_tool_utils import memory_ref_parser, memory_ref_scan_hook


class TestMemoryRefScanHook(TestCase):
    """Verify guarded citation accounting in the external response hook."""

    def setUp(self):
        """Create response text and isolate title-index cache state."""
        self.response = (
            "Use @memory[Known.md] while thinking. "
            "Then cite @memory[ known.MD ] in the final answer."
        )
        memory_ref_scan_hook._reset_title_index_cache()
        self.signature_patcher = patch(
            "topsailai.tools.memory_tool_utils.memory_ref_scan_hook."
            "_get_story_folder_signature",
            return_value=(1, 2, 3),
        )
        self.get_signature = self.signature_patcher.start()

    def tearDown(self):
        """Remove signature patches and cached state after each test."""
        self.signature_patcher.stop()
        memory_ref_scan_hook._reset_title_index_cache()

    @patch("topsailai.tools.memory_tool_utils.memory_stat.record_memory_event")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_records_one_cite_for_duplicate_refs(
        self, list_memories, record_memory_event
    ):
        """Count a canonical memory at most once in one raw LLM response."""
        list_memories.return_value = ["Known.md"]

        result = memory_ref_scan_hook.hook_execute(self.response)

        self.assertIs(result, self.response)
        record_memory_event.assert_called_once()
        workspace, memory_id, event = record_memory_event.call_args.args
        self.assertTrue(workspace)
        self.assertEqual((memory_id, event), ("Known.md", "cite"))

    @patch("topsailai.tools.memory_tool_utils.memory_stat.record_memory_event")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_unknown_and_ambiguous_refs_are_not_recorded(
        self, list_memories, record_memory_event
    ):
        """Ignore unresolved titles while preserving raw response processing."""
        list_memories.return_value = ["Clash.md", "clash.md"]
        response = "@memory[CLASH.MD] and @memory[Missing.md]"

        result = memory_ref_scan_hook.hook_execute(response)

        self.assertIs(result, response)
        record_memory_event.assert_not_called()

    @patch("topsailai.tools.memory_tool_utils.memory_ref_parser.build_title_index")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_unchanged_signature_reuses_title_index(
        self, list_memories, build_title_index
    ):
        """Reuse the cached index while story-directory metadata is unchanged."""
        list_memories.return_value = ["Known.md"]
        sentinel_index = object()
        build_title_index.return_value = sentinel_index

        first = memory_ref_scan_hook._get_title_index(
            story_memory_tool, memory_ref_parser
        )
        second = memory_ref_scan_hook._get_title_index(
            story_memory_tool, memory_ref_parser
        )

        self.assertIs(first, sentinel_index)
        self.assertIs(second, sentinel_index)
        self.assertEqual(self.get_signature.call_count, 2)
        list_memories.assert_called_once()
        build_title_index.assert_called_once_with(["Known.md"])

    @patch("topsailai.tools.memory_tool_utils.memory_ref_parser.build_title_index")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_changed_signature_rebuilds_title_index(
        self, list_memories, build_title_index
    ):
        """Rebuild the cached index when story-directory metadata changes."""
        self.get_signature.side_effect = [(1, 2, 3), (4, 5, 6)]
        list_memories.side_effect = [["Known.md"], ["New.md"]]
        build_title_index.side_effect = [object(), object()]

        first = memory_ref_scan_hook._get_title_index(
            story_memory_tool, memory_ref_parser
        )
        second = memory_ref_scan_hook._get_title_index(
            story_memory_tool, memory_ref_parser
        )

        self.assertIsNot(first, second)
        self.assertEqual(list_memories.call_count, 2)
        self.assertEqual(build_title_index.call_count, 2)

    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_disabled_env_is_fast_noop(self, list_memories):
        """Skip imports, title enumeration, and writes when explicitly disabled."""
        with patch.dict(
            os.environ,
            {"TOPSAILAI_MEMORY_REFERENCE_SCAN_ENABLED": "0"},
        ):
            result = memory_ref_scan_hook.hook_execute(self.response)

        self.assertIs(result, self.response)
        self.get_signature.assert_not_called()
        list_memories.assert_not_called()

    @patch("topsailai.tools.memory_tool_utils.memory_ref_scan_hook.logger.warning")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_accounting_error_is_logged_and_swallowed(
        self, list_memories, log_warning
    ):
        """Never let citation-accounting failures interrupt response delivery."""
        list_memories.side_effect = RuntimeError("unavailable")

        result = memory_ref_scan_hook.hook_execute(self.response)

        self.assertIs(result, self.response)
        log_warning.assert_called_once()
        self.assertIn(
            "Failed to record story-memory references",
            log_warning.call_args.args[0],
        )

    @patch("topsailai.tools.memory_tool_utils.memory_stat.record_memory_event")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_non_string_content_is_returned_unchanged(
        self, list_memories, record_memory_event
    ):
        """Preserve unexpected content types without recording citations."""
        list_memories.return_value = ["Known.md"]
        content = {"content": "@memory[Known.md]"}

        result = memory_ref_scan_hook.hook_execute(content)

        self.assertIs(result, content)
        record_memory_event.assert_not_called()


class TestStoryFolderSignature(TestCase):
    """Verify cache invalidation metadata for nested story storage."""

    def test_visible_date_directory_changes_signature(self):
        """Detect memory-file changes below an existing date directory."""
        with TemporaryDirectory() as workspace:
            story_folder = os.path.join(workspace, "story")
            date_folder = os.path.join(story_folder, "20260824")
            stats_folder = os.path.join(story_folder, ".stats")
            os.makedirs(date_folder)
            os.makedirs(stats_folder)

            before = memory_ref_scan_hook._get_story_folder_signature(workspace)
            memory_file = os.path.join(date_folder, "Known.md")
            with open(memory_file, "w", encoding="utf-8") as stream:
                stream.write("memory")
            directory_stat = os.stat(date_folder)
            os.utime(
                date_folder,
                ns=(directory_stat.st_atime_ns, directory_stat.st_mtime_ns + 2_000_000_000),
            )
            after = memory_ref_scan_hook._get_story_folder_signature(workspace)

        self.assertNotEqual(before, after)
        self.assertTrue(any(date_folder == item[0] for item in after))
        self.assertFalse(any(stats_folder == item[0] for item in after))
